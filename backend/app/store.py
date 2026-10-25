"""SQLite-backed project documents with atomic history and optimistic edits."""
from __future__ import annotations

import copy
from contextlib import closing
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException


ANNOTATION_DEFAULTS = {'speaker': '', 'overlap': False, 'unclear': False}


def normalize_annotations(project: dict) -> dict:
    """Add optional annotation defaults without rewriting old revision numbers."""
    def fill(item):
        if isinstance(item, dict):
            for name, value in ANNOTATION_DEFAULTS.items():
                item.setdefault(name, value)

    for item in project.get('segments', []):
        fill(item)
    for track in project.get('reference_tracks', []):
        for item in track.get('segments', []):
            fill(item)
    for transaction in project.get('revisions', []):
        for change in transaction.get('changes', []):
            fill(change.get('before'))
            fill(change.get('after'))
    return project


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return str(uuid.uuid4())


def data_dir() -> Path:
    path = Path(os.getenv('SUBTITLE_DATA_DIR', str(Path(__file__).resolve().parents[2] / '.workbench-data'))).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(data_dir() / 'workbench.sqlite3', timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA busy_timeout=20000')
    connection.execute('CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, name TEXT NOT NULL, updated_at TEXT NOT NULL, document TEXT NOT NULL)')
    return connection


class Conflict(HTTPException):
    def __init__(self, message: str, current_revision: int | None = None):
        detail: dict[str, Any] = {'message': message}
        if current_revision is not None:
            detail['current_revision'] = current_revision
        super().__init__(409, detail)


def _read(conn: sqlite3.Connection, project_id: str) -> dict:
    row = conn.execute('SELECT document FROM projects WHERE project_id=?', (project_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Project not found')
    return normalize_annotations(json.loads(row['document']))


def read_project(project_id: str) -> dict:
    with closing(connect()) as conn:
        return _read(conn, project_id)


def create_project(project: dict) -> dict:
    normalize_annotations(project)
    with closing(connect()) as conn:
        conn.execute('INSERT INTO projects VALUES (?,?,?,?)', (project['project_id'], project['name'], project['updated_at'], json.dumps(project, ensure_ascii=False)))
        conn.commit()
    return project


def list_projects() -> list[dict]:
    with closing(connect()) as conn:
        docs = [json.loads(row[0]) for row in conn.execute('SELECT document FROM projects ORDER BY updated_at DESC')]
    return [{key: p.get(key) for key in ('project_id', 'name', 'document_revision', 'created_at', 'updated_at', 'media')} | {'segment_count': sum(not s.get('deleted') for s in p['segments']), 'reviewed_count': sum(not s.get('deleted') and s['review_status'] == 'reviewed' for s in p['segments'])} for p in docs]


def segment(project: dict, segment_id: str, include_deleted: bool = False) -> dict:
    found = next((s for s in project['segments'] if s['segment_id'] == segment_id), None)
    if found is None or (found.get('deleted') and not include_deleted):
        raise HTTPException(404, 'Segment not found or has been replaced')
    return found


def check_revision(value: dict, base_revision: int) -> None:
    if value['revision'] != base_revision:
        raise Conflict('This subtitle has changed. Reload before saving.', value['revision'])


def mutate_project(project_id: str, actor: str, reason: str, callback: Callable[[dict], Any], undoable: bool = True) -> dict:
    conn = connect()
    try:
        conn.execute('BEGIN IMMEDIATE')
        project = _read(conn, project_id)
        before = copy.deepcopy(project)
        result = callback(project)
        from .subtitles import refresh_risks
        refresh_risks(project)
        project['document_revision'] = before['document_revision'] + 1
        project['updated_at'] = now()
        old = {s['segment_id']: s for s in before['segments']}
        new = {s['segment_id']: s for s in project['segments']}
        changes = []
        for sid in old.keys() | new.keys():
            if ({k: v for k, v in old.get(sid, {}).items() if k != 'risk_flags'} != {k: v for k, v in new.get(sid, {}).items() if k != 'risk_flags'}):
                changes.append({'segment_id': sid, 'before': old.get(sid), 'after': copy.deepcopy(new.get(sid))})
        old_candidates = {c['candidate_id']: c for c in before.get('candidates', [])}
        new_candidates = {c['candidate_id']: c for c in project.get('candidates', [])}
        candidate_changes = [{'candidate_id': cid, 'before': old_candidates.get(cid), 'after': copy.deepcopy(new_candidates.get(cid))} for cid in old_candidates.keys() | new_candidates.keys() if old_candidates.get(cid) != new_candidates.get(cid)]
        transaction = {'candidate_changes': candidate_changes, 'transaction_id': uid(), 'actor': actor, 'reason': reason, 'created_at': now(), 'document_revision': project['document_revision'], 'changes': changes, 'undoable': bool(undoable and changes), 'undone_by': None}
        project.setdefault('revisions', []).append(transaction)
        conn.execute('UPDATE projects SET name=?, updated_at=?, document=? WHERE project_id=?', (project['name'], project['updated_at'], json.dumps(project, ensure_ascii=False), project_id))
        conn.commit()
        if isinstance(result, dict):
            result = {**result, 'transaction_id': transaction['transaction_id']}
        return {'project': project, 'result': result}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def consistent_backup(destination: Path) -> None:
    with closing(connect()) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)
