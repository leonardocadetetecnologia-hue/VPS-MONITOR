"""Análise de processos de maior consumo: domínio, persistência e API."""

import sqlite3
from datetime import timedelta

import pytest

from app.domain.processes import (
    TOP_N_AMOSTRA,
    analisar_grupo,
    filtrar,
    grupo_de,
    reduzir_serie,
    regressao_linear,
    resumir,
    selecionar_para_amostra,
)
from app.models import Origem, Processo
from app.models.processes import AmostraProcesso, PontoProcesso
from app.storage.repositories import ProcessosRepository
from tests.conftest import AGORA

GIB = 1024**3
MIB = 1024**2


def _proc(pid=10, nome="node", cpu=1.0, mem=1.0, unidade="app.service", categoria="aplicacao", **extra):
    return Processo(
        pid=pid, nome=nome, usuario="appsvc", comando=f"/usr/bin/{nome}", categoria=categoria,
        cpu_percentual=cpu, memoria_percentual=mem, memoria_rss_bytes=int(mem / 100 * 15 * GIB),
        estado="S", iniciado_em=extra.get("iniciado_em", AGORA - timedelta(days=1)),
        unidade_systemd=unidade, origem=Origem.SIMULADO,
    )  # fmt: skip


def _amostras(pid, minutos, rss_mib, inicio=None, cpu=5.0, nome="node"):
    """Uma amostra por minuto; rss_mib(i) dá a RSS no minuto i."""
    inicio = inicio or AGORA - timedelta(minutes=minutos - 1)
    iniciado = inicio - timedelta(minutes=5)
    return [
        AmostraProcesso(
            momento=inicio + timedelta(minutes=i),
            pid=pid,
            iniciado_em=iniciado,
            nome=nome,
            cpu_percentual=cpu(i) if callable(cpu) else cpu,
            memoria_percentual=min(100.0, rss_mib(i) * MIB / (15 * GIB) * 100),
            memoria_rss_bytes=int(rss_mib(i) * MIB),
        )
        for i in range(minutos)
    ]


def _analisar(amostras, ram=15 * GIB):
    return analisar_grupo("g", amostras, horas=6, ram_total_bytes=ram, origem=Origem.SIMULADO)


def _codigos(analise):
    return [s.codigo for s in analise.sinais]


# --- regras de domínio --------------------------------------------------------


def test_grupo_e_a_unidade_ou_o_nome():
    assert grupo_de(_proc(unidade="apache2.service", nome="apache2")) == "apache2.service"
    assert grupo_de(_proc(unidade=None, nome="redis-server")) == "redis-server"


def test_amostra_guarda_maiores_por_cpu_e_por_memoria_sem_duplicar():
    processos = [_proc(pid=i, cpu=i, mem=100 - i) for i in range(1, 61)]
    escolhidos = {p.pid for p in selecionar_para_amostra(processos)}
    assert len(escolhidos) == 2 * TOP_N_AMOSTRA
    assert 60 in escolhidos and 1 in escolhidos  # maior CPU e maior memória
    poucos = [_proc(pid=i) for i in range(1, 4)]
    assert len(selecionar_para_amostra(poucos)) == 3


@pytest.mark.parametrize(
    ("busca", "categoria", "esperado"),
    [
        ("", None, {1, 2, 3}),
        ("POSTGRES", None, {2}),  # sem diferenciar maiúsculas
        ("joão", None, {3}),
        ("JOÃO", None, {3}),
        ("3", None, {3}),  # por pid
        ("app-web", None, {1}),  # por unidade
        (None, "banco", {2}),
        ("node", "banco", set()),
        ("inexistente", None, set()),
    ],
)
def test_filtro_de_busca_e_categoria(busca, categoria, esperado):
    processos = [
        _proc(pid=1, nome="node", unidade="app-web-next.service"),
        _proc(pid=2, nome="postgres", unidade="postgresql@16-main.service", categoria="banco"),
        _proc(pid=3, nome="relatorio-joão", unidade=None),
    ]
    assert {p.pid for p in filtrar(processos, busca, categoria)} == esperado


