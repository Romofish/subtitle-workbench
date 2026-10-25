"""Real OS checks for exclusive workers and reclamation of owned processes."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from app.platform_runtime import ProcessTree, WorkerAlreadyRunning, worker_lock


BACKEND = Path(__file__).resolve().parents[1]


def process_running(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # Linux may briefly retain an already-dead orphan as a zombie.
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists() and stat.read_text().split(")", 1)[1].split()[0] == "Z":
        return False
    return True


class PlatformRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="subtitle runtime ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(BACKEND), str(self.root))), "PYTHONUTF8": "1"}

    def wait_for(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.05)
        self.fail("Timed out waiting for the test process")

    def read_pids(self, marker):
        try:
            return json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def holder(self):
        path = self.root / "worker.lock"
        ready = self.root / "ready"
        code = """
from pathlib import Path
import sys
from app.platform_runtime import worker_lock
with worker_lock(Path(sys.argv[1])):
    Path(sys.argv[2]).write_text('ready', encoding='utf-8')
    sys.stdin.buffer.read(1)
"""
        process = subprocess.Popen([sys.executable, "-c", code, str(path), str(ready)],
                                   env=self.env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            process.stdin.close()
        self.addCleanup(cleanup)
        self.wait_for(ready.exists)
        return process, path

    def test_worker_lock_excludes_another_process_and_releases(self):
        process, path = self.holder()
        with self.assertRaises(WorkerAlreadyRunning):
            with worker_lock(path):
                self.fail("A second worker entered the critical section")
        process.stdin.close()
        self.assertEqual(process.wait(timeout=3), 0)
        with worker_lock(path):
            self.assertTrue(path.is_file())

    def test_worker_lock_releases_after_abrupt_exit(self):
        process, path = self.holder()
        process.kill()
        process.wait(timeout=3)
        with worker_lock(path):
            self.assertTrue(path.is_file())

    def fixture(self):
        module = self.root / "runtime_fixture.py"
        module.write_text("""
import json, os, pathlib, signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
if hasattr(signal, 'SIGBREAK'):
    signal.signal(signal.SIGBREAK, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, '-c',
    "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "signal.signal(signal.SIGBREAK, signal.SIG_IGN) if hasattr(signal, 'SIGBREAK') else None; time.sleep(30)"])
marker = pathlib.Path(sys.argv[1])
marker.write_text(json.dumps([os.getpid(), child.pid]), encoding='utf-8')
time.sleep(30)
""", encoding="utf-8")
        return self.root / "processes.json"

    def test_shutdown_removes_service_and_descendant_even_if_they_ignore_stop(self):
        marker = self.fixture()
        tree = ProcessTree()
        self.addCleanup(tree.shutdown, .1)
        process = tree.start_module("runtime_fixture", [str(marker)], cwd=self.root,
                                    env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.wait_for(lambda: len(self.read_pids(marker)) == 2)
        pids = self.read_pids(marker)
        self.assertTrue(all(process_running(pid) for pid in pids))
        tree.shutdown(.2)
        self.assertIsNotNone(process.poll())
        self.wait_for(lambda: not any(process_running(pid) for pid in pids))

    def test_shutdown_requests_cooperative_service_exit(self):
        (self.root / "cooperative_fixture.py").write_text("""
import pathlib, signal, sys, time
ready, stopped = map(pathlib.Path, sys.argv[1:])
stopping = False
def stop(signum, frame):
    global stopping
    stopped.write_text(str(signum), encoding='utf-8')
    stopping = True
signal.signal(signal.SIGTERM, stop)
if hasattr(signal, 'SIGBREAK'):
    signal.signal(signal.SIGBREAK, stop)
ready.write_text('ready', encoding='utf-8')
while not stopping:
    time.sleep(.05)
""", encoding="utf-8")
        ready, stopped, outcome = [self.root / name for name in ("ready", "stopped", "outcome")]
        code = """
import pathlib, subprocess, sys, time
from app.platform_runtime import ProcessTree
ready, stopped, outcome = map(pathlib.Path, sys.argv[1:])
tree = ProcessTree()
try:
    process = tree.start_module('cooperative_fixture', [str(ready), str(stopped)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 5
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(.05)
finally:
    tree.shutdown(3)
outcome.write_text(str(process.returncode), encoding='utf-8')
"""
        options = {}
        if os.name == "nt":
            # A console is required for targeted CTRL_BREAK. Hide this test
            # console; background hosts commonly have no console to inherit.
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            options = {"creationflags": subprocess.CREATE_NEW_CONSOLE, "startupinfo": startup}
        result = subprocess.run([sys.executable, "-c", code, str(ready), str(stopped), str(outcome)],
                                cwd=self.root, env=self.env, capture_output=True, timeout=12, **options)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outcome.read_text(encoding="utf-8"), "0")
        expected = signal.SIGBREAK if os.name == "nt" else signal.SIGTERM
        self.assertEqual(stopped.read_text(encoding="utf-8"), str(expected))

    @unittest.skipUnless(os.name == "nt", "Windows job lifetime check")
    def test_abrupt_launcher_exit_closes_job_and_removes_descendants(self):
        marker = self.fixture()
        code = """
import subprocess, sys, time
from app.platform_runtime import ProcessTree
tree = ProcessTree()
tree.start_module('runtime_fixture', [sys.argv[1]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(30)
"""
        owner = subprocess.Popen([sys.executable, "-c", code, str(marker)], cwd=self.root,
                                 env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def cleanup():
            if owner.poll() is None:
                owner.kill()
            owner.wait(timeout=3)
        self.addCleanup(cleanup)
        self.wait_for(lambda: len(self.read_pids(marker)) == 2)
        pids = self.read_pids(marker)
        owner.kill()  # Equivalent handle cleanup to closing the launcher's console.
        owner.wait(timeout=3)
        self.wait_for(lambda: not any(process_running(pid) for pid in pids))


if __name__ == "__main__":
    unittest.main()
