"""Análise de consumo de processos.

- Agrupamento: um "grupo" é a unidade systemd do processo, ou o nome dele quando
  não há unidade. Assim os workers do Apache somam juntos, e um serviço que
  reiniciou (pid novo) continua sendo o mesmo grupo.
- Sinais: achados MEDIDOS nas amostras (crescimento de memória, reinício, CPU
  sustentada, pico). Seguem a mesma lógica das evidências do diagnóstico. A única
  extrapolação é a projeção linear de memória, sempre rotulada como estimativa.
"""

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta

from app.domain.thresholds import fmt
from app.models import Origem, Processo, Severidade
from app.models.processes import (
    AmostraProcesso,
    AnaliseGrupo,
    EstatisticaSerie,
    GrupoConsumo,
    InstanciaProcesso,
    PontoProcesso,
    ResumoProcessos,
    SinalProcesso,
)

MIB = 1024**2

# Quantos processos entram em cada amostra persistida: os N maiores por CPU ∪ os N maiores
# por memória. Mantém o volume previsível num host com centenas de processos.
TOP_N_AMOSTRA = 15

# Crescimento de memória: inclinação mínima, aderência mínima da reta e base mínima de dados.
# Duas janelas sobre as leituras mais recentes de cada instância: a curta pega rampa
# rápida (vazamento que termina em OOM); a longa pega crescimento lento sob ruído.
JANELAS_TENDENCIA = (timedelta(hours=1), timedelta(hours=2))
TENDENCIA_MIN_MIB_H = 30.0
TENDENCIA_MIN_R2 = 0.7
TENDENCIA_MIN_PONTOS = 10
TENDENCIA_MIN_DURACAO = timedelta(minutes=30)
PROJECAO_MAX_HORAS = 72  # além disso a projeção linear não diz nada útil

CPU_SUSTENTADA_PCT = 50.0
CPU_SUSTENTADA_DURACAO = timedelta(minutes=10)
MEMORIA_PICO_RELEVANTE_PCT = 20.0
JANELA_REINICIO = timedelta(minutes=10)


def grupo_de(processo: Processo) -> str:
    return processo.unidade_systemd or processo.nome


def selecionar_para_amostra(processos: list[Processo]) -> list[Processo]:
    por_cpu = sorted(processos, key=lambda p: p.cpu_percentual, reverse=True)[:TOP_N_AMOSTRA]
    por_mem = sorted(processos, key=lambda p: p.memoria_percentual, reverse=True)[:TOP_N_AMOSTRA]
    escolhidos: dict[int, Processo] = {}
    for p in por_cpu + por_mem:
        escolhidos.setdefault(p.pid, p)
    return list(escolhidos.values())


def filtrar(
    processos: list[Processo], busca: str | None = None, categoria: str | None = None
) -> list[Processo]:
    termo = (busca or "").strip().casefold()

    def casa(p: Processo) -> bool:
        if categoria and p.categoria != categoria:
            return False
        if not termo:
            return True
        campos = (p.nome, p.comando, p.usuario, p.unidade_systemd or "", str(p.pid))
        return any(termo in c.casefold() for c in campos)

    return [p for p in processos if casa(p)]


def _participacao(valor: float, total: float) -> float:
    return round(valor / total * 100, 1) if total > 0 else 0.0