def test_resumo_participacao_e_concentracao():
    processos = [
        _proc(pid=1, cpu=40, mem=10, unidade="a.service"),
        _proc(pid=2, cpu=20, mem=10, unidade="a.service"),  # mesmo grupo: soma
        _proc(pid=3, cpu=30, mem=60, unidade="b.service"),
        _proc(pid=4, cpu=10, mem=20, unidade=None, nome="c"),
    ]
    r = resumir(processos)
    assert r.total_processos == 4 and r.total_grupos == 3
    a = next(g for g in r.grupos if g.grupo == "a.service")
    assert (a.processos, a.cpu_percentual, a.participacao_cpu) == (2, 60, 60.0)
    assert sum(g.participacao_cpu for g in r.grupos) == pytest.approx(100, abs=0.2)
    assert sum(g.participacao_memoria for g in r.grupos) == pytest.approx(100, abs=0.2)
    assert r.concentracao_top3_cpu == 100  # só existem 3 grupos


def test_resumo_vazio_e_consumo_zero_nao_dividem_por_zero():
    assert resumir([]).total_processos == 0
    r = resumir([_proc(cpu=0, mem=0)])
    assert r.grupos[0].participacao_cpu == 0 and r.concentracao_top3_memoria == 0


def test_regressao_linear():
    resultado = regressao_linear([0, 1, 2, 3], [10, 12, 14, 16])
    assert resultado is not None
    inclinacao, r2 = resultado
    assert inclinacao == pytest.approx(2) and r2 == pytest.approx(1)
    assert regressao_linear([0, 1, 2], [5, 5, 5]) == (0.0, 0.0)
    assert regressao_linear([1, 1, 1], [1, 2, 3]) is None
    assert regressao_linear([1], [1]) is None


def test_serie_estavel_nao_gera_sinal():
    analise = _analisar(_amostras(1, 120, lambda i: 500 + (i % 3)))
    assert analise.sinais == []
    assert analise.instancias[0].encerrado is False


def test_crescimento_continuo_de_memoria_e_detectado():
    analise = _analisar(_amostras(1, 90, lambda i: 500 + i * 2))  # 2 MiB/min = 120 MiB/h
    assert _codigos(analise) == ["MEMORIA_CRESCENTE"]
    inst = analise.instancias[0]
    assert inst.tendencia_rss_mib_h == pytest.approx(120, rel=0.01)
    assert inst.tendencia_r2 == pytest.approx(1, abs=0.001)


def test_crescimento_lento_abaixo_do_limiar_nao_gera_sinal():
    analise = _analisar(_amostras(1, 90, lambda i: 500 + i * 0.3))  # 18 MiB/h
    assert "MEMORIA_CRESCENTE" not in _codigos(analise)


def test_poucas_leituras_nao_permitem_tendencia():
    analise = _analisar(_amostras(1, 9, lambda i: 500 + i * 50))
    assert analise.instancias[0].tendencia_rss_mib_h is None
    assert analise.sinais == []


def test_projecao_quando_a_ram_acabaria_em_menos_de_um_dia():
    # 14 GiB ocupados crescendo 1 GiB/h numa RAM de 15 GiB → ~1 h para acabar
    analise = _analisar(_amostras(1, 60, lambda i: 14 * 1024 + i * 1024 / 60))
    sinal = next(s for s in analise.sinais if s.codigo == "MEMORIA_CRESCENTE")
    assert sinal.severidade == "alto"
    assert "Projeção linear (estimativa)" in sinal.descricao


def test_reinicio_detectado_quando_pid_some_e_outro_assume():
    antigo = _amostras(100, 60, lambda i: 800, inicio=AGORA - timedelta(minutes=121))
    novo_inicio = antigo[-1].momento + timedelta(minutes=2)
    novo = _amostras(200, 60, lambda i: 300, inicio=novo_inicio)
    novo = [a.model_copy(update={"iniciado_em": novo_inicio}) for a in novo]
    analise = _analisar(antigo + novo)
    reinicio = next(s for s in analise.sinais if s.codigo == "REINICIO")
    assert reinicio.pid == 200 and "pid 100" in reinicio.titulo
    assert [i.encerrado for i in analise.instancias] == [True, False]


