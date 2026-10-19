"""Tradução das exceções do FastAPI/Starlette para o formato único de erro."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import ErroAplicacao, corpo_erro, corpo_erro_http


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _detalhes_validacao(exc: RequestValidationError) -> list[dict[str, Any]]:
    # Só local e mensagem: o valor enviado não é ecoado de volta.
    return [
        {"campo": ".".join(str(p) for p in e.get("loc", ()) if p != "query"), "mensagem": e.get("msg", "")}
        for e in exc.errors()
    ]


def registrar_tratadores(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validacao(request: Request, exc: RequestValidationError) -> JSONResponse:
        rid = _request_id(request)
        corpo = corpo_erro(
            "parametro_invalido", "Um ou mais parâmetros são inválidos.", rid, _detalhes_validacao(exc)
        )
        return JSONResponse(corpo, status_code=422)

    @app.exception_handler(ErroAplicacao)
    async def _aplicacao(request: Request, exc: ErroAplicacao) -> JSONResponse:
        return JSONResponse(
            corpo_erro(exc.codigo, exc.mensagem, _request_id(request)), status_code=exc.status
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # `detail` padrão do Starlette ("Not Found") não é repassado: mensagem própria em pt-BR.
        return JSONResponse(
            corpo_erro_http(exc.status_code, _request_id(request)),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )
