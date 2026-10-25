"""Platform-specific worker locking and owned process-tree lifetime."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import time


class WorkerAlreadyRunning(RuntimeError):
    pass


@contextmanager
def worker_lock(path: Path):
    """Hold an OS lock, automatically released even when the process is killed.

    Keep the lock file in place: unlinking it would allow another process to lock
    a different file while an existing worker still owns the old one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise WorkerAlreadyRunning(str(path)) from error
                raise
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise WorkerAlreadyRunning(str(path)) from error
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


class _WindowsJob:
    """A non-inherited job handle kills all owned processes when its owner exits."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self._api = ctypes.WinDLL("kernel32", use_last_error=True)
        self._api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self._api.CreateJobObjectW.restype = wintypes.HANDLE
        self._api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self._api.SetInformationJobObject.restype = wintypes.BOOL
        self._api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._api.AssignProcessToJobObject.restype = wintypes.BOOL
        self._api.CloseHandle.argtypes = [wintypes.HANDLE]
        self._api.CloseHandle.restype = wintypes.BOOL
        # NULL security attributes create a non-inheritable handle. Only the
        # launcher owns it, so closing a console also closes the last job handle.
        self._handle = self._api.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not self._api.SetInformationJobObject(self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process: subprocess.Popen):
        import ctypes

        # Popen retains the actual handle, avoiding a PID lookup/reuse race.
        if not self._api.AssignProcessToJobObject(self._handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self._handle:
            self._api.CloseHandle(self._handle)
            self._handle = None


class ProcessTree:
    """Launch Python services and stop only this launcher's process trees."""

    def __init__(self):
        self.processes: list[subprocess.Popen] = []
        self._job = _WindowsJob() if os.name == "nt" else None
        self._closed = False

    def start_module(self, module: str, arguments=(), **kwargs) -> subprocess.Popen:
        if self._closed:
            raise RuntimeError("Process supervisor is closed")
        if os.name == "nt":
            # The bootstrap waits for a byte before importing the service. This
            # makes assignment atomic from the service's perspective: it cannot
            # launch ffmpeg/Whisper before it belongs to our job.
            command = [sys.executable, "-m", "app.platform_runtime", "--run-module", module, *arguments]
            process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                       creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, **kwargs)
            self.processes.append(process)
            try:
                self._job.assign(process)
                process.stdin.write(b"1")
                process.stdin.flush()
            except BaseException:
                process.kill()
                process.wait(timeout=3)
                raise
            finally:
                process.stdin.close()
        else:
            process = subprocess.Popen([sys.executable, "-m", module, *arguments],
                                       stdin=subprocess.DEVNULL, start_new_session=True, **kwargs)
            self.processes.append(process)
        return process

    def shutdown(self, timeout: float = 8):
        if self._closed:
            return
        self._closed = True
        try:
            for process in self.processes:
                try:
                    if os.name == "nt":
                        if process.poll() is None:
                            process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    # No console (e.g. a background launch) can prevent BREAK.
                    # The job still guarantees the entire tree is reclaimed.
                    pass
            deadline = time.monotonic() + timeout
            for process in self.processes:
                try:
                    process.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if self._job is not None:
                self._job.close()
            else:
                # A service may exit while a descendant still holds its group.
                for process in self.processes:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            for process in self.processes:
                process.wait(timeout=3)


def _run_module():
    if len(sys.argv) < 3 or sys.argv[1] != "--run-module":
        raise SystemExit("Internal service bootstrap requires --run-module")
    if sys.stdin.buffer.read(1) != b"1":
        raise SystemExit("Launcher exited before assigning the service process")
    sys.stdin.close()
    sys.stdin = open(os.devnull, encoding="utf-8")
    module = sys.argv[2]
    sys.argv = [module, *sys.argv[3:]]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    _run_module()
