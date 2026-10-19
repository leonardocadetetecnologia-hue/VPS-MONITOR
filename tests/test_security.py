"""Testes das salvaguardas: API só leitura, loopback, cabeçalhos, auditoria e
ausência de código capaz de alcançar a produção."""

import ast
from pathlib import Path

import pytest

from app.security.guard import host_confiavel

RAIZ_APP = Path(__file__).resolve().parent.parent / "app"


@pytest.mark.parametrize("metodo", ["POST", "PUT", "PATCH", "DELETE"])
def test_api_e_somente_leitura(cliente, metodo):
    r = cliente.request(metodo, "/api/services")
    assert r.status_code == 405
    assert r.headers["allow"] == "GET, HEAD, OPTIONS"


def test_bloqueio_fica_auditado(cliente):
    cliente.post("/api/health")
    bloqueios = cliente.get("/api/audit", params={"categoria": "bloqueio"}).json()["dados"]["itens"]
    assert bloqueios[0]["acao"] == "POST /api/health"
    assert bloqueios[0]["detalhe"] == "metodo_nao_permitido"


def test_host_nao_confiavel_e_recusado(cliente):
    r = cliente.get("/api/health", headers={"Host": "atacante.exemplo.com"})
    assert r.status_code == 400


@pytest.mark.parametrize(
    "host,ok",
    [
        ("127.0.0.1:8765", True),
        ("localhost", True),
        ("[::1]:8765", True),
        ("evil.com", False),
        ("127.0.0.1.evil.com", False),
        ("", False),
        (None, False),
    ],
)
def test_validacao_do_cabecalho_host(host, ok):
    assert host_confiavel(host, ("127.0.0.1", "localhost", "[::1]")) is ok


def test_cabecalhos_de_seguranca(cliente):
    h = cliente.get("/").headers
    assert "default-src 'self'" in h["content-security-policy"]
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY"
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-data-origin"] == "SIMULADO"


def test_requisicoes_sao_auditadas(cliente):
    cliente.get("/api/processes")
    trilha = cliente.get("/api/audit").json()["dados"]["itens"]
    acoes = [a["acao"] for a in trilha]
    assert "GET /api/processes" in acoes
    assert any(a["categoria"] == "sistema" and a["acao"] == "inicializacao" for a in trilha)


# --- Varredura estática: nada no código consegue alcançar a VPS ------------

MODULOS_PROIBIDOS = {
    "subprocess",
    "socket",
    "ssl",
    "paramiko",
    "fabric",
    "asyncssh",
    "pexpect",
    "telnetlib",
    "ftplib",
    "smtplib",
    "requests",
    "httpx",
    "aiohttp",
    "urllib.request",
    "http.client",
    "psutil",
    "docker",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "pymysql",
    "mysql",
    "mariadb",
    "sqlalchemy",
    "dbus",
    "pystemd",
    "ctypes",
    "multiprocessing",
}
CHAMADAS_PROIBIDAS = {
    "system",
    "popen",
    "spawnl",
    "spawnv",
    "execv",
    "execl",
    "fork",
    "kill",
    "remove",
    "unlink",
    "rmtree",
}


def _arquivos_python():
    return sorted(RAIZ_APP.rglob("*.py"))


def test_existem_arquivos_para_varrer():
    assert len(_arquivos_python()) > 10


@pytest.mark.parametrize("arquivo", _arquivos_python(), ids=lambda p: str(p.relative_to(RAIZ_APP)))
def test_codigo_nao_importa_modulos_de_acesso_remoto_ou_ao_sistema(arquivo):
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        nomes = []
        if isinstance(no, ast.Import):
            nomes = [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes = [no.module]
        for nome in nomes:
            raiz = nome.split(".")[0]
            assert nome not in MODULOS_PROIBIDOS and raiz not in MODULOS_PROIBIDOS, (
                f"{arquivo.name} importa {nome}"
            )
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and isinstance(no.func.value, ast.Name)
            and no.func.value.id in {"os", "shutil"}
        ):
            assert no.func.attr not in CHAMADAS_PROIBIDAS, (
                f"{arquivo.name} chama {no.func.value.id}.{no.func.attr}"
            )
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name):
            assert no.func.id not in {"eval", "exec", "__import__"}, f"{arquivo.name} usa {no.func.id}"
