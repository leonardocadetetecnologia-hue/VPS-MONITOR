#!/usr/bin/env sh
# Sobe o VPS Insight localmente (Linux/macOS).
#   ./rodar.sh             servidor em http://127.0.0.1:8765
#   ./rodar.sh testes      só os testes (pytest)
#   ./rodar.sh verificar   ciclo completo: formatação, lint, tipos, testes, smoke e telas
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -r requirements-dev.txt
case "$1" in
  testes) exec .venv/bin/python -m pytest ;;
  verificar) exec .venv/bin/python scripts/verificar.py ;;
esac
exec .venv/bin/python -m app.main
