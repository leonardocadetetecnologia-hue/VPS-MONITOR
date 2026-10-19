from fastapi import APIRouter, Request

from app import __version__
from app.models import AVISO_SIMULADO

router = APIRouter(tags=["sistema"])


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    s = request.app.state.settings
    return {
        "status": "ok",
        "versao": __version__,
        "modo": s.modo,
        "origem": "SIMULADO",
        "aviso": AVISO_SIMULADO,
        "coleta_real": False,
        "pontos_historico": request.app.state.monitor.metricas_repo.contar(),
        "versao_banco": request.app.state.monitor.metricas_repo.db.versao(),
    }
