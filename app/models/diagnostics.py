"""Modelos de diagnóstico: separação explícita entre EVIDÊNCIA e HIPÓTESE.

- Evidência: fato observado nos dados (valor medido, estado lido, evento
  registrado). Não contém interpretação.
- Hipótese: interpretação possível, sempre ligada a evidências existentes,
  com grau de confiança e passos para confirmar. Nunca é dada como confirmada
  pelo sistema — confirmar é trabalho humano.

O validador de `Diagnostico` impede hipótese sem evidência ou apontando para
evidência inexistente, para que a separação não dependa de disciplina.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from app.models.common import Origem, Severidade


class Confianca(StrEnum):
    BAIXA = "baixa"
    MEDIA = "media"
    ALTA = "alta"


class Evidencia(BaseModel):
    id: str
    observado_em: datetime
    fonte: str = Field(description="Origem técnica do fato, ex.: metricas.memoria, systemd, timeline")
    descricao: str
    valor: float | str | None = None
    unidade: str | None = None
    limiar: float | None = None
    severidade: Severidade
    origem: Origem


class Hipotese(BaseModel):
    id: str
    titulo: str
    explicacao: str
    confianca: Confianca
    evidencias_ids: list[str] = Field(min_length=1)
    verificacoes_sugeridas: list[str] = Field(min_length=1)
    status: str = Field(default="nao_confirmada", pattern="^nao_confirmada$")


class Diagnostico(BaseModel):
    gerado_em: datetime
    origem: Origem
    aviso: str
    evidencias: list[Evidencia]
    hipoteses: list[Hipotese]

    @model_validator(mode="after")
    def _hipoteses_apontam_para_evidencias(self) -> "Diagnostico":
        ids = {e.id for e in self.evidencias}
        if len(ids) != len(self.evidencias):
            raise ValueError("IDs de evidência duplicados")
        for h in self.hipoteses:
            faltando = [i for i in h.evidencias_ids if i not in ids]
            if faltando:
                raise ValueError(f"Hipótese {h.id} referencia evidências inexistentes: {faltando}")
        return self
