from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.domain.criticality import aplicar_criticidade
from app.domain.diagnostics import Contexto, gerar_diagnostico
from app.domain.thresholds import classificar
from app.domain.timeline import eventos_de_transicao
from app.models import (
    Confianca,
    Criticidade,
    Diagnostico,
    Evidencia,
    Hipotese,
    Nivel,
    Origem,
    PontoHistorico,
    Severidade,
)
from tests.conftest import AGORA


@pytest.mark.parametrize(
    "metrica,valor,esperado",
    [
        ("cpu", 10, Nivel.NORMAL),
        ("cpu", 70, Nivel.AVISO),
        ("cpu", 90, Nivel.ALTO),
        ("cpu", 99, Nivel.CRITICO),
        ("swap", 19.9, Nivel.NORMAL),
        ("swap", 20, Nivel.AVISO),
        ("memoria", 93, Nivel.CRITICO),
    ],
)
def test_classificacao_por_limiar(metrica, valor, esperado):
    assert classificar(metrica, valor) is esperado


def test_criticidade_infra_por_regra_e_apps_indefinidas(cenario):
    servicos = {s.unidade: s for s in aplicar_criticidade(cenario.servicos(AGORA))}
    assert servicos["apache2.service"].criticidade is Criticidade.ALTA
    assert servicos["postgresql@16-main.service"].criticidade is Criticidade.ALTA
    assert servicos["fwupd-refresh.service"].criticidade is Criticidade.BAIXA
    for nome, s in servicos.items():
        if nome.startswith("app-"):
            assert s.criticidade is Criticidade.INDEFINIDA
            assert "Pendente" in s.justificativa_criticidade


def _ponto(cpu=10, mem=40, swap=5):
    return PontoHistorico(
        momento=AGORA,
        origem=Origem.SIMULADO,
        cpu_percentual=cpu,
        memoria_percentual=mem,
        swap_percentual=swap,
        disco_percentual=70,
        rede_rx_bytes_s=0,
        rede_tx_bytes_s=0,
    )


def test_transicao_gera_evento_ao_subir_e_ao_recuar():
    subiu = eventos_de_transicao(_ponto(mem=40), _ponto(mem=88))
    assert [e.codigo for e in subiu] == ["LIMIAR_MEMORIA_SUBIU"]
    assert subiu[0].severidade is Severidade.ALTO
    recuou = eventos_de_transicao(_ponto(mem=88), _ponto(mem=40))
    assert recuou[0].codigo == "LIMIAR_MEMORIA_RECUOU" and recuou[0].severidade is Severidade.INFO
    assert eventos_de_transicao(_ponto(), _ponto()) == []


def _contexto(cenario):
    historico = [
        PontoHistorico.de_snapshot(cenario.snapshot(AGORA - timedelta(minutes=m)))
        for m in range(24 * 60, -1, -5)
    ]
    return Contexto(
        agora=AGORA,
        snapshot=cenario.snapshot(AGORA),
        historico=historico,
        servicos=aplicar_criticidade(cenario.servicos(AGORA)),
        processos=cenario.processos(AGORA),
        eventos=cenario.eventos_roteirizados(),
    )


def test_diagnostico_separa_evidencias_de_hipoteses(cenario):
    d = gerar_diagnostico(_contexto(cenario))
    ids_ev = {e.id for e in d.evidencias}
    assert d.evidencias and d.hipoteses
    for h in d.hipoteses:
        assert h.status == "nao_confirmada"
        assert set(h.evidencias_ids) <= ids_ev
        assert h.verificacoes_sugeridas
    # evidência é fato: não carrega confiança nem verificação
    assert "confianca" not in Evidencia.model_fields


def test_diagnostico_encontra_o_incidente_roteirizado(cenario):
    d = gerar_diagnostico(_contexto(cenario))
    ids_h = {h.id for h in d.hipoteses}
    assert {"H-vazamento-memoria", "H-swap-residual", "H-unidades-orfas"} <= ids_h
    fontes = {e.fonte for e in d.evidencias}
    assert {"timeline.OOM_KILL", "historico.memoria", "systemd"} <= fontes


def test_hipotese_sem_evidencia_e_recusada():
    with pytest.raises(ValidationError):
        Hipotese(
            id="h",
            titulo="t",
            explicacao="e",
            confianca=Confianca.BAIXA,
            evidencias_ids=[],
            verificacoes_sugeridas=["v"],
        )


def test_hipotese_apontando_para_evidencia_inexistente_e_recusada():
    h = Hipotese(
        id="h",
        titulo="t",
        explicacao="e",
        confianca=Confianca.BAIXA,
        evidencias_ids=["E-nao-existe"],
        verificacoes_sugeridas=["v"],
    )
    with pytest.raises(ValidationError, match="inexistentes"):
        Diagnostico(gerado_em=AGORA, origem=Origem.SIMULADO, aviso="", evidencias=[], hipoteses=[h])


def test_hipotese_nao_pode_nascer_confirmada():
    with pytest.raises(ValidationError):
        Hipotese(
            id="h",
            titulo="t",
            explicacao="e",
            confianca=Confianca.ALTA,
            evidencias_ids=["E1"],
            verificacoes_sugeridas=["v"],
            status="confirmada",
        )
