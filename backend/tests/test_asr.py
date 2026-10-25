import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import asr
from app.asr_quality import asr_quality_warnings
from app.store import list_projects, read_project, data_dir


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBTITLE_DATA_DIR', str(tmp_path / 'data'))
    engine = tmp_path / 'whisper-cli.py'
    engine.write_text('''#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
prefix = pathlib.Path(args[args.index('-of') + 1])
assert '-tr' not in args and '--translate' not in args
assert args[args.index('-l') + 1] in ('auto', 'th', 'en')
prefix.with_suffix('.srt').write_text('1\\n00:00:00,100 --> 00:00:00,900\\nสวัสดี Hello\\n\\n', encoding='utf-8')
prefix.with_suffix('.json').write_text(json.dumps({'result': {'language': 'th'}, 'transcription': [{'text': 'สวัสดี 中文'}]}, ensure_ascii=False), encoding='utf-8')
print('whisper_print_progress_callback: progress = 100%', file=sys.stderr)
''', encoding='utf-8')
    # Exercise a real process on both platforms without relying on Unix shebang execution.
    original_popen = subprocess.Popen
    def popen(arguments, *args, **kwargs):
        if arguments[0] == str(engine):
            arguments = [sys.executable, *arguments]
        return original_popen(arguments, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', popen)
    config = {'ready': True, 'engine': 'whisper.cpp', 'model': 'test-mock-only', 'model_label': 'Test',
              'reasons': [], 'local': True, 'engine_path': str(engine), 'model_path': str(tmp_path / 'mock.bin')}
    monkeypatch.setattr(asr, 'configuration', lambda: config)
    if not shutil.which('ffmpeg'):
        pytest.skip('real ffmpeg required')
    media = tmp_path / 'voice.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                    '-c:a', 'pcm_s16le', str(media)], check=True)
    with TestClient(app) as client:
        yield client, engine, media, config


def queue(prepared, **fields):
    client, _, media, _ = prepared
    response = client.post('/api/transcriptions', files={'media': ('input.wav', media.read_bytes(), 'audio/wav')},
                           data={'name': '本地识别测试', 'language': 'auto', **fields})
    assert response.status_code == 202, response.text
    return response.json()


def test_real_extraction_mock_recognition_creates_separate_review_project(prepared):
    client, _, media, _ = prepared
    task = queue(prepared)
    assert task['status'] == 'queued' and task['project_id'] is None
    assert not any(key.startswith('_') for key in task)
    assert asr.run_one()
    result = client.get('/api/transcriptions/' + task['task_id']).json()
    assert result['status'] == 'completed' and result['progress'] == 100, result
    project = read_project(result['project_id'])
    assert project['track']['source_type'] == 'local_asr'
    assert project['track']['asr']['task'] == 'transcribe'
    assert project['language'] == 'th'
    assert project['segments'][0]['review_status'] == 'needs_review'
    assert project['segments'][0]['zh_text'] == ''
    assert project['segments'][0]['source_text'] == 'สวัสดี Hello'
    assert Path(project['media']['path']).read_bytes() == media.read_bytes()
    assert project['media']['sha256'] == hashlib.sha256(media.read_bytes()).hexdigest()
    assert not (data_dir() / 'transcriptions' / task['task_id']).exists()
    assert len(list_projects()) == 1
    assert not asr.run_one()
    exported = client.get('/api/projects/' + result['project_id'] + '/export?format=srt&mode=source')
    assert exported.status_code == 200 and 'สวัสดี Hello' in exported.text


def test_cancel_queued_task_does_not_create_project(prepared):
    client = prepared[0]
    task = queue(prepared)
    response = client.post('/api/transcriptions/' + task['task_id'] + '/cancel')
    assert response.json()['status'] == 'cancelled'
    assert not asr.run_one()
    assert list_projects() == []
    assert not (data_dir() / 'transcriptions' / task['task_id']).exists()


def test_silent_child_can_be_cancelled(prepared):
    client, engine, _, _ = prepared
    engine.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n')
    task = queue(prepared)
    errors = []
    def work():
        try:
            asr.run_one()
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=work)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if asr.get_task(task['task_id'])['stage'] == '本地语音识别':
            break
        time.sleep(.05)
    client.post('/api/transcriptions/' + task['task_id'] + '/cancel')
    thread.join(timeout=5)
    assert not thread.is_alive() and not errors
    assert asr.get_task(task['task_id'])['status'] == 'cancelled'
    assert list_projects() == []


