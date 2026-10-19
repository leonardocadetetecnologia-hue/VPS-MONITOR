from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import envelope, get_monitor
from app.models import Envelope, Nivel, PontoHistorico, SnapshotMetricas
from app.monitor import Monitor

router = APIRouter(prefix="/metrics", tags=["metricas"])


class ResumoMetricas(BaseModel):
    snapshot: SnapshotMetricas
    niveis: dict[str, Nivel]
    limiares: dict[str, dict[str, float | str]]


@router.get("/current", response_model=Envelope[ResumoMetricas])
def atual(monitor: Annotated[Monitor, Depends(get_monitor)]) -> Envelope[ResumoMetricas]:
    snap = monitor.snapshot()
    return envelope(ResumoMetricas(snapshot=snap, niveis=monitor.niveis(snap), limiares=monitor.limiares()))


@router.get("/history", response_model=Envelope[list[PontoHistorico]])
def historico(
    monitor: Annotated[Monitor, Depends(get_monitor)],
    horas: Annotated[float, Query(gt=0, le=240)] = 6,
    max_pontos: Annotated[int, Query(ge=10, le=2000)] = 360,
) -> Envelope[list[PontoHistorico]]:
    return envelope(monitor.historico(horas, max_pontos))
