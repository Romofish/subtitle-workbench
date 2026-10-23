#!/usr/bin/env python3
"""Run the local API and separate translation worker until Ctrl+C."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="启动本地字幕工作台")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--port", type=int, default=8765, help="本地端口，默认 8765")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口必须在 1024–65535 之间")
    load_dotenv(ROOT / ".env", override=False)
    os.environ.setdefault("SUBTITLE_DATA_DIR", str(ROOT / ".workbench-data"))
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["SUBTITLE_PORT"] = str(args.port)
    os.environ["PYTHONPATH"] = str(ROOT / "backend")
    data_dir = Path(os.environ["SUBTITLE_DATA_DIR"]).expanduser().resolve()
    os.environ["SUBTITLE_DATA_DIR"] = str(data_dir)
    logs_dir = data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    try:
        with socket.socket() as check:
            check.bind(("127.0.0.1", args.port))
    except OSError:
        print(f"端口 {args.port} 已被占用，请关闭旧工作台，或用 --port 指定另一端口。", file=sys.stderr)
        return 1

    children: list[subprocess.Popen] = []
    stopped = False

    def request_stop(_signum=None, _frame=None):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    url = f"http://127.0.0.1:{args.port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with (logs_dir / "api.log").open("a", buffering=1) as api_log, (logs_dir / "worker.log").open("a", buffering=1) as worker_log:
        try:
            api = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
                cwd=ROOT / "backend", stdout=api_log, stderr=subprocess.STDOUT, start_new_session=True,
            )
            children.append(api)
            deadline = time.monotonic() + 30
            while not stopped and time.monotonic() < deadline:
                if api.poll() is not None:
                    raise RuntimeError(f"API 启动失败，详见 {logs_dir / 'api.log'}")
                try:
                    with opener.open(url + "/api/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.2)
            else:
                if stopped:
                    return 0
                raise RuntimeError(f"API 启动超时，详见 {logs_dir / 'api.log'}")
            worker = subprocess.Popen(
                [sys.executable, "-m", "app.worker"], cwd=ROOT / "backend",
                stdout=worker_log, stderr=subprocess.STDOUT, start_new_session=True,
            )
            children.append(worker)
            print(f"字幕工作台已启动：{url}\n项目数据：{data_dir}\n运行日志：{logs_dir}\n保持此窗口打开；按 Ctrl+C 安全关闭 API 与翻译 worker。", flush=True)
            if not args.no_open:
                subprocess.run(["open", url], check=False)
            while not stopped:
                for name, process in (("API", api), ("worker", worker)):
                    if process.poll() is not None:
                        raise RuntimeError(f"{name} 意外退出，详见 {logs_dir}")
                time.sleep(0.5)
        except (OSError, RuntimeError) as error:
            print(str(error), file=sys.stderr)
            return 1
        finally:
            for process in children:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
            for process in children:
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
            print("工作台已关闭。已提交的编辑保留在本地数据目录。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
