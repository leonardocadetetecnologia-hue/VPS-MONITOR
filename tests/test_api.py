import pytest

from tests.conftest import AGORA

ENDPOINTS_ENVELOPE = [
    "/api/metrics/current",
    "/api/metrics/history",
    "/api/processes",
    "/api/services",
    "/api/events",
    "/api/diagnostics",
    "/api/integrations",
    "/api/audit",
]


@pytest.mark.parametrize("url", ENDPOINTS_ENVELOPE)
def test_toda_resposta_declara_origem_simulada(cliente, url):
    r = cliente.get(url)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["origem"] == "SIMULADO"
    assert "SIMULADOS" in corpo["aviso"]
    assert "dados" in corpo


def test_health(cliente):
    corpo = cliente.get("/api/health").json()
    assert corpo["status"] == "ok"
    assert corpo["modo"] == "simulado"
    assert corpo["coleta_real"] is False
    assert corpo["pontos_historico"] == 24 * 60 + 1


def test_metricas_atuais_com_niveis(cliente):
    d = cliente.get("/api/metrics/current").json()["dados"]
    assert d["snapshot"]["coletado_em"].startswith(AGORA.isoformat()[:16])
    assert set(d["niveis"]) == {"cpu", "memoria", "swap", "disco"}
    assert d["niveis"]["swap"] == "aviso"  # resíduo do incidente roteirizado


def test_historico_respeita_janela_e_limite(cliente):
    pontos = cliente.get("/api/metrics/history", params={"horas": 1, "max_pontos": 20}).json()["dados"]
    assert 0 < len(pontos) <= 20
    tudo = cliente.get("/api/metrics/history", params={"horas": 24, "max_pontos": 2000}).json()["dados"]
    assert len(tudo) == 24 * 60 + 1
    assert max(p["memoria_percentual"] for p in tudo) > 85


@pytest.mark.parametrize("params", [{"horas": 0}, {"horas": 999}, {"max_pontos": 1}])
def test_historico_valida_parametros(cliente, params):
    assert cliente.get("/api/metrics/history", params=params).status_code == 422


def test_processos_ordenados_e_limitados(cliente):
    por_mem = cliente.get("/api/processes", params={"ordenar_por": "memoria", "limite": 5}).json()["dados"]
    assert len(por_mem) == 5
    valores = [p["memoria_percentual"] for p in por_mem]
    assert valores == sorted(valores, reverse=True)
    assert cliente.get("/api/processes", params={"ordenar_por": "pid"}).status_code == 422


def test_servicos_falhas_primeiro_e_filtros(cliente):
    inv = cliente.get("/api/services").json()["dados"]
    assert inv["servicos"][0]["estado_ativo"] == "failed"
    assert inv["por_estado"]["failed"] >= 2
    so_falhas = cliente.get("/api/services", params={"estado": "failed"}).json()["dados"]["servicos"]
    assert so_falhas and all(s["estado_ativo"] == "failed" for s in so_falhas)
    indef = cliente.get("/api/services", params={"criticidade": "indefinida"}).json()["dados"]["servicos"]
    assert all(s["unidade"].startswith("app-") for s in indef)


def test_linha_do_tempo_ordem_e_filtros(cliente):
    eventos = cliente.get("/api/events", params={"horas": 24}).json()["dados"]
    momentos = [e["momento"] for e in eventos]
    assert momentos == sorted(momentos, reverse=True)
    codigos = {e["codigo"] for e in eventos}
    assert "OOM_KILL" in codigos and "LIMIAR_MEMORIA_SUBIU" in codigos
    # falha antiga (9 dias) só aparece com janela maior
    assert not any(e["recurso"] == "app-sync-legado.service" for e in eventos)
    longos = cliente.get("/api/events", params={"horas": 240}).json()["dados"]
    assert any(e["recurso"] == "app-sync-legado.service" for e in longos)
    criticos = cliente.get("/api/events", params={"severidade": "critico"}).json()["dados"]
    assert criticos and all(e["severidade"] == "critico" for e in criticos)


def test_diagnostico_pela_api(cliente):
    d = cliente.get("/api/diagnostics").json()["dados"]
    ids = {e["id"] for e in d["evidencias"]}
    assert d["hipoteses"]
    for h in d["hipoteses"]:
        assert h["status"] == "nao_confirmada"
        assert set(h["evidencias_ids"]) <= ids


def test_integracoes_futuras_sao_apenas_planejadas(cliente):
    itens = cliente.get("/api/integrations").json()["dados"]
    assert {i["chave"] for i in itens} == {"http", "docker", "bancos"}
    assert all(i["status"] == "planejado" and i["salvaguardas"] for i in itens)


def test_dashboard_e_estaticos(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "VPS Insight" in r.text and "DADOS SIMULADOS" in r.text
    assert cliente.get("/static/vendor/chart.umd.min.js").status_code == 200
    for js in ["app", "api", "dom", "charts"]:
        assert cliente.get(f"/static/js/{js}.js").status_code == 200
    for view in [
        "overview",
        "processes",
        "services",
        "history",
        "timeline",
        "diagnostics",
        "integrations",
        "audit",
    ]:
        assert cliente.get(f"/static/js/views/{view}.js").status_code == 200
