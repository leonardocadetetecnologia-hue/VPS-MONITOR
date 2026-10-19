# Sobe o VPS Insight localmente (Windows).
#   .\rodar.ps1              servidor em http://127.0.0.1:8765
#   .\rodar.ps1 -Testes      só os testes (pytest)
#   .\rodar.ps1 -Verificar   ciclo completo: formatação, lint, tipos, testes, smoke e telas
param([switch]$Testes, [switch]$Verificar)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -q -r requirements-dev.txt
if ($Testes) { .\.venv\Scripts\python.exe -m pytest; exit $LASTEXITCODE }
if ($Verificar) { .\.venv\Scripts\python.exe scripts\verificar.py; exit $LASTEXITCODE }
.\.venv\Scripts\python.exe -m app.main
