from datetime import UTC, datetime

from fastapi import Request

from app.audit.audit import Auditor
from app.models import AVISO_SIMULADO, Envelope, Origem
from app.monitor import Monitor


def get_monitor(request: Request) -> Monitor:
    return request.app.state.monitor


def get_auditor(request: Request) -> Auditor:
    return request.app.state.auditor


def envelope[T](dados: T, origem: Origem = Origem.SIMULADO) -> Envelope[T]:
    return Envelope(
        origem=origem,
        aviso=AVISO_SIMULADO if origem is Origem.SIMULADO else "",
        gerado_em=datetime.now(UTC),
        dados=dados,
    )
