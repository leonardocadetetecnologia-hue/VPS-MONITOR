"""Ciclo de validação completo do projeto, num comando (MASTER_PROMPT §39).

    python scripts/verificar.py              # tudo
    python scripts/verificar.py --rapido     # sem servidor nem navegador
    python scripts/verificar.py --capturas   # salva screenshots das telas

Etapas: formatação → lint → tipos → sintaxe JS → testes → smoke test com o
servidor real (latência por endpoint) → telas em 6 larguras num Chrome headless.

Tudo roda NESTA máquina: o servidor sobe em 127.0.0.1 numa porta própria, com
banco temporário, e é encerrado ao final. Nada acessa a VPS.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PY = sys.executable
PORTA_SMOKE = 8799
BASE = f"http://127.0.0.1:{PORTA_SMOKE}"
# Orçamento de latência por endpoint no smoke test (servidor local, dados simulados).
LIMITE_MS = 1000

CHROME_CANDIDATOS = [
    os.environ.get("CHROME", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


@dataclass
class Resultado:
    etapa: str
    status: str  # ok | FALHA | pulado
    detalhe: str = ""


def rodar(cmd: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def etapa_comando(nome: str, cmd: list[str]) -> Callable[[], Resultado]:
    def executar() -> Resultado:
        ok, saida = rodar(cmd)
        ultima = saida.splitlines()[-1] if saida else ""
        if not ok:
            print(saida)
        return Resultado(nome, "ok" if ok else "FALHA", ultima)

    return executar


def sintaxe_js() -> Resultado:
    node = shutil.which("node")
    if not node:
        return Resultado("sintaxe JS", "pulado", "node não encontrado")
    arquivos = [*sorted((RAIZ / "app/web/static/js").rglob("*.js")), RAIZ / "scripts/validar_telas.mjs"]
    ruins = [str(a.relative_to(RAIZ)) for a in arquivos if not rodar([node, "--check", str(a)])[0]]
    if ruins:
        return Resultado("sintaxe JS", "FALHA", ", ".join(ruins))
    return Resultado("sintaxe JS", "ok", f"{len(arquivos)} arquivos")


def _get(caminho: str, metodo: str = "GET") -> tuple[int, dict, float, dict]:
    req = urllib.request.Request(BASE + caminho, method=metodo)  # noqa: S310 (URL local fixa)
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            corpo, status, cab = resp.read(), resp.status, {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        corpo, status, cab = exc.read(), exc.code, {k.lower(): v for k, v in exc.headers.items()}
    ms = (time.perf_counter() - inicio) * 1000
    try:
        dados = json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        dados = {}
    return status, dados, ms, cab


def smoke() -> Resultado:
    problemas = []
    endpoints = [
        "/api/metrics/current",
        "/api/metrics/history?horas=24&max_pontos=2000",
        "/api/processes",
        "/api/services",
        "/api/events?horas=240",
        "/api/diagnostics",
        "/api/integrations",
        "/api/audit",
    ]
    print(f"  {'endpoint':<48} {'status':>6} {'ms':>8}")
    for ep in endpoints:
        status, dados, ms, _ = _get(ep)
        print(f"  {ep:<48} {status:>6} {ms:>8.1f}")
        if status != 200 or dados.get("origem") != "SIMULADO":
            problemas.append(f"{ep} → {status}")
        if ms > LIMITE_MS:
            problemas.append(f"{ep} lento ({ms:.0f} ms > {LIMITE_MS})")
    status, dados, _, cab = _get("/api/health", "POST")
    if (
        status != 405
        or dados.get("erro", {}).get("codigo") != "metodo_nao_permitido"
        or "x-request-id" not in cab
    ):
        problemas.append("POST não foi bloqueado no formato padrão")
    status, dados, _, _ = _get("/api/nao-existe")
    if status != 404 or "erro" not in dados:
        problemas.append("404 fora do formato padrão")
    if _get("/")[0] != 200:
        problemas.append("dashboard (/) não respondeu 200")
    return Resultado(
        "smoke test", "FALHA" if problemas else "ok", "; ".join(problemas) or f"{len(endpoints)} endpoints"
    )


def telas(capturas: bool) -> Resultado:
    node = shutil.which("node")
    chrome = next((c for c in CHROME_CANDIDATOS if c and Path(c).exists()), None)
    if not node or not chrome:
        return Resultado("telas (6 larguras)", "pulado", "node ou Chrome/Edge não encontrado")
    saida = Path(tempfile.gettempdir()) / "vps-insight-telas"
    cmd = [node, str(RAIZ / "scripts/validar_telas.mjs"), chrome, BASE, str(saida)]
    if capturas:
        cmd.append("--capturas")
    ok, texto = rodar(cmd)
    print(
        "\n".join(
            "  " + linha for linha in texto.splitlines() if linha.startswith(("FALHA", "Erro")) or not ok
        )
    )
    detalhe = texto.splitlines()[-1] if texto else ""
    if capturas:
        detalhe += f" Capturas em {saida}"
    return Resultado("telas (6 larguras)", "ok" if ok else "FALHA", detalhe)


def com_servidor(etapas: list[Callable[[], Resultado]]) -> list[Resultado]:
    banco = Path(tempfile.mkdtemp(prefix="vps-insight-verif-")) / "verif.sqlite3"
    env = {
        **os.environ,
        "VPS_INSIGHT_PORTA": str(PORTA_SMOKE),
        "VPS_INSIGHT_DB": str(banco),
        "VPS_INSIGHT_AMOSTRAGEM_S": "0",
        "PYTHONIOENCODING": "utf-8",
    }
    servidor = subprocess.Popen(
        [PY, "-m", "app.main"], cwd=RAIZ, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        for _ in range(80):
            try:
                if _get("/api/health")[0] == 200:
                    break
            except OSError:
                time.sleep(0.25)
        else:
            return [Resultado("servidor local", "FALHA", "não respondeu em 20 s")]
        return [executar() for executar in etapas]
    finally:
        servidor.terminate()
        try:
            servidor.wait(timeout=10)
        except subprocess.TimeoutExpired:
            servidor.kill()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--rapido", action="store_true", help="pula smoke test e validação de telas")
    parser.add_argument("--capturas", action="store_true", help="salva screenshots de cada tela/largura")
    args = parser.parse_args()

    etapas = [
        etapa_comando("formatação (ruff format)", [PY, "-m", "ruff", "format", "--check", "."]),
        etapa_comando("lint (ruff)", [PY, "-m", "ruff", "check", "."]),
        etapa_comando("tipos (mypy)", [PY, "-m", "mypy", "app", "tests", "scripts"]),
        sintaxe_js,
        etapa_comando("testes (pytest)", [PY, "-m", "pytest", "-p", "no:cacheprovider"]),
    ]
    resultados = []
    for executar in etapas:
        r = executar()
        print(f"[{r.status:^6}] {r.etapa} {r.detalhe}")
        resultados.append(r)

    if not args.rapido:
        print("[  ..  ] subindo servidor local para smoke test e telas…")
        for r in com_servidor([smoke, lambda: telas(args.capturas)]):
            print(f"[{r.status:^6}] {r.etapa} {r.detalhe}")
            resultados.append(r)

    falhas = [r for r in resultados if r.status == "FALHA"]
    pulados = [r for r in resultados if r.status == "pulado"]
    print("\n" + ("FALHOU: " + ", ".join(r.etapa for r in falhas) if falhas else "TUDO OK"), end="")
    print(f" (pulado: {', '.join(r.etapa for r in pulados)})" if pulados else "")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
