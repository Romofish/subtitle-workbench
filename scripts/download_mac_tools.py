#!/usr/bin/env python3
"""Download pinned official free Mac applications and verify publisher SHA-256.

Ranged chunks make slow connections resumable. This does not disable Gatekeeper,
remove quarantine, install system components, or start applications.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "tools" / "mac-apps" / "downloads"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct", action="store_true", help="不使用代理，直连官方站点")
    parser.add_argument("--connections", type=int, default=6)
    parser.add_argument("--only", nargs="+", metavar="APP", help="仅下载指定应用（名称不区分大小写；含空格的名称需加引号）")
    args = parser.parse_args()
    if not 1 <= args.connections <= 16:
        parser.error("connections 必须是 1–16")
    apps = json.loads((DEST.parent / "manifest.json").read_text())["apps"]
    if args.only:
        known = {app["name"].casefold() for app in apps}
        unknown = [name for name in args.only if name.casefold() not in known]
        if unknown:
            parser.error(f'未知应用：{", ".join(unknown)}。清单应用：{", ".join(app["name"] for app in apps)}')
        wanted = {name.casefold() for name in args.only}
        apps = [app for app in apps if app["name"].casefold() in wanted]
    for app in apps:
        filename = app.get("file")
        if (not isinstance(filename, str) or not filename or filename in (".", "..")
                or Path(filename).name != filename or "\\" in filename
                or any(ord(char) < 32 or ord(char) == 127 for char in filename)):
            parser.error(f'{app["name"]} 的 file 必须是单个文件名，不能包含目录或控制字符。')
    DEST.mkdir(parents=True, exist_ok=True)
    pending = []
    chunk_bytes = 4 * 1024 * 1024
    for app in apps:
        target = DEST / app["file"]
        if target.exists() and target.stat().st_size == app["bytes"] and sha256(target) == app["sha256"]:
            print(f'{app["name"]} {app["version"]}: 已有完整文件，SHA-256 通过。', flush=True)
            continue
        parts_dir = DEST / (app["file"] + ".parts")
        parts_dir.mkdir(exist_ok=True)
        # Retain the useful full chunks of an earlier interrupted plain download.
        if target.exists():
            with target.open("rb") as existing:
                for index, offset in enumerate(range(0, app["bytes"], chunk_bytes)):
                    block_size = min(chunk_bytes, app["bytes"] - offset)
                    block = existing.read(block_size)
                    if len(block) != block_size:
                        break
                    part = parts_dir / f"{index:04}.part"
                    if not part.exists():
                        part.write_bytes(block)
        for index, offset in enumerate(range(0, app["bytes"], chunk_bytes)):
            size = min(chunk_bytes, app["bytes"] - offset)
            part = parts_dir / f"{index:04}.part"
            if not part.exists() or part.stat().st_size != size:
                pending.append((app, offset, size, part))

    def get_chunk(task):
        app, offset, size, part = task
        temp = part.with_suffix(".downloading")
        tail = part.with_suffix(".tail")
        for _ in range(5):
            have = temp.stat().st_size if temp.exists() else 0
            if have == size:
                break
            if have > size:
                raise RuntimeError(f'{app["name"]} 分段大小不匹配；保留临时文件，拒绝合并。')
            tail.unlink(missing_ok=True)
            command = ["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "2", "--retry-all-errors", "--connect-timeout", "20", "--max-time", "180", "--speed-limit", "8192", "--speed-time", "30", "--range", f"{offset + have}-{offset + size - 1}", "--output", str(tail)]
            if args.direct:
                command.extend(["--noproxy", "*"])
            command.append(app["url"])
            subprocess.run(command, check=False)
            if tail.exists() and tail.stat().st_size:
                if tail.stat().st_size > size - have:
                    raise RuntimeError(f'{app["name"]} 服务器未遵守分段大小，拒绝合并。')
                with temp.open("ab") as output:
                    output.write(tail.read_bytes())
                tail.unlink()
        if not temp.exists() or temp.stat().st_size != size:
            raise RuntimeError(f'{app["name"]} 分段暂未下载完成；已保留可恢复字节。')
        temp.replace(part)
        return app["name"]

    if pending:
        print(f"下载 {len(pending)} 个分段，使用 {args.connections} 个连接；来源与预期哈希见 tools/mac-apps/manifest.json。", flush=True)
        failures = []
        with ThreadPoolExecutor(max_workers=args.connections) as pool:
            for index, future in enumerate(as_completed([pool.submit(get_chunk, task) for task in pending]), 1):
                try:
                    print(f"{index}/{len(pending)} 分段完成：{future.result()}", flush=True)
                except (subprocess.CalledProcessError, OSError, RuntimeError) as error:
                    failures.append(str(error))
                    print(f"{index}/{len(pending)} 分段失败；保留其余下载进度，结束后重试。", flush=True)
        if failures:
            raise SystemExit(f"{len(failures)} 个分段未完成；再次运行同一命令即可续传。尚未接受不完整安装包。")

    for app in apps:
        target = DEST / app["file"]
        if target.exists() and target.stat().st_size == app["bytes"] and sha256(target) == app["sha256"]:
            continue
        assembled = target.with_suffix(".assembling")
        parts_dir = DEST / (app["file"] + ".parts")
        with assembled.open("wb") as output:
            for index in range((app["bytes"] + chunk_bytes - 1) // chunk_bytes):
                output.write((parts_dir / f"{index:04}.part").read_bytes())
        if sha256(assembled) != app["sha256"]:
            raise RuntimeError(f'{app["name"]} SHA-256 不匹配；拒绝采用下载文件。')
        assembled.replace(target)
        for part in parts_dir.glob("*.part"):
            part.unlink()
        parts_dir.rmdir()
        print(f'{app["name"]} {app["version"]}: 下载完成，官方 SHA-256 通过。', flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
