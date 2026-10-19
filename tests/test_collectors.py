from datetime import timedelta

import pytest

from app.collectors.future import (
    ColetaRealDesabilitada,
    ColetorBancosMonitoramento,
    ColetorDockerSomenteLeitura,
    ColetorLogsApache,
    ColetorMetricasPsutil,
    ColetorProcessosPsutil,
    ColetorServicosSystemd,
)
from app.collectors.registry import construir_coletores
from app.collectors.simulated import CenarioSimulado, ColetorMetricasSimulado
from app.config import Settings
from app.models import EstadoAtivo, Origem
from tests.conftest import AGORA, relogio_fixo


def test_mesma_semente_mesmo_instante_mesmos_dados(cenario):
    outro = CenarioSimulado(ancora=AGORA, semente=42)
    assert cenario.snapshot(AGORA) == outro.snapshot(AGORA)


def test_semente_diferente_muda_o_ruido(cenario):
    outro = CenarioSimulado(ancora=AGORA, semente=7)
    assert cenario.snapshot(AGORA).cpu.uso_percentual != outro.snapshot(AGORA).cpu.uso_percentual


def test_snapshot_reflete_o_hardware_declarado(cenario):
    s = cenario.snapshot(AGORA)
    assert s.origem is Origem.SIMULADO
    assert s.cpu.nucleos == 4 and len(s.cpu.por_nucleo) == 4
    assert s.memoria.total_bytes == 15 * 1024**3
    assert {d.ponto_montagem for d in s.discos} == {"/", "/boot"}
    assert s.memoria.usado_bytes + s.memoria.disponivel_bytes == s.memoria.total_bytes


def test_valores_ficam_em_faixas_validas_por_24h(cenario):
    for minuto in range(0, 24 * 60, 7):
        s = cenario.snapshot(AGORA - timedelta(minutes=minuto))
        assert 0 <= s.cpu.uso_percentual <= 100
        assert 0 <= s.memoria.uso_percentual <= 100
        assert 0 <= s.memoria.swap_percentual <= 100
        assert all(r.rx_bytes_s >= 0 and r.tx_bytes_s >= 0 for r in s.rede)


def test_cenario_de_incidente(cenario):
    antes = cenario.snapshot(cenario.inicio_vazamento - timedelta(minutes=5))
    pico = cenario.snapshot(cenario.oom_kill - timedelta(minutes=1))
    depois = cenario.snapshot(AGORA)
    assert pico.memoria.uso_percentual > 85 > antes.memoria.uso_percentual
    assert pico.memoria.swap_percentual > 40
    assert depois.memoria.uso_percentual < 75
    # swap demora a ser devolvida: ainda acima do nível normal
    assert depois.memoria.swap_percentual > antes.memoria.swap_percentual


def test_processo_web_troca_de_pid_apos_oom(cenario):
    antes = {p.pid for p in cenario.processos(cenario.oom_kill - timedelta(minutes=1))}
    depois = {p.pid for p in cenario.processos(AGORA)}
    assert 48211 in antes and 48211 not in depois
    assert 51877 in depois


def test_servicos_incluem_unidades_em_falha(cenario):
    servicos = cenario.servicos(AGORA)
    falhas = {s.unidade for s in servicos if s.estado_ativo is EstadoAtivo.FAILED}
    assert "app-relatorios-worker.service" in falhas
    assert "app-sync-legado.service" in falhas
    assert {"apache2.service", "docker.service", "mariadb.service", "postgresql@16-main.service"} <= {
        s.unidade for s in servicos
    }
    assert all(s.origem is Origem.SIMULADO for s in servicos)


def test_aplicacoes_corporativas_sao_marcadas_como_ficticias(cenario):
    for s in cenario.servicos(AGORA):
        if s.unidade.startswith("app-"):
            assert "[Fictício]" in s.descricao


def test_eventos_roteirizados_em_ordem_e_com_id_unico(cenario):
    eventos = cenario.eventos_roteirizados()
    assert len({e.id for e in eventos}) == len(eventos)
    assert any(e.codigo == "OOM_KILL" for e in eventos)


def test_registry_monta_apenas_coletores_simulados():
    col = construir_coletores(Settings(), AGORA, relogio_fixo)
    for c in (col.metricas, col.processos, col.servicos, col.eventos):
        assert c.origem is Origem.SIMULADO
    assert isinstance(col.metricas, ColetorMetricasSimulado)
    assert col.metricas.coletar().coletado_em == AGORA


@pytest.mark.parametrize(
    "chamada",
    [
        lambda: ColetorMetricasPsutil().coletar(),
        lambda: ColetorProcessosPsutil().listar(),
        lambda: ColetorServicosSystemd().listar(),
        lambda: ColetorLogsApache().ler(AGORA, 10),
        lambda: ColetorDockerSomenteLeitura().listar_containers(),
        lambda: ColetorBancosMonitoramento().estatisticas(),
    ],
)
def test_coletores_reais_estao_bloqueados(chamada):
    with pytest.raises(ColetaRealDesabilitada):
        chamada()
