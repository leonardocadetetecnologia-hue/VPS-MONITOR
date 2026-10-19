from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import envelope, get_monitor
from app.models import Diagnostico, Envelope
from app.monitor import Monitor

router = APIRouter(prefix="/diagnostics", tags=["diagnostico"])


@router.get("", response_model=Envelope[Diagnostico])
def diagnostico(
    monitor: Annotated[Monitor, Depends(get_monitor)],
    horas: Annotated[float, Query(gt=0, le=240)] = 24,
) -> Envelope[Diagnostico]:
    return envelope(monitor.diagnostico(horas))
