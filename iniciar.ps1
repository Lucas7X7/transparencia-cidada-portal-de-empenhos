$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $here "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venv)) {
    Write-Host "Criando ambiente virtual..."
    python -m venv (Join-Path $here "backend\.venv")
    & $venv -m pip install --quiet -r (Join-Path $here "backend\requirements.txt")
}
Write-Host "Iniciando Portal de Transparência Cidadã em http://127.0.0.1:8010"
& $venv -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --app-dir (Join-Path $here "backend")