def test_cancel_at_commit_never_creates_project(prepared, monkeypatch):
    task = queue(prepared)
    finish = asr._finish
    def cancel_then_finish(*args):
        asr.cancel(task['task_id'])
        return finish(*args)
    monkeypatch.setattr(asr, '_finish', cancel_then_finish)
    asr.run_one()
    assert asr.get_task(task['task_id'])['status'] == 'cancelled'
    assert list_projects() == []
    assert list((data_dir() / 'projects').iterdir()) == []


def test_invalid_track_and_empty_result_fail_without_project(prepared):
    _, engine, _, _ = prepared
    task = queue(prepared, audio_track='5')
    asr.run_one()
    assert asr.get_task(task['task_id'])['status'] == 'failed'
    assert '音轨' in asr.get_task(task['task_id'])['error']
    engine.write_text('''#!/usr/bin/env python3
import pathlib, sys
prefix = pathlib.Path(sys.argv[sys.argv.index('-of') + 1])
prefix.with_suffix('.srt').write_text('')
prefix.with_suffix('.json').write_text('{}')
''')
    task = queue(prepared)
    asr.run_one()
    assert asr.get_task(task['task_id'])['status'] == 'failed'
    assert '人声' in asr.get_task(task['task_id'])['error']
    assert list_projects() == []


def test_recovery_never_marks_interrupted_task_completed(prepared):
    task = queue(prepared)
    asr.transition(task['task_id'], status='running', progress=90)
    asr.recover()
    result = asr.get_task(task['task_id'])
    assert result['status'] == 'failed' and result['project_id'] is None
    assert not asr.run_one() and list_projects() == []


def test_unready_and_invalid_inputs_do_not_queue(prepared):
    client, _, media, config = prepared
    config.update(ready=False, reasons=['模型缺失'])
    response = client.post('/api/transcriptions', files={'media': ('input.wav', media.read_bytes())})
    assert response.status_code == 503
    config.update(ready=True, reasons=[])
    response = client.post('/api/transcriptions', files={'media': ('input.wav', b'')})
    assert response.status_code == 422
    response = client.post('/api/transcriptions', files={'media': ('input.wav', media.read_bytes())}, data={'language': 'xx'})
    assert response.status_code == 422
    assert asr.list_tasks() == []


def test_progress_is_engine_based_and_bounded():
    assert asr._engine_progress('whisper_print_progress_callback: progress = 50%') == 52
    assert asr._engine_progress('progress = 999%') == 95
    assert asr._engine_progress('unrelated text') is None


def test_quality_hints_preserve_repetition_and_do_not_guess_speakers():
    text = 'นี่' * 109
    assert asr_quality_warnings(text, 30000) == ['asr_repetition', 'asr_long_segment']
    assert asr_quality_warnings('No, no, no!', 2000) == []
    assert asr_quality_warnings('สวัสดี Hello 中文', 12000) == ['asr_long_segment']
    segments, repairs = asr.parse_engine_subtitles(
        f'1\n00:00:00,000 --> 00:00:30,000\n{text}\n'.encode('utf-8'), 60000)
    assert segments[0]['source_text'] == text and repairs == []
    assert segments[0]['asr_warnings'] == ['asr_repetition', 'asr_long_segment']
    assert not segments[0].get('speaker') and not segments[0].get('overlap')


