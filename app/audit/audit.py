"""Trilha de auditoria: quem consultou o quê, e o que o próprio sistema fez.

Registra toda requisição à API, toda requisição bloqueada pelas regras de
segurança e os eventos de ciclo de vida (inicialização, carga de histórico).
"""

from collections.abc import Callable
from datetime import UTC, datetime

from app.models.audit import CategoriaAuditoria, PaginaAuditoria
from app.storage.repositories import AuditoriaRepository


def _agora() -> datetime:
    return datetime.now(UTC)


class Auditor:
    def __init__(self, repo: AuditoriaRepository, relogio: Callable[[], datetime] = _agora) -> None:
        self.repo = repo
        self.relogio = relogio

    def requisicao(
        self, metodo: str, caminho: str, status: int, cliente: str | None, duracao_ms: float, request_id: str
    ) -> None:
        self.repo.registrar(
            self.relogio(), CategoriaAuditoria.REQUISICAO, f"{metodo} {caminho}",
            status=status, cliente=cliente, duracao_ms=round(duracao_ms, 2), request_id=request_id,
        )  # fmt: skip

    def bloqueio(self, motivo: str, metodo: str, caminho: str, cliente: str | None, request_id: str) -> None:
        self.repo.registrar(
            self.relogio(), CategoriaAuditoria.BLOQUEIO, f"{metodo} {caminho}",
            detalhe=motivo, cliente=cliente, request_id=request_id,
        )  # fmt: skip

    def sistema(self, acao: str, detalhe: str | None = None) -> None:
        self.repo.registrar(self.relogio(), CategoriaAuditoria.SISTEMA, acao, detalhe=detalhe)

    def listar(
        self, limite: int = 100, categoria: CategoriaAuditoria | None = None, antes_id: int | None = None
    ) -> PaginaAuditoria:
        return self.repo.listar(limite, categoria, antes_id)
