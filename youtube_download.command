#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
PYTHON="${DOWNLOADER_PYTHON:-${WORKBENCH_PYTHON:-}}"
if [ -n "$PYTHON" ]; then
    if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        echo 'DOWNLOADER_PYTHON must point to a working Python 3.10+ executable.' >&2
        exit 1
    fi
else
    for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 || true)" /usr/bin/python3; do
        if [ -x "$candidate" ] && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10) or sys.prefix != sys.base_prefix)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    done
    if [ -z "$PYTHON" ]; then
        echo 'Install Python 3.10+ or set DOWNLOADER_PYTHON to its executable; Studio setup is not required.' >&2
        exit 1
    fi
fi
exec "$PYTHON" -X utf8 "$ROOT/scripts/downloader.py" "$@"
