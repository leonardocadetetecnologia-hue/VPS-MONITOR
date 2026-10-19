"""Formato único de erro da API.

Todo erro — validação, rota inexistente, bloqueio de segurança ou falha
interna — sai como:

    {"erro": {"codigo": "...", "mensagem": "...", "detalhes": [...], "request_id": "..."}}

`mensagem` é para pessoas; `codigo` é estável para programas; `request_id`
liga a resposta à linha do log. Stack trace nunca vai para a resposta.
"""

from typing import Any

MENSAGENS_HTTP: dict[int, tuple[str, str]] = {
    400: ("requisicao_invalida", "Requisição inválida."),
    404: ("nao_encontrado", "Recurso não encontrado."),
    405: ("metodo_nao_permitido", "API somente leitura: apenas GET, HEAD e OPTIONS."),
    422: ("parametro_invalido", "Um ou mais parâmetros são inválidos."),
    500: ("erro_interno", "Erro interno. Consulte o log do servidor pelo request_id."),
}


class ErroAplicacao(Exception):
    """Erro previsível de regra/consulta, já com status e mensagem para o usuário."""

    status = 400
    codigo = "requisicao_invalida"

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem


class NaoEncontrado(ErroAplicacao):
    status = 404
    codigo = "nao_encontrado"


def corpo_erro(
    codigo: str, mensagem: str, request_id: str | None, detalhes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    erro: dict[str, Any] = {"codigo": codigo, "mensagem": mensagem, "request_id": request_id}
    if detalhes:
        erro["detalhes"] = detalhes
    return {"erro": erro}


def corpo_erro_http(status: int, request_id: str | None, mensagem: str | None = None) -> dict[str, Any]:
    codigo, padrao = MENSAGENS_HTTP.get(status, (f"http_{status}", "Falha na requisição."))
    return corpo_erro(codigo, mensagem or padrao, request_id)
