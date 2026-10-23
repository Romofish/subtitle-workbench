#!/usr/bin/env python3
"""Install pinned whisper.cpp + multilingual model in tools/asr (no paid API).

Requires macOS Apple Silicon, Python 3.12+, curl, and Apple command-line tools.
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
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tools/asr"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connections", type=int, default=6)
    parser.add_argument("--direct", action="store_true", help="直连官方站点，不使用代理")
    parser.add_argument("--rebuild", action="store_true", help="重新构建引擎")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("此安装器仅为 Apple Silicon macOS 构建。")
    if not 1 <= args.connections <= 12:
        parser.error("connections 必须是 1–12")
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
    manifest_path = BASE / "manifest.json"
    manifest = {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "platform": "macOS arm64; Apple Silicon Metal",
        "engine": {"name": "whisper.cpp", "version": VERSION, "path": str(engine_path), "sha256": digest(engine_path), "bytes": engine_path.stat().st_size, "source_commit": COMMIT, "build": "Release arm64; static ggml/whisper; embedded Metal kernels", "dynamic_dependencies": dependencies.splitlines()[1:]},
        "model": {"name": MODEL["name"], "path": str(model_path), "sha256": MODEL["sha256"], "bytes": MODEL["bytes"], "repository_revision": MODEL_REVISION, "multilingual": True},
        "sources": {"engine_release": f"https://github.com/ggml-org/whisper.cpp/releases/tag/v{VERSION}", "source_archive": SOURCE, "model": MODEL, "model_lfs_metadata": f"https://huggingface.co/api/models/ggerganov/whisper.cpp/revision/{MODEL_REVISION}?blobs=true", "build_tool": CMAKE},
        "verification": {"engine_version": version, "model_sha256": "passed against official Hugging Face LFS metadata", "runtime_smoke": "pending"},
    }
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if previous.get("engine", {}).get("sha256") == manifest["engine"]["sha256"] and previous.get("model", {}).get("sha256") == MODEL["sha256"]:
            manifest["verification"].update(previous.get("verification", {}))
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(manifest_path)
    print(f"本地 ASR 已安装并校验。\n引擎：{engine_path}\n模型：{model_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
