#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname -- "${BASH_SOURCE[0]}")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir -r requirements.lock
if command -v chromium >/dev/null 2>&1; then
  chromium --version
elif [[ -n "${CHROMIUM_EXECUTABLE:-}" && -x "${CHROMIUM_EXECUTABLE}" ]]; then
  "$CHROMIUM_EXECUTABLE" --version
else
  .venv/bin/python -m playwright install chromium
fi
.venv/bin/python -c 'import fastapi, httpx, reportlab, playwright; print("ZanDop dependencies ready")'
