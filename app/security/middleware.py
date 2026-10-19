"""Middleware único de segurança, auditoria e observabilidade (ASGI puro).

Em cada requisição HTTP:
1. gera um request_id (exposto em X-Request-ID, no log e na auditoria);
2. Host confiável (loopback) — senão 400;
3. método somente leitura — senão 405;
4. repassa à aplicação e injeta os cabeçalhos de segurança;
5. se a aplicação falhar sem ter respondido, registra o stack trace no log
   e devolve 500 no formato padrão — sem detalhe interno na resposta;
6. audita e registra em log toda chamada a /api/*.
"""

import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.audit.audit import Auditor
from app.errors import corpo_erro_http
from app.security.guard import (
    CABECALHOS_SEGURANCA,
    CAMINHOS_DOCS,
    CSP_DOCS,
    host_confiavel,
    metodo_permitido,
)

log = logging.getLogger("vps_insight.http")


class SegurancaAuditoriaMiddleware:
    def __init__(
        self, app: ASGIApp, auditor_fn: Callable[[], Auditor | None], hosts_confiaveis: tuple[str, ...]
    ) -> None:
        self.app = app
        self.auditor_fn = auditor_fn  # tardio: o auditor nasce no lifespan
        self.hosts_confiaveis = hosts_confiaveis

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = rid
        metodo = scope["method"]
        caminho = scope["path"]
        cliente = scope["client"][0] if scope.get("client") else None
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        auditor = self.auditor_fn()

        if not host_confiavel(headers.get("host"), self.hosts_confiaveis):
            if auditor:
                auditor.bloqueio("host_nao_confiavel", metodo, caminho, cliente, rid)
            log.warning(
                "bloqueio motivo=host_nao_confiavel metodo=%s caminho=%s request_id=%s", metodo, caminho, rid
            )
            await _responder(
                send,
                400,
                corpo_erro_http(400, rid, "Host não permitido: o dashboard atende apenas em loopback."),
                rid,
            )
            return

        if not metodo_permitido(metodo):
            if auditor:
                auditor.bloqueio("metodo_nao_permitido", metodo, caminho, cliente, rid)
            log.warning(
                "bloqueio motivo=metodo_nao_permitido metodo=%s caminho=%s request_id=%s",
                metodo,
                caminho,
                rid,
            )
            await _responder(
                send, 405, corpo_erro_http(405, rid), rid, extra=[(b"allow", b"GET, HEAD, OPTIONS")]
            )
            return

        inicio = time.perf_counter()
        estado = {"status": 500, "iniciada": False}

        async def enviar(mensagem: Message) -> None:
            if mensagem["type"] == "http.response.start":
                estado["status"] = mensagem["status"]
                estado["iniciada"] = True
                mensagem = {**mensagem, "headers": _com_cabecalhos(mensagem.get("headers", []), caminho, rid)}
            await send(mensagem)

        try:
            await self.app(scope, receive, enviar)
        except Exception:
            log.exception("falha_interna metodo=%s caminho=%s request_id=%s", metodo, caminho, rid)
            estado["status"] = 500
            if not estado["iniciada"]:
                await _responder(send, 500, corpo_erro_http(500, rid), rid)
            # Resposta já iniciada: não há como trocar o status; o log tem o detalhe.
        finally:
            if caminho.startswith("/api/"):
                duracao = (time.perf_counter() - inicio) * 1000
                status = int(estado["status"])
                log.info(
                    "requisicao metodo=%s caminho=%s status=%s ms=%.1f request_id=%s",
                    metodo,
                    caminho,
                    status,
                    duracao,
                    rid,
                )
                if auditor:
                    auditor.requisicao(metodo, caminho, status, cliente, duracao, rid)


def _com_cabecalhos(existentes: Any, caminho: str, rid: str) -> list[tuple[bytes, bytes]]:
    cab = list(existentes)
    nomes = {k.lower() for k, _ in cab}
    cabecalhos = {**CABECALHOS_SEGURANCA, "X-Request-ID": rid}
    if caminho in CAMINHOS_DOCS:
        cabecalhos["Content-Security-Policy"] = CSP_DOCS
    for nome, valor in cabecalhos.items():
        if nome.lower().encode() not in nomes:
            cab.append((nome.lower().encode(), valor.encode()))
    return cab


async def _responder(
    send: Send, status: int, corpo: dict[str, Any], rid: str, extra: list[tuple[bytes, bytes]] | None = None
) -> None:
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    cab = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(dados)).encode()),
    ]
    cab = _com_cabecalhos(cab + (extra or []), "", rid)
    await send({"type": "http.response.start", "status": status, "headers": cab})
    await send({"type": "http.response.body", "body": dados})