def resumir(processos: list[Processo]) -> ResumoProcessos:
    por_grupo: dict[str, list[Processo]] = defaultdict(list)
    for p in processos:
        por_grupo[grupo_de(p)].append(p)
    cpu_total = sum(p.cpu_percentual for p in processos)
    mem_total = sum(p.memoria_percentual for p in processos)

    grupos = []
    for nome, membros in por_grupo.items():
        cpu = sum(p.cpu_percentual for p in membros)
        mem = sum(p.memoria_percentual for p in membros)
        grupos.append(
            GrupoConsumo(
                grupo=nome,
                categoria=membros[0].categoria,
                processos=len(membros),
                cpu_percentual=round(cpu, 1),
                memoria_percentual=round(mem, 2),
                memoria_rss_bytes=sum(p.memoria_rss_bytes for p in membros),
                participacao_cpu=_participacao(cpu, cpu_total),
                participacao_memoria=_participacao(mem, mem_total),
            )
        )
    grupos.sort(key=lambda g: (g.cpu_percentual, g.memoria_percentual), reverse=True)

    def top3(chave: Callable[[GrupoConsumo], float]) -> float:
        return round(min(100.0, sum(sorted((chave(g) for g in grupos), reverse=True)[:3])), 1)

    return ResumoProcessos(
        total_processos=len(processos),
        total_grupos=len(grupos),
        concentracao_top3_cpu=top3(lambda g: g.participacao_cpu),
        concentracao_top3_memoria=top3(lambda g: g.participacao_memoria),
        grupos=grupos,
    )


