#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$ROOT/.cache/pip}"
export npm_config_cache="${npm_config_cache:-$ROOT/.cache/npm}"

find_python() {
  local candidate
  for candidate in "${WORKBENCH_PYTHON:-}" /opt/homebrew/opt/python@3.13/bin/python3.13 /usr/local/opt/python@3.13/bin/python3.13 python3.13 python3.12; do
    if [ -n "$candidate" ] && command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if (3,12) <= sys.version_info[:2] <= (3,13) else 1)' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PYTHON_BIN="$(find_python)"; then
  if command -v brew >/dev/null 2>&1; then
    echo '安装工作台使用的稳定 Python 3.13（独立于系统 Python）…'
    brew install python@3.13
    PYTHON_BIN="$(find_python)"
  else
    echo '缺少 Python 3.12/3.13。请安装 Python 3.13 后重试，或指定 WORKBENCH_PYTHON=/路径/python3.13。' >&2
    exit 1
  fi
fi

if [ -x .venv/bin/python ]; then
  if ! .venv/bin/python -c 'import sys; sys.exit(0 if (3,12) <= sys.version_info[:2] <= (3,13) else 1)'; then
    echo '.venv 版本不兼容。请保留并重命名该目录后重新运行，脚本不会删除已有环境。' >&2
    exit 1
  fi
else
  "$PYTHON_BIN" -m venv .venv
fi

if ! command -v node >/dev/null 2>&1 || ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22 ? 0 : 1)'; then
  echo '需要 Node.js 20.19+ 或 22.12+；请安装官方 LTS 后重试。' >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install ffmpeg
  else
    echo '缺少 FFmpeg / ffprobe。请安装官方构建并加入 PATH，或通过 Homebrew 安装 ffmpeg。' >&2
    exit 1
  fi
fi

if [ -f backend/requirements.lock ]; then
  .venv/bin/python -m pip install -r backend/requirements.lock
else
  .venv/bin/python -m pip install -r backend/requirements.txt
fi

cd "$ROOT/frontend"
if [ -f package-lock.json ]; then npm ci; else npm install; fi
npm run build
cd "$ROOT"

if [ ! -f .env ] && [ -f .env.example ]; then
  (umask 077; cp .env.example .env)
fi
echo '工作台环境已就绪。双击 start.command 启动；Ctrl+C 关闭服务。'
