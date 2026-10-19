from datetime import datetime

from pydantic import BaseModel, Field

from app.models.common import Origem

Percentual = Field(ge=0, le=100)


class CpuMetricas(BaseModel):
    nucleos: int = Field(gt=0)
    uso_percentual: float = Percentual
    por_nucleo: list[float]
    load_1: float = Field(ge=0)
    load_5: float = Field(ge=0)
    load_15: float = Field(ge=0)


class MemoriaMetricas(BaseModel):
    total_bytes: int = Field(gt=0)
    usado_bytes: int = Field(ge=0)
    disponivel_bytes: int = Field(ge=0)
    uso_percentual: float = Percentual
    swap_total_bytes: int = Field(ge=0)
    swap_usado_bytes: int = Field(ge=0)
    swap_percentual: float = Percentual


class DiscoMetricas(BaseModel):
    ponto_montagem: str
    dispositivo: str
    total_bytes: int = Field(gt=0)
    usado_bytes: int = Field(ge=0)
    uso_percentual: float = Percentual
    leitura_bytes_s: float = Field(ge=0)
    escrita_bytes_s: float = Field(ge=0)


class RedeMetricas(BaseModel):
    interface: str
    rx_bytes_s: float = Field(ge=0)
    tx_bytes_s: float = Field(ge=0)
    erros: int = Field(ge=0)
    conexoes_estabelecidas: int = Field(ge=0)


class SnapshotMetricas(BaseModel):
    """Leitura completa do host em um instante."""

    coletado_em: datetime
    origem: Origem
    cpu: CpuMetricas
    memoria: MemoriaMetricas
    discos: list[DiscoMetricas] = Field(min_length=1)
    rede: list[RedeMetricas]

    def disco_principal(self) -> DiscoMetricas:
        """Fonte única da regra "qual disco representa o host": a raiz, ou o primeiro listado."""
        return next((d for d in self.discos if d.ponto_montagem == "/"), self.discos[0])


class PontoHistorico(BaseModel):
    """Versão compacta do snapshot, persistida no SQLite para séries temporais."""

    momento: datetime
    origem: Origem
    cpu_percentual: float = Percentual
    memoria_percentual: float = Percentual
    swap_percentual: float = Percentual
    disco_percentual: float = Percentual
    rede_rx_bytes_s: float = Field(ge=0)
    rede_tx_bytes_s: float = Field(ge=0)

    @classmethod
    def de_snapshot(cls, snap: SnapshotMetricas) -> "PontoHistorico":
        raiz = snap.disco_principal()
        return cls(
            momento=snap.coletado_em,
            origem=snap.origem,
            cpu_percentual=snap.cpu.uso_percentual,
            memoria_percentual=snap.memoria.uso_percentual,
            swap_percentual=snap.memoria.swap_percentual,
            disco_percentual=raiz.uso_percentual,
            rede_rx_bytes_s=sum(r.rx_bytes_s for r in snap.rede),
            rede_tx_bytes_s=sum(r.tx_bytes_s for r in snap.rede),
        )