def regressao_linear(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """Inclinação e R² por mínimos quadrados. None se não houver variação em x."""
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    inclinacao = sxy / sxx
    ss_tot = sum((y - my) ** 2 for y in ys)
    if ss_tot == 0:
        return 0.0, 0.0  # série constante: sem tendência
    ss_res = sum((y - (my + inclinacao * (x - mx))) ** 2 for x, y in zip(xs, ys, strict=True))
    return inclinacao, max(0.0, 1 - ss_res / ss_tot)


def _cresce(inclinacao: float, r2: float) -> bool:
    return inclinacao >= TENDENCIA_MIN_MIB_H and r2 >= TENDENCIA_MIN_R2


def _tendencia_rss(amostras: list[AmostraProcesso]) -> tuple[float, float, int] | None:
    """(MiB/h, R², janela em minutos) da RSS nas leituras mais recentes da instância.

    Usa a primeira janela de JANELAS_TENDENCIA em que o crescimento se qualifica;
    se nenhuma qualificar, devolve a medição da maior janela disponível."""
    if not amostras:
        return None
    medida: tuple[float, float, int] | None = None
    for janela in JANELAS_TENDENCIA:
        recentes = [a for a in amostras if a.momento >= amostras[-1].momento - janela]
        duracao = recentes[-1].momento - recentes[0].momento
        if len(recentes) < TENDENCIA_MIN_PONTOS or duracao < TENDENCIA_MIN_DURACAO:
            continue
        base = recentes[0].momento
        xs = [(a.momento - base).total_seconds() / 3600 for a in recentes]
        ys = [a.memoria_rss_bytes / MIB for a in recentes]
        resultado = regressao_linear(xs, ys)
        if resultado is None:
            continue
        medida = (resultado[0], resultado[1], round(duracao.total_seconds() / 60))
        if _cresce(resultado[0], resultado[1]):
            break
    return medida


def _estatistica(serie: list[PontoProcesso], campo: str) -> EstatisticaSerie:
    valores = [float(getattr(p, campo)) for p in serie]
    i_max = max(range(len(valores)), key=valores.__getitem__)
    return EstatisticaSerie(
        atual=valores[-1],
        media=round(sum(valores) / len(valores), 2),
        minimo=min(valores),
        maximo=valores[i_max],
        momento_maximo=serie[i_max].momento,
    )


def _serie_agregada(amostras: list[AmostraProcesso]) -> list[PontoProcesso]:
    por_momento: dict[datetime, list[AmostraProcesso]] = defaultdict(list)
    for a in amostras:
        por_momento[a.momento].append(a)
    return [
        PontoProcesso(
            momento=m,
            cpu_percentual=round(sum(a.cpu_percentual for a in grupo), 1),
            memoria_percentual=round(min(100.0, sum(a.memoria_percentual for a in grupo)), 2),
            memoria_rss_bytes=sum(a.memoria_rss_bytes for a in grupo),
            processos=len(grupo),
        )
        for m, grupo in sorted(por_momento.items())
    ]


def reduzir_serie(serie: list[PontoProcesso], max_pontos: int) -> list[PontoProcesso]:
    """Baldes consecutivos com o MÁXIMO de cada medida: o pico nunca some do gráfico."""
    if max_pontos < 1:
        raise ValueError("max_pontos deve ser >= 1")
    if len(serie) <= max_pontos:
        return serie
    tamanho = -(-len(serie) // max_pontos)
    return [
        PontoProcesso(
            momento=balde[-1].momento,
            cpu_percentual=max(p.cpu_percentual for p in balde),
            memoria_percentual=max(p.memoria_percentual for p in balde),
            memoria_rss_bytes=max(p.memoria_rss_bytes for p in balde),
            processos=max(p.processos for p in balde),
        )
        for balde in (serie[i : i + tamanho] for i in range(0, len(serie), tamanho))
    ]


def _instancias(amostras: list[AmostraProcesso], ultimo_momento: datetime) -> list[InstanciaProcesso]:
    por_instancia: dict[tuple[int, datetime], list[AmostraProcesso]] = defaultdict(list)
    for a in amostras:
        por_instancia[(a.pid, a.iniciado_em)].append(a)
    instancias = []
    for (pid, iniciado_em), lista in por_instancia.items():
        lista.sort(key=lambda a: a.momento)
        tendencia = _tendencia_rss(lista)
        instancias.append(
            InstanciaProcesso(
                pid=pid,
                nome=lista[0].nome,
                iniciado_em=iniciado_em,
                primeira_amostra=lista[0].momento,
                ultima_amostra=lista[-1].momento,
                amostras=len(lista),
                encerrado=lista[-1].momento < ultimo_momento,
                rss_atual_bytes=lista[-1].memoria_rss_bytes,
                # "+ 0.0" normaliza -0.0 (série estável com ruído) para 0.0
                tendencia_rss_mib_h=round(tendencia[0], 1) + 0.0 if tendencia else None,
                tendencia_r2=round(tendencia[1], 3) if tendencia else None,
                tendencia_janela_min=tendencia[2] if tendencia else None,
            )
        )
    instancias.sort(key=lambda i: (i.primeira_amostra, i.pid))
    return instancias


def _minutos(delta: timedelta) -> str:
    return f"{round(delta.total_seconds() / 60)} min"


def _sinais(
    serie: list[PontoProcesso],
    instancias: list[InstanciaProcesso],
    memoria: EstatisticaSerie,
    ram_total_bytes: int,
) -> list[SinalProcesso]:
    sinais: list[SinalProcesso] = []

    # Reinício: instância some e outra de mesmo nome começa logo depois.
    for fim in (i for i in instancias if i.encerrado):
        nova = next(
            (
                i
                for i in instancias
                if i.nome == fim.nome
                and i.pid != fim.pid
                and fim.ultima_amostra - JANELA_REINICIO
                <= i.iniciado_em
                <= fim.ultima_amostra + JANELA_REINICIO
            ),
            None,
        )
        if nova:
            sinais.append(
                SinalProcesso(
                    codigo="REINICIO",
                    severidade=Severidade.AVISO,
                    titulo=f"Reinício: pid {fim.pid} → pid {nova.pid}",
                    descricao=(
                        f"O processo {fim.nome} (pid {fim.pid}) deixou de aparecer e o pid {nova.pid} "
                        f"iniciou {_minutos(abs(nova.iniciado_em - fim.ultima_amostra))} "
                        "depois da última leitura do anterior."
                    ),
                    momento=nova.iniciado_em,
                    pid=nova.pid,
                )
            )
        else:
            sinais.append(
                SinalProcesso(
                    codigo="ENCERRADO",
                    severidade=Severidade.INFO,
                    titulo=f"pid {fim.pid} deixou de aparecer",
                    descricao=(
                        f"O processo {fim.nome} (pid {fim.pid}) não está nas amostras mais recentes. "
                        "Pode ter terminado ou saído dos maiores consumidores."
                    ),
                    momento=fim.ultima_amostra,
                    pid=fim.pid,
                )
            )

    # Crescimento contínuo de memória, por instância.
    for i in instancias:
        if i.tendencia_rss_mib_h is None or i.tendencia_r2 is None:
            continue
        if not _cresce(i.tendencia_rss_mib_h, i.tendencia_r2):
            continue
        descricao = (
            f"RSS do pid {i.pid} cresceu em média {fmt(i.tendencia_rss_mib_h)} MiB/h nos últimos "
            f"{i.tendencia_janela_min} min de leituras (aderência da reta R² = {fmt(i.tendencia_r2 * 100)}%)."
        )
        severidade = Severidade.AVISO
        if i.encerrado:
            descricao += " A instância deixou de aparecer em seguida."
            severidade = Severidade.ALTO
        elif ram_total_bytes > i.rss_atual_bytes:
            horas = (ram_total_bytes - i.rss_atual_bytes) / MIB / i.tendencia_rss_mib_h
            if horas <= PROJECAO_MAX_HORAS:
                descricao += (
                    f" Projeção linear (estimativa): no ritmo atual, ocuparia toda a RAM em ~{fmt(horas)} h."
                )
                if horas <= 24:
                    severidade = Severidade.ALTO
        sinais.append(
            SinalProcesso(
                codigo="MEMORIA_CRESCENTE",
                severidade=severidade,
                titulo=f"Memória em crescimento contínuo (pid {i.pid})",
                descricao=descricao,
                momento=i.ultima_amostra,
                pid=i.pid,
            )
        )

    # CPU sustentada: maior trecho contínuo com CPU somada acima do limiar.
    inicio_trecho: datetime | None = None
    melhor: tuple[datetime, datetime] | None = None
    for p in serie:
        if p.cpu_percentual >= CPU_SUSTENTADA_PCT:
            inicio_trecho = inicio_trecho or p.momento
            if melhor is None or p.momento - inicio_trecho > melhor[1] - melhor[0]:
                melhor = (inicio_trecho, p.momento)
        else:
            inicio_trecho = None
    if melhor and melhor[1] - melhor[0] >= CPU_SUSTENTADA_DURACAO:
        sinais.append(
            SinalProcesso(
                codigo="CPU_SUSTENTADA",
                severidade=Severidade.AVISO,
                titulo=f"CPU acima de {fmt(CPU_SUSTENTADA_PCT)}% por {_minutos(melhor[1] - melhor[0])}",
                descricao="Consumo de CPU do grupo ficou acima do limiar sem interrupção nesse trecho.",
                momento=melhor[0],
            )
        )

    if memoria.maximo >= MEMORIA_PICO_RELEVANTE_PCT:
        sinais.append(
            SinalProcesso(
                codigo="PICO_MEMORIA",
                severidade=Severidade.ALTO
                if memoria.maximo >= 2 * MEMORIA_PICO_RELEVANTE_PCT
                else Severidade.AVISO,
                titulo=f"Pico de {fmt(memoria.maximo)}% da RAM",
                descricao=f"O grupo chegou a ocupar {fmt(memoria.maximo)}% da memória do host no período.",
                momento=memoria.momento_maximo,
            )
        )
    return sorted(sinais, key=lambda s: s.momento)


def analisar_grupo(
    grupo: str,
    amostras: list[AmostraProcesso],
    horas: float,
    ram_total_bytes: int,
    origem: Origem,
    max_pontos: int = 360,
) -> AnaliseGrupo:
    if not amostras:
        raise ValueError("sem amostras para analisar")
    serie = _serie_agregada(amostras)
    memoria = _estatistica(serie, "memoria_percentual")
    instancias = _instancias(amostras, serie[-1].momento)
    return AnaliseGrupo(
        grupo=grupo,
        horas=horas,
        origem=origem,
        serie=reduzir_serie(serie, max_pontos),
        cpu=_estatistica(serie, "cpu_percentual"),
        memoria=memoria,
        rss=_estatistica(serie, "memoria_rss_bytes"),
        instancias=instancias,
        sinais=_sinais(serie, instancias, memoria, ram_total_bytes),
    )
