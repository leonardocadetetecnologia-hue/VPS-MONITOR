"""Monta o conjunto de coletores conforme o modo configurado."""

from dataclasses import dataclass
from datetime import datetime

from app.collectors.base import ColetorMetricas, ColetorProcessos, ColetorServicos, FonteEventos
from app.collectors.simulated import (
    CenarioSimulado,
    ColetorMetricasSimulado,
    ColetorProcessosSimulado,
    ColetorServicosSimulado,
    FonteEventosSimulada,
    Relogio,
    relogio_utc,
)
from app.config import MODO_SIMULADO, ConfiguracaoInvalida, Settings


@dataclass(frozen=True)
class Coletores:
    metricas: ColetorMetricas
    processos: ColetorProcessos
    servicos: ColetorServicos
    eventos: FonteEventos
    cenario: CenarioSimulado | None = None


def construir_coletores(settings: Settings, ancora: datetime, relogio: Relogio = relogio_utc) -> Coletores:
    if settings.modo != MODO_SIMULADO:
        # Redundante com Settings, de propósito: defesa em profundidade.
        raise ConfiguracaoInvalida("Somente coletores simulados estão disponíveis nesta etapa.")
    cenario = CenarioSimulado(ancora=ancora, semente=settings.semente)
    return Coletores(
        metricas=ColetorMetricasSimulado(cenario, relogio),
        processos=ColetorProcessosSimulado(cenario, relogio),
        servicos=ColetorServicosSimulado(cenario, relogio),
        eventos=FonteEventosSimulada(cenario, relogio),
        cenario=cenario,
    )
