import copy
import json
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app import ai
from app.store import create_project, mutate_project, read_project, now, uid
from app.subtitles import new_segment


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBTITLE_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('OPENAI_API_KEY', 'local-test-only-not-real')
    monkeypatch.setenv('OPENAI_MODEL', 'test-model')
    monkeypatch.setenv('TRANSLATION_ALLOW_PAID', 'true')
    p = {'project_id': uid(), 'name': 'AI protection fixture', 'schema_version': 1,
         'document_revision': 1, 'created_at': now(), 'updated_at': now(),
         'segments': [new_segment(0, 2000, 'สวัสดี hello'), new_segment(2100, 4000, 'Next sentence')],
         'media': None, 'candidates': [], 'jobs': [], 'glossary': [], 'glossary_version': 0, 'revisions': []}
    create_project(p)
    return p


def enqueue(p):
    result = ai.queue(p['project_id'], ai.QueueRequest(segment_ids=[p['segments'][0]['segment_id']],
                     base_document_revision=p['document_revision'], confirm_send=True))
    return result['result']['job_id']


def fake_provider(job, batch):
    return [{'segment_id': s['segment_id'], 'zh_text': '你好', 'uncertainties': ['文本测试，无音频证据']} for s in batch], {'total_tokens': 42}


def test_no_configuration_never_queues(project, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY')
    assert not ai.status()['ready']
    with pytest.raises(HTTPException) as e:
        enqueue(project)
    assert e.value.status_code == 503
    assert read_project(project['project_id'])['jobs'] == []


def test_arriving_result_does_not_overwrite_manual_edit(project):
    pid, sid = project['project_id'], project['segments'][0]['segment_id']
    jid = enqueue(project)
    def during_request(job, batch):
        def edit(p):
            s = p['segments'][0]
            s.update(zh_text='人工保留稿', manual_zh=True, revision=s['revision']+1)
        mutate_project(pid, 'human', 'edit', edit)
        return fake_provider(job, batch)
    ai.run_batch(pid, jid, during_request)
    p = read_project(pid)
    assert p['segments'][0]['zh_text'] == '人工保留稿'
    assert p['candidates'][0]['stale']
    with pytest.raises(HTTPException) as e:
        ai.accept(pid, p['candidates'][0]['candidate_id'], ai.CandidateAction(base_revision=p['segments'][0]['revision']))
    assert e.value.status_code == 409


def test_explicit_accept_and_idempotent_completion(project):
    pid = project['project_id']
    jid = enqueue(project)
    ai.run_batch(pid, jid, fake_provider)
    ai.run_batch(pid, jid, fake_provider)
    p = read_project(pid)
    assert len(p['candidates']) == 1
    assert p['segments'][0]['zh_text'] == ''
    ai.accept(pid, p['candidates'][0]['candidate_id'], ai.CandidateAction(base_revision=1))
    s = read_project(pid)['segments'][0]
    assert s['zh_text'] == '你好' and s['manual_zh'] and s['revision'] == 2
    assert s['review_status'] == 'needs_review'


def test_adoption_undo_restores_human_text_and_candidate_atomically(project):
    from app.main import undo, Undo
    pid = project['project_id']
    jid = enqueue(project)
    ai.run_batch(pid, jid, fake_provider)
    p = read_project(pid)
    cid = p['candidates'][0]['candidate_id']
    ai.accept(pid, cid, ai.CandidateAction(base_revision=1))
    result = undo(pid, Undo())['project']
    assert result['segments'][0]['zh_text'] == ''
    assert result['segments'][0]['revision'] == 3
    assert result['candidates'][0]['status'] == 'pending'
    assert result['candidates'][0]['stale']


def test_retry_is_bounded_and_imported_jobs_require_new_preview(project):
    pid = project['project_id']
    jid = enqueue(project)
    def failing(*_):
        raise ai.ProviderError('controlled failure')
    for attempt in range(3):
        ai.run_batch(pid, jid, failing)
        assert read_project(pid)['jobs'][0]['attempts'] == attempt+1
        if attempt < 2:
            ai.retry(pid, jid)
    with pytest.raises(HTTPException) as e:
        ai.retry(pid, jid)
    assert e.value.status_code == 409
    mutate_project(pid, 'test', 'restored', lambda p: p['jobs'][0].update(attempts=1, restored=True), undoable=False)
    with pytest.raises(HTTPException) as e:
        ai.retry(pid, jid)
    assert e.value.status_code == 409


@pytest.mark.parametrize('change', ['context', 'glossary', 'split'])
def test_changed_context_glossary_or_deleted_target_archives_result(project, change):
    pid = project['project_id']
    jid = enqueue(project)
    def edit(p):
        if change == 'context':
            p['segments'][1]['source_text'] = 'Different meaning'
            p['segments'][1]['source_revision'] += 1
        elif change == 'glossary':
            p['glossary_version'] = 1
            p['glossary'] = [{'source': 'hello', 'target': '您好', 'note': ''}]
        else:
            p['segments'][0]['deleted'] = True
    mutate_project(pid, 'human', change, edit)
    ai.run_batch(pid, jid, fake_provider)
    p = read_project(pid)
    assert p['candidates'][0]['stale']
    assert p['segments'][0]['zh_text'] == ''


def test_cancel_during_request_discards_uncommitted_results(project):
    pid = project['project_id']
    jid = enqueue(project)
    def cancelled(job, batch):
        ai.cancel(pid, jid)
        return fake_provider(job, batch)
    ai.run_batch(pid, jid, cancelled)
    p = read_project(pid)
    assert p['jobs'][0]['status'] == 'cancelled' and not p['candidates']


def test_worker_restart_requires_retry_and_preserves_committed_batches(project):
    from app.worker import recover
    pid = project['project_id']
    jid = enqueue(project)
    mutate_project(pid, 'worker', 'claim', lambda p: p['jobs'][0].update(status='running', attempts=1), undoable=False)
    recover()
    assert read_project(pid)['jobs'][0]['status'] == 'failed'
    ai.retry(pid, jid)
    ai.run_batch(pid, jid, fake_provider)
    assert len(read_project(pid)['candidates']) == 1


def test_preview_revision_cannot_silently_change(project):
    mutate_project(project['project_id'], 'human', 'edit', lambda p: p.update(name='changed'))
    with pytest.raises(HTTPException) as e:
        enqueue(project)
    assert e.value.status_code == 409


@pytest.mark.parametrize('kind', ['duplicate', 'unknown', 'missing', 'incomplete'])
def test_provider_rejects_untrusted_id_response(project, kind):
    batch = ai.make_request(project, [s['segment_id'] for s in project['segments']])['segments']
    job = {'request': {'segments': batch}, 'model': 'test-model', 'base_url': 'https://api.openai.com/v1', 'max_output_tokens': 4096}
    rows = fake_provider(job, batch)[0]
    if kind == 'duplicate': rows[1]['segment_id'] = rows[0]['segment_id']
    if kind == 'unknown': rows[1]['segment_id'] = 'unknown-id'
    if kind == 'missing': rows.pop()
    result = {'status': 'incomplete' if kind == 'incomplete' else 'completed',
              'output': [{'content': [{'type': 'output_text', 'text': json.dumps({'translations': rows})}]}]}
    with patch.object(httpx.Client, 'post', return_value=httpx.Response(200, json=result)):
        with pytest.raises(ai.ProviderError):
            ai.call_provider(job, batch)
