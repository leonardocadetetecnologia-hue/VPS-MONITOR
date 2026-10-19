from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import envelope, get_monitor
from app.models import Criticidade, Envelope, EstadoAtivo, Servico
from app.monitor import Monitor

router = APIRouter(prefix="/services", tags=["servicos"])


class InventarioServicos(BaseModel):
    total: int
    por_estado: dict[str, int]
    por_criticidade: dict[str, int]
    servicos: list[Servico]


@router.get("", response_model=Envelope[InventarioServicos])
def inventario(
    monitor: Annotated[Monitor, Depends(get_monitor)],
    estado: EstadoAtivo | None = None,
    criticidade: Criticidade | None = None,
) -> Envelope[InventarioServicos]:
    todos = monitor.servicos()
    filtrados = [
        s
        for s in todos
        if (estado is None or s.estado_ativo is estado)
        and (criticidade is None or s.criticidade is criticidade)
    ]
    # Ordem de leitura investigativa: falhas primeiro, depois por nome.
    filtrados.sort(key=lambda s: (s.estado_ativo is not EstadoAtivo.FAILED, s.unidade))
    return envelope(
        InventarioServicos(
            total=len(todos),
            por_estado=dict(Counter(s.estado_ativo.value for s in todos)),
            por_criticidade=dict(Counter(s.criticidade.value for s in todos)),
            servicos=filtrados,
        )
    )
