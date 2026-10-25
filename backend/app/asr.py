"""Local whisper.cpp tasks. Media stays on disk; task completion and project creation commit together."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Callable

from fastapi import HTTPException

from . import media as media_utils
from .store import connect, data_dir, now, uid
from .subtitles import TIMING, parse_subtitles, refresh_risks, time_ms, timestamp
from .asr_quality import QUALITY_RULE_VERSION, asr_quality_warnings

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ('queued', 'running')


def configuration() -> dict:
    default = (Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) /
               'Programs/SubtitleWorkbench/asr') if os.name == 'nt' else ROOT / 'tools' / 'asr'
    base = Path(os.environ.get('SUBTITLE_ASR_DIR', default)).expanduser().resolve()
    engine = base / 'bin' / ('whisper-cli.exe' if os.name == 'nt' else 'whisper-cli')
    model = base / 'models' / 'ggml-large-v3-turbo-q5_0.bin'
    device = os.environ.get('SUBTITLE_ASR_DEVICE', 'auto').lower()
    reasons = []
    if device not in ('auto', 'cpu'):
        reasons.append('SUBTITLE_ASR_DEVICE 只支持 auto 或 cpu')
    if not engine.is_file() or not os.access(engine, os.X_OK):
        reasons.append('本地识别引擎未安装，请运行 scripts/setup_asr.py')
    if not model.is_file() or model.stat().st_size < 1024 * 1024:
        reasons.append('多语言模型未下载完整，请运行 scripts/setup_asr.py')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        reasons.append('未找到 FFmpeg / ffprobe')
    return {'ready': not reasons, 'engine': 'whisper.cpp', 'model': 'large-v3-turbo-q5_0',
            'model_label': 'Whisper large-v3-turbo · 多语言 · Q5', 'local': True,
            'reasons': reasons, 'engine_path': str(engine), 'model_path': str(model),
            'device': device, 'manifest_path': str(base / 'manifest.json')}


def _connect():
    conn = connect()
    conn.execute('CREATE TABLE IF NOT EXISTS asr_tasks (task_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL, document TEXT NOT NULL)')
    return conn


def _read(conn, task_id: str) -> dict:
    row = conn.execute('SELECT document FROM asr_tasks WHERE task_id=?', (task_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '转写任务不存在')
    return json.loads(row['document'])


def _write(conn, task: dict):
    task['updated_at'] = now()
    conn.execute('UPDATE asr_tasks SET status=?, document=? WHERE task_id=?',
                 (task['status'], json.dumps(task, ensure_ascii=False), task['task_id']))


def public(task: dict) -> dict:
    return {key: value for key, value in task.items() if not key.startswith('_')}


def get_task(task_id: str) -> dict:
    with closing(_connect()) as conn:
        return _read(conn, task_id)


def list_tasks() -> list[dict]:
    with closing(_connect()) as conn:
        return [public(json.loads(row['document'])) for row in conn.execute('SELECT document FROM asr_tasks ORDER BY created_at DESC LIMIT 100')]


def enqueue(path: Path, digest: str, filename: str, name: str, language: str,
            audio_track: int | None, task_id: str) -> dict:
    task = {'task_id': task_id, 'status': 'queued', 'stage': '排队等待', 'progress': 0,
            'filename': filename, 'name': name.strip() or Path(filename).stem, 'language': language,
            'audio_track': audio_track, 'created_at': now(), 'updated_at': now(), 'error': None,
            'project_id': None, '_path': str(path), '_sha256': digest}
    with closing(_connect()) as conn:
        conn.execute('INSERT INTO asr_tasks VALUES (?,?,?,?)',
                     (task_id, task['created_at'], task['status'], json.dumps(task, ensure_ascii=False)))
        conn.commit()
    return public(task)


def cancel(task_id: str) -> dict:
    with closing(_connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        task = _read(conn, task_id)
        previous = task['status']
        if previous in ACTIVE:
            task.update(status='cancelled', stage='已取消', error=None)
            _write(conn, task)
        conn.commit()
    # A running worker owns its files until its child has exited.
    if previous == 'queued':
        _cleanup(task)
    return public(task)


def _cleanup(task: dict):
    directory = data_dir() / 'transcriptions' / task['task_id']
    if directory.is_dir():
        try:
            shutil.rmtree(directory)
        except OSError:
            # A cleanup problem must not invalidate an already committed project.
            print(f'转写临时目录未能清理：{directory}', flush=True)


def transition(task_id: str, **values) -> bool:
    with closing(_connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        task = _read(conn, task_id)
        if task['status'] not in ACTIVE:
            return False
        if 'progress' in values:
            values['progress'] = max(task['progress'], values['progress'])
        task.update(values)
        _write(conn, task)
        conn.commit()
        return True


def recover():
    """Interrupted work needs an explicit new request; never create phantom completed projects."""
    with closing(_connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        tasks = [json.loads(row[0]) for row in conn.execute("SELECT document FROM asr_tasks WHERE status IN ('queued','running')")]
        for task in tasks:
            task.update(status='failed', stage='识别中断', error='工作台上次退出时识别尚未完成，请重新选择媒体开始。原媒体未改动。')
            _write(conn, task)
        conn.commit()
    for task in tasks:
        _cleanup(task)


class Cancelled(Exception):
    pass


def run_command(arguments: list[str], task_id: str, log: Path, stopped: Callable[[], bool],
                progress: Callable[[str], int | None] | None = None, timeout: int = 14400):
    """Poll rather than blocking on stderr: cancellation also works when an engine is silent."""
    started = time.monotonic()
    offset = 0
    with log.open('wb') as handle:
        # Children inherit the worker's process group so launcher shutdown also reaps them.
        child = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT)
        try:
            while True:
                if stopped() or get_task(task_id)['status'] == 'cancelled':
                    raise Cancelled()
                result = child.poll()
                if result is not None:
                    if result != 0:
                        raise RuntimeError(f'本地工具运行失败（退出码 {result}），请检查媒体格式或识别引擎。')
                    return
                if time.monotonic() - started > timeout:
                    raise RuntimeError('本地处理超过 4 小时，已停止；请用较短片段重试。')
                if progress and log.exists():
                    with log.open('rb') as reader:
                        reader.seek(offset)
                        chunk = reader.read(128 * 1024)
                        offset = reader.tell()
                    value = progress(chunk.decode('utf-8', errors='replace'))
                    if value is not None:
                        transition(task_id, progress=value)
                time.sleep(0.4)
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)


def _engine_progress(text: str) -> int | None:
    values = re.findall(r'progress\s*=\s*(\d+)%', text)
    return min(95, 10 + int(values[-1]) * 85 // 100) if values else None


def parse_engine_subtitles(raw: bytes, duration_ms: int | None) -> tuple[list[dict], list[dict]]:
    """Represent zero-duration engine cues as explicit, provisional 1 ms windows.

    Keep every cue and its words. The untouched SRT/JSON remain source evidence;
    external user imports still use the strict parser with no such adjustment.
    This is an import repair, not forced alignment or a synchronization claim.
    """
    try:
        text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    except UnicodeDecodeError:
        # Preserve the standard parser's clear encoding error.
        return parse_subtitles(raw, 'transcription.srt'), []
    blocks = re.split(r'\n[ \t]*\n', text.strip())
    repairs = []
    cue_index = 0
    for index, block in enumerate(blocks):
        lines = block.splitlines()
        if not lines:
            continue
        cue_index += 1
        timing_index = next((i for i, line in enumerate(lines[:2]) if '-->' in line), None)
        if timing_index is None:
            continue
        match = TIMING.match(lines[timing_index])
        if match is None:
            continue
        try:
            start, end = time_ms(match[1]), time_ms(match[2])
        except (ValueError, TypeError):
            continue
        if start != end or start < 0:
            continue
        repaired_start, repaired_end = (start - 1, start) if start > 0 and start == duration_ms else (start, start + 1)
        lines[timing_index] = f'{timestamp(repaired_start, "srt")} --> {timestamp(repaired_end, "srt")}'
        blocks[index] = '\n'.join(lines)
        repairs.append({'cue_index': cue_index, 'original_start_ms': start, 'original_end_ms': end,
                        'start_ms': repaired_start, 'end_ms': repaired_end,
                        'reason': 'engine_zero_duration', 'method': 'provisional_1ms_review_window'})
    segments = parse_subtitles(('\n\n'.join(blocks) + '\n').encode('utf-8'), 'transcription.srt')
    for item in segments:
        item['asr_warnings'] = asr_quality_warnings(item['source_text'], item['end_ms'] - item['start_ms'])
    for repair in repairs:
        item = segments[repair['cue_index'] - 1]
        repair['segment_id'] = item['segment_id']
        item['asr_warnings'].append('asr_timing_repaired')
        item['asr_timing_reviewed'] = False
    return segments, repairs


def preserve_diagnostics(task_id: str, directory: Path) -> Path | None:
    """Keep bounded engine evidence on failure, without keeping uploaded media/WAV."""
    files = [directory / name for name in ('transcription.srt', 'transcription.json', 'asr.log', 'ffmpeg.log')]
    if not any(path.is_file() for path in files):
        return None
    destination = data_dir() / 'asr-diagnostics' / task_id
    try:
        destination.mkdir(parents=True, exist_ok=True)
        for path in files:
            if path.is_file():
                shutil.copy2(path, destination / path.name)
        return destination
    except OSError:
        return None


def _finish(task: dict, media: dict, segments: list[dict], raw: bytes, result_json: dict, config: dict):
    task_id = task['task_id']
    pid = uid()
    directory = data_dir() / 'projects' / pid
    directory.mkdir(parents=True)
    committed = False
    try:
        # Hard-link the immutable uploaded media on the same data volume; no second large copy.
        target = directory / Path(task['_path']).name
        os.link(task['_path'], target)
        (directory / 'original-subtitle').write_bytes(raw)
        shutil.copyfile(data_dir() / 'transcriptions' / task_id / 'transcription.json',
                        directory / 'asr-result.json')
        media.update(path=str(target), url=f'/api/projects/{pid}/media')
        detected = (result_json.get('result') or {}).get('language')
        language = task['language'] if task['language'] != 'auto' else detected or 'unknown'
        provenance = {'engine': config['engine'], 'model': config['model'], 'task': 'transcribe',
                      'local': True, 'requested_language': task['language'], 'detected_language': detected,
                      'audio_track': media['selected_audio_track'], 'media_sha256': media['sha256'],
                      'timeline': 'media_origin_milliseconds', 'mixed_language_review_required': True}
        warning_counts = {code: sum(code in item.get('asr_warnings', []) for item in segments)
                          for code in ('asr_repetition', 'asr_long_segment', 'asr_timing_repaired')}
        provenance['quality_review'] = {'rule_version': QUALITY_RULE_VERSION, 'warning_counts': warning_counts,
                                        'flagged_segment_count': sum(bool(item.get('asr_warnings')) for item in segments),
                                        'text_preserved': True, 'speaker_diarization': False,
                                        'overlap_separation': False, 'human_listening_required': True}
        provenance['timing_repairs'] = config.get('timing_repairs', [])
        manifest = Path(config.get('manifest_path', ROOT / 'tools' / 'asr' / 'manifest.json'))
        if manifest.is_file():
            try:
                installed = json.loads(manifest.read_text(encoding='utf-8'))
                provenance['installation'] = installed
            except (ValueError, OSError):
                pass
        for segment in segments:
            segment['review_status'] = 'needs_review'
        project = {'project_id': pid, 'name': task['name'], 'schema_version': 1,
                   'document_revision': 1, 'created_at': now(), 'updated_at': now(),
                   'target_language': 'zh-Hans', 'language': language, 'glossary_version': 0,
                   'glossary': [], 'media': media,
                   'track': {'track_id': uid(), 'language': language, 'source_type': 'local_asr',
                             'source_note': '本地 Whisper 自动识别底稿，尚未人工核验；不自动区分说话人或分离重叠人声，混说、重复、专名与同步需复核。',
                             'filename': 'transcription.srt', 'sha256': hashlib.sha256(raw).hexdigest(),
                             'media_id': media['media_id'], 'confidence': 'machine_unverified', 'asr': provenance},
                   'segments': segments, 'candidates': [], 'jobs': [], 'revisions': [],
                   'reference_tracks': [], 'exports': []}
        refresh_risks(project)
        with closing(_connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            current = _read(conn, task_id)
            if current['status'] != 'running':
                raise Cancelled()
            conn.execute('INSERT INTO projects VALUES (?,?,?,?)',
                         (pid, project['name'], project['updated_at'], json.dumps(project, ensure_ascii=False)))
            current.update(status='completed', stage='完成', progress=100, project_id=pid,
                           segment_count=len(segments), detected_language=detected, error=None)
            _write(conn, current)
            conn.commit()
            committed = True
    finally:
        if not committed:
            shutil.rmtree(directory)


def run_one(stopped: Callable[[], bool] = lambda: False) -> bool:
    with closing(_connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT document FROM asr_tasks WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if row is None:
            return False
        task = json.loads(row[0])
        task.update(status='running', stage='读取媒体', progress=1)
        _write(conn, task)
        conn.commit()
    task_id = task['task_id']
    directory = data_dir() / 'transcriptions' / task_id
    try:
        config = configuration()
        if not config['ready']:
            raise RuntimeError('；'.join(config['reasons']))
        if stopped() or get_task(task_id)['status'] == 'cancelled':
            raise Cancelled()
        source = Path(task['_path'])
        media = media_utils.describe(source, task['filename'], task_id, task['_sha256'])
        if media.get('probe_error'):
            raise RuntimeError('无法读取媒体，请检查文件是否完整或格式是否支持。')
        streams = [stream['index'] for stream in media['streams'] if stream['codec_type'] == 'audio']
        audio = task['audio_track'] if task['audio_track'] is not None else (streams[0] if streams else None)
        if audio not in streams:
            raise RuntimeError('所选媒体中没有可用的指定音轨，请检查文件与音轨索引。')
        media['selected_audio_track'] = audio
        transition(task_id, stage='提取音轨', progress=3)
        wave = directory / 'audio.wav'
        run_command(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                     '-copyts', '-start_at_zero', '-i', str(source), '-map', f'0:{audio}',
                     '-vn', '-sn', '-dn', '-af', 'aresample=async=1:first_pts=0',
                     '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wave)],
                    task_id, directory / 'ffmpeg.log', stopped)
        transition(task_id, stage='本地语音识别', progress=10)
        prefix = directory / 'transcription'
        engine_arguments = [config['engine_path'], '-m', config['model_path'], '-f', str(wave),
                     '-l', task['language'], '-ojf', '-osrt', '-of', str(prefix), '-pp',
                     '-t', str(min(8, os.cpu_count() or 4))]
        if config.get('device') == 'cpu':
            engine_arguments.append('-ng')
        run_command(engine_arguments,
                    task_id, directory / 'asr.log', stopped, _engine_progress)
        transition(task_id, stage='创建审阅项目', progress=97)
        raw = prefix.with_suffix('.srt').read_bytes()
        result_json = json.loads(prefix.with_suffix('.json').read_text(encoding='utf-8'))
        if not isinstance(result_json, dict):
            raise RuntimeError('本地识别结果格式无效，请检查引擎版本。')
        try:
            segments, timing_repairs = parse_engine_subtitles(raw, media.get('duration_ms'))
        except HTTPException as error:
            hint = '未生成字幕，可能没有可识别人声。' if error.detail == 'No subtitle cues found' else '请检查原始识别输出。'
            raise RuntimeError(f'识别输出无法导入：{error.detail}。{hint}') from error
        config = {**config, 'timing_repairs': timing_repairs}
        if stopped():
            raise Cancelled()
        _finish(task, media, segments, raw, result_json, config)
    except Cancelled:
        transition(task_id, status='cancelled', stage='已取消', error=None)
    except Exception as error:
        message = str(error) if isinstance(error, RuntimeError) else '本地转写失败，请检查媒体、磁盘空间与识别工具后重新选择文件。'
        diagnostics = preserve_diagnostics(task_id, directory)
        if diagnostics is not None:
            message += f' 诊断输出保留在：{diagnostics}'
        transition(task_id, status='failed', stage='识别失败', error=message)
    finally:
        _cleanup(task)
    return True
