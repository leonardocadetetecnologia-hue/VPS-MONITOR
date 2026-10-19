from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import envelope, get_auditor
from app.audit.audit import Auditor
from app.models import Envelope
from app.models.audit import CategoriaAuditoria, PaginaAuditoria

router = APIRouter(prefix="/audit", tags=["auditoria"])


@router.get("", response_model=Envelope[PaginaAuditoria])
def trilha(
    auditor: Annotated[Auditor, Depends(get_auditor)],
    limite: Annotated[int, Query(ge=1, le=500)] = 100,
    categoria: CategoriaAuditoria | None = None,
    antes_id: Annotated[
        int | None, Query(ge=1, description="Cursor: proximo_antes_id da página anterior")
    ] = None,
) -> Envelope[PaginaAuditoria]:
    return envelope(auditor.listar(limite, categoria, antes_id))
