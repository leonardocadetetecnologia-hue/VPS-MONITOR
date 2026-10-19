"""Esboços dos coletores REAIS — propositalmente NÃO implementados.

Cada classe documenta como a coleta real deverá funcionar quando for
autorizada, mas qualquer chamada falha com `ColetaRealDesabilitada`.
Nenhuma biblioteca de acesso ao sistema (psutil, systemd/D-Bus, Docker SDK,
drivers de banco) é importada aqui, nem de forma tardia.

Premissas para a próxima etapa (a validar com quem administra a VPS):
- o coletor roda NA própria VPS, como usuário sem privilégios, sem SSH;
- somente leitura: psutil para métricas/processos, `systemctl show`
  via D-Bus para estados, leitura de logs com permissão de grupo `adm`;
- Docker apenas via socket com proxy somente-GET (sem acesso privilegiado);
- bancos com usuário de monitoramento sem permissão de escrita;
- envio para o dashboard por canal autenticado, nunca porta aberta pública.
"""

from datetime import datetime
from typing import NoReturn

from app.collectors.base import (
    ColetorBancos,
    ColetorDocker,
    ColetorLogsHttp,
    ColetorMetricas,
    ColetorProcessos,
    ColetorServicos,
)
from app.models import Origem, Processo, Servico, SnapshotMetricas
from app.models.integrations import ContainerDocker, EstatisticaBanco, RegistroHttp


class ColetaRealDesabilitada(RuntimeError):
    """Coleta real não faz parte desta etapa."""


def _bloqueado(nome: str) -> NoReturn:
    raise ColetaRealDesabilitada(
        f"{nome}: coleta real não implementada nesta etapa — o MVP usa apenas dados simulados."
    )


class ColetorMetricasPsutil(ColetorMetricas):
    """Futuro: psutil.cpu_percent / virtual_memory / swap_memory / disk_usage / net_io_counters."""

    origem = Origem.REAL
    nome = "metricas-psutil"

    def coletar(self) -> SnapshotMetricas:
        _bloqueado(self.nome)


class ColetorProcessosPsutil(ColetorProcessos):
    """Futuro: psutil.process_iter(['pid','name','username','cpu_percent','memory_info'])."""

    origem = Origem.REAL
    nome = "processos-psutil"

    def listar(self) -> list[Processo]:
        _bloqueado(self.nome)


class ColetorServicosSystemd(ColetorServicos):
    """Futuro: leitura de ActiveState/SubState/NRestarts via D-Bus (somente propriedades)."""

    origem = Origem.REAL
    nome = "servicos-systemd"

    def listar(self) -> list[Servico]:
        _bloqueado(self.nome)


class ColetorLogsApache(ColetorLogsHttp):
    """Futuro: tail do access.log (formato combined) com IP anonimizado por hash."""

    origem = Origem.REAL
    nome = "logs-apache"

    def ler(self, desde: datetime, limite: int) -> list[RegistroHttp]:
        _bloqueado(self.nome)


class ColetorDockerSomenteLeitura(ColetorDocker):
    """Futuro: GET /containers/json e /containers/{id}/stats via proxy somente leitura."""

    origem = Origem.REAL
    nome = "docker-leitura"

    def listar_containers(self) -> list[ContainerDocker]:
        _bloqueado(self.nome)


class ColetorBancosMonitoramento(ColetorBancos):
    """Futuro: pg_stat_activity / pg_stat_statements e SHOW GLOBAL STATUS, usuário sem escrita."""

    origem = Origem.REAL
    nome = "bancos-monitoramento"

    def estatisticas(self) -> list[EstatisticaBanco]:
        _bloqueado(self.nome)
