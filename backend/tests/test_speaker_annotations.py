import copy
import io
import json
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import ANNOTATION_DEFAULTS, connect, read_project
from app.subtitles import live_segments, parse_subtitles


SRT = b'1\n00:00:00,000 --> 00:00:04,000\nHello\n\n2\n00:00:05,000 --> 00:00:07,000\nSecond line\n'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBTITLE_DATA_DIR', str(tmp_path / 'data'))
    with TestClient(app) as value:
        yield value


def imported(client):
    response = client.post('/api/projects/import', files={'subtitle': ('speech.srt', SRT)}, data={'name': '多人审阅'})
    assert response.status_code == 201, response.text
    return response.json()


def patch(client, project, index=0, **values):
    item = project['segments'][index]
    return client.patch(f'/api/projects/{project["project_id"]}/segments/{item["segment_id"]}',
                        json={'base_revision': item['revision'], **values})


def restore(client, project):
    return client.post('/api/projects/restore', files={'file': ('project.json', json.dumps(project).encode('utf-8'))})


def assert_annotations(item, speaker='', overlap=False, unclear=False):
    assert {name: item[name] for name in ANNOTATION_DEFAULTS} == {
        'speaker': speaker, 'overlap': overlap, 'unclear': unclear}


def test_annotation_edit_is_versioned_reviewable_and_undoable(client):
    original = imported(client)
    first = original['segments'][0]
    assert_annotations(first)
    result = patch(client, original, speaker='说话人 A', overlap=True, unclear=True)
    assert result.status_code == 200, result.text
    updated = result.json()['project']
    item = updated['segments'][0]
    assert_annotations(item, '说话人 A', True, True)
    assert item['source_text'] == first['source_text'] and item['zh_text'] == first['zh_text']
    assert item['source_revision'] == first['source_revision']
    assert item['revision'] == first['revision'] + 1 and item['review_status'] == 'needs_review'
    assert 'speaker_overlap' in item['risk_flags'] and 'unclear' in item['risk_flags']
    assert 'overlap' not in item['risk_flags']  # Speech annotation is distinct from intersecting cue times.
    assert patch(client, original, speaker='stale overwrite').status_code == 409
    undone = client.post(f'/api/projects/{original["project_id"]}/undo', json={})
    assert undone.status_code == 200, undone.text
    reverted = undone.json()['project']['segments'][0]
    assert_annotations(reverted)
    assert reverted['revision'] == 3
    assert 'speaker_overlap' not in reverted['risk_flags'] and 'unclear' not in reverted['risk_flags']


def test_undo_refuses_to_overwrite_a_later_annotation_edit(client):
    project = imported(client)
    first = patch(client, project, speaker='A').json()
    project = patch(client, first['project'], speaker='B').json()['project']
    response = client.post(f'/api/projects/{project["project_id"]}/undo',
                           json={'transaction_id': first['result']['transaction_id']})
    assert response.status_code == 409
    assert read_project(project['project_id'])['segments'][0]['speaker'] == 'B'


@pytest.mark.parametrize('values', [
    {'overlap': 1}, {'overlap': 'true'}, {'unclear': 'false'}, {'unclear': None},
    {'speaker': None}, {'speaker': 7}, {'speaker': ['A']}, {'speaker': 'A\nB'},
    {'speaker': 'A\u2028B'}, {'speaker': 'A' * 101},
])
def test_annotation_patch_rejects_invalid_types_and_multiline_labels(client, values):
    project = imported(client)
    response = patch(client, project, **values)
    assert response.status_code == 422, response.text
    assert read_project(project['project_id'])['document_revision'] == 1


