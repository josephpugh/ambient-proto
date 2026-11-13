#!/usr/bin/env bash
# Start the backend inside backend/.venv, creating it and installing requirements if needed. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  echo "Creating .venv and installing requirements"
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt
fi
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example. Put your OPENAI_API_KEY in it."; }
exec .venv/bin/python -m ambient "$@"
