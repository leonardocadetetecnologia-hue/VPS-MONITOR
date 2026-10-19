from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CategoriaAuditoria(StrEnum):
    REQUISICAO = "requisicao"
    BLOQUEIO = "bloqueio"
    SISTEMA = "sistema"


class RegistroAuditoria(BaseModel):
    id: int
    momento: datetime
    categoria: CategoriaAuditoria
    acao: str
    detalhe: str | None = None
    status: int | None = None
    cliente: str | None = None
    duracao_ms: float | None = None
    request_id: str | None = None


class PaginaAuditoria(BaseModel):
    """Página por cursor: para a próxima, envie `antes_id = proximo_antes_id`."""

    itens: list[RegistroAuditoria]
    proximo_antes_id: int | None = Field(description="None quando não há mais registros")
