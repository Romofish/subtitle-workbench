import copy
import hashlib
import io
import json
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.store import create_project, mutate_project, read_project
from app.subtitles import parse_subtitles, serialize

SRT = b'\xef\xbb\xbf1\r\n00:00:01,001 --> 00:00:02,123\r\nHello 2026\r\n\r\n2\r\n00:00:02,500 --> 00:00:04,000\r\nSecond line\r\n'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBTITLE_DATA_DIR', str(tmp_path / 'data'))
    with TestClient(app) as value:
        yield value


def imported(client, raw=SRT, filename='subtitles.srt', media=None):
    files = {'subtitle': (filename, raw, 'text/plain')}
    if media:
        files['media'] = ('source.mp4', media, 'video/mp4')
    response = client.post('/api/projects/import', files=files, data={'name': '测试 Thai English', 'language': 'th'})
    assert response.status_code == 201, response.text
    return response.json()


def edit(client, p, s, **fields):
    return client.patch(f'/api/projects/{p["project_id"]}/segments/{s["segment_id"]}', json={'base_revision': s['revision'], **fields})


def test_utf8_bom_vtt_and_srt_roundtrip(client):
    raw = 'WEBVTT\n\ncue-id\n00:01.001 --> 00:02.123 align:start\nสวัสดี Hello 中文\nsecond\n\nNOTE ignored\nhello\n'.encode()
    p = imported(client, raw, 'input.vtt')
    assert p['segments'][0]['source_text'] == 'สวัสดี Hello 中文\nsecond'
    for format in ('srt', 'vtt'):
        data, _ = serialize(p, format, 'source')
        parsed = parse_subtitles(data, f'out.{format}')
        assert [(s['start_ms'], s['end_ms'], s['source_text']) for s in parsed] == [(1001, 2123, 'สวัสดี Hello 中文\nsecond')]
    invalid = client.post('/api/projects/import', files={'subtitle': ('bad.srt', b'1\n00:77:00,000 --> 00:00:05,000\nx\n')})
    assert invalid.status_code == 422
    invalid = client.post('/api/projects/import', files={'subtitle': ('bad.srt', b'1\n00:00:06,000 --> 00:00:05,000\nx\n')})
    assert invalid.status_code == 422


def test_optimistic_saves_and_staleness(client):
    p = imported(client)
    s = p['segments'][0]
    response = edit(client, p, s, zh_text='你好', review_status='reviewed')
    assert response.status_code == 200
    current = response.json()['project']['segments'][0]
    assert current['manual_zh'] and current['review_status'] == 'reviewed'
    rejected = edit(client, p, s, zh_text='late overwrite')
    assert rejected.status_code == 409
    assert read_project(p['project_id'])['segments'][0]['zh_text'] == '你好'
    updated = edit(client, p, current, source_text='Hello changed').json()['project']
    s2 = updated['segments'][0]
    assert s2['source_revision'] == 2 and s2['translation_stale']
    assert s2['zh_text'] == '你好' and s2['review_status'] == 'needs_review'
    assert updated['document_revision'] == 3
    assert read_project(p['project_id']) == updated


def test_split_atomic_undo_and_conflict_refusal(client):
    p = imported(client)
    s = p['segments'][0]
    body = {'segment_id': s['segment_id'], 'base_revision': s['revision'], 'parts': [{'start_ms': 1001, 'end_ms': 1500, 'source_text': 'Hello'}, {'start_ms': 1500, 'end_ms': 2123, 'source_text': '2026'}]}
    result = client.post(f'/api/projects/{p["project_id"]}/split', json=body)
    assert result.status_code == 200, result.text
    output = result.json()
    ids = output['result']['segment_ids']
    project = output['project']
    assert project['segments'][0]['deleted']
    assert all(next(s for s in project['segments'] if s['segment_id'] == sid)['parent_ids'] == [s['segment_id']] for sid in ids)
    child = next(s for s in project['segments'] if s['segment_id'] == ids[0])
    edit(client, p, child, zh_text='你好')
    before = read_project(p['project_id'])
    refused = client.post(f'/api/projects/{p["project_id"]}/undo', json={'transaction_id': output['result']['transaction_id']})
    assert refused.status_code == 409
    assert read_project(p['project_id']) == before
    # Separate untouched split can undo every associated parent/child atomically.
    p2 = imported(client)
    body['segment_id'] = p2['segments'][0]['segment_id']
    split = client.post(f'/api/projects/{p2["project_id"]}/split', json=body).json()
    restored = client.post(f'/api/projects/{p2["project_id"]}/undo', json={}).json()['project']
    assert len([s for s in restored['segments'] if not s['deleted']]) == 2
    assert restored['segments'][0]['revision'] == 3
    assert all(s['deleted'] for s in restored['segments'][2:])


