"""Testes de limite (MASTER_PROMPT §41): bordas de parâmetros, vazio, virada de ano, dados ausentes."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.collectors.simulated import CenarioSimulado
from app.domain.criticality import aplicar_criticidade
from app.domain.diagnostics import Contexto, gerar_diagnostico
from app.models import Origem, PontoHistorico
from app.storage.repositories import MetricasRepository, reduzir
from tests.conftest import AGORA


@pytest.mark.parametrize(
    ("url", "params", "status"),
    [
        ("/api/processes", {"limite": 1}, 200),
        ("/api/processes", {"limite": 100}, 200),
        ("/api/processes", {"limite": 0}, 422),
        ("/api/processes", {"limite": 101}, 422),
        ("/api/processes", {"limite": -1}, 422),
        ("/api/processes", {"limite": "abc"}, 422),
        ("/api/metrics/history", {"horas": 240}, 200),
        ("/api/metrics/history", {"horas": 240.01}, 422),
        ("/api/metrics/history", {"horas": 0.01}, 200),
        ("/api/metrics/history", {"max_pontos": 10}, 200),
        ("/api/metrics/history", {"max_pontos": 9}, 422),
        ("/api/metrics/history", {"max_pontos": 2001}, 422),
        ("/api/events", {"horas": 720}, 200),
        ("/api/events", {"horas": 721}, 422),
        ("/api/events", {"tipo": "inexistente"}, 422),
        ("/api/events", {"severidade": "CRITICO"}, 422),  # enum é sensível a caixa
        ("/api/services", {"estado": "failed"}, 200),
        ("/api/services", {"estado": "quebrado"}, 422),
        ("/api/audit", {"limite": 500}, 200),
        ("/api/audit", {"limite": 501}, 422),
        ("/api/audit", {"antes_id": 0}, 422),
        ("/api/audit", {"categoria": "outra"}, 422),
        ("/api/diagnostics", {"horas": 0}, 422),
    ],
)
def test_bordas_dos_parametros(cliente, url, params, status):
    assert cliente.get(url, params=params).status_code == status


def test_limite_minimo_retorna_exatamente_um(cliente):
    assert len(cliente.get("/api/processes", params={"limite": 1}).json()["dados"]) == 1


def test_filtro_sem_resultado_e_lista_vazia_nao_erro(cliente):
    r = cliente.get("/api/events", params={"horas": 0.01, "tipo": "seguranca"})
    assert r.status_code == 200 and r.json()["dados"] == []


def test_cursor_alem_do_fim_retorna_pagina_vazia(cliente):
    dados = cliente.get("/api/audit", params={"antes_id": 1}).json()["dados"]
    assert dados == {"itens": [], "proximo_antes_id": None}


def test_historico_vazio_e_diagnostico_sem_historico(db, cenario):
    repo = MetricasRepository(db)
    assert repo.intervalo(AGORA - timedelta(hours=1), AGORA) == []
    assert repo.ultimo() is None
    ctx = Contexto(
        agora=AGORA, snapshot=cenario.snapshot(AGORA), historico=[], servicos=[], processos=[], eventos=[]
    )
    diag = gerar_diagnostico(ctx)  # não pode quebrar sem dados
    assert all(h.evidencias_ids for h in diag.hipoteses)


def _ponto(momento, cpu=10.0):
    return PontoHistorico(
        momento=momento, origem=Origem.SIMULADO, cpu_percentual=cpu, memoria_percentual=40,
        swap_percentual=5, disco_percentual=70, rede_rx_bytes_s=0, rede_tx_bytes_s=0,
    )  # fmt: skip


def test_reduzir_bordas():
    um = [_ponto(AGORA)]
    assert reduzir(um, 1) == um
    tres = [_ponto(AGORA + timedelta(minutes=i), cpu=i) for i in range(3)]
    assert [p.cpu_percentual for p in reduzir(tres, 2)] == [1, 2]  # baldes de 2: máximo de cada
    with pytest.raises(ValueError):
        reduzir(tres, 0)


def test_valores_extremos_aceitos_e_fora_da_faixa_recusados():
    _ponto(AGORA, cpu=0)
    _ponto(AGORA, cpu=100)
    for invalido in (-0.1, 100.1):
        with pytest.raises(ValidationError):
            _ponto(AGORA, cpu=invalido)


def test_virada_de_ano_no_historico_e_na_ordenacao(db):
    """Comparação textual de ISO no SQLite precisa continuar cronológica na troca de ano."""
    repo = MetricasRepository(db)
    virada = datetime(2027, 1, 1, 0, 0, tzinfo=UTC)
    repo.inserir([_ponto(virada + timedelta(minutes=m)) for m in range(-30, 31, 10)])
    pontos = repo.intervalo(virada - timedelta(hours=1), virada + timedelta(hours=1))
    assert len(pontos) == 7
    assert pontos[0].momento.year == 2026 and pontos[-1].momento.year == 2027


def test_cenario_ancorado_na_virada_de_ano_e_ano_bissexto():
    for ancora in (datetime(2027, 1, 1, 0, 30, tzinfo=UTC), datetime(2028, 2, 29, 23, 59, tzinfo=UTC)):
        cen = CenarioSimulado(ancora=ancora)
        for minutos in range(0, 24 * 60, 30):
            cen.snapshot(ancora - timedelta(minutes=minutos))  # validação Pydantic garante as faixas
        assert aplicar_criticidade(cen.servicos(ancora))


def test_fuso_diferente_de_utc_e_normalizado(db):
    repo = MetricasRepository(db)
    from datetime import timezone

    sp = timezone(timedelta(hours=-3))
    repo.inserir([_ponto(datetime(2026, 10, 16, 9, 0, tzinfo=sp))])  # = 12:00 UTC
    ultimo = repo.ultimo()
    assert ultimo is not None
    assert ultimo.momento == datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def test_snapshot_sem_disco_raiz_usa_o_primeiro_e_sem_disco_e_invalido(cenario):
    snap = cenario.snapshot(AGORA)
    sem_raiz = snap.model_copy(update={"discos": [d for d in snap.discos if d.ponto_montagem != "/"]})
    assert sem_raiz.disco_principal().ponto_montagem == "/boot"
    assert PontoHistorico.de_snapshot(sem_raiz).disco_percentual == sem_raiz.discos[0].uso_percentual
    with pytest.raises(ValidationError):
        type(snap).model_validate({**snap.model_dump(), "discos": []})
