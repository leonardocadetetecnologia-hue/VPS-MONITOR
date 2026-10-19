from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

AVISO_SIMULADO = (
    "DADOS SIMULADOS — gerados localmente para demonstração. "
    "Nenhuma informação foi coletada da VPS de produção."
)


class Origem(StrEnum):
    """De onde veio o dado. Todo registro carrega sua origem."""

    SIMULADO = "SIMULADO"
    REAL = "REAL"  # reservado para coletores futuros; não utilizado no MVP


class Severidade(StrEnum):
    INFO = "info"
    AVISO = "aviso"
    ALTO = "alto"
    CRITICO = "critico"


class Nivel(StrEnum):
    """Classificação de uma métrica frente aos limiares do domínio."""

    NORMAL = "normal"
    AVISO = "aviso"
    ALTO = "alto"
    CRITICO = "critico"


class Envelope[T](BaseModel):
    """Formato padrão de resposta da API: o dado sempre acompanhado da origem."""

    origem: Origem
    aviso: str
    gerado_em: datetime
    dados: T = Field(description="Conteúdo da resposta")
