"""Concorrência (MASTER_PROMPT §35), desempenho com volume (§60) e configuração (§47)."""

import threading
import time
from datetime import timedelta

import pytest

from app.config import ConfiguracaoInvalida, carregar_settings
from app.models.audit import CategoriaAuditoria
from app.storage.repositories import AuditoriaRepository
from tests.conftest import AGORA


def test_escritas_concorrentes_nao_perdem_registros(db):
    repo = AuditoriaRepository(db)
    erros: list[BaseException] = []

    def escrever(n):
        try:
            for i in range(50):
                repo.registrar(AGORA, CategoriaAuditoria.REQUISICAO, f"GET /t{n}/{i}")
        except BaseException as exc:  # coleta para falhar o teste na thread principal
            erros.append(exc)

    threads = [threading.Thread(target=escrever, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not erros
    assert len(repo.listar(limite=500).itens) == 400


def test_eventos_reinseridos_nao_duplicam(cliente):
    monitor = cliente.app.state.monitor
    antes = len(monitor.eventos(horas=720, limite=1000))
    monitor.semear_historico(24, 1)  # recarga do simulado: mesmo cenário
    assert len(monitor.eventos(horas=720, limite=1000)) == antes


def test_amostragem_ao_vivo_persiste_ponto(monitor):
    ponto = monitor.amostrar()
    assert monitor.metricas_repo.ultimo() == ponto


def test_desempenho_carga_inicial_e_consultas_com_volume(monitor):
    """Orçamento folgado (máquina comum): 10 dias de histórico a cada minuto = 14.401 pontos."""
    inicio = time.perf_counter()
    assert monitor.semear_historico(horas=240, passo_min=1) == 240 * 60 + 1
    assert time.perf_counter() - inicio < 30

    inicio = time.perf_counter()
    pontos = monitor.historico(horas=240, max_pontos=360)
    assert len(pontos) <= 360
    assert time.perf_counter() - inicio < 1.0

    inicio = time.perf_counter()
    monitor.diagnostico(horas=240)
    assert time.perf_counter() - inicio < 2.0
    assert monitor.eventos(horas=240, limite=1000)[0].momento <= AGORA + timedelta(seconds=1)


@pytest.mark.parametrize("variavel", ["VPS_INSIGHT_PORTA", "VPS_INSIGHT_SEMENTE", "VPS_INSIGHT_AMOSTRAGEM_S"])
def test_variavel_numerica_invalida_tem_mensagem_clara(monkeypatch, variavel):
    monkeypatch.setenv(variavel, "oito mil")
    with pytest.raises(ConfiguracaoInvalida, match=variavel):
        carregar_settings()


def test_rota_inexistente_do_frontend_nao_quebra_roteador():
    """Regressão: '#/constructor' achava Object.prototype.constructor e quebrava a tela."""
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "app/web/static/js/app.js").read_text(encoding="utf-8")
    assert "Object.hasOwn(TELAS, r)" in js
