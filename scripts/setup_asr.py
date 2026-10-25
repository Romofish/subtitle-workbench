#!/usr/bin/env python3
"""Install pinned whisper.cpp + multilingual model (no paid API).

Windows x64 uses the official CPU/CUDA binaries; Apple Silicon builds Metal.
Requires Python 3.12+ and curl; only macOS needs Apple command-line tools.
Downloads and builds only; it never transcribes a user's media automatically.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from datetime import datetime, timezone

from windows_environment import asr_directory

ROOT = Path(__file__).resolve().parents[1]
BASE = (asr_directory() if os.name == "nt" else
        Path(os.environ.get("SUBTITLE_ASR_DIR") or ROOT / "tools/asr").expanduser().resolve())
DOWNLOADS = BASE / "downloads"
VERSION = "1.9.5"
COMMIT = "d1be6fde11ac6e0407606b4e42fe72d34add8037"
MODEL_REVISION = "5359861c739e955e79d9a303bcbc70fb988958b1"
MODEL_NAME = "ggml-large-v3-turbo-q5_0.bin"
MODEL = {
    "name": "large-v3-turbo-q5_0", "file": MODEL_NAME, "bytes": 574041195,
    "sha256": "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
    "url": f"https://huggingface.co/ggerganov/whisper.cpp/resolve/{MODEL_REVISION}/{MODEL_NAME}",
    "sha256_source": "Hugging Face model repository API, LFS SHA-256",
}
CMAKE = {
    "name": "CMake 4.1.0", "file": "cmake-4.1.0-macos-universal.tar.gz", "bytes": 81099137,
    "sha256": "08cbe0b807799a90216923acf457481538c8d0608a19ba9203219387427a4055",
    "url": "https://cmake.org/files/v4.1/cmake-4.1.0-macos-universal.tar.gz",
    "release_url": "https://github.com/Kitware/CMake/releases/tag/v4.1.0",
    "sha256_source": "Kitware GitHub release asset digest",
}
SOURCE = {
    "name": "whisper.cpp source v1.9.5", "file": "whisper.cpp-v1.9.5.tar.gz", "bytes": 9626464,
    "sha256": "ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720",
    "url": "https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v1.9.5",
    "sha256_source": "locally pinned after official HTTPS download; tag resolves to recorded commit",
}
WINDOWS_RELEASE = "b5454"
WINDOWS = {
    "cuda": {
        "name": "whisper.cpp Windows x64 CUDA 12.4", "file": "whisper-bin-win-cuda-12.4.0-x64.zip",
        "bytes": 684913404,
        "sha256": "afef0b881c500958921c3f5523b50e59ee2ec9b6f5cbd25b324c51ed308a957a",
    },
    "cpu": {
        "name": "whisper.cpp Windows x64 CPU", "file": "whisper-bin-x64.zip",
        "bytes": 8928640,
        "sha256": "6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb",
    },
}
for artifact in WINDOWS.values():
    artifact.update(url=f"https://github.com/ggml-org/whisper.cpp/releases/download/{WINDOWS_RELEASE}/{artifact['file']}",
                    sha256_source="ggml-org GitHub release asset digest")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked(path: Path, artifact: dict) -> bool:
    return path.is_file() and path.stat().st_size == artifact["bytes"] and digest(path) == artifact["sha256"]


def download(artifact: dict, destination: Path, connections: int, direct: bool) -> Path:
    if checked(destination, artifact):
        print(f'{artifact["name"]}: 已存在且 SHA-256 正确。', flush=True)
        return destination
    if destination.exists():
        raise RuntimeError(f"{destination} 已存在但校验失败；请另存后重试，脚本不会覆盖它。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    parts = DOWNLOADS / (artifact["file"] + ".parts")
    parts.mkdir(exist_ok=True)
    chunk_size = 8 * 1024 * 1024
    chunks = []
    for index, start in enumerate(range(0, artifact["bytes"], chunk_size)):
        size = min(chunk_size, artifact["bytes"] - start)
        path = parts / f"{index:05}.part"
        if not path.exists() or path.stat().st_size != size:
            chunks.append((start, size, path))

    def fetch(chunk):
        start, size, final = chunk
        partial = final.with_suffix(".partial")
        tail = final.with_suffix(".tail")
        # A cancelled previous run may have received bytes not yet appended.
        if tail.exists() and tail.stat().st_size:
            have = partial.stat().st_size if partial.exists() else 0
            if tail.stat().st_size > size - have:
                raise RuntimeError(f"保留分段大小错误：{tail}")
            with partial.open("ab") as stream:
                stream.write(tail.read_bytes())
            tail.unlink()
        for attempt in range(10):
            have = partial.stat().st_size if partial.exists() else 0
            if have == size:
                break
            if have > size:
                raise RuntimeError(f"下载分段大小错误：{partial}")
            tail.unlink(missing_ok=True)
            if attempt:
                time.sleep(1)
            command = ["curl", "--fail", "--location", "--silent", "--show-error", "--http1.1", "--connect-timeout", "20", "--max-time", "120", "--speed-limit", "8192", "--speed-time", "30", "--range", f"{start + have}-{start + size - 1}", "--output", str(tail)]
            if direct:
                command += ["--noproxy", "*"]
            subprocess.run(command + [artifact["url"]], check=False)
            if tail.exists() and tail.stat().st_size:
                if tail.stat().st_size > size - have:
                    raise RuntimeError("服务器未遵守分段大小；拒绝合并。")
                with partial.open("ab") as stream:
                    stream.write(tail.read_bytes())
                tail.unlink()
        if not partial.is_file() or partial.stat().st_size != size:
            raise RuntimeError(f"分段未完成：{partial}；可再次执行续传。")
        partial.replace(final)

    errors = []
    with ThreadPoolExecutor(max_workers=connections) as executor:
        for i, future in enumerate(as_completed([executor.submit(fetch, c) for c in chunks]), 1):
            try:
                future.result()
                print(f'{artifact["name"]}: {i}/{len(chunks)} 分段完成。', flush=True)
            except Exception as error:
                errors.append(str(error))
    if errors:
        raise RuntimeError(f'{artifact["name"]}: {len(errors)} 分段未完成，请重新执行续传。')
    temporary = destination.with_suffix(destination.suffix + ".verifying")
    with temporary.open("wb") as stream:
        for index in range((artifact["bytes"] + chunk_size - 1) // chunk_size):
            with (parts / f"{index:05}.part").open("rb") as part:
                shutil.copyfileobj(part, stream)
    if not checked(temporary, artifact):
        raise RuntimeError(f'{artifact["name"]} SHA-256 校验失败，拒绝采用下载文件。')
    temporary.replace(destination)
    for part in parts.glob("*.part"):
        part.unlink()
    parts.rmdir()
    print(f'{artifact["name"]}: 完整 SHA-256 通过。', flush=True)
    return destination


def unpack(archive: Path, destination: Path, expected: Path) -> None:
    if expected.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(destination, filter="data")
    if not expected.exists():
        raise RuntimeError(f"解压未生成预期文件：{expected}")


def nvidia_available() -> bool:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return False
    try:
        result = subprocess.run([executable, "--query-gpu=name", "--format=csv,noheader"],
                                capture_output=True, timeout=10)
        return result.returncode == 0 and bool(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def write_manifest(manifest: dict) -> None:
    manifest_path = BASE / "manifest.json"
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            previous = {}
        if (previous.get("engine", {}).get("sha256") == manifest["engine"]["sha256"]
                and previous.get("model", {}).get("sha256") == MODEL["sha256"]):
            # Do not overwrite the newly verified current version or dependency list.
            if "runtime_smoke" in previous.get("verification", {}):
                manifest["verification"]["runtime_smoke"] = previous["verification"]["runtime_smoke"]
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)


def install_windows(args) -> int:
    backend = args.backend
    if backend == "auto":
        backend = "cuda" if nvidia_available() else "cpu"
    artifact = WINDOWS[backend]
    model_path = BASE / "models" / MODEL_NAME
    engine_dir = BASE / "bin"
    engine_path = engine_dir / "whisper-cli.exe"
    print(f"Windows x64 识别引擎：{backend}；安装目录：{BASE}", flush=True)
    previous = {}
    manifest_path = BASE / "manifest.json"
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    # Reuse a complete, hash-verified installation without downloading its ZIP again.
    installed_files = previous.get("engine", {}).get("files", [])
    reusable = (previous.get("sources", {}).get("binary_archive", {}).get("sha256") == artifact["sha256"]
                and bool(installed_files) and engine_path.is_file()
                and all(checked(engine_dir / item["path"], item) for item in installed_files))
    with ThreadPoolExecutor(max_workers=2) as parallel:
        model_future = parallel.submit(download, MODEL, model_path, args.connections, args.direct)
        if not reusable or args.rebuild:
            archive = download(artifact, DOWNLOADS / artifact["file"], args.connections, args.direct)
            with tempfile.TemporaryDirectory(prefix="unpack-", dir=BASE) as temporary:
                destination = Path(temporary).resolve()
                with zipfile.ZipFile(archive) as bundle:
                    # Never permit an archive entry to escape the fresh staging directory.
                    for member in bundle.infolist():
                        target = (destination / member.filename).resolve()
                        if not target.is_relative_to(destination) or member.filename.startswith(("/", "\\")):
                            raise RuntimeError("引擎压缩包包含不安全路径，已拒绝解压。")
                    bundle.extractall(destination)
                candidates = list(destination.rglob("whisper-cli.exe"))
                if len(candidates) != 1:
                    raise RuntimeError("官方压缩包中的 whisper-cli.exe 不唯一或缺失。")
                staging = candidates[0].parent
                if engine_dir.exists():
                    backup = BASE / ("bin-backup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
                    engine_dir.rename(backup)
                    print(f"保留原引擎：{backup}", flush=True)
                # Keep every DLL from the official Release directory, including CUDA runtimes.
                staging.rename(engine_dir)
        else:
            print("现有引擎与全部配套文件 SHA-256 正确，直接复用。", flush=True)
        result = subprocess.run([str(engine_path), "--version"], cwd=engine_dir,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        version = (result.stdout + result.stderr).strip()
        if result.returncode != 0 or VERSION not in version:
            raise RuntimeError(f"引擎未能正常启动或版本不匹配（退出码 {result.returncode}）：{version}")
        model_future.result()
    files = [{"path": str(path.relative_to(engine_dir)), "bytes": path.stat().st_size, "sha256": digest(path)}
             for path in sorted(engine_dir.rglob("*")) if path.is_file()]
    manifest = {
        "schema_version": 1, "installed_at": datetime.now(timezone.utc).isoformat(),
        "platform": f"Windows x64; {backend}",
        "engine": {"name": "whisper.cpp", "version": VERSION, "path": str(engine_path),
                   "sha256": digest(engine_path), "bytes": engine_path.stat().st_size,
                   "source_commit": COMMIT, "build": f"official {WINDOWS_RELEASE} Windows x64 {backend}",
                   "backend": backend, "files": files,
                   "dynamic_dependencies": [item["path"] for item in files if item["path"].lower().endswith(".dll")]},
        "model": {"name": MODEL["name"], "path": str(model_path), "sha256": MODEL["sha256"],
                  "bytes": MODEL["bytes"], "repository_revision": MODEL_REVISION, "multilingual": True},
        "sources": {"engine_release": f"https://github.com/ggml-org/whisper.cpp/releases/tag/{WINDOWS_RELEASE}",
                    "binary_archive": artifact, "model": MODEL,
                    "model_lfs_metadata": f"https://huggingface.co/api/models/ggerganov/whisper.cpp/revision/{MODEL_REVISION}?blobs=true"},
        "verification": {"engine_version": version, "binary_archive_sha256": "passed against official GitHub asset digest",
                         "model_sha256": "passed against official Hugging Face LFS metadata", "runtime_smoke": "pending"},
    }
    write_manifest(manifest)
    print(f"本地 ASR 已安装并校验。\n引擎：{engine_path}\n模型：{model_path}", flush=True)
    if backend == "cuda":
        print("默认自动使用 GPU；如需 CPU 运行，可设置 SUBTITLE_ASR_DEVICE=cpu 后重启工作台。", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connections", type=int, default=6)
    parser.add_argument("--direct", action="store_true", help="直连官方站点，不使用代理")
    parser.add_argument("--rebuild", action="store_true", help="重新构建引擎")
    parser.add_argument("--backend", choices=("auto", "cuda", "cpu"), default="auto",
                        help="Windows 引擎：auto 检测 NVIDIA；cuda 使用 CUDA；cpu 使用 CPU")
    args = parser.parse_args()
    if not 1 <= args.connections <= 12:
        parser.error("connections 必须是 1–12")
    if os.name == "nt":
        if platform.machine().lower() not in ("amd64", "x86_64"):
            parser.error("当前 Windows 安装器支持 x64。")
        if not shutil.which("curl"):
            parser.error("缺少 curl.exe，请先安装 Windows 系统下载组件。")
        DOWNLOADS.mkdir(parents=True, exist_ok=True)
        return install_windows(args)
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("此安装器支持 Windows x64 或 Apple Silicon macOS。")
    for command in ("curl", "clang", "make"):
        if not shutil.which(command):
            parser.error(f"缺少 {command}，请先安装 Apple Command Line Tools。")
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    source_dir = BASE / "source" / f"whisper.cpp-{VERSION}"
    cmake_root = BASE / "build-tools" / "cmake-4.1.0-macos-universal"
    cmake_bin = cmake_root / "CMake.app/Contents/bin/cmake"
    model_path = BASE / "models" / MODEL_NAME
    engine_path = BASE / "bin/whisper-cli"
    with ThreadPoolExecutor(max_workers=2) as parallel:
        model_future = parallel.submit(download, MODEL, model_path, args.connections, args.direct)
        cmake_future = parallel.submit(download, CMAKE, DOWNLOADS / CMAKE["file"], args.connections, args.direct)
        source_archive = download(SOURCE, DOWNLOADS / SOURCE["file"], min(2, args.connections), args.direct)
        unpack(source_archive, source_dir.parent, source_dir / "CMakeLists.txt")
        cmake_archive = cmake_future.result()
        unpack(cmake_archive, cmake_root.parent, cmake_bin)
        build_dir = BASE / "build"
        if not engine_path.is_file() or args.rebuild:
            subprocess.run([str(cmake_bin), "-S", str(source_dir), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_OSX_ARCHITECTURES=arm64", "-DBUILD_SHARED_LIBS=OFF", "-DGGML_BACKEND_DL=OFF", "-DGGML_METAL=ON", "-DGGML_METAL_EMBED_LIBRARY=ON", "-DWHISPER_BUILD_IS_DEV=OFF", "-DWHISPER_BUILD_TESTS=OFF", "-DWHISPER_BUILD_EXAMPLES=ON", "-DWHISPER_BUILD_SERVER=OFF"], check=True)
            subprocess.run([str(cmake_bin), "--build", str(build_dir), "--target", "whisper-cli", "--config", "Release", "--parallel", "4"], check=True)
            engine_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(build_dir / "bin/whisper-cli", engine_path)
        version = subprocess.check_output([str(engine_path), "--version"], text=True).strip()
        if VERSION not in version or "-dev" in version:
            raise RuntimeError(f"引擎版本不匹配：{version}")
        dependencies = subprocess.check_output(["otool", "-L", str(engine_path)], text=True)
        model_future.result()
    manifest = {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "platform": "macOS arm64; Apple Silicon Metal",
        "engine": {"name": "whisper.cpp", "version": VERSION, "path": str(engine_path), "sha256": digest(engine_path), "bytes": engine_path.stat().st_size, "source_commit": COMMIT, "build": "Release arm64; static ggml/whisper; embedded Metal kernels", "dynamic_dependencies": dependencies.splitlines()[1:]},
        "model": {"name": MODEL["name"], "path": str(model_path), "sha256": MODEL["sha256"], "bytes": MODEL["bytes"], "repository_revision": MODEL_REVISION, "multilingual": True},
        "sources": {"engine_release": f"https://github.com/ggml-org/whisper.cpp/releases/tag/v{VERSION}", "source_archive": SOURCE, "model": MODEL, "model_lfs_metadata": f"https://huggingface.co/api/models/ggerganov/whisper.cpp/revision/{MODEL_REVISION}?blobs=true", "build_tool": CMAKE},
        "verification": {"engine_version": version, "model_sha256": "passed against official Hugging Face LFS metadata", "runtime_smoke": "pending"},
    }
    write_manifest(manifest)
    print(f"本地 ASR 已安装并校验。\n引擎：{engine_path}\n模型：{model_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
