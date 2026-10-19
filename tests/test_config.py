import pytest

from app.config import ConfiguracaoInvalida, Settings, carregar_settings


def test_padrao_e_simulado_em_loopback():
    s = Settings()
    assert s.modo == "simulado"
    assert s.host == "127.0.0.1"


@pytest.mark.parametrize("modo", ["real", "producao", "REAL", ""])
def test_recusa_modo_diferente_de_simulado(modo):
    with pytest.raises(ConfiguracaoInvalida, match="simulado"):
        Settings(modo=modo)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.0.10", "srv.exemplo.com"])
def test_recusa_host_fora_do_loopback(host):
    with pytest.raises(ConfiguracaoInvalida, match="loopback"):
        Settings(host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_aceita_loopback(host):
    assert Settings(host=host).host == host


def test_recusa_porta_privilegiada():
    with pytest.raises(ConfiguracaoInvalida):
        Settings(porta=80)


def test_variavel_de_ambiente_nao_contorna_validacao(monkeypatch):
    monkeypatch.setenv("VPS_INSIGHT_HOST", "0.0.0.0")
    with pytest.raises(ConfiguracaoInvalida):
        carregar_settings()
    monkeypatch.setenv("VPS_INSIGHT_HOST", "127.0.0.1")
    monkeypatch.setenv("VPS_INSIGHT_MODO", "real")
    with pytest.raises(ConfiguracaoInvalida):
        carregar_settings()