def test_processo_que_sumiu_sem_substituto():
    sumiu = _amostras(100, 30, lambda i: 100, inicio=AGORA - timedelta(minutes=89))
    continua = _amostras(101, 90, lambda i: 100, nome="outro")
    assert "ENCERRADO" in _codigos(_analisar(sumiu + continua))


@pytest.mark.parametrize(("minutos_alta", "espera_sinal"), [(9, False), (11, True)])
def test_cpu_sustentada_exige_duracao_minima(minutos_alta, espera_sinal):
    def cpu(i):
        return 90.0 if 20 <= i < 20 + minutos_alta else 5.0

    analise = _analisar(_amostras(1, 60, lambda i: 100, cpu=cpu))
    assert ("CPU_SUSTENTADA" in _codigos(analise)) is espera_sinal


def test_estatisticas_da_serie():
    analise = _analisar(_amostras(1, 30, lambda i: 100, cpu=lambda i: 50.0 if i == 10 else 10.0))
    assert analise.cpu.maximo == 50 and analise.cpu.atual == 10
    assert analise.cpu.momento_maximo == analise.serie[10].momento
    assert analise.cpu.media == pytest.approx((29 * 10 + 50) / 30, abs=0.01)


def test_reducao_da_serie_preserva_pico():
    serie = [
        PontoProcesso(momento=AGORA + timedelta(minutes=i), cpu_percentual=99 if i == 37 else 1,
                      memoria_percentual=1, memoria_rss_bytes=1, processos=1)
        for i in range(100)
    ]  # fmt: skip
    reduzida = reduzir_serie(serie, 10)
    assert len(reduzida) == 10 and max(p.cpu_percentual for p in reduzida) == 99
    assert reduzir_serie(serie[:5], 10) == serie[:5]
    with pytest.raises(ValueError):
        reduzir_serie(serie, 0)


def test_analise_sem_amostras_e_erro():
    with pytest.raises(ValueError):
        _analisar([])


# --- persistência ---------------------------------------------------------------


def test_instancia_gravada_uma_vez_e_amostras_por_momento(db):
    repo = ProcessosRepository(db)
    p = _proc()
    repo.inserir([(AGORA - timedelta(minutes=m), p, "g") for m in range(5)])
    repo.inserir([(AGORA + timedelta(minutes=1), p, "g")])
    with db.transacao() as conn:
        assert conn.execute("SELECT COUNT(*) FROM processos").fetchone()[0] == 1
    assert len(repo.amostras_grupo("g", AGORA - timedelta(hours=1), AGORA + timedelta(hours=1))) == 6
    assert repo.amostras_grupo("outro", AGORA - timedelta(hours=1), AGORA) == []


def test_pid_reaproveitado_vira_outra_instancia(db):
    repo = ProcessosRepository(db)
    velho = _proc(pid=500, iniciado_em=AGORA - timedelta(days=2))
    novo = _proc(pid=500, iniciado_em=AGORA - timedelta(hours=1))
    repo.inserir([(AGORA - timedelta(hours=2), velho, "g"), (AGORA, novo, "g")])
    instancias = {a.iniciado_em for a in repo.amostras_grupo("g", AGORA - timedelta(days=1), AGORA)}
    assert len(instancias) == 2


