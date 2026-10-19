"""Motor de diagnóstico investigativo.

Funciona em duas etapas, mantidas separadas de propósito:

1. `levantar_evidencias` — só registra FATOS: valor acima do limiar, pico no
   histórico, unidade em falha, evento do kernel. Sem interpretação.
2. `formular_hipoteses` — cruza evidências e propõe EXPLICAÇÕES possíveis,
   com confiança e verificações sugeridas. Toda hipótese cita as evidências
   em que se apoia e nasce `nao_confirmada`.
"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.thresholds import LIMIARES, LOAD_POR_NUCLEO_ALTO, classificar, fmt, severidade_de
from app.models import (
    AVISO_SIMULADO,
    Confianca,
    Criticidade,
    Diagnostico,
    EstadoAtivo,
    Evento,
    Evidencia,
    Hipotese,
    Nivel,
    Origem,
    PontoHistorico,
    Processo,
    Servico,
    Severidade,
    SnapshotMetricas,
)

PROCESSO_MEMORIA_RELEVANTE = 20.0  # % da RAM ocupada por um único processo


@dataclass
class Contexto:
    agora: datetime
    snapshot: SnapshotMetricas
    historico: list[PontoHistorico]
    servicos: list[Servico]
    processos: list[Processo]
    eventos: list[Evento]

    @property
    def origem(self) -> Origem:
        return self.snapshot.origem


def levantar_evidencias(ctx: Contexto) -> list[Evidencia]:
    ev: list[Evidencia] = []
    o = ctx.origem
    snap = ctx.snapshot

    atuais = {
        "cpu": snap.cpu.uso_percentual,
        "memoria": snap.memoria.uso_percentual,
        "swap": snap.memoria.swap_percentual,
        "disco": snap.disco_principal().uso_percentual,
    }
    for metrica, valor in atuais.items():
        nivel = classificar(metrica, valor)
        if nivel is not Nivel.NORMAL:
            lim = LIMIARES[metrica]
            ev.append(
                Evidencia(
                    id=f"E-atual-{metrica}",
                    observado_em=snap.coletado_em,
                    fonte=f"metricas.{metrica}",
                    descricao=f"{lim.rotulo} em {fmt(valor)}{lim.unidade} agora (nível {nivel.value}).",
                    valor=valor,
                    unidade=lim.unidade,
                    limiar=lim.aviso,
                    severidade=severidade_de(nivel),
                    origem=o,
                )
            )

    load_por_nucleo = snap.cpu.load_5 / snap.cpu.nucleos
    if load_por_nucleo >= LOAD_POR_NUCLEO_ALTO:
        ev.append(
            Evidencia(
                id="E-atual-load",
                observado_em=snap.coletado_em,
                fonte="metricas.cpu.load",
                descricao=f"Load médio de 5 min = {fmt(snap.cpu.load_5)} para {snap.cpu.nucleos} núcleos.",
                valor=snap.cpu.load_5,
                limiar=snap.cpu.nucleos * LOAD_POR_NUCLEO_ALTO,
                severidade=Severidade.AVISO,
                origem=o,
            )
        )

    if ctx.historico:
        campos = {"cpu": "cpu_percentual", "memoria": "memoria_percentual", "swap": "swap_percentual"}
        for metrica, campo in campos.items():
            pico = max(ctx.historico, key=lambda p: getattr(p, campo))
            valor = getattr(pico, campo)
            nivel = classificar(metrica, valor)
            if nivel in (Nivel.ALTO, Nivel.CRITICO):
                lim = LIMIARES[metrica]
                ev.append(
                    Evidencia(
                        id=f"E-pico-{metrica}",
                        observado_em=pico.momento,
                        fonte=f"historico.{metrica}",
                        descricao=f"Pico de {lim.rotulo} de {fmt(valor)}{lim.unidade} no período analisado.",
                        valor=valor,
                        unidade=lim.unidade,
                        limiar=lim.alto,
                        severidade=severidade_de(nivel),
                        origem=o,
                    )
                )

    for s in ctx.servicos:
        if s.estado_ativo is EstadoAtivo.FAILED:
            ev.append(
                Evidencia(
                    id=f"E-falha-{s.unidade}",
                    observado_em=s.desde,
                    fonte="systemd",
                    descricao=(
                        f"{s.unidade} em estado failed "
                        f"(criticidade: {s.criticidade.value}; {s.reinicios_24h} reinícios em 24h)."
                    ),
                    valor=s.estado_ativo.value,
                    severidade=Severidade.ALTO
                    if s.criticidade in (Criticidade.CRITICA, Criticidade.ALTA, Criticidade.INDEFINIDA)
                    else Severidade.AVISO,
                    origem=o,
                )
            )
        elif s.reinicios_24h > 0:
            ev.append(
                Evidencia(
                    id=f"E-reinicio-{s.unidade}",
                    observado_em=s.desde,
                    fonte="systemd",
                    descricao=(
                        f"{s.unidade} reiniciou {s.reinicios_24h}x nas últimas 24h; "
                        "ativo desde o último reinício."
                    ),
                    valor=s.reinicios_24h,
                    severidade=Severidade.AVISO,
                    origem=o,
                )
            )

    for p in sorted(ctx.processos, key=lambda p: p.memoria_percentual, reverse=True)[:1]:
        if p.memoria_percentual >= PROCESSO_MEMORIA_RELEVANTE:
            ev.append(
                Evidencia(
                    id=f"E-proc-mem-{p.pid}",
                    observado_em=ctx.agora,
                    fonte="processos",
                    descricao=f"Processo {p.nome} (pid {p.pid}) usa {fmt(p.memoria_percentual)}% da RAM.",
                    valor=p.memoria_percentual,
                    unidade="%",
                    limiar=PROCESSO_MEMORIA_RELEVANTE,
                    severidade=Severidade.ALTO,
                    origem=o,
                )
            )

    vistos: set[str] = set()
    for e in ctx.eventos:
        if (
            e.codigo in {"OOM_KILL", "SERVICE_START_LIMIT", "PROCESSO_RSS_ALTO", "SSH_FALHAS"}
            and e.id not in vistos
        ):
            vistos.add(e.id)
            ev.append(
                Evidencia(
                    id=f"E-evento-{e.id}",
                    observado_em=e.momento,
                    fonte=f"timeline.{e.codigo}",
                    descricao=e.titulo,
                    valor=e.recurso,
                    severidade=e.severidade,
                    origem=o,
                )
            )
    return ev


def formular_hipoteses(ctx: Contexto, evidencias: list[Evidencia]) -> list[Hipotese]:
    ids = {e.id: e for e in evidencias}
    hip: list[Hipotese] = []

    # H1 — vazamento de memória em aplicação
    oom = [e.id for e in evidencias if e.fonte == "timeline.OOM_KILL"]
    rss = [e.id for e in evidencias if e.fonte == "timeline.PROCESSO_RSS_ALTO"]
    pico_mem = [i for i in ("E-pico-memoria", "E-pico-swap") if i in ids]
    reinicio = [e.id for e in evidencias if e.id.startswith("E-reinicio-")]
    if oom and (pico_mem or rss):
        apoio = oom + rss + pico_mem + reinicio
        hip.append(
            Hipotese(
                id="H-vazamento-memoria",
                titulo="Vazamento de memória em processo de aplicação levou ao OOM",
                explicacao=(
                    "O crescimento contínuo de RSS de um único processo, seguido de uso de swap e do "
                    "OOM killer, é compatível com vazamento de memória. Também é compatível com pico "
                    "legítimo de carga ou limite de heap mal dimensionado — por isso não está confirmado."
                ),
                confianca=Confianca.MEDIA if rss else Confianca.BAIXA,
                evidencias_ids=apoio,
                verificacoes_sugeridas=[
                    "Comparar o volume de requisições HTTP no período (exige logs do Apache — etapa futura).",
                    "Verificar se houve deploy da aplicação pouco antes do início do crescimento.",
                    "Acompanhar o RSS do novo processo após o reinício: "
                    "crescimento linear reforça a hipótese.",
                    "Revisar --max-old-space-size e limites de memória do serviço (MemoryMax).",
                ],
            )
        )

    # H2 — swap residual ainda pressionando
    if "E-atual-swap" in ids and "E-atual-memoria" not in ids:
        apoio = ["E-atual-swap"] + [i for i in ("E-pico-swap",) if i in ids] + oom
        hip.append(
            Hipotese(
                id="H-swap-residual",
                titulo="Swap elevada é resíduo do incidente, não pressão atual",
                explicacao=(
                    "A RAM está em nível normal, mas a swap segue acima do limiar. O kernel só traz "
                    "páginas de volta quando são acessadas, então swap alta após um pico é esperada "
                    "e tende a cair sozinha. Se não cair, pode haver processo ocioso inchado."
                ),
                confianca=Confianca.MEDIA if oom else Confianca.BAIXA,
                evidencias_ids=apoio,
                verificacoes_sugeridas=[
                    "Observar a tendência da swap nas próximas horas no Histórico.",
                    "Identificar quais processos têm páginas em swap "
                    "(VmSwap em /proc/<pid>/status — coleta futura).",
                ],
            )
        )

    # H3 — unidades em falha sem criticidade definida
    falhas_indef = [
        f"E-falha-{s.unidade}"
        for s in ctx.servicos
        if s.estado_ativo is EstadoAtivo.FAILED and s.criticidade is Criticidade.INDEFINIDA
    ]
    if falhas_indef:
        hip.append(
            Hipotese(
                id="H-unidades-orfas",
                titulo="Unidades em falha podem ser serviços descontinuados ou dependências quebradas",
                explicacao=(
                    "Há unidades de aplicação em failed sem criticidade definida. Falhas antigas sem "
                    "tentativa de reinício costumam indicar serviço abandonado; falhas recentes que "
                    "esgotaram reinícios sugerem erro de configuração ou dependência indisponível."
                ),
                confianca=Confianca.BAIXA,
                evidencias_ids=falhas_indef
                + [e.id for e in evidencias if e.fonte == "timeline.SERVICE_START_LIMIT"],
                verificacoes_sugeridas=[
                    "Levantar com os responsáveis se cada unidade ainda é necessária e qual sua criticidade.",
                    "Ler o journal da unidade no momento da falha (coleta de logs — etapa futura).",
                    "Checar se a falha coincide com atualização de pacotes ou mudança de credenciais.",
                ],
            )
        )

    # H4 — saturação de CPU
    cpu_ev = [i for i in ("E-atual-cpu", "E-atual-load", "E-pico-cpu") if i in ids]
    if "E-atual-load" in ids or "E-atual-cpu" in ids:
        hip.append(
            Hipotese(
                id="H-saturacao-cpu",
                titulo="CPU saturada com fila de execução",
                explicacao="Uso e load acima da capacidade indicam processos esperando CPU.",
                confianca=Confianca.MEDIA if len(cpu_ev) >= 2 else Confianca.BAIXA,
                evidencias_ids=cpu_ev,
                verificacoes_sugeridas=["Ver os maiores consumidores na tela Processos no mesmo instante."],
            )
        )
    return hip


def gerar_diagnostico(ctx: Contexto) -> Diagnostico:
    evidencias = levantar_evidencias(ctx)
    hipoteses = formular_hipoteses(ctx, evidencias)
    return Diagnostico(
        gerado_em=ctx.agora,
        origem=ctx.origem,
        aviso=AVISO_SIMULADO if ctx.origem is Origem.SIMULADO else "",
        evidencias=sorted(evidencias, key=lambda e: e.observado_em),
        hipoteses=hipoteses,
    )
