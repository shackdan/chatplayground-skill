#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install --upgrade pip
.venv/bin/pip install pytest playwright
.venv/bin/python -m playwright install chromium

echo "Setup complete. Next: run '! scripts/login.py' once to log in."