@pytest.mark.parametrize('format', ['srt', 'vtt'])
@pytest.mark.parametrize('mode', ['source', 'zh', 'bilingual'])
def test_speaker_labels_are_opt_in_export_only(client, format, mode):
    project = imported(client)
    project = patch(client, project, speaker='A', zh_text='你好').json()['project']
    project = patch(client, project, index=1, speaker='B').json()['project']
    pid = project['project_id']
    plain = client.get(f'/api/projects/{pid}/export', params={'format': format, 'mode': mode})
    assert plain.status_code == 200
    labeled = client.get(f'/api/projects/{pid}/export', params={
        'format': format, 'mode': mode, 'include_speakers': True, 'bundle': True})
    assert labeled.status_code == 200
    with zipfile.ZipFile(io.BytesIO(labeled.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        output = archive.read(manifest['filename'])
    assert manifest['include_speakers'] is True
    assert b'[A]' not in plain.content and '[A] '.encode() in output
    cues = parse_subtitles(output, f'export.{format}')
    if mode == 'zh':
        assert len(cues) == 1 and cues[0]['source_text'] == '[A] 你好'
        assert b'[B]' not in output  # An empty translation must not become a label-only cue.
    elif mode == 'bilingual':
        assert cues[0]['source_text'] == '[A] Hello\n[A] 你好'
    else:
        assert cues[0]['source_text'] == '[A] Hello'
    stored = read_project(pid)['segments'][0]
    assert stored['source_text'] == 'Hello' and stored['zh_text'] == '你好'
    assert_annotations(stored, 'A')


def test_project_package_and_database_backup_preserve_annotations(client, tmp_path):
    project = imported(client)
    project = patch(client, project, speaker='A 与 B', overlap=True, unclear=True).json()['project']
    pid = project['project_id']
    package = client.get(f'/api/projects/{pid}/backup')
    response = client.post('/api/projects/restore', files={'file': ('project.zip', package.content)})
    assert response.status_code == 201, response.text
    recovered = response.json()
    assert_annotations(recovered['segments'][0], 'A 与 B', True, True)
    assert_annotations(recovered['revisions'][0]['changes'][0]['after'], 'A 与 B', True, True)
    database = client.post('/api/backup')
    path = tmp_path / 'backup.sqlite3'
    path.write_bytes(database.content)
    with sqlite3.connect(path) as connection:
        saved = json.loads(connection.execute('SELECT document FROM projects WHERE project_id=?', (pid,)).fetchone()[0])
    assert_annotations(saved['segments'][0], 'A 与 B', True, True)


def strip_annotations(project):
    for item in project['segments']:
        for name in ANNOTATION_DEFAULTS:
            item.pop(name, None)
    for transaction in project['revisions']:
        for change in transaction['changes']:
            for state in (change['before'], change['after']):
                if state:
                    for name in ANNOTATION_DEFAULTS:
                        state.pop(name, None)


def test_legacy_reads_restore_and_history_undo_remain_compatible(client):
    project = imported(client)
    project = patch(client, project, zh_text='你好').json()['project']
    strip_annotations(project)
    # Simulate a database written before annotation fields existed.
    connection = connect()
    try:
        connection.execute('UPDATE projects SET document=? WHERE project_id=?', (json.dumps(project), project['project_id']))
        connection.commit()
    finally:
        connection.close()
    current = client.get(f'/api/projects/{project["project_id"]}').json()
    assert current['document_revision'] == project['document_revision']
    assert_annotations(current['segments'][0])
    assert_annotations(current['revisions'][0]['changes'][0]['before'])
    response = restore(client, project)
    assert response.status_code == 201, response.text
    restored = response.json()
    assert_annotations(restored['segments'][0])
    edited = patch(client, restored, speaker='A').json()['project']
    for _ in range(2):
        undone = client.post(f'/api/projects/{edited["project_id"]}/undo', json={})
        assert undone.status_code == 200, undone.text
    final = undone.json()['project']['segments'][0]
    assert_annotations(final)
    assert final['zh_text'] == ''


@pytest.mark.parametrize('values', [
    {'speaker': 4}, {'speaker': 'A\nB'}, {'overlap': 'false'}, {'unclear': 0},
    {'asr_warnings': 'asr_repetition'}, {'asr_warnings': ['identity_guessed']}, {'asr_warnings': [1]},
    {'asr_timing_reviewed': 'false'},
])
def test_restore_strictly_checks_optional_annotation_and_asr_types(client, values):
    project = imported(client)
    project['segments'][0].update(values)
    assert restore(client, project).status_code == 422


def test_restore_validates_history_and_reference_annotations(client):
    project = imported(client)
    project = patch(client, project, speaker='A').json()['project']
    malformed = copy.deepcopy(project)
    malformed['revisions'][0]['changes'][0]['before']['overlap'] = 'no'
    assert restore(client, malformed).status_code == 422
    malformed = copy.deepcopy(project)
    malformed['reference_tracks'] = [{'segments': [{'speaker': None}]}]
    assert restore(client, malformed).status_code == 422


def test_split_inherits_annotations_and_merge_preserves_flags_without_guessing_identity(client):
    project = imported(client)
    project = patch(client, project, speaker='A', overlap=True, unclear=True).json()['project']
    item = project['segments'][0]
    split = client.post(f'/api/projects/{project["project_id"]}/split', json={
        'segment_id': item['segment_id'], 'base_revision': item['revision'],
        'parts': [{'start_ms': 0, 'end_ms': 2000, 'source_text': 'First'},
                  {'start_ms': 2000, 'end_ms': 4000, 'source_text': 'Second'}]})
    assert split.status_code == 200, split.text
    project = split.json()['project']
    parts = live_segments(project)[:2]
    for item in parts:
        assert_annotations(item, 'A', True, True)
    index = next(index for index, item in enumerate(project['segments']) if item['segment_id'] == parts[1]['segment_id'])
    project = patch(client, project, index=index, speaker='B').json()['project']
    parts = live_segments(project)[:2]
    merged = client.post(f'/api/projects/{project["project_id"]}/merge', json={
        'segment_ids': [item['segment_id'] for item in parts],
        'base_revisions': {item['segment_id']: item['revision'] for item in parts},
        'source_text': 'First Second'})
    assert merged.status_code == 200, merged.text
    item = merged.json()['project']['segments'][-1]
    assert_annotations(item, '', True, True)
    assert item['review_status'] == 'needs_review'


def test_asr_provenance_survives_edits_while_quality_flags_follow_current_text(client):
    project = imported(client)
    original = ['asr_repetition', 'asr_long_segment']
    project['segments'][0].update(source_text='Testing phrase ' * 8, end_ms=15000, asr_warnings=original)
    response = restore(client, project)
    assert response.status_code == 201, response.text
    project = response.json()
    assert all(warning in project['segments'][0]['risk_flags'] for warning in original)
    assert_annotations(project['segments'][0])  # Quality hints never infer a speaker or overlapping speech.
    changed = patch(client, project, source_text='Corrected by listening', end_ms=4000)
    assert changed.status_code == 200, changed.text
    item = changed.json()['project']['segments'][0]
    assert item['asr_warnings'] == original
    assert not any(warning in item['risk_flags'] for warning in original)


@pytest.mark.parametrize('edit', [{'end_ms': 1000}, {'review_status': 'reviewed'}])
def test_asr_timing_acknowledgement_is_undoable_and_keeps_original_evidence(client, edit):
    project = imported(client)
    project['segments'][0].update(end_ms=1, asr_warnings=['asr_timing_repaired'], asr_timing_reviewed=False)
    project = restore(client, project).json()
    assert 'asr_timing_repaired' in project['segments'][0]['risk_flags']
    changed = patch(client, project, **edit)
    assert changed.status_code == 200, changed.text
    project = changed.json()['project']
    item = project['segments'][0]
    assert item['asr_timing_reviewed'] is True
    assert item['asr_warnings'] == ['asr_timing_repaired']
    assert 'asr_timing_repaired' not in item['risk_flags']
    if 'end_ms' in edit:
        assert item['review_status'] == 'needs_review' and 'timing_changed' in item['risk_flags']
    undone = client.post(f'/api/projects/{project["project_id"]}/undo', json={})
    assert undone.status_code == 200, undone.text
    item = undone.json()['project']['segments'][0]
    assert item['asr_timing_reviewed'] is False
    assert 'asr_timing_repaired' in item['risk_flags']