def test_zero_duration_engine_cues_keep_every_word_and_original_times():
    raw = ('1\n00:00:00,000 --> 00:00:00,000\nสวัสดี\n\n\n\n'
           '2\n00:00:00,500 --> 00:00:00,500\nHello\n\n'
           '3\n00:00:00,500 --> 00:00:00,500\n另一个声音\n\n'
           '4\n00:00:01,000 --> 00:00:01,000\n结束\n').encode('utf-8')
    segments, repairs = asr.parse_engine_subtitles(raw, 1000)
    assert [s['source_text'] for s in segments] == ['สวัสดี', 'Hello', '另一个声音', '结束']
    assert [(s['start_ms'], s['end_ms']) for s in segments] == [(0, 1), (500, 501), (500, 501), (999, 1000)]
    assert all(s['asr_warnings'] == ['asr_timing_repaired'] for s in segments)
    assert [(r['original_start_ms'], r['original_end_ms']) for r in repairs] == [(0, 0), (500, 500), (500, 500), (1000, 1000)]
    assert [r['segment_id'] for r in repairs] == [s['segment_id'] for s in segments]
    # External imports retain the strict end > start contract.
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        asr.parse_subtitles(raw, 'external.srt')
    with pytest.raises(HTTPException):
        asr.parse_engine_subtitles(b'1\n00:00:02,000 --> 00:00:01,000\nreversed\n', 3000)


def test_zero_duration_recognition_creates_review_project_with_source_evidence(prepared):
    _, engine, _, _ = prepared
    engine.write_text(engine.read_text(encoding='utf-8').replace('00:00:00,900', '00:00:00,100'), encoding='utf-8')
    task = queue(prepared)
    asr.run_one()
    result = asr.get_task(task['task_id'])
    assert result['status'] == 'completed', result
    project = read_project(result['project_id'])
    cue = project['segments'][0]
    assert cue['source_text'] == 'สวัสดี Hello' and cue['review_status'] == 'needs_review'
    assert (cue['start_ms'], cue['end_ms']) == (100, 101)
    assert 'asr_timing_repaired' in cue['asr_warnings']
    assert cue['asr_timing_reviewed'] is False
    assert 'asr_timing_repaired' in cue['risk_flags']
    provenance = project['track']['asr']
    assert provenance['quality_review']['warning_counts']['asr_timing_repaired'] == 1
    assert provenance['quality_review']['speaker_diarization'] is False
    assert provenance['quality_review']['overlap_separation'] is False
    assert provenance['timing_repairs'][0]['original_end_ms'] == 100
    directory = Path(project['media']['path']).parent
    assert b'00:00:00,100 --> 00:00:00,100' in (directory / 'original-subtitle').read_bytes()
    assert (directory / 'asr-result.json').read_bytes() == json.dumps(
        {'result': {'language': 'th'}, 'transcription': [{'text': 'สวัสดี 中文'}]},
        ensure_ascii=False).encode('utf-8')


def test_invalid_engine_timing_preserves_diagnostics_and_specific_error(prepared):
    _, engine, _, _ = prepared
    engine.write_text(engine.read_text(encoding='utf-8').replace('00:00:00,900', '00:00:00,050'), encoding='utf-8')
    task = queue(prepared)
    asr.run_one()
    result = asr.get_task(task['task_id'])
    assert result['status'] == 'failed' and result['project_id'] is None
    assert 'Block 1' in result['error'] and 'end must be later than start' in result['error']
    diagnostics = data_dir() / 'asr-diagnostics' / task['task_id']
    assert (diagnostics / 'transcription.srt').is_file()
    assert (diagnostics / 'transcription.json').is_file()
    assert not (diagnostics / 'audio.wav').exists()
    assert not (data_dir() / 'transcriptions' / task['task_id']).exists()
    assert list_projects() == []


