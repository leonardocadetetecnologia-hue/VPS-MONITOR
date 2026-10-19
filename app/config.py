"""Configuração da aplicação.

A validação aqui é a primeira barreira de segurança: nesta etapa o sistema
só pode rodar em modo SIMULADO e só pode escutar em interface de loopback.
Qualquer outra combinação é recusada na inicialização, antes de a API subir.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODO_SIMULADO = "simulado"
MODOS_SUPORTADOS = frozenset({MODO_SIMULADO})

HOSTS_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

RAIZ_PROJETO = Path(__file__).resolve().parent.parent


class ConfiguracaoInvalida(ValueError):
    """Configuração recusada por violar as restrições do MVP."""


@dataclass(frozen=True)
class Settings:
    modo: str = MODO_SIMULADO
    host: str = "127.0.0.1"
    porta: int = 8765
    db_path: Path = RAIZ_PROJETO / "data" / "vps_insight.sqlite3"
    semente: int = 42
    # Janela de histórico simulado gerada na inicialização.
    historico_horas: int = 24
    passo_historico_min: int = 1
    # Intervalo da amostragem simulada "ao vivo" enquanto o servidor roda (0 desliga).
    amostragem_ao_vivo_s: int = 15
    # Recria o histórico simulado ao subir. False usa o banco como está (os testes
    # partem de um banco já semeado, para não refazer a carga a cada teste).
    semear_historico: bool = True
    # Cabeçalho Host aceito nas requisições (proteção contra DNS rebinding).
    hosts_confiaveis: tuple[str, ...] = field(default=("127.0.0.1", "localhost", "[::1]"))

    def __post_init__(self) -> None:
        if self.modo not in MODOS_SUPORTADOS:
            raise ConfiguracaoInvalida(
                f"Modo '{self.modo}' não é suportado nesta etapa. "
                "Somente o modo 'simulado' está habilitado; coleta real não foi implementada."
            )
        if self.host not in HOSTS_LOOPBACK:
            raise ConfiguracaoInvalida(
                f"Host '{self.host}' recusado. O dashboard só pode escutar em loopback "
                f"({', '.join(sorted(HOSTS_LOOPBACK))}) — não deve ser exposto à rede."
            )
        if not 1024 <= self.porta <= 65535:
            raise ConfiguracaoInvalida("Porta deve estar entre 1024 e 65535 (sem privilégio).")
        if not 1 <= self.historico_horas <= 24 * 10:
            raise ConfiguracaoInvalida("historico_horas deve estar entre 1 e 240.")
        if self.passo_historico_min < 1:
            raise ConfiguracaoInvalida("passo_historico_min deve ser >= 1.")
        if self.amostragem_ao_vivo_s < 0:
            raise ConfiguracaoInvalida("amostragem_ao_vivo_s não pode ser negativa.")


def _inteiro(nome: str, valor: str) -> int:
    try:
        return int(valor.strip())
    except ValueError:
        raise ConfiguracaoInvalida(f"{nome} deve ser um número inteiro (recebido: {valor!r}).") from None


def carregar_settings() -> Settings:
    """Lê a configuração de variáveis de ambiente VPS_INSIGHT_* (todas opcionais)."""
    env = os.environ
    kwargs: dict[str, Any] = {}
    if "VPS_INSIGHT_MODO" in env:
        kwargs["modo"] = env["VPS_INSIGHT_MODO"].strip().lower()
    if "VPS_INSIGHT_HOST" in env:
        kwargs["host"] = env["VPS_INSIGHT_HOST"].strip()
    if "VPS_INSIGHT_PORTA" in env:
        kwargs["porta"] = _inteiro("VPS_INSIGHT_PORTA", env["VPS_INSIGHT_PORTA"])
    if "VPS_INSIGHT_DB" in env:
        kwargs["db_path"] = Path(env["VPS_INSIGHT_DB"])
    if "VPS_INSIGHT_SEMENTE" in env:
        kwargs["semente"] = _inteiro("VPS_INSIGHT_SEMENTE", env["VPS_INSIGHT_SEMENTE"])
    if "VPS_INSIGHT_AMOSTRAGEM_S" in env:
        kwargs["amostragem_ao_vivo_s"] = _inteiro("VPS_INSIGHT_AMOSTRAGEM_S", env["VPS_INSIGHT_AMOSTRAGEM_S"])
    return Settings(**kwargs)
