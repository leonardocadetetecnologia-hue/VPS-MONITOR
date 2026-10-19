from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.common import Origem


class EstadoAtivo(StrEnum):
    """ActiveState do systemd."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    ACTIVATING = "activating"


class Criticidade(StrEnum):
    CRITICA = "critica"
    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"
    INDEFINIDA = "indefinida"  # ainda não acordada com o responsável


class Servico(BaseModel):
    unidade: str
    descricao: str
    categoria: str = Field(description="web | aplicacao | banco | container | sistema")
    estado_ativo: EstadoAtivo
    sub_estado: str
    habilitado: bool
    desde: datetime
    reinicios_24h: int = Field(ge=0)
    pid_principal: int | None = None
    memoria_bytes: int | None = Field(default=None, ge=0)
    criticidade: Criticidade = Criticidade.INDEFINIDA
    justificativa_criticidade: str = "Não classificada"
    origem: Origem