def test_merge_validates_all_versions_before_writing(client):
    p = imported(client)
    a, b = p['segments']
    body = {'segment_ids': [a['segment_id'], b['segment_id']], 'base_revisions': {a['segment_id']: 1, b['segment_id']: 999}, 'source_text': 'Together', 'zh_text': '合并'}
    response = client.post(f'/api/projects/{p["project_id"]}/merge', json=body)
    assert response.status_code == 409
    assert read_project(p['project_id']) == p
    body['base_revisions'][b['segment_id']] = 1
    merged = client.post(f'/api/projects/{p["project_id"]}/merge', json=body).json()['project']
    assert sum(not s['deleted'] for s in merged['segments']) == 1
    assert merged['segments'][-1]['start_ms'] == 1001 and merged['segments'][-1]['end_ms'] == 4000
    assert set(merged['segments'][-1]['parent_ids']) == {a['segment_id'], b['segment_id']}


def test_export_frozen_manifest_restore_backup_and_reference(client, tmp_path):
    p = imported(client)
    p = edit(client, p, p['segments'][0], zh_text='你好').json()['project']
    pid = p['project_id']
    for format in ('srt', 'vtt'):
        for mode in ('source', 'zh', 'bilingual'):
            r = client.get(f'/api/projects/{pid}/export', params={'format': format, 'mode': mode, 'bundle': True})
            assert r.status_code == 200, r.text
            with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                data = archive.read(manifest['filename'])
                assert hashlib.sha256(data).hexdigest() == manifest['sha256']
                assert manifest['draft']
                assert parse_subtitles(data, manifest['filename'])
    package = client.get(f'/api/projects/{pid}/backup')
    restored = client.post('/api/projects/restore', files={'file': ('project.zip', package.content)}).json()
    assert restored['project_id'] != pid
    assert restored['segments'] == read_project(pid)['segments']
    backup = client.post('/api/backup')
    backup_path = tmp_path / 'restored.sqlite3'
    backup_path.write_bytes(backup.content)
    with sqlite3.connect(backup_path) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0] == 2
    old = read_project(pid)
    preview = client.post(f'/api/projects/{pid}/reimport-preview', files={'subtitle': ('edited.srt', SRT.replace(b'Hello', b'Edited'))})
    assert preview.json()['mode'] == 'reference_track' and preview.json()['differences']
    assert read_project(pid) == old
    ref = client.post(f'/api/projects/{pid}/reference-tracks', files={'subtitle': ('reference.srt', SRT)})
    assert ref.status_code == 200
    assert ref.json()['project']['segments'] == old['segments']


def test_media_range_and_hash_relink(client):
    payload = b'0123456789abcdef'
    p = imported(client, media=payload)
    pid = p['project_id']
    r = client.get(f'/api/projects/{pid}/media', headers={'Range': 'bytes=3-7'})
    assert r.status_code == 206 and r.content == b'34567'
    assert r.headers['content-range'] == 'bytes 3-7/16'
    assert client.get(f'/api/projects/{pid}/media', headers={'Range': 'bytes=88-99'}).status_code == 416
    assert client.post(f'/api/projects/{pid}/relink', files={'media': ('wrong.mp4', b'not same')}).status_code == 409
    backup = client.get(f'/api/projects/{pid}/backup')
    restored = client.post('/api/projects/restore', files={'file': ('p.zip', backup.content)}).json()
    rid = restored['project_id']
    assert client.get(f'/api/projects/{rid}/media').status_code == 404
    assert client.post(f'/api/projects/{rid}/relink', files={'media': ('same.mp4', payload)}).status_code == 200
    assert client.get(f'/api/projects/{rid}/media').content == payload


