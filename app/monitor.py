"""Camada de aplicação: orquestra coletores, regras de domínio e persistência.

As rotas da API chamam apenas o `Monitor`; ele decide de onde vêm os dados
(coletor ou SQLite) e aplica as regras de negócio antes de devolver.
"""

from datetime import datetime, timedelta

from app.collectors.registry import Coletores
from app.collectors.simulated import ColetorMetricasSimulado, ColetorProcessosSimulado, Relogio
from app.domain.criticality import aplicar_criticidade
from app.domain.diagnostics import Contexto, gerar_diagnostico
from app.domain.processes import analisar_grupo, filtrar, grupo_de, resumir, selecionar_para_amostra
from app.domain.thresholds import LIMIARES, classificar, fmt
from app.domain.timeline import eventos_de_transicao
from app.errors import NaoEncontrado
from app.models import (
    Diagnostico,
    Evento,
    Nivel,
    Origem,
    PontoHistorico,
    Processo,
    Servico,
    Severidade,
    SnapshotMetricas,
    TipoEvento,
)
from app.models.processes import AnaliseGrupo, ProcessoListado, ResumoProcessos
from app.storage.repositories import EventosRepository, MetricasRepository, ProcessosRepository


class Monitor:
    def __init__(
        self,
        coletores: Coletores,
        metricas: MetricasRepository,
        eventos: EventosRepository,
        processos: ProcessosRepository,
        relogio: Relogio,
    ) -> None:
        self.coletores = coletores
        self.metricas_repo = metricas
        self.eventos_repo = eventos
        self.processos_repo = processos
        self.relogio = relogio

    # -- carga e amostragem --------------------------------------------------

    def semear_historico(self, horas: int, passo_min: int) -> int:
        """Recria o histórico SIMULADO das últimas `horas` (dados reais nunca são tocados)."""
        coletor = self.coletores.metricas
        if not isinstance(coletor, ColetorMetricasSimulado):
            return 0
        coletor_proc = self.coletores.processos
        self.metricas_repo.limpar_origem(Origem.SIMULADO)
        self.eventos_repo.limpar_origem(Origem.SIMULADO)
        self.processos_repo.limpar_origem(Origem.SIMULADO)

        fim = self.relogio().replace(second=0, microsecond=0)
        inicio = fim - timedelta(hours=horas)
        pontos: list[PontoHistorico] = []
        eventos: list[Evento] = []
        leituras_proc: list[tuple[datetime, Processo, str]] = []
        anterior: PontoHistorico | None = None
        momento = inicio
        while momento <= fim:
            ponto = PontoHistorico.de_snapshot(coletor.coletar_em(momento))
            eventos.extend(eventos_de_transicao(anterior, ponto))
            pontos.append(ponto)
            anterior = ponto
            if isinstance(coletor_proc, ColetorProcessosSimulado):
                leituras_proc += self._leituras_processos(momento, coletor_proc.listar_em(momento))
            momento += timedelta(minutes=passo_min)

        # Eventos roteirizados cobrem uma janela maior (falhas antigas também contam).
        eventos.extend(self.coletores.eventos.eventos(inicio - timedelta(days=30), fim))
        self.metricas_repo.inserir(pontos)
        self.eventos_repo.inserir(eventos)
        self.processos_repo.inserir(leituras_proc)
        return len(pontos)

    @staticmethod
    def _leituras_processos(
        momento: datetime, processos: list[Processo]
    ) -> list[tuple[datetime, Processo, str]]:
        return [(momento, p, grupo_de(p)) for p in selecionar_para_amostra(processos)]

    def amostrar(self) -> PontoHistorico:
        """Uma leitura nova (métricas + maiores processos), persistida, com eventos de transição."""
        anterior = self.metricas_repo.ultimo()
        ponto = PontoHistorico.de_snapshot(self.coletores.metricas.coletar())
        self.metricas_repo.inserir([ponto])
        self.eventos_repo.inserir(eventos_de_transicao(anterior, ponto))
        self.processos_repo.inserir(
            self._leituras_processos(ponto.momento, self.coletores.processos.listar())
        )
        return ponto

    # -- consultas -------------------------------------------------------------

    def snapshot(self) -> SnapshotMetricas:
        return self.coletores.metricas.coletar()

    def niveis(self, snap: SnapshotMetricas) -> dict[str, Nivel]:
        raiz = snap.disco_principal()
        return {
            "cpu": classificar("cpu", snap.cpu.uso_percentual),
            "memoria": classificar("memoria", snap.memoria.uso_percentual),
            "swap": classificar("swap", snap.memoria.swap_percentual),
            "disco": classificar("disco", raiz.uso_percentual),
        }

    @staticmethod
    def limiares() -> dict[str, dict[str, float | str]]:
        return {
            k: {"aviso": lim.aviso, "alto": lim.alto, "critico": lim.critico, "rotulo": lim.rotulo}
            for k, lim in LIMIARES.items()
        }

    def historico(self, horas: float, max_pontos: int) -> list[PontoHistorico]:
        fim = self.relogio()
        return self.metricas_repo.intervalo(fim - timedelta(hours=horas), fim, max_pontos)

    def processos(
        self,
        ordenar_por: str = "cpu",
        limite: int = 15,
        busca: str | None = None,
        categoria: str | None = None,
    ) -> list[ProcessoListado]:
        chave = "memoria_percentual" if ordenar_por == "memoria" else "cpu_percentual"
        candidatos = filtrar(self.coletores.processos.listar(), busca, categoria)
        maiores = sorted(candidatos, key=lambda p: getattr(p, chave), reverse=True)[:limite]
        return [ProcessoListado(**p.model_dump(), grupo=grupo_de(p)) for p in maiores]

    def resumo_processos(self) -> ResumoProcessos:
        return resumir(self.coletores.processos.listar())

    def analise_processos(self, grupo: str, horas: float, max_pontos: int = 360) -> AnaliseGrupo:
        fim = self.relogio()
        amostras = self.processos_repo.amostras_grupo(grupo, fim - timedelta(hours=horas), fim)
        if not amostras:
            raise NaoEncontrado(f"Nenhuma amostra do grupo “{grupo}” nas últimas {fmt(horas)} h.")
        return analisar_grupo(
            grupo,
            amostras,
            horas,
            ram_total_bytes=self.snapshot().memoria.total_bytes,
            origem=self.coletores.processos.origem,
            max_pontos=max_pontos,
        )

    def servicos(self) -> list[Servico]:
        return aplicar_criticidade(self.coletores.servicos.listar())

    def eventos(
        self,
        horas: float,
        tipo: TipoEvento | None = None,
        severidade: Severidade | None = None,
        limite: int = 200,
    ) -> list[Evento]:
        agora = self.relogio()
        return self.eventos_repo.listar(agora - timedelta(hours=horas), agora, tipo, severidade, limite)

    def diagnostico(self, horas: float = 24) -> Diagnostico:
        agora = self.relogio()
        ctx = Contexto(
            agora=agora,
            snapshot=self.snapshot(),
            historico=self.metricas_repo.intervalo(agora - timedelta(hours=horas), agora),
            servicos=self.servicos(),
            processos=self.coletores.processos.listar(),
            eventos=self.eventos_repo.listar(agora - timedelta(hours=horas), agora, limite=1000),
        )
        return gerar_diagnostico(ctx)

    def momento(self) -> datetime:
        return self.relogio()
