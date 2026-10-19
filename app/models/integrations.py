"""Modelos reservados para integrações futuras (logs HTTP, Docker, bancos).

Existem para fixar o contrato de dados antes da coleta real. Nenhum coletor
os preenche nesta etapa.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.common import Origem


class RegistroHttp(BaseModel):
    """Linha de access log do Apache (combined), já parseada."""

    momento: datetime
    vhost: str
    metodo: str
    caminho: str
    status: int = Field(ge=100, le=599)
    bytes_resposta: int = Field(ge=0)
    duracao_ms: float | None = None
    ip_cliente_hash: str = Field(description="IP anonimizado (hash) — nunca o IP em claro")
    user_agent: str | None = None
    origem: Origem


class ContainerDocker(BaseModel):
    id_curto: str
    nome: str
    imagem: str
    estado: str
    saude: str | None = None
    reinicios: int = Field(ge=0)
    cpu_percentual: float = Field(ge=0)
    memoria_bytes: int = Field(ge=0)
    origem: Origem


class EstatisticaBanco(BaseModel):
    motor: str = Field(description="postgresql | mariadb")
    instancia: str
    conexoes_ativas: int = Field(ge=0)
    conexoes_max: int = Field(gt=0)
    consultas_lentas_15min: int = Field(ge=0)
    tamanho_total_bytes: int = Field(ge=0)
    replicacao_atraso_s: float | None = None
    origem: Origem


class IntegracaoPlanejada(BaseModel):
    chave: str
    nome: str
    status: str = "planejado"
    descricao: str
    modelo: str
    campos: list[str]
    fonte_prevista: str
    salvaguardas: list[str]