def test_external_asr_directory_and_device_are_explicit(tmp_path, monkeypatch):
    base = tmp_path / '语音 tools'
    (base / 'bin').mkdir(parents=True)
    (base / 'models').mkdir()
    engine = base / 'bin' / ('whisper-cli.exe' if os.name == 'nt' else 'whisper-cli')
    engine.write_bytes(b'test engine, never executed')
    engine.chmod(0o755)
    (base / 'models' / 'ggml-large-v3-turbo-q5_0.bin').write_bytes(b'\0' * (1024 * 1024))
    monkeypatch.setenv('SUBTITLE_ASR_DIR', str(base))
    monkeypatch.setenv('SUBTITLE_ASR_DEVICE', 'cpu')
    monkeypatch.setattr(shutil, 'which', lambda command: str(tmp_path / command))
    config = asr.configuration()
    assert config['ready'] and config['device'] == 'cpu'
    assert Path(config['engine_path']) == engine
    assert Path(config['manifest_path']) == base / 'manifest.json'
    monkeypatch.setenv('SUBTITLE_ASR_DEVICE', 'misspelled')
    assert not asr.configuration()['ready']


def test_cpu_request_and_utf8_installation_provenance(prepared, tmp_path):
    _, engine, _, config = prepared
    config['device'] = 'cpu'
    manifest = tmp_path / '语音安装清单.json'
    installation = {'platform': 'Windows x64', '说明': 'ภาษาไทย 中文'}
    manifest.write_text(json.dumps(installation, ensure_ascii=False), encoding='utf-8')
    config['manifest_path'] = str(manifest)
    engine.write_text("import sys\nassert '-ng' in sys.argv\n" + engine.read_text(encoding='utf-8'), encoding='utf-8')
    task = queue(prepared)
    asr.run_one()
    finished = asr.get_task(task['task_id'])
    assert finished['status'] == 'completed', finished
    project = read_project(finished['project_id'])
    assert project['track']['asr']['installation'] == installation
    result = json.loads((Path(project['media']['path']).parent / 'asr-result.json').read_text(encoding='utf-8'))
    assert result['transcription'][0]['text'] == 'สวัสดี 中文'


@pytest.mark.parametrize('container_offset', [0, 5])
def test_selected_audio_delay_is_preserved_in_pcm_and_subtitle_timeline(prepared, tmp_path, container_offset):
    """Real FFmpeg conversion, mock recognizer that inspects its exact WAV input."""
    client, engine, _, _ = prepared
    media = tmp_path / f'offset-{container_offset}.mkv'
    subprocess.run([
        'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=160x90:r=10:d=4',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=4',
        '-itsoffset', '1.25', '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=2.5',
        '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264', '-c:a', 'pcm_s16le',
        '-output_ts_offset', str(container_offset), str(media),
    ], check=True)
    engine.write_text('''#!/usr/bin/env python3
import array, json, pathlib, sys, wave
args=sys.argv[1:]
with wave.open(args[args.index('-f')+1], 'rb') as audio:
    assert audio.getframerate()==16000 and audio.getnchannels()==1 and audio.getsampwidth()==2
    samples=array.array('h',audio.readframes(audio.getnframes()))
first=next(i for i,value in enumerate(samples) if abs(value)>100)/16000
assert 1.24 < first < 1.26, first
central=samples[24000:40000]
crossings=sum(a<=0<b for a,b in zip(central,central[1:]))
assert 860 < crossings < 900, crossings
prefix=pathlib.Path(args[args.index('-of')+1])
prefix.with_suffix('.srt').write_text('1\\n00:00:01,300 --> 00:00:01,900\\nselected delayed track\\n')
prefix.with_suffix('.json').write_text(json.dumps({'result':{'language':'en'}}))
''')
    response = client.post('/api/transcriptions', files={'media': (media.name, media.read_bytes())},
                           data={'language': 'en', 'audio_track': '2'})
    assert response.status_code == 202, response.text
    task = response.json()
    assert asr.run_one()
    finished = asr.get_task(task['task_id'])
    assert finished['status'] == 'completed', finished
    project = read_project(finished['project_id'])
    assert project['media']['selected_audio_track'] == 2
    assert project['media']['requires_audio_preview'] is True
    assert project['track']['asr']['audio_track'] == 2
    assert [(s['start_ms'], s['end_ms']) for s in project['segments']] == [(1300, 1900)]
    assert hashlib.sha256(Path(project['media']['path']).read_bytes()).hexdigest() == hashlib.sha256(media.read_bytes()).hexdigest()


