#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$ROOT"
if [ ! -x .venv/bin/python ] || [ ! -f frontend/dist/index.html ]; then
  /bin/bash scripts/setup.sh
elif ! .venv/bin/python -c 'import fastapi, uvicorn, dotenv, httpx, multipart' >/dev/null 2>&1; then
  /bin/bash scripts/setup.sh
fi
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/launch.py" "$@"
