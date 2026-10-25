"""Single local worker. Run with PYTHONPATH=backend python -m app.worker."""
import argparse
import signal
import time

from .store import data_dir, list_projects, read_project, mutate_project, now
from .ai import run_batch, configuration
from . import asr
from .platform_runtime import WorkerAlreadyRunning, worker_lock

stopping = False


def stop(*_):
    global stopping
    stopping = True


def project_ids():
    rows = list_projects()
    if isinstance(rows, dict):
        rows = rows['projects']
    return [p['project_id'] for p in rows]


def recover():
    for pid in project_ids():
        if not any(j['status'] == 'running' for j in read_project(pid).get('jobs', [])):
            continue
        def update(p):
            for job in p.get('jobs', []):
                if job['status'] == 'running':
                    # Ambiguous external request may have been billed. Require explicit retry.
                    job.update(status='failed', error='worker 中断：已提交批次保留；当前未提交批次需手动重试，可能再次计费', updated_at=now())
        mutate_project(pid, 'worker', 'recover_interrupted_translation', update, undoable=False)


def main():
    global stopping
    stopping = False
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    lock_path = data_dir() / 'worker.lock'
    try:
        with worker_lock(lock_path):
            run(args.once)
    except WorkerAlreadyRunning:
        print('已有字幕 worker 运行。', flush=True)
        return 1
    return 0


def run(once=False):
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, stop)
    recover()
    asr.recover()
    print('字幕 worker 已启动；本地转写无需 AI 密钥，翻译任务按配置执行。', flush=True)
    while not stopping:
        worked = asr.run_one(lambda: stopping)
        if configuration()['ready']:
            for pid in project_ids():
                for job in read_project(pid).get('jobs', []):
                    if stopping:
                        break
                    if job['status'] == 'queued':
                        run_batch(pid, job['job_id'])
                        worked = True
        if once:
            break
        if not worked:
            time.sleep(1)


if __name__ == '__main__':
    raise SystemExit(main())
