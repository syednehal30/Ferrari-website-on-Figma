#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
exec .venv/bin/python -m uvicorn zandop.main:app --host 127.0.0.1 --port "${PORT:-8000}" --workers 1
