from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import envelope, get_monitor
from app.models import Envelope
from app.models.processes import AnaliseGrupo, ProcessoListado, ResumoProcessos
from app.monitor import Monitor

router = APIRouter(prefix="/processes", tags=["processos"])

Categoria = Literal["web", "aplicacao", "banco", "container", "sistema"]


@router.get("", response_model=Envelope[list[ProcessoListado]])
def listar(
    monitor: Annotated[Monitor, Depends(get_monitor)],
    ordenar_por: Literal["cpu", "memoria"] = "cpu",
    limite: Annotated[int, Query(ge=1, le=100)] = 15,
    busca: Annotated[
        str | None, Query(max_length=100, description="Trecho de nome, comando, usuário, unidade ou pid")
    ] = None,
    categoria: Categoria | None = None,
) -> Envelope[list[ProcessoListado]]:
    return envelope(monitor.processos(ordenar_por, limite, busca, categoria))


@router.get("/summary", response_model=Envelope[ResumoProcessos])
def resumo(monitor: Annotated[Monitor, Depends(get_monitor)]) -> Envelope[ResumoProcessos]:
    """Consumo agora, somado por grupo (unidade systemd ou nome), com participação e concentração."""
    return envelope(monitor.resumo_processos())


@router.get("/analysis", response_model=Envelope[AnaliseGrupo])
def analise(
    monitor: Annotated[Monitor, Depends(get_monitor)],
    grupo: Annotated[
        str, Query(min_length=1, max_length=200, description="Unidade systemd ou nome do processo")
    ],
    horas: Annotated[float, Query(gt=0, le=240)] = 6,
    max_pontos: Annotated[int, Query(ge=10, le=2000)] = 360,
) -> Envelope[AnaliseGrupo]:
    """Histórico do grupo: série, estatísticas, instâncias (pids) e sinais medidos."""
    return envelope(monitor.analise_processos(grupo, horas, max_pontos))
