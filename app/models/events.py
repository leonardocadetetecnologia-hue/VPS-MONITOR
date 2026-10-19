from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.models.common import Origem, Severidade


class TipoEvento(StrEnum):
    METRICA = "metrica"
    SERVICO = "servico"
    PROCESSO = "processo"
    SISTEMA = "sistema"
    SEGURANCA = "seguranca"


class Evento(BaseModel):
    """Item da linha do tempo. `codigo` é estável e serve às regras de diagnóstico."""

    id: str
    momento: datetime
    tipo: TipoEvento
    severidade: Severidade
    codigo: str
    titulo: str
    descricao: str
    recurso: str | None = None
    origem: Origem
