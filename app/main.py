"""Ponto de entrada: `python -m app.main` sobe o servidor em 127.0.0.1.

Não há serviço systemd, agendamento nem inicialização automática: o servidor
só existe enquanto este processo estiver rodando no terminal de quem o abriu.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.errors import registrar_tratadores
from app.api.router import api_router
from app.audit.audit import Auditor
from app.collectors.registry import construir_coletores
from app.collectors.simulated import Relogio
from app.config import Settings, carregar_settings
from app.monitor import Monitor
from app.security.middleware import SegurancaAuditoriaMiddleware
from app.storage.database import Database
from app.storage.repositories import (
    AuditoriaRepository,
    EventosRepository,
    MetricasRepository,
    ProcessosRepository,
)

log = logging.getLogger("vps_insight")
STATIC_DIR = Path(__file__).parent / "web" / "static"
# Linha de log no formato chave=valor: legível no terminal e fácil de filtrar (grep request_id=...).
FORMATO_LOG = "%(asctime)s nivel=%(levelname)s origem=%(name)s %(message)s"


def _relogio() -> datetime:
    return datetime.now(UTC)


async def _amostragem(monitor: Monitor, intervalo_s: int) -> None:
    while True:
        await asyncio.sleep(intervalo_s)
        try:
            await asyncio.to_thread(monitor.amostrar)
        except Exception:  # amostragem nunca derruba o servidor
            log.exception("Falha na amostragem simulada")


def create_app(settings: Settings | None = None, relogio: Relogio = _relogio) -> FastAPI:
    settings = settings or carregar_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.db_path)
        auditor = Auditor(AuditoriaRepository(db), relogio)
        ancora = relogio()
        monitor = Monitor(
            construir_coletores(settings, ancora, relogio),
            MetricasRepository(db),
            EventosRepository(db),
            ProcessosRepository(db),
            relogio,
        )
        app.state.settings = settings
        app.state.auditor = auditor
        app.state.monitor = monitor

        auditor.sistema("inicializacao", f"modo={settings.modo}; host={settings.host}; versao={__version__}")
        if settings.semear_historico:
            pontos = monitor.semear_historico(settings.historico_horas, settings.passo_historico_min)
            auditor.sistema("historico_simulado", f"{pontos} pontos gerados ({settings.historico_horas}h)")

        tarefa = None
        if settings.amostragem_ao_vivo_s > 0:
            tarefa = asyncio.create_task(_amostragem(monitor, settings.amostragem_ao_vivo_s))
        try:
            yield
        finally:
            if tarefa:
                tarefa.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tarefa
            auditor.sistema("encerramento")
            db.fechar()

    app = FastAPI(
        title="VPS Insight",
        version=__version__,
        description="Monitoramento investigativo de VPS — **MVP com dados SIMULADOS**.",
        lifespan=lifespan,
    )
    app.state.auditor = None
    app.add_middleware(
        SegurancaAuditoriaMiddleware,
        auditor_fn=lambda: getattr(app.state, "auditor", None),
        hosts_confiaveis=settings.hosts_confiaveis,
    )
    registrar_tratadores(app)
    app.include_router(api_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def main() -> None:
    import uvicorn

    settings = carregar_settings()  # valida modo e host antes de qualquer coisa
    logging.basicConfig(level=logging.INFO, format=FORMATO_LOG)
    print(f"VPS Insight {__version__} — modo SIMULADO — http://{settings.host}:{settings.porta}")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.porta, log_level="info")


if __name__ == "__main__":
    main()
