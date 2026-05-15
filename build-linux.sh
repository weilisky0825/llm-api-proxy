#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Installing dependencies ==="
pip install -q -r requirements.txt

echo "=== Cleaning previous build artifacts ==="
rm -rf build/ __pycache__/

echo "=== Building Linux binary ==="
pyinstaller --onefile \
  --name llm-api-proxy \
  --add-data "config.yaml:." \
  --add-data "app/web/templates:app/web/templates" \
  --hidden-import uvicorn \
  --hidden-import aiosqlite \
  --hidden-import bcrypt \
  --hidden-import jinja2 \
  --hidden-import yaml \
  --collect-all jinja2 \
  run.py

echo "=== Build complete ==="
ls -lh dist/llm-api-proxy
