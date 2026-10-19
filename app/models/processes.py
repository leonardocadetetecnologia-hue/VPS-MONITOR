from datetime import datetime

from pydantic import BaseModel, Field

from app.models.common import Origem, Severidade


class Processo(BaseModel):
    pid: int = Field(gt=0)
    nome: str
    usuario: str
    comando: str
    categoria: str = Field(description="web | aplicacao | banco | container | sistema")
    cpu_percentual: float = Field(ge=0, description="Pode passar de 100 em processos multi-thread")
    memoria_percentual: float = Field(ge=0, le=100)
    memoria_rss_bytes: int = Field(ge=0)
    estado: str
    iniciado_em: datetime
    unidade_systemd: str | None = None
    origem: Origem


class ProcessoListado(Processo):
    """Processo como a API devolve: com o grupo de análise já resolvido pelo domínio."""

    grupo: str


# --- Análise de consumo ----------------------------------------------------


class GrupoConsumo(BaseModel):
    """Consumo somado de um grupo (unidade systemd, ou nome do processo quando não há unidade)."""

    grupo: str
    categoria: str
    processos: int = Field(ge=1)
    cpu_percentual: float = Field(ge=0)
    memoria_percentual: float = Field(ge=0)
    memoria_rss_bytes: int = Field(ge=0)
    participacao_cpu: float = Field(ge=0, le=100, description="% da CPU somada de todos os processos")
    participacao_memoria: float = Field(ge=0, le=100, description="% da memória somada de todos os processos")


class ResumoProcessos(BaseModel):
    total_processos: int = Field(ge=0)
    total_grupos: int = Field(ge=0)
    concentracao_top3_cpu: float = Field(ge=0, le=100, description="% da CPU nos 3 grupos que mais consomem")
    concentracao_top3_memoria: float = Field(ge=0, le=100)
    grupos: list[GrupoConsumo]


class AmostraProcesso(BaseModel):
    """Leitura de uma instância de processo num instante (o que o banco guarda)."""

    momento: datetime
    pid: int = Field(gt=0)
    iniciado_em: datetime
    nome: str
    cpu_percentual: float = Field(ge=0)
    memoria_percentual: float = Field(ge=0, le=100)
    memoria_rss_bytes: int = Field(ge=0)


class PontoProcesso(BaseModel):
    """Consumo somado do grupo num instante — base dos gráficos."""

    momento: datetime
    cpu_percentual: float = Field(ge=0)
    memoria_percentual: float = Field(ge=0)
    memoria_rss_bytes: int = Field(ge=0)
    processos: int = Field(ge=1)


class EstatisticaSerie(BaseModel):
    atual: float
    media: float
    minimo: float
    maximo: float
    momento_maximo: datetime


class InstanciaProcesso(BaseModel):
    """Uma execução de processo: pid + horário de início (o pid sozinho é reaproveitado)."""

    pid: int
    nome: str
    iniciado_em: datetime
    primeira_amostra: datetime
    ultima_amostra: datetime
    amostras: int = Field(ge=1)
    encerrado: bool = Field(description="Ausente na amostra mais recente do período")
    rss_atual_bytes: int = Field(ge=0, description="RSS na última amostra da instância")
    tendencia_rss_mib_h: float | None = Field(
        default=None, description="Inclinação da RSS (regressão linear)"
    )
    tendencia_r2: float | None = Field(default=None, ge=0, le=1, description="Aderência da reta (0 a 1)")
    tendencia_janela_min: int | None = Field(
        default=None, description="Minutos de leitura usados na tendência"
    )


class SinalProcesso(BaseModel):
    """Achado medido nas amostras. Não é hipótese: descreve o que os dados mostram."""

    codigo: str
    severidade: Severidade
    titulo: str
    descricao: str
    momento: datetime
    pid: int | None = None


class AnaliseGrupo(BaseModel):
    grupo: str
    horas: float
    origem: Origem
    serie: list[PontoProcesso]
    cpu: EstatisticaSerie
    memoria: EstatisticaSerie
    rss: EstatisticaSerie
    instancias: list[InstanciaProcesso]
    sinais: list[SinalProcesso]
