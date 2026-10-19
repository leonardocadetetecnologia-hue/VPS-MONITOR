"""Coletores SIMULADOS.

Geram dados plausíveis para uma VPS Ubuntu 24.04 (4 vCPU, 15 GiB RAM, Apache,
Docker, MariaDB, PostgreSQL 16, apps Next.js e Python), a partir de funções
determinísticas do tempo: a mesma semente e o mesmo instante produzem sempre
o mesmo valor. Nada aqui lê o sistema operacional.

O `CenarioSimulado` roteiriza um incidente investigável, relativo ao momento
de inicialização (`ancora`):
  - ~5h40 antes: app-relatorios-worker.service falha e esgota as tentativas;
  - ~3h10 antes: o processo Next.js de app-web-next começa a vazar memória,
    a RAM sobe, a swap passa a ser usada e a CPU sobe (kswapd);
  - ~2h25 antes: OOM killer encerra o node; o systemd reinicia o serviço;
  - depois: RAM normaliza, mas a swap ainda demora a ser devolvida.
Todos os nomes de aplicações corporativas são fictícios.
"""

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from app.collectors.base import ColetorMetricas, ColetorProcessos, ColetorServicos, FonteEventos
from app.models import (
    CpuMetricas,
    DiscoMetricas,
    EstadoAtivo,
    Evento,
    MemoriaMetricas,
    Origem,
    Processo,
    RedeMetricas,
    Servico,
    Severidade,
    SnapshotMetricas,
    TipoEvento,
)

GIB = 1024**3
MIB = 1024**2
NUCLEOS = 4
MEM_TOTAL = 15 * GIB
SWAP_TOTAL = 4 * GIB
DISCO_RAIZ_TOTAL = 193 * GIB
DISCO_BOOT_TOTAL = 2 * GIB
FUSO_LOCAL = timezone(timedelta(hours=-3))

Relogio = Callable[[], datetime]


def relogio_utc() -> datetime:
    return datetime.now(UTC)


def _limitar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


