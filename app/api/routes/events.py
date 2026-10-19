from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import envelope, get_monitor
from app.models import Envelope, Evento, Severidade, TipoEvento
from app.monitor import Monitor

router = APIRouter(prefix="/events", tags=["linha-do-tempo"])


@router.get("", response_model=Envelope[list[Evento]])
def linha_do_tempo(
    monitor: Annotated[Monitor, Depends(get_monitor)],
    horas: Annotated[float, Query(gt=0, le=24 * 30)] = 24,
    tipo: TipoEvento | None = None,
    severidade: Severidade | None = None,
    limite: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> Envelope[list[Evento]]:
    return envelope(monitor.eventos(horas, tipo, severidade, limite))