def test_two_worker_claims_cannot_duplicate_one_task_project(prepared, monkeypatch):
    task = queue(prepared)
    reached_commit, release_commit = threading.Event(), threading.Event()
    original_finish = asr._finish
    errors = []
    def delayed_finish(*args):
        reached_commit.set()
        assert release_commit.wait(timeout=5)
        return original_finish(*args)
    monkeypatch.setattr(asr, '_finish', delayed_finish)
    def work():
        try:
            asr.run_one()
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=work)
    thread.start()
    try:
        assert reached_commit.wait(timeout=5)
        assert asr.get_task(task['task_id'])['status'] == 'running'
        assert asr.run_one() is False
    finally:
        release_commit.set()
        thread.join(timeout=5)
    assert not thread.is_alive() and not errors
    assert asr.get_task(task['task_id'])['status'] == 'completed'
    assert len(list_projects()) == 1
    assert asr.run_one() is False


def test_completed_project_survives_late_cancel_cleanup_recovery_and_later_failure(prepared):
    client, engine, _, _ = prepared
    task = queue(prepared)
    asr.run_one()
    completed = asr.get_task(task['task_id'])
    project = read_project(completed['project_id'])
    sid = project['segments'][0]['segment_id']
    response = client.patch(f'/api/projects/{project["project_id"]}/segments/{sid}',
                            json={'base_revision': 1, 'zh_text': '人工修改不可覆盖', 'review_status': 'reviewed'})
    assert response.status_code == 200
    human_project = response.json()['project']
    media = Path(human_project['media']['path'])
    digest = hashlib.sha256(media.read_bytes()).hexdigest()
    # A completion-winning cancellation must leave the completed project and hard-linked media alone.
    assert client.post(f'/api/transcriptions/{task["task_id"]}/cancel').json()['status'] == 'completed'
    asr.recover()
    assert media.is_file() and hashlib.sha256(media.read_bytes()).hexdigest() == digest
    engine.write_text('''#!/usr/bin/env python3
import pathlib,sys
prefix=pathlib.Path(sys.argv[sys.argv.index('-of')+1])
prefix.with_suffix('.srt').write_text('1\\n00:00:00,100 --> 00:00:00,900\\nother source\\n')
prefix.with_suffix('.json').write_text('[]')
''')
    failed = queue(prepared)
    asr.run_one()
    assert asr.get_task(failed['task_id'])['status'] == 'failed'
    assert len(list_projects()) == 1
    assert read_project(project['project_id']) == human_project
    assert media.is_file() and hashlib.sha256(media.read_bytes()).hexdigest() == digest
    assert not (data_dir() / 'transcriptions' / failed['task_id']).exists()


def test_stop_signal_cleans_silent_child_without_a_phantom_project(prepared, tmp_path):
    _, engine, _, _ = prepared
    pid_path = tmp_path / 'silent-engine.pid'
    engine.write_text(f'''#!/usr/bin/env python3
import os,pathlib,time
pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))
time.sleep(60)
''')
    task = queue(prepared)
    stop = threading.Event()
    errors = []
    def work():
        try:
            asr.run_one(stop.is_set)
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=work)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert pid_path.exists()
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive() and not errors
    assert asr.get_task(task['task_id'])['status'] == 'cancelled'
    assert list_projects() == []
    assert not (data_dir() / 'transcriptions' / task['task_id']).exists()
    pid = int(pid_path.read_text())
    if os.name == 'nt':
        # os.kill(pid, 0) is not a portable existence check on Windows.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            try:
                code = wintypes.DWORD()
                assert kernel.GetExitCodeProcess(handle, ctypes.byref(code))
                assert code.value != 259  # STILL_ACTIVE
            finally:
                kernel.CloseHandle(handle)
    else:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