class CenarioSimulado:
    """Linha do tempo roteirizada + funções determinísticas de cada métrica."""

    def __init__(self, ancora: datetime, semente: int = 42) -> None:
        if ancora.tzinfo is None:
            raise ValueError("ancora deve ter fuso horário")
        self.ancora = ancora
        self.semente = semente
        self.boot = ancora - timedelta(days=12, hours=4)
        self.falha_sync_legado = ancora - timedelta(days=9, hours=2)
        self.falha_relatorios = ancora - timedelta(hours=5, minutes=40)
        self.atualizacao_apt = ancora - timedelta(hours=4, minutes=30)
        self.inicio_vazamento = ancora - timedelta(hours=3, minutes=10)
        self.oom_kill = ancora - timedelta(hours=2, minutes=25)
        self.reinicio_web = self.oom_kill + timedelta(minutes=1)
        self.falhas_ssh = ancora - timedelta(hours=1, minutes=40)
        self.falha_fwupd = ancora - timedelta(hours=1, minutes=5)

    # -- blocos básicos -----------------------------------------------------

    def ruido(self, momento: datetime, canal: str) -> float:
        """Ruído em [-1, 1], estável por janela de 15 s."""
        janela = int(momento.timestamp() // 15)
        # Hash da chave em vez de random.Random(chave): mesmo determinismo, ~10x mais
        # rápido (a carga de 24 h chama isto ~100 mil vezes). Não é uso criptográfico.
        digest = hashlib.blake2b(f"{self.semente}:{canal}:{janela}".encode(), digest_size=8).digest()
        return int.from_bytes(digest) / 2**63 - 1.0

    @staticmethod
    def ciclo_diario(momento: datetime) -> float:
        """[-1, 1], pico às 15h e vale às 3h (horário de Brasília)."""
        local = momento.astimezone(FUSO_LOCAL)
        hora = local.hour + local.minute / 60
        return math.sin(2 * math.pi * (hora - 9) / 24)

    def fracao_vazamento(self, momento: datetime) -> float:
        """0 fora do incidente; cresce de 0 a 1 entre início do vazamento e o OOM."""
        if not self.inicio_vazamento <= momento < self.oom_kill:
            return 0.0
        total = (self.oom_kill - self.inicio_vazamento).total_seconds()
        return (momento - self.inicio_vazamento).total_seconds() / total

    def minutos_apos_oom(self, momento: datetime) -> float | None:
        if momento < self.oom_kill:
            return None
        return (momento - self.oom_kill).total_seconds() / 60

    # -- métricas -------------------------------------------------------------

    def cpu(self, m: datetime) -> float:
        vaz = self.fracao_vazamento(m)
        valor = 20 + 10 * self.ciclo_diario(m) + 6 * self.ruido(m, "cpu") + 48 * vaz**2
        apos = self.minutos_apos_oom(m)
        if apos is not None and apos < 4:
            valor += 22  # reinício + reaquecimento de cache
        return round(_limitar(valor, 1.0, 100.0), 1)

    def memoria(self, m: datetime) -> float:
        vaz = self.fracao_vazamento(m)
        valor = 46 + 5 * self.ciclo_diario(m) + 1.5 * self.ruido(m, "mem") + 47 * vaz
        return round(_limitar(valor, 3.0, 98.5), 1)

    def swap(self, m: datetime) -> float:
        base = 5 + 0.8 * self.ruido(m, "swap")
        vaz = self.fracao_vazamento(m)
        if vaz > 0.55:
            base += (vaz - 0.55) / 0.45 * 55
        apos = self.minutos_apos_oom(m)
        if apos is not None:
            base += 55 * math.exp(-apos / 120)  # páginas em swap voltam devagar
        return round(_limitar(base, 0.0, 100.0), 1)

    def disco_raiz(self, m: datetime) -> float:
        horas = (m - self.ancora).total_seconds() / 3600
        return round(_limitar(73.1 + 0.08 * horas + 0.05 * self.ruido(m, "disco"), 0, 100), 2)

    def rede(self, m: datetime) -> tuple[float, float]:
        c = self.ciclo_diario(m)
        degradacao = 1 - 0.4 * self.fracao_vazamento(m)
        rx = 420_000 * (1 + 0.5 * c) + 60_000 * self.ruido(m, "rx")
        tx = (1_100_000 * (1 + 0.6 * c) + 150_000 * self.ruido(m, "tx")) * degradacao
        return max(rx, 0.0), max(tx, 0.0)

    def load(self, m: datetime, minutos: int) -> float:
        amostras = [m - timedelta(minutes=i) for i in range(max(1, minutos))]
        media_cpu = sum(self.cpu(a) for a in amostras) / len(amostras)
        media_vaz = sum(self.fracao_vazamento(a) for a in amostras) / len(amostras)
        return round(media_cpu / 100 * NUCLEOS * 1.1 + 2.5 * media_vaz, 2)

    def snapshot(self, m: datetime) -> SnapshotMetricas:
        cpu = self.cpu(m)
        mem = self.memoria(m)
        swap = self.swap(m)
        rx, tx = self.rede(m)
        vaz = self.fracao_vazamento(m)
        usado = int(MEM_TOTAL * mem / 100)
        swap_usado = int(SWAP_TOTAL * swap / 100)
        raiz = self.disco_raiz(m)
        return SnapshotMetricas(
            coletado_em=m,
            origem=Origem.SIMULADO,
            cpu=CpuMetricas(
                nucleos=NUCLEOS,
                uso_percentual=cpu,
                por_nucleo=[
                    round(_limitar(cpu + 9 * self.ruido(m, f"core{i}"), 0, 100), 1) for i in range(NUCLEOS)
                ],
                load_1=self.load(m, 1),
                load_5=self.load(m, 5),
                load_15=self.load(m, 15),
            ),
            memoria=MemoriaMetricas(
                total_bytes=MEM_TOTAL,
                usado_bytes=usado,
                disponivel_bytes=MEM_TOTAL - usado,
                uso_percentual=mem,
                swap_total_bytes=SWAP_TOTAL,
                swap_usado_bytes=swap_usado,
                swap_percentual=swap,
            ),
            discos=[
                DiscoMetricas(
                    ponto_montagem="/",
                    dispositivo="/dev/sda1",
                    total_bytes=DISCO_RAIZ_TOTAL,
                    usado_bytes=int(DISCO_RAIZ_TOTAL * raiz / 100),
                    uso_percentual=raiz,
                    leitura_bytes_s=max(0.0, 2.1 * MIB + 26 * MIB * vaz + 0.6 * MIB * self.ruido(m, "rd")),
                    escrita_bytes_s=max(0.0, 3.4 * MIB + 9 * MIB * vaz + 0.8 * MIB * self.ruido(m, "wr")),
                ),
                DiscoMetricas(
                    ponto_montagem="/boot",
                    dispositivo="/dev/sda16",
                    total_bytes=DISCO_BOOT_TOTAL,
                    usado_bytes=int(DISCO_BOOT_TOTAL * 0.312),
                    uso_percentual=31.2,
                    leitura_bytes_s=0.0,
                    escrita_bytes_s=0.0,
                ),
            ],
            rede=[
                RedeMetricas(
                    interface="eth0",
                    rx_bytes_s=round(rx, 1),
                    tx_bytes_s=round(tx, 1),
                    erros=0,
                    conexoes_estabelecidas=int(140 + 60 * self.ciclo_diario(m) + 15 * self.ruido(m, "conn")),
                )
            ],
        )

    # -- processos ------------------------------------------------------------

    def processos(self, m: datetime) -> list[Processo]:
        vaz = self.fracao_vazamento(m)
        apos = self.minutos_apos_oom(m)
        boot = self.boot

        if apos is None:
            web_pid, web_inicio = 48211, boot + timedelta(days=3)
            web_mem = 6.0 + 46 * vaz
        else:
            web_pid, web_inicio = 51877, self.reinicio_web
            web_mem = min(6.0 + apos * 0.01, 9.0)

        @dataclass
        class Def:
            pid: int
            nome: str
            usuario: str
            comando: str
            categoria: str
            cpu: float
            mem: float
            inicio: datetime
            unidade: str | None = None
            estado: str = "S"

        defs = [
            Def(
                web_pid,
                "node",
                "appsvc",
                "node /opt/apps/web-next/node_modules/.bin/next start -p 3000",
                "aplicacao",
                9 + 55 * vaz,
                web_mem,
                web_inicio,
                "app-web-next.service",
                "R" if vaz > 0.5 else "S",
            ),
            Def(
                3021,
                "node",
                "appsvc",
                "node /opt/apps/painel-next/server.js",
                "aplicacao",
                3.5,
                4.2,
                boot + timedelta(minutes=2),
                "app-painel-next.service",
            ),
            Def(
                2874,
                "python",
                "appsvc",
                "/opt/apps/api-python/.venv/bin/python -m uvicorn main:app --port 8001 --workers 2",
                "aplicacao",
                4.8,
                3.1,
                boot + timedelta(minutes=2),
                "app-api-python.service",
            ),
            Def(
                1340,
                "mariadbd",
                "mysql",
                "/usr/sbin/mariadbd",
                "banco",
                3.2,
                7.4,
                boot + timedelta(minutes=1),
                "mariadb.service",
            ),
            Def(
                1290,
                "postgres",
                "postgres",
                "/usr/lib/postgresql/16/bin/postgres -D /var/lib/postgresql/16/main",
                "banco",
                1.1,
                1.6,
                boot + timedelta(minutes=1),
                "postgresql@16-main.service",
            ),
            Def(
                1297,
                "postgres",
                "postgres",
                "postgres: 16/main: checkpointer",
                "banco",
                0.2,
                0.9,
                boot + timedelta(minutes=1),
                "postgresql@16-main.service",
            ),
            Def(
                1102,
                "apache2",
                "root",
                "/usr/sbin/apache2 -k start",
                "web",
                0.3,
                0.4,
                boot + timedelta(minutes=1),
                "apache2.service",
            ),
            Def(
                23110,
                "apache2",
                "www-data",
                "/usr/sbin/apache2 -k start",
                "web",
                4.0,
                0.9,
                self.ancora - timedelta(hours=6),
                "apache2.service",
            ),
            Def(
                23111,
                "apache2",
                "www-data",
                "/usr/sbin/apache2 -k start",
                "web",
                3.1,
                0.9,
                self.ancora - timedelta(hours=6),
                "apache2.service",
            ),
            Def(
                1020,
                "dockerd",
                "root",
                "/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock",
                "container",
                0.8,
                1.1,
                boot + timedelta(minutes=1),
                "docker.service",
            ),
            Def(
                980,
                "containerd",
                "root",
                "/usr/bin/containerd",
                "container",
                0.5,
                0.6,
                boot + timedelta(minutes=1),
                "containerd.service",
            ),
            Def(
                4410,
                "redis-server",
                "999",
                "redis-server *:6379 (container cache-sessoes)",
                "container",
                0.9,
                0.7,
                boot + timedelta(minutes=3),
            ),
            Def(
                412,
                "systemd-journal",
                "root",
                "/usr/lib/systemd/systemd-journald",
                "sistema",
                0.4,
                0.5,
                boot,
                "systemd-journald.service",
            ),
            Def(
                95,
                "kswapd0",
                "root",
                "[kswapd0]",
                "sistema",
                0.0 + 22 * max(0.0, vaz - 0.5) * 2,
                0.0,
                boot,
                None,
                "R" if vaz > 0.6 else "S",
            ),
            Def(
                1050,
                "sshd",
                "root",
                "sshd: /usr/sbin/sshd -D [listener]",
                "sistema",
                0.0,
                0.1,
                boot + timedelta(minutes=1),
                "ssh.service",
            ),
            Def(1, "systemd", "root", "/sbin/init", "sistema", 0.1, 0.1, boot),
        ]

        processos = []
        for d in defs:
            fator = 1 + 0.35 * self.ruido(m, f"p{d.pid}")
            mem = round(_limitar(d.mem * (1 + 0.03 * self.ruido(m, f"pm{d.pid}")), 0, 100), 2)
            processos.append(
                Processo(
                    pid=d.pid,
                    nome=d.nome,
                    usuario=d.usuario,
                    comando=d.comando,
                    categoria=d.categoria,
                    cpu_percentual=round(max(0.0, d.cpu * fator), 1),
                    memoria_percentual=mem,
                    memoria_rss_bytes=int(MEM_TOTAL * mem / 100),
                    estado=d.estado,
                    iniciado_em=d.inicio,
                    unidade_systemd=d.unidade,
                    origem=Origem.SIMULADO,
                )
            )
        return processos

    # -- serviços -------------------------------------------------------------

    def servicos(self, m: datetime) -> list[Servico]:
        procs = {p.unidade_systemd: p for p in self.processos(m) if p.unidade_systemd}
        apos = self.minutos_apos_oom(m)
        boot_ok = self.boot + timedelta(minutes=1)

        def ativo(unidade, descricao, categoria, desde=boot_ok, reinicios=0):
            p = procs.get(unidade)
            return Servico(
                unidade=unidade,
                descricao=descricao,
                categoria=categoria,
                estado_ativo=EstadoAtivo.ACTIVE,
                sub_estado="running",
                habilitado=True,
                desde=desde,
                reinicios_24h=reinicios,
                pid_principal=p.pid if p else None,
                memoria_bytes=p.memoria_rss_bytes if p else None,
                origem=Origem.SIMULADO,
            )

        web_desde = self.reinicio_web if apos is not None else self.boot + timedelta(days=3)
        lista = [
            ativo("apache2.service", "The Apache HTTP Server", "web"),
            ativo("docker.service", "Docker Application Container Engine", "container"),
            ativo("containerd.service", "containerd container runtime", "container"),
            ativo("mariadb.service", "MariaDB 10.11 database server", "banco"),
            ativo("postgresql@16-main.service", "PostgreSQL Cluster 16-main", "banco"),
            ativo("ssh.service", "OpenBSD Secure Shell server", "sistema"),
            ativo("cron.service", "Regular background program processing daemon", "sistema"),
            ativo("systemd-journald.service", "Journal Service", "sistema", desde=self.boot),
            ativo(
                "app-web-next.service",
                "[Fictício] Portal web Next.js",
                "aplicacao",
                desde=web_desde,
                reinicios=1 if apos is not None else 0,
            ),
            ativo("app-painel-next.service", "[Fictício] Painel administrativo Next.js", "aplicacao"),
            ativo("app-api-python.service", "[Fictício] API Python (uvicorn)", "aplicacao"),
        ]
        if m >= self.falha_relatorios:
            lista.append(
                Servico(
                    unidade="app-relatorios-worker.service",
                    descricao="[Fictício] Worker de relatórios (Python)",
                    categoria="aplicacao",
                    estado_ativo=EstadoAtivo.FAILED,
                    sub_estado="failed",
                    habilitado=True,
                    desde=self.falha_relatorios + timedelta(minutes=1),
                    reinicios_24h=3,
                    origem=Origem.SIMULADO,
                )
            )
        lista.append(
            Servico(
                unidade="app-sync-legado.service",
                descricao="[Fictício] Sincronização com sistema legado",
                categoria="aplicacao",
                estado_ativo=EstadoAtivo.FAILED,
                sub_estado="failed",
                habilitado=True,
                desde=self.falha_sync_legado,
                reinicios_24h=0,
                origem=Origem.SIMULADO,
            )
        )
        if m >= self.falha_fwupd:
            lista.append(
                Servico(
                    unidade="fwupd-refresh.service",
                    descricao="Refresh fwupd metadata and update motd",
                    categoria="sistema",
                    estado_ativo=EstadoAtivo.FAILED,
                    sub_estado="failed",
                    habilitado=False,
                    desde=self.falha_fwupd,
                    reinicios_24h=0,
                    origem=Origem.SIMULADO,
                )
            )
        lista.append(
            Servico(
                unidade="app-backup-noturno.service",
                descricao="[Fictício] Backup noturno (disparado por timer)",
                categoria="aplicacao",
                estado_ativo=EstadoAtivo.INACTIVE,
                sub_estado="dead",
                habilitado=True,
                desde=self.ancora - timedelta(hours=10),
                reinicios_24h=0,
                origem=Origem.SIMULADO,
            )
        )
        return lista

    # -- eventos --------------------------------------------------------------

    def eventos_roteirizados(self) -> list[Evento]:
        def ev(momento, tipo, sev, codigo, titulo, descricao, recurso=None):
            return Evento(
                id=f"sim-{codigo.lower()}-{int(momento.timestamp())}",
                momento=momento,
                tipo=tipo,
                severidade=sev,
                codigo=codigo,
                titulo=titulo,
                descricao=descricao,
                recurso=recurso,
                origem=Origem.SIMULADO,
            )

        T, S = TipoEvento, Severidade
        return [
            ev(
                self.boot,
                T.SISTEMA,
                S.INFO,
                "BOOT",
                "Sistema inicializado",
                "Kernel 6.8 carregado; Ubuntu 24.04.4 LTS.",
            ),
            ev(
                self.falha_sync_legado,
                T.SERVICO,
                S.ALTO,
                "SERVICE_FAILED",
                "app-sync-legado.service entrou em falha",
                "Processo principal saiu com código 2. Nenhuma tentativa de reinício configurada.",
                "app-sync-legado.service",
            ),
            ev(
                self.falha_relatorios,
                T.SERVICO,
                S.ALTO,
                "SERVICE_FAILED",
                "app-relatorios-worker.service entrou em falha",
                "Processo principal saiu com código 1 (status=1/FAILURE).",
                "app-relatorios-worker.service",
            ),
            ev(
                self.falha_relatorios + timedelta(minutes=1),
                T.SERVICO,
                S.ALTO,
                "SERVICE_START_LIMIT",
                "app-relatorios-worker.service atingiu o limite de reinícios",
                "3 tentativas em 60 s; systemd parou de tentar (start-limit-hit).",
                "app-relatorios-worker.service",
            ),
            ev(
                self.atualizacao_apt,
                T.SISTEMA,
                S.INFO,
                "APT_UPGRADE",
                "Atualizações automáticas aplicadas",
                "unattended-upgrades instalou 4 pacotes de segurança.",
            ),
            ev(
                self.inicio_vazamento + timedelta(minutes=25),
                T.PROCESSO,
                S.AVISO,
                "PROCESSO_RSS_ALTO",
                "Processo node (app-web-next) passou de 2 GiB de RSS",
                "Crescimento contínuo de memória residente sem queda correspondente.",
                "app-web-next.service",
            ),
            ev(
                self.oom_kill,
                T.PROCESSO,
                S.CRITICO,
                "OOM_KILL",
                "OOM killer encerrou o processo node (pid 48211)",
                "Kernel: Out of memory: Killed process 48211 (node) total-vm 11.2 GiB, anon-rss 7.6 GiB.",
                "app-web-next.service",
            ),
            ev(
                self.reinicio_web,
                T.SERVICO,
                S.AVISO,
                "SERVICE_RESTART",
                "app-web-next.service reiniciado pelo systemd",
                "Restart=on-failure; novo pid 51877.",
                "app-web-next.service",
            ),
            ev(
                self.falhas_ssh,
                T.SEGURANCA,
                S.AVISO,
                "SSH_FALHAS",
                "Tentativas de login SSH malsucedidas",
                "17 falhas de autenticação em 2 minutos a partir do mesmo endereço externo (anonimizado).",
            ),
            ev(
                self.falha_fwupd,
                T.SERVICO,
                S.AVISO,
                "SERVICE_FAILED",
                "fwupd-refresh.service entrou em falha",
                "Falha ao baixar metadados (comum em servidores sem firmware gerenciável).",
                "fwupd-refresh.service",
            ),
        ]


# --- Adaptadores para as interfaces de coletor ---------------------------


class _BaseSimulada:
    origem = Origem.SIMULADO

    def __init__(self, cenario: CenarioSimulado, relogio: Relogio = relogio_utc) -> None:
        self.cenario = cenario
        self.relogio = relogio


class ColetorMetricasSimulado(_BaseSimulada, ColetorMetricas):
    nome = "metricas-simuladas"

    def coletar(self) -> SnapshotMetricas:
        return self.cenario.snapshot(self.relogio())

    def coletar_em(self, momento: datetime) -> SnapshotMetricas:
        """Exclusivo do simulador: permite gerar o histórico retroativo."""
        return self.cenario.snapshot(momento)


class ColetorProcessosSimulado(_BaseSimulada, ColetorProcessos):
    nome = "processos-simulados"

    def listar(self) -> list[Processo]:
        return self.cenario.processos(self.relogio())

    def listar_em(self, momento: datetime) -> list[Processo]:
        """Exclusivo do simulador: permite gerar o histórico retroativo."""
        return self.cenario.processos(momento)


class ColetorServicosSimulado(_BaseSimulada, ColetorServicos):
    nome = "servicos-simulados"

    def listar(self) -> list[Servico]:
        return self.cenario.servicos(self.relogio())


class FonteEventosSimulada(_BaseSimulada, FonteEventos):
    nome = "eventos-simulados"

    def eventos(self, inicio: datetime, fim: datetime) -> list[Evento]:
        return [e for e in self.cenario.eventos_roteirizados() if inicio <= e.momento <= fim]
