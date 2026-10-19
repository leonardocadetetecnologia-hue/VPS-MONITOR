import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.collectors.registry import construir_coletores
from app.collectors.simulated import CenarioSimulado
from app.config import Settings
from app.main import create_app
from app.monitor import Monitor
from app.storage.database import Database
from app.storage.repositories import EventosRepository, MetricasRepository, ProcessosRepository

# Instante fixo: todos os testes enxergam o mesmo cenário.
AGORA = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)


def relogio_fixo() -> datetime:
    return AGORA


def _monitor(db: Database) -> Monitor:
    return Monitor(
        construir_coletores(Settings(), AGORA, relogio_fixo),
        MetricasRepository(db),
        EventosRepository(db),
        ProcessosRepository(db),
        relogio_fixo,
    )


@pytest.fixture(scope="session")
def banco_semeado(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Banco com as 24 h simuladas, gerado UMA vez por sessão (a carga leva ~1,5 s).
    Cada teste recebe uma cópia, então continuam isolados entre si."""
    caminho = tmp_path_factory.mktemp("modelo") / "semeado.sqlite3"
    db = Database(caminho)
    _monitor(db).semear_historico(horas=24, passo_min=1)
    db.fechar()  # fecha o WAL: o arquivo principal fica completo para cópia
    return caminho


@pytest.fixture
def settings(tmp_path: Path, banco_semeado: Path) -> Settings:
    destino = tmp_path / "teste.sqlite3"
    shutil.copyfile(banco_semeado, destino)
    return Settings(
        db_path=destino,
        amostragem_ao_vivo_s=0,
        historico_horas=24,
        semear_historico=False,
        hosts_confiaveis=("testserver", "127.0.0.1", "localhost"),
    )


@pytest.fixture
def cliente(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, relogio=relogio_fixo)) as c:
        yield c


@pytest.fixture
def cenario() -> CenarioSimulado:
    return CenarioSimulado(ancora=AGORA, semente=42)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    banco = Database(tmp_path / "repo.sqlite3")
    yield banco
    banco.fechar()


@pytest.fixture
def monitor(db: Database) -> Monitor:
    """Monitor completo sobre um banco temporário vazio, sem subir a API."""
    return _monitor(db)
