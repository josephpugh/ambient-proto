# Start the backend inside backend\.venv, creating it and installing requirements if needed.
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) {
  Write-Host "Creating .venv and installing requirements"
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
  .\.venv\Scripts\pip.exe install -r requirements.txt
}
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env from .env.example. Put your OPENAI_API_KEY in it." }
& .\.venv\Scripts\python.exe -m ambient @args