def test_limpar_origem_remove_amostras_em_cascata(db):
    repo = ProcessosRepository(db)
    repo.inserir([(AGORA, _proc(), "g")])
    repo.limpar_origem(Origem.SIMULADO)
    assert repo.contar_amostras() == 0


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO processos (pid, iniciado_em, nome, usuario, categoria, grupo, comando, origem) "
        "VALUES (0, 't', 'n', 'u', 'c', 'g', 'x', 'SIMULADO')",
        "INSERT INTO processos (pid, iniciado_em, nome, usuario, categoria, grupo, comando, origem) "
        "VALUES (1, 't', 'n', 'u', 'c', '', 'x', 'SIMULADO')",
        "INSERT INTO processos_amostras VALUES (999, 't', 1, 1, 1)",  # FK inexistente
    ],
)
def test_banco_garante_integridade_dos_processos(db, sql):
    with pytest.raises(sqlite3.IntegrityError), db.transacao() as conn:
        conn.execute(sql)


def test_amostragem_ao_vivo_grava_processos(monitor):
    antes = monitor.processos_repo.contar_amostras()
    monitor.amostrar()
    assert monitor.processos_repo.contar_amostras() > antes


# --- API e cenário simulado ----------------------------------------------------


def test_lista_traz_grupo_e_aceita_busca(cliente):
    dados = cliente.get("/api/processes").json()["dados"]
    assert all(p["grupo"] for p in dados)
    apache = next(p for p in dados if p["nome"] == "apache2")
    assert apache["grupo"] == "apache2.service"
    so_postgres = cliente.get("/api/processes", params={"busca": "postgres"}).json()["dados"]
    assert so_postgres and all("postgres" in p["nome"] for p in so_postgres)
    assert cliente.get("/api/processes", params={"busca": "não-existe"}).json()["dados"] == []
    bancos = cliente.get("/api/processes", params={"categoria": "banco"}).json()["dados"]
    assert {p["categoria"] for p in bancos} == {"banco"}


@pytest.mark.parametrize("params", [{"busca": "x" * 101}, {"categoria": "outra"}, {"ordenar_por": "pid"}])
def test_lista_valida_parametros(cliente, params):
    assert cliente.get("/api/processes", params=params).status_code == 422


def test_resumo_pela_api(cliente):
    r = cliente.get("/api/processes/summary").json()["dados"]
    assert r["total_processos"] >= r["total_grupos"] > 0
    assert sum(g["participacao_memoria"] for g in r["grupos"]) == pytest.approx(100, abs=0.5)
    assert 0 < r["concentracao_top3_cpu"] <= 100


def test_analise_conta_a_historia_do_incidente(cliente):
    """Cenário: node vaza memória → some (OOM) → systemd sobe outro pid, que volta a crescer."""
    a = cliente.get("/api/processes/analysis", params={"grupo": "app-web-next.service", "horas": 6}).json()[
        "dados"
    ]
    assert [(i["pid"], i["encerrado"]) for i in a["instancias"]] == [(48211, True), (51877, False)]
    codigos = [(s["codigo"], s["pid"]) for s in a["sinais"]]
    assert ("REINICIO", 51877) in codigos
    assert ("MEMORIA_CRESCENTE", 48211) in codigos  # vazamento antes do OOM
    assert ("MEMORIA_CRESCENTE", 51877) in codigos  # e continua depois do reinício
    assert a["memoria"]["maximo"] > 40
    assert len(a["serie"]) <= 360


def test_grupo_estavel_nao_tem_sinais(cliente):
    a = cliente.get("/api/processes/analysis", params={"grupo": "apache2.service"}).json()["dados"]
    assert a["sinais"] == []
    assert len(a["instancias"]) == 3  # master + 2 workers somados no grupo


def test_analise_de_grupo_inexistente_e_404_no_formato_padrao(cliente):
    r = cliente.get("/api/processes/analysis", params={"grupo": "../../etc/passwd"})
    assert r.status_code == 404
    erro = r.json()["erro"]
    assert erro["codigo"] == "nao_encontrado" and "../../etc/passwd" in erro["mensagem"]


@pytest.mark.parametrize(
    "params",
    [{}, {"grupo": ""}, {"grupo": "x" * 201}, {"grupo": "a", "horas": 0}, {"grupo": "a", "horas": 241}],
)
def test_analise_valida_parametros(cliente, params):
    assert cliente.get("/api/processes/analysis", params=params).status_code == 422
