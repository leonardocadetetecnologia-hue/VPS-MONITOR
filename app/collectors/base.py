"""Interfaces dos coletores.

Toda fonte de dados — simulada hoje, real no futuro — implementa uma destas
classes. O resto do sistema (domínio, API) depende só das interfaces, então
trocar a fonte não exige mudar regras nem telas.

Contrato comum a todo coletor:
- declarar `origem` (SIMULADO ou REAL) e marcar cada registro com ela;
- ser somente leitura: nenhum método pode alterar o host observado;
- não abrir conexões remotas: um coletor real roda NA máquina observada,
  por decisão explícita de quem administra o servidor.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from app.models import Evento, Origem, Processo, Servico, SnapshotMetricas
from app.models.integrations import ContainerDocker, EstatisticaBanco, RegistroHttp


class Coletor(ABC):
    origem: Origem
    nome: str


class ColetorMetricas(Coletor):
    @abstractmethod
    def coletar(self) -> SnapshotMetricas:
        """Leitura de CPU, memória, swap, disco e rede no instante atual."""


class ColetorProcessos(Coletor):
    @abstractmethod
    def listar(self) -> list[Processo]:
        """Processos em execução (a ordenação/limite fica com o domínio)."""


class ColetorServicos(Coletor):
    @abstractmethod
    def listar(self) -> list[Servico]:
        """Unidades systemd e seus estados, sem classificação de criticidade."""


class FonteEventos(Coletor):
    @abstractmethod
    def eventos(self, inicio: datetime, fim: datetime) -> list[Evento]:
        """Eventos ocorridos no intervalo [inicio, fim]."""


# --- Interfaces reservadas para a próxima etapa ---------------------------


class ColetorLogsHttp(Coletor):
    @abstractmethod
    def ler(self, desde: datetime, limite: int) -> list[RegistroHttp]:
        """Linhas do access log a partir de `desde`."""


class ColetorDocker(Coletor):
    @abstractmethod
    def listar_containers(self) -> list[ContainerDocker]:
        """Containers e consumo, via API somente leitura."""


class ColetorBancos(Coletor):
    @abstractmethod
    def estatisticas(self) -> list[EstatisticaBanco]:
        """Indicadores de saúde dos bancos (usuário de monitoramento sem escrita)."""
