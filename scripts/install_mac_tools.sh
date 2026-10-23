#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/tools/mac-apps"
PYTHON_BIN="$ROOT/.venv/bin/python"
for argument in "$@"; do
  if [ "$argument" = "--help" ] || [ "$argument" = "-h" ]; then
    cat <<'HELP'
用法：scripts/install_mac_tools.sh [--only APP [APP ...]]

默认按 tools/mac-apps/manifest.json 安装全部应用；已有 .app 会跳过。
--only  仅安装指定应用，名称不区分大小写；含空格的名称需加引号。

示例：scripts/install_mac_tools.sh --only Aegisub HandBrake
      scripts/install_mac_tools.sh --only "Subtitle Edit"
HELP
    exit 0
  fi
done
if [ ! -x "$PYTHON_BIN" ]; then
  echo '请先运行 setup.command 创建独立 Python 环境。' >&2
  exit 1
fi
MOUNT=""
PLAN=""
cleanup() {
  if [ -n "$MOUNT" ] && mount | grep -F " on $MOUNT " >/dev/null 2>&1; then
    hdiutil detach "$MOUNT" -quiet || true
  fi
  if [ -n "$MOUNT" ]; then rmdir "$MOUNT" 2>/dev/null || true; fi
  if [ -n "$PLAN" ]; then rm -f "$PLAN"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

PLAN="$(mktemp "${TMPDIR:-/tmp}/subtitle-tools-plan.XXXXXX")"
"$PYTHON_BIN" - "$DEST" "$@" >"$PLAN" <<'PY'
import argparse, hashlib, json, sys
from pathlib import Path

base = Path(sys.argv[1])
parser = argparse.ArgumentParser(prog='scripts/install_mac_tools.sh')
parser.add_argument('--only', nargs='+', metavar='APP', help='仅安装指定应用，名称不区分大小写')
args = parser.parse_args(sys.argv[2:])
apps = json.loads((base / 'manifest.json').read_text())['apps']
if args.only:
    known = {app['name'].casefold() for app in apps}
    unknown = [name for name in args.only if name.casefold() not in known]
    if unknown:
        parser.error(f'未知应用：{", ".join(unknown)}。清单应用：{", ".join(app["name"] for app in apps)}')
    wanted = {name.casefold() for name in args.only}
    apps = [app for app in apps if app['name'].casefold() in wanted]

def filename(value, label):
    if (not isinstance(value, str) or not value or value in ('.', '..')
            or Path(value).name != value or '\\' in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        parser.error(f'{label} 必须是单个文件名，不能包含目录或控制字符。')
    return value

pending = []
for app in apps:
    bundle = filename(app.get('installed_app', app['name'] + '.app'), 'installed_app')
    if not bundle.endswith('.app') or bundle == '.app':
        parser.error('installed_app 必须以 .app 结尾。')
    installed = base / bundle
    if installed.is_dir():
        print(f'{bundle} 已存在，保留当前安装。', file=sys.stderr)
        continue
    if installed.exists() or installed.is_symlink():
        raise SystemExit(f'{bundle} 已存在但不是应用目录，拒绝覆盖。')
    dmg = filename(app.get('file'), f'{app["name"]} 的 file')
    path = base / 'downloads' / dmg
    if not path.is_file():
        raise SystemExit(f'缺少 {path.name}；先运行 scripts/download_mac_tools.py。')
    if path.resolve().parent != (base / 'downloads').resolve():
        raise SystemExit(f'{path.name} 指向下载目录之外，拒绝安装。')
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != app['sha256']:
        raise SystemExit(f'{path.name} 官方 SHA-256 不匹配，拒绝安装。')
    print(f'{app["name"]}: SHA-256 通过', file=sys.stderr)
    pending.append((dmg, bundle))

# NUL-delimited fields preserve spaces without evaluating any manifest text.
for dmg, bundle in pending:
    sys.stdout.buffer.write(dmg.encode('utf-8') + b'\0' + bundle.encode('utf-8') + b'\0')
PY

install_app() {
  local dmg="$1" app="$2"
  if [ -d "$DEST/$app" ]; then
    echo "$app 已存在，保留当前安装。"
    return
  fi
  MOUNT="$(mktemp -d "${TMPDIR:-/tmp}/subtitle-tools.XXXXXX")"
  hdiutil attach "$DEST/downloads/$dmg" -readonly -nobrowse -mountpoint "$MOUNT" -quiet
  if [ ! -d "$MOUNT/$app" ]; then
    echo "安装包中没有预期的 $app；停止安装。" >&2
    exit 1
  fi
  codesign --verify --deep --strict "$MOUNT/$app"
  spctl --assess --type execute --verbose=2 "$MOUNT/$app"
  ditto "$MOUNT/$app" "$DEST/$app"
  codesign --verify --deep --strict "$DEST/$app"
  hdiutil detach "$MOUNT" -quiet
  rmdir "$MOUNT"
  MOUNT=""
  echo "已放置 $DEST/$app"
}

while IFS= read -r -d '' dmg && IFS= read -r -d '' app; do
  install_app "$dmg" "$app"
done <"$PLAN"
echo 'Mac 工具已就绪，可直接从 tools/mac-apps 双击打开；也可以手动拖到 Applications。'