def test_local_origin_security(client):
    assert client.get('/api/projects', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/backup', headers={'Origin': 'null'}).status_code == 403
    assert client.get('/api/health', headers={'Host': 'evil.example'}).status_code == 400
    assert client.get('/api/health', headers={'Origin': 'http://localhost:5173'}).status_code == 200


def test_repeated_undo_keeps_versions_monotonic(client):
    p = imported(client)
    original = p['segments'][0]
    p = edit(client, p, original, zh_text='第一稿').json()['project']
    p = edit(client, p, p['segments'][0], zh_text='第二稿').json()['project']
    first_undo = client.post(f'/api/projects/{p["project_id"]}/undo', json={})
    assert first_undo.status_code == 200
    second_undo = client.post(f'/api/projects/{p["project_id"]}/undo', json={})
    assert second_undo.status_code == 200, second_undo.text
    segment = second_undo.json()['project']['segments'][0]
    assert segment['zh_text'] == '' and segment['revision'] == 5


def test_malformed_restore_and_missing_tail_difference(client):
    p = imported(client)
    for change in ({'name': None}, {'document_revision': 'oops'}, {'candidates': [None]}, {'segments': [None]}, {'media': {'sha256': 'x'}}):
        malformed = {**p, **change}
        response = client.post('/api/projects/restore', files={'file': ('p.json', json.dumps(malformed).encode())})
        assert response.status_code == 422, response.text
    preview = client.post(f'/api/projects/{p["project_id"]}/reimport-preview', files={'subtitle': ('one.srt', b'1\n00:00:01,001 --> 00:00:02,123\nHello 2026\n')}).json()
    assert len(preview['differences']) == 1 and preview['differences'][0]['incoming'] is None


def test_candidate_accept_undo_restores_associations_atomically(client):
    from app.ai import request_item
    from app.store import uid
    p = imported(client)
    s = p['segments'][0]
    cid = uid()
    basis = request_item(p, s['segment_id'])
    candidate = {'candidate_id': cid, 'segment_id': s['segment_id'], 'base_revision': 1, 'source_revision': 1, 'fingerprint': basis['fingerprint'], 'zh_text': '你好，2026', 'status': 'pending', 'stale': False}
    mutate_project(p['project_id'], 'test', 'fixture_candidate', lambda value: value['candidates'].append(candidate), undoable=False)
    accepted = client.post(f'/api/projects/{p["project_id"]}/candidates/{cid}/accept', json={'base_revision': 1})
    assert accepted.status_code == 200
    assert accepted.json()['project']['candidates'][0]['status'] == 'accepted'
    result = client.post(f'/api/projects/{p["project_id"]}/undo', json={})
    assert result.status_code == 200, result.text
    restored = result.json()['project']
    assert restored['segments'][0]['zh_text'] == '' and restored['segments'][0]['revision'] == 3
    assert restored['candidates'][0]['status'] == 'pending' and restored['candidates'][0]['stale']


def test_restored_inflight_job_is_cancelled_and_requires_new_preview(client):
    from app.store import uid
    p = imported(client)
    p['jobs'] = [{'job_id': uid(), 'status': 'queued', 'attempts': 0, 'next_index': 0, 'request': {'segments': [{'segment_id': p['segments'][0]['segment_id']}]}}]
    response = client.post('/api/projects/restore', files={'file': ('p.json', json.dumps(p).encode())})
    assert response.status_code == 201
    job = response.json()['jobs'][0]
    assert job['restored'] and job['status'] == 'cancelled'
    p['jobs'][0].pop('status')
    assert client.post('/api/projects/restore', files={'file': ('p.json', json.dumps(p).encode())}).status_code == 422


def test_real_ffmpeg_preview_retains_original_and_duration(client, tmp_path):
    import shutil
    import subprocess
    from pathlib import Path
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg/ffprobe not installed')
    sample = tmp_path / 'sample.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=25', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-y', str(sample)], check=True)
    source = sample.read_bytes()
    p = imported(client, media=source)
    pid = p['project_id']
    response = client.post(f'/api/projects/{pid}/preview')
    assert response.status_code == 200, response.text
    project = client.get(f'/api/projects/{pid}').json()
    preview = project['media']['preview']
    assert preview['status'] == 'ready', preview
    assert abs(preview['duration_difference_ms']) <= 100
    assert hashlib.sha256(Path(project['media']['path']).read_bytes()).hexdigest() == hashlib.sha256(source).hexdigest()
    assert client.get(preview['url'], headers={'Range': 'bytes=0-15'}).status_code == 206
    assert project['media']['selected_audio_track'] == 1
    assert preview['source_sha256'] == project['media']['sha256']
    package = client.get(f'/api/projects/{pid}/backup').content
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        packaged = json.loads(archive.read('project.json'))
        assert 'path' not in packaged['media'] and 'path' not in packaged['media']['preview']
    # Simulate an interrupted preview, then app startup recovery.
    mutate_project(pid, 'test', 'simulate_interruption', lambda value: value['media']['preview'].update(status='running'), undoable=False)
    with TestClient(app) as restarted:
        recovered = restarted.get(f'/api/projects/{pid}').json()['media']['preview']
        assert recovered['status'] == 'failed' and 'interrupted' in recovered['error']


def test_multiline_export_normalizes_blank_lines_and_records_manifest(client):
    p = imported(client)
    p = edit(client, p, p['segments'][0], zh_text='第一行\n\n第二行\n \n第三行').json()['project']
    for format in ('srt', 'vtt'):
        r = client.get(f'/api/projects/{p["project_id"]}/export', params={'format': format, 'mode': 'zh', 'bundle': True})
        assert r.status_code == 200
        with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            output = archive.read(manifest['filename'])
            parsed = parse_subtitles(output, manifest['filename'])
            assert len(parsed) == 1 and parsed[0]['source_text'] == '第一行\n第二行\n第三行'
            assert manifest['segments'][0]['normalizations']
    assert read_project(p['project_id'])['segments'][0]['zh_text'] == '第一行\n\n第二行\n \n第三行'


def test_multiaudio_requires_preview_with_exact_selected_track(client, tmp_path):
    import shutil
    import subprocess
    from pathlib import Path
    from app.media import probe
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg/ffprobe not installed')
    sample = tmp_path / 'multiaudio.mkv'
    subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000', '-map', '0:v', '-map', '1:a', '-map', '2:a', '-t', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'pcm_s16le', '-y', str(sample)], check=True)
    response = client.post('/api/projects/import', files={'subtitle': ('test.srt', SRT), 'media': ('multiaudio.mkv', sample.read_bytes())}, data={'audio_track': '2'})
    assert response.status_code == 201, response.text
    p = response.json()
    assert p['media']['requires_audio_preview'] and p['media']['audio_track_count'] == 2
    assert p['media']['selected_audio_track'] == 2
    assert client.post(f'/api/projects/{p["project_id"]}/preview').status_code == 200
    p = client.get(f'/api/projects/{p["project_id"]}').json()
    path = Path(p['media']['preview']['path'])
    streams = probe(path)['streams']
    assert sum(stream['codec_type'] == 'audio' for stream in streams) == 1
    # Recover decoded PCM and count positive zero crossings: selected 880 Hz,
    # not the first 440 Hz stream, must be audible in the preview.
    import array
    raw = subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', str(path), '-vn', '-ac', '1', '-ar', '48000', '-f', 's16le', '-'], capture_output=True, check=True).stdout
    samples = array.array('h', raw)
    central = samples[4800:38400]
    crossings = sum(a <= 0 < b for a, b in zip(central, central[1:]))
    frequency = crossings / (len(central) / 48000)
    assert 850 < frequency < 910, frequency
    package = client.get(f'/api/projects/{p["project_id"]}/backup')
    restored = client.post('/api/projects/restore', files={'file': ('p.zip', package.content)}).json()
    assert restored['media']['requires_audio_preview'] and restored['media']['selected_audio_track'] == 2
