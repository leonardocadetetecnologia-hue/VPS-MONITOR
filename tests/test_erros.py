"""Formato único de erro, request_id e ausência de detalhe interno (MASTER_PROMPT §25, §33, §44, §49)."""

import pytest

from app.models.audit import CategoriaAuditoria


def _erro(resposta):
    corpo = resposta.json()
    assert set(corpo) == {"erro"}, corpo
    erro = corpo["erro"]
    assert erro["codigo"] and erro["mensagem"]
    assert erro["request_id"] == resposta.headers["x-request-id"]
    return erro


def test_toda_resposta_tem_request_id_unico(cliente):
    ids = {cliente.get("/api/health").headers["x-request-id"] for _ in range(5)}
    assert len(ids) == 5
    assert cliente.get("/").headers["x-request-id"]


def test_validacao_422_no_formato_padrao_sem_ecoar_valor(cliente):
    r = cliente.get("/api/processes", params={"limite": "<script>alert(1)</script>"})
    assert r.status_code == 422
    erro = _erro(r)
    assert erro["codigo"] == "parametro_invalido"
    assert erro["detalhes"][0]["campo"] == "limite"
    assert "<script>" not in r.text  # valor enviado não volta na resposta


def test_rota_inexistente_404_no_formato_padrao(cliente):
    r = cliente.get("/api/nao-existe")
    assert r.status_code == 404
    assert _erro(r)["codigo"] == "nao_encontrado"
    assert "Not Found" not in r.text  # mensagem padrão do framework (em inglês) não vaza


@pytest.mark.parametrize(
    ("metodo", "headers", "status", "codigo"),
    [("POST", {}, 405, "metodo_nao_permitido"), ("GET", {"Host": "evil.com"}, 400, "requisicao_invalida")],
)
def test_bloqueios_no_formato_padrao(cliente, metodo, headers, status, codigo):
    r = cliente.request(metodo, "/api/health", headers=headers)
    assert r.status_code == status
    assert _erro(r)["codigo"] == codigo
    assert r.headers["content-security-policy"]  # cabeçalhos de segurança também nas respostas de bloqueio


def test_falha_interna_vira_500_sem_stack_trace_e_fica_rastreavel(cliente, monkeypatch, caplog):
    monitor = cliente.app.state.monitor

    def explodir(*_a, **_k):
        raise RuntimeError("segredo interno: senha=123")

    monkeypatch.setattr(monitor, "processos", explodir)
    r = cliente.get("/api/processes")

    assert r.status_code == 500
    erro = _erro(r)
    assert erro["codigo"] == "erro_interno"
    assert "Traceback" not in r.text and "senha" not in r.text and "RuntimeError" not in r.text
    # o detalhe vai para o log, ligado pelo request_id
    assert any(erro["request_id"] in rec.getMessage() and rec.exc_info for rec in caplog.records)
    # e a auditoria registra o 500 com o mesmo request_id
    itens = cliente.app.state.auditor.listar(categoria=CategoriaAuditoria.REQUISICAO).itens
    falha = next(a for a in itens if a.acao == "GET /api/processes")
    assert falha.status == 500 and falha.request_id == erro["request_id"]


def test_servidor_segue_respondendo_apos_falha_interna(cliente, monkeypatch):
    monkeypatch.setattr(cliente.app.state.monitor, "processos", lambda *a, **k: 1 / 0)
    assert cliente.get("/api/processes").status_code == 500
    assert cliente.get("/api/health").status_code == 200
