from __future__ import annotations

import copy
from contextlib import asynccontextmanager
import hashlib
import io
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import media as media_utils
from . import asr
from .store import ANNOTATION_DEFAULTS, Conflict, check_revision, consistent_backup, create_project, data_dir, list_projects, mutate_project, now, read_project, segment, uid
from .subtitles import live_segments, new_segment, parse_subtitles, refresh_risks, serialize

@asynccontextmanager
async def lifespan(_app):
    for summary in list_projects():
        preview = (summary.get('media') or {}).get('preview') or {}
        if preview.get('status') in ('queued', 'running'):
            def recover(project):
                value = project['media']['preview']
                value.update(status='failed', error='Preview generation was interrupted. Generate a new preview to retry.', updated_at=now())
                return {'preview_id': value.get('preview_id')}
            mutate_project(summary['project_id'], 'system', 'recover_interrupted_preview', recover, undoable=False)
    yield


app = FastAPI(title='Subtitle Workbench', version='0.1.0', lifespan=lifespan)
ALLOWED_ORIGINS = ['http://127.0.0.1:5173', 'http://localhost:5173', 'http://127.0.0.1:8765', 'http://localhost:8765']
try:
    configured_port = int(os.getenv('SUBTITLE_PORT', '8765'))
    if 1 <= configured_port <= 65535:
        ALLOWED_ORIGINS.extend([f'http://127.0.0.1:{configured_port}', f'http://localhost:{configured_port}'])
except ValueError:
    pass
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=False, allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'], allow_headers=['Content-Type'])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])


@app.middleware('http')
async def local_origin_only(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.url.path.startswith('/api') and origin and origin not in ALLOWED_ORIGINS:
        return JSONResponse({'detail': 'This local service only accepts the workbench origin.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


SourceType = Literal['platform_regular', 'platform_auto', 'auto_translation', 'external_asr', 'local_asr', 'human_import', 'unknown']


def valid_speaker(value: str) -> bool:
    return isinstance(value, str) and len(value) <= 100 and not any(
        ord(character) < 32 or character in '\x7f\x85\u2028\u2029' for character in value)


class PatchSegment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_revision: int = Field(ge=1)
    source_text: str | None = Field(default=None, max_length=50000)
    zh_text: str | None = Field(default=None, max_length=50000)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=1)
    review_status: Literal['unreviewed', 'needs_review', 'reviewed'] | None = None
    speaker: StrictStr | None = Field(default=None, max_length=100)
    overlap: StrictBool | None = None
    unclear: StrictBool | None = None

    @field_validator('speaker')
    @classmethod
    def single_line_speaker(cls, value):
        if value is not None and not valid_speaker(value):
            raise ValueError('Speaker must be a single-line label without control characters')
        return value


class Part(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=1)
    source_text: str = Field(min_length=1, max_length=50000)
    zh_text: str = Field(default='', max_length=50000)

    @model_validator(mode='after')
    def valid_time(self):
        if self.end_ms <= self.start_ms:
            raise ValueError('end_ms must be later than start_ms')
        if not self.source_text.strip():
            raise ValueError('Source text cannot be blank')
        return self


class Split(BaseModel):
    segment_id: str
    base_revision: int
    parts: list[Part] = Field(min_length=2, max_length=100)


class Merge(BaseModel):
    segment_ids: list[str] = Field(min_length=2, max_length=100)
    base_revisions: dict[str, int]
    source_text: str = Field(min_length=1, max_length=50000)
    zh_text: str = Field(default='', max_length=50000)


class Undo(BaseModel):
    transaction_id: str | None = None


async def save_upload(upload: UploadFile, directory: Path, limit: int | None = None) -> tuple[Path, str]:
    directory.mkdir(parents=True, exist_ok=True)
    filename = Path(upload.filename or 'upload').name
    target = directory / f'{uid()}-{filename}'
    digest = hashlib.sha256()
    size = 0
    try:
        with target.open('wb') as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if limit and size > limit:
                    raise HTTPException(413, 'File is too large')
                digest.update(chunk)
                handle.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target, digest.hexdigest()


def invalidate_candidates(project: dict, ids: set[str] | None = None):
    for candidate in project.get('candidates', []):
        if ids is None or candidate.get('segment_id') in ids or candidate.get('target_id') in ids:
            candidate['stale'] = True
            candidate['stale_reason'] = 'Subtitle or context changed; compare before adopting'


def attachment(data: bytes, filename: str, media_type: str) -> Response:
    return Response(data, media_type=media_type, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"})


@app.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'subtitle-workbench', 'version': '0.1.0', 'ffmpeg': bool(shutil.which('ffmpeg')), 'ffprobe': bool(shutil.which('ffprobe'))}


@app.get('/api/projects')
def projects():
    return {'projects': list_projects()}


@app.get('/api/asr/status')
def asr_status():
    return {key: value for key, value in asr.configuration().items() if not key.endswith('_path')}


@app.get('/api/transcriptions')
def transcriptions():
    return {'tasks': asr.list_tasks()}


@app.get('/api/transcriptions/{task_id}')
def transcription(task_id: str):
    return asr.public(asr.get_task(task_id))


@app.post('/api/transcriptions/{task_id}/cancel')
def cancel_transcription(task_id: str):
    return asr.cancel(task_id)


@app.post('/api/transcriptions', status_code=202)
async def transcribe(media: UploadFile = File(...), name: str = Form(''),
                     language: Literal['auto', 'th', 'en'] = Form('auto'),
                     audio_track: int | None = Form(None)):
    config = asr.configuration()
    if not config['ready']:
        raise HTTPException(503, '；'.join(config['reasons']))
    if len(name) > 500 or (audio_track is not None and audio_track < 0):
        raise HTTPException(422, '项目名称过长或音轨索引无效')
    if not media.filename:
        raise HTTPException(422, '请选择视频或音频文件')
    task_id = uid()
    directory = data_dir() / 'transcriptions' / task_id
    try:
        path, digest = await save_upload(media, directory, limit=20 * 1024 * 1024 * 1024)
        if path.stat().st_size == 0:
            raise HTTPException(422, '媒体文件为空')
        return asr.enqueue(path, digest, Path(media.filename).name, name, language, audio_track, task_id)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise


@app.post('/api/projects/import', status_code=201)
async def import_project(subtitle: UploadFile = File(...), media: UploadFile | None = File(None), name: str = Form('Untitled project'), language: str = Form('unknown'), source_type: SourceType = Form('human_import'), source_note: str = Form(''), audio_track: int | None = Form(None)):
    if len(name) > 500:
        raise HTTPException(422, 'Project name cannot exceed 500 characters')
    raw = await subtitle.read(20 * 1024 * 1024 + 1)
    segments = parse_subtitles(raw, subtitle.filename or '')
    pid = uid()
    directory = data_dir() / 'projects' / pid
    directory.mkdir(parents=True, exist_ok=True)
    original_name = Path(subtitle.filename or 'subtitles.srt').name
    (directory / 'original-subtitle').write_bytes(raw)
    media_record = None
    try:
        if media and media.filename:
            path, digest = await save_upload(media, directory)
            media_record = media_utils.describe(path, Path(media.filename).name, pid, digest)
            if audio_track is not None:
                if audio_track not in [stream['index'] for stream in media_record['streams'] if stream['codec_type'] == 'audio']:
                    raise HTTPException(422, 'Selected audio track does not exist in this media')
                media_record['selected_audio_track'] = audio_track
        project = {'project_id': pid, 'name': name.strip() or original_name, 'schema_version': 1, 'document_revision': 1, 'created_at': now(), 'updated_at': now(), 'target_language': 'zh-Hans', 'language': language, 'glossary_version': 0, 'glossary': [], 'media': media_record, 'track': {'track_id': uid(), 'language': language, 'source_type': source_type, 'source_note': source_note, 'filename': original_name, 'sha256': hashlib.sha256(raw).hexdigest(), 'media_id': media_record['media_id'] if media_record else None, 'confidence': 'user_declared'}, 'segments': segments, 'candidates': [], 'jobs': [], 'revisions': [], 'reference_tracks': [], 'exports': []}
        refresh_risks(project)
        return create_project(project)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


@app.get('/api/projects/{pid}')
def get_project(pid: str):
    return read_project(pid)


@app.patch('/api/projects/{pid}/segments/{sid}')
def patch_segment(pid: str, sid: str, body: PatchSegment):
    def change(project):
        item = segment(project, sid)
        check_revision(item, body.base_revision)
        values = body.model_dump(exclude_unset=True, exclude={'base_revision'})
        if any(value is None for value in values.values()):
            raise HTTPException(422, 'Fields cannot be null')
        start, end = values.get('start_ms', item['start_ms']), values.get('end_ms', item['end_ms'])
        if end <= start:
            raise HTTPException(422, 'end_ms must be later than start_ms')
        if 'source_text' in values and not values['source_text'].strip():
            raise HTTPException(422, 'Source text cannot be empty')
        source_changed = 'source_text' in values and values['source_text'] != item['source_text']
        time_changed = start != item['start_ms'] or end != item['end_ms']
        annotation_changed = any(name in values and values[name] != item.get(name, default)
                                 for name, default in ANNOTATION_DEFAULTS.items())
        item.update(values)
        if 'zh_text' in values:
            invalidate_candidates(project)
            item['manual_zh'] = True
            item['translation_stale'] = False
            if body.review_status is None:
                item['review_status'] = 'needs_review'
        if source_changed:
            item['source_revision'] += 1
            item['translation_stale'] = bool(item['zh_text'])
            item['review_status'] = 'needs_review'
            invalidate_candidates(project)
            ordered = live_segments(project)
            position = next(i for i, value in enumerate(ordered) if value['segment_id'] == sid)
            for neighbor in ordered[max(0, position - 2):position + 3]:
                if neighbor['segment_id'] != sid and neighbor['zh_text']:
                    neighbor['context_changed'] = True
                    neighbor['review_status'] = 'needs_review'
                    neighbor['revision'] += 1
        if time_changed:
            item['timing_changed'] = True
            item['review_status'] = 'needs_review'
            invalidate_candidates(project, {sid})
        if annotation_changed:
            item['review_status'] = 'needs_review'
            invalidate_candidates(project, {sid})
        if 'asr_timing_repaired' in item.get('asr_warnings', []) and (time_changed or body.review_status == 'reviewed'):
            item['asr_timing_reviewed'] = True
        if body.review_status == 'reviewed' and not (source_changed or time_changed or annotation_changed):
            item['translation_stale'] = False
            item['timing_changed'] = False
            item['context_changed'] = False
        item['revision'] += 1
        refresh_risks(project)
        return {'segment_id': sid}
    return mutate_project(pid, 'human', 'edit_segment', change)


@app.post('/api/projects/{pid}/split')
def split_segment(pid: str, body: Split):
    def change(project):
        parent = segment(project, body.segment_id)
        check_revision(parent, body.base_revision)
        parts = body.parts
        for index, part in enumerate(parts):
            if part.start_ms < parent['start_ms'] or part.end_ms > parent['end_ms']:
                raise HTTPException(422, 'Split parts must stay inside the original subtitle interval')
            if index and parts[index - 1].end_ms > part.start_ms:
                raise HTTPException(422, 'Split parts must be in order without overlap')
        parent['deleted'] = True
        parent['revision'] += 1
        children = [new_segment(p.start_ms, p.end_ms, p.source_text, p.zh_text, [parent['segment_id']]) for p in parts]
        for item in children:
            item.update({name: parent.get(name, default) for name, default in ANNOTATION_DEFAULTS.items()})
            if 'asr_warnings' in parent:
                item['asr_warnings'] = list(parent['asr_warnings'])
            if 'asr_timing_reviewed' in parent:
                item['asr_timing_reviewed'] = parent['asr_timing_reviewed']
            item['review_status'] = 'needs_review'
        project['segments'].extend(children)
        invalidate_candidates(project)
        refresh_risks(project)
        return {'segment_ids': [s['segment_id'] for s in children]}
    return mutate_project(pid, 'human', 'split', change)


@app.post('/api/projects/{pid}/merge')
def merge_segments(pid: str, body: Merge):
    def change(project):
        if not body.source_text.strip():
            raise HTTPException(422, 'Source text cannot be blank')
        if len(set(body.segment_ids)) != len(body.segment_ids):
            raise HTTPException(422, 'Repeated segment ID')
        items = [segment(project, sid) for sid in body.segment_ids]
        for item in items:
            if item['segment_id'] not in body.base_revisions:
                raise HTTPException(422, 'A base revision is required for every subtitle')
            check_revision(item, body.base_revisions[item['segment_id']])
        ordered_ids = [s['segment_id'] for s in live_segments(project)]
        positions = sorted(ordered_ids.index(sid) for sid in body.segment_ids)
        if positions != list(range(positions[0], positions[-1] + 1)):
            raise HTTPException(422, 'Only consecutive subtitles can be merged')
        merged = new_segment(min(s['start_ms'] for s in items), max(s['end_ms'] for s in items), body.source_text, body.zh_text, [ordered_ids[i] for i in positions])
        speakers = {item.get('speaker', '') for item in items}
        # Never guess which identity describes a merged multi-speaker interval.
        merged['speaker'] = speakers.pop() if len(speakers) == 1 else ''
        merged['overlap'] = any(item.get('overlap', False) for item in items)
        merged['unclear'] = any(item.get('unclear', False) for item in items)
        merged['review_status'] = 'needs_review'
        if any('asr_warnings' in item for item in items):
            merged['asr_warnings'] = sorted({warning for item in items for warning in item.get('asr_warnings', [])})
            if 'asr_timing_repaired' in merged['asr_warnings']:
                merged['asr_timing_reviewed'] = all(item.get('asr_timing_reviewed', False) for item in items
                                                   if 'asr_timing_repaired' in item.get('asr_warnings', []))
        for item in items:
            item['deleted'] = True
            item['revision'] += 1
        project['segments'].append(merged)
        invalidate_candidates(project)
        refresh_risks(project)
        return {'segment_id': merged['segment_id']}
    return mutate_project(pid, 'human', 'merge', change)


@app.post('/api/projects/{pid}/undo')
def undo(pid: str, body: Undo):
    def change(project):
        history = project['revisions']
        tx = next((t for t in reversed(history) if (not body.transaction_id or t['transaction_id'] == body.transaction_id) and t.get('undoable') and not t.get('undone_by')), None)
        if tx is None:
            raise HTTPException(404, 'No undoable transaction')
        for item in tx['changes']:
            current = segment(project, item['segment_id'], include_deleted=True)
            expected = item['after']
            expected_revision = tx.get('undo_expected_revisions', {}).get(item['segment_id'], (expected or {}).get('revision'))
            if expected is None or current['revision'] != expected_revision:
                raise Conflict('Undo would overwrite a later edit; no part of the transaction was reverted.', current['revision'])
        for change in tx.get('candidate_changes', []):
            current_candidate = next((c for c in project.get('candidates', []) if c['candidate_id'] == change['candidate_id']), None)
            if current_candidate != change['after']:
                raise Conflict('A candidate changed after this transaction; undo was rejected atomically.')
        for change in tx.get('candidate_changes', []):
            project['candidates'] = [c for c in project['candidates'] if c['candidate_id'] != change['candidate_id']]
            if change['before'] is not None:
                project['candidates'].append(copy.deepcopy(change['before']))
        for item in tx['changes']:
            current = segment(project, item['segment_id'], include_deleted=True)
            if item['before'] is None:
                current['deleted'] = True
                current['revision'] += 1
            else:
                restored = copy.deepcopy(item['before'])
                restored['revision'] = current['revision'] + 1
                restored['source_revision'] = max(current['source_revision'], restored['source_revision']) + (current['source_text'] != restored['source_text'])
                current.clear()
                current.update(restored)
        tx['undone_by'] = 'undo:' + str(project['document_revision'] + 1)
        invalidate_candidates(project)
        refresh_risks(project)
        # A successful undo may expose an older transaction without resetting versions.
        # Only rebase undo expectations when every later write to these IDs was undone.
        def semantic(value):
            return {key: item for key, item in value.items() if key not in ('revision', 'source_revision', 'risk_flags')}
        for index, earlier in enumerate(history):
            if not earlier.get('undoable') or earlier.get('undone_by'):
                continue
            ids = {change['segment_id'] for change in earlier['changes']}
            blockers = [later for later in history[index + 1:] if not later.get('undone_by') and later['reason'] != 'undo' and any(change['segment_id'] in ids for change in later['changes'])]
            if blockers:
                continue
            states = [(change, segment(project, change['segment_id'], include_deleted=True)) for change in earlier['changes']]
            if all(change['after'] is not None and semantic(change['after']) == semantic(current) for change, current in states):
                earlier['undo_expected_revisions'] = {change['segment_id']: current['revision'] for change, current in states}
        return {'undone_transaction_id': tx['transaction_id']}
    return mutate_project(pid, 'human', 'undo', change, undoable=False)


@app.get('/api/projects/{pid}/media')
def get_media(pid: str, request: Request):
    media = read_project(pid).get('media')
    if not media or not media.get('path'):
        raise HTTPException(404, 'Media missing; relink original media')
    return media_utils.stream_file(Path(media['path']), request)



@app.post('/api/projects/{pid}/preview')
def create_preview(pid: str, background_tasks: BackgroundTasks):
    if not shutil.which('ffmpeg'):
        raise HTTPException(503, 'FFmpeg is not installed; run the Mac setup script')
    preview_id = uid()
    def change(project):
        media = project.get('media')
        if not media or not media.get('path') or not Path(media['path']).is_file():
            raise HTTPException(422, 'Relink the original media before generating a preview')
        if (media.get('preview') or {}).get('status') in ('queued', 'running'):
            raise Conflict('Preview generation is already running')
        media['preview'] = {'preview_id': preview_id, 'status': 'queued', 'source_sha256': media['sha256'], 'created_at': now(), 'url': f'/api/projects/{pid}/preview-media', 'timeline_mapping': 'same_origin_milliseconds', 'verification': '首、中、尾同步及方向、色彩需要人工检查；预览不替代原片。'}
        return {'preview_id': preview_id}
    result = mutate_project(pid, 'human', 'queue_preview', change, undoable=False)
    background_tasks.add_task(media_utils.generate_preview, pid, preview_id)
    return result


@app.get('/api/projects/{pid}/preview-media')
def get_preview(pid: str, request: Request):
    preview = (read_project(pid).get('media') or {}).get('preview') or {}
    if preview.get('status') != 'ready' or not preview.get('path'):
        raise HTTPException(404, 'Preview is not ready')
    return media_utils.stream_file(Path(preview['path']), request)


@app.post('/api/projects/{pid}/relink')
async def relink(pid: str, media: UploadFile = File(...)):
    project = read_project(pid)
    if not project.get('media'):
        raise HTTPException(422, 'This subtitle-only project has no media fingerprint; import a new media-bound project')
    path, digest = await save_upload(media, data_dir() / 'projects' / pid)
    if digest != project['media']['sha256']:
        path.unlink(missing_ok=True)
        raise Conflict('Media SHA-256 does not match. A different timeline requires a new project.')
    refreshed = media_utils.probe(path)
    audio_streams = [stream for stream in refreshed['streams'] if stream['codec_type'] == 'audio']
    if not refreshed.get('probe_error') and project['media'].get('selected_audio_track') not in [stream['index'] for stream in audio_streams] and project['media'].get('selected_audio_track') is not None:
        path.unlink(missing_ok=True)
        raise HTTPException(422, 'Saved audio-track index is absent; verify the package media metadata')
    def change(value):
        if not refreshed.get('probe_error'):
            value['media'].update(refreshed)
            value['media'].update(requires_audio_preview=len(audio_streams) > 1, audio_track_count=len(audio_streams))
        value['media'].update({'path': str(path), 'status': 'available', 'url': f'/api/projects/{pid}/media'})
        return {'media_id': value['media']['media_id']}
    return mutate_project(pid, 'human', 'relink_media', change, undoable=False)


@app.get('/api/projects/{pid}/export')
def export_project(pid: str, format: str = 'srt', mode: str = 'bilingual', bundle: bool = False, include_speakers: bool = False):
    project = read_project(pid)  # Detached snapshot: edits after this point cannot alter the export.
    content, mapping = serialize(project, format, mode, include_speakers=include_speakers)
    export_id = uid()
    filename = f'subtitles-{mode}.{format}'
    manifest = {'schema_version': 1, 'export_id': export_id, 'project_id': pid, 'document_revision': project['document_revision'], 'created_at': now(), 'media_sha256': (project.get('media') or {}).get('sha256'), 'mode': mode, 'format': format, 'draft': any(s['review_status'] != 'reviewed' for s in live_segments(project)), 'filename': filename, 'sha256': hashlib.sha256(content).hexdigest(), 'segments': mapping, 'track': project['track']}
    manifest['include_speakers'] = include_speakers
    mutate_project(pid, 'system', 'export_snapshot', lambda p: p['exports'].append(manifest), undoable=False)
    if bundle:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(filename, content)
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        return attachment(buffer.getvalue(), f'subtitles-{mode}-{export_id[:8]}.zip', 'application/zip')
    response = attachment(content, filename, 'text/vtt' if format == 'vtt' else 'application/x-subrip')
    response.headers['X-Export-Id'] = export_id
    response.headers['X-Document-Revision'] = str(project['document_revision'])
    return response


def portable(project: dict) -> dict:
    output = copy.deepcopy(project)
    if output.get('media'):
        output['media'].pop('path', None)
        output['media']['status'] = 'missing'
        output['media']['url'] = None
        if output['media'].get('preview'):
            output['media']['preview'].pop('path', None)
            output['media']['preview']['status'] = 'missing'
            output['media']['preview']['url'] = None
    return output


@app.get('/api/projects/{pid}/json')
def project_json(pid: str):
    return attachment(json.dumps(portable(read_project(pid)), ensure_ascii=False, indent=2).encode(), 'project.json', 'application/json')


@app.get('/api/projects/{pid}/backup')
def backup_project(pid: str):
    project = portable(read_project(pid))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('project.json', json.dumps(project, ensure_ascii=False, indent=2))
        original = data_dir() / 'projects' / pid / 'original-subtitle'
        if original.is_file():
            archive.writestr('original-subtitle', original.read_bytes())
        archive.writestr('README.txt', 'Restore project.json or this ZIP in Subtitle Workbench. Original media is excluded; relink an identical file using the saved SHA-256. AI credentials are never included.\n')
    return attachment(buffer.getvalue(), f'project-{pid[:8]}.zip', 'application/zip')


def validate_segment_annotations(item: dict):
    if 'speaker' in item and not valid_speaker(item['speaker']):
        raise HTTPException(422, 'Invalid speaker label: expected a single-line string of at most 100 characters')
    for name in ('overlap', 'unclear', 'asr_timing_reviewed'):
        if name in item and type(item[name]) is not bool:
            raise HTTPException(422, f'Invalid {name}: expected a boolean')
    if 'asr_warnings' in item:
        warnings = item['asr_warnings']
        allowed = {'asr_repetition', 'asr_long_segment', 'asr_timing_repaired'}
        if (not isinstance(warnings, list) or
                any(not isinstance(warning, str) or warning not in allowed for warning in warnings)):
            raise HTTPException(422, 'Invalid ASR warnings')


def validate_restore(project: dict):
    if not isinstance(project, dict) or project.get('schema_version') != 1:
        raise HTTPException(422, 'Unsupported project schema')
    required = ('project_id', 'name', 'document_revision', 'segments', 'track', 'created_at', 'updated_at')
    if any(k not in project for k in required) or not isinstance(project['segments'], list):
        raise HTTPException(422, 'Invalid project package')
    if not isinstance(project['name'], str) or len(project['name']) > 500 or not isinstance(project['document_revision'], int) or project['document_revision'] < 1 or not isinstance(project['track'], dict):
        raise HTTPException(422, 'Invalid project metadata')
    if not isinstance(project['created_at'], str) or not isinstance(project['updated_at'], str):
        raise HTTPException(422, 'Invalid project timestamps')
    for key in ('revisions', 'candidates', 'glossary', 'jobs', 'reference_tracks', 'exports', 'glossary_history'):
        if key in project and (not isinstance(project[key], list) or any(not isinstance(v, dict) for v in project[key])):
            raise HTTPException(422, f'Invalid project {key}')
    for collection, identity in (('candidates', 'candidate_id'), ('jobs', 'job_id'), ('revisions', 'transaction_id')):
        ids = [item.get(identity) for item in project.get(collection, [])]
        if any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
            raise HTTPException(422, f'Invalid identities in {collection}')
    for job in project.get('jobs', []):
        if job.get('status') not in ('queued', 'running', 'completed', 'failed', 'cancelled'):
            raise HTTPException(422, 'Invalid AI job status')
        if not isinstance(job.get('attempts'), int) or not 0 <= job['attempts'] <= 3 or not isinstance(job.get('next_index'), int) or job['next_index'] < 0:
            raise HTTPException(422, 'Invalid AI job progress')
        request = job.get('request')
        if not isinstance(request, dict) or not isinstance(request.get('segments'), list):
            raise HTTPException(422, 'Invalid AI request history')
        if any(not isinstance(item, dict) or not isinstance(item.get('segment_id'), str) for item in request['segments']):
            raise HTTPException(422, 'Invalid AI request subtitles')
    for candidate in project.get('candidates', []):
        if not isinstance(candidate.get('segment_id'), str) or not isinstance(candidate.get('zh_text'), str) or not isinstance(candidate.get('base_revision'), int) or not isinstance(candidate.get('fingerprint'), str) or candidate.get('status', 'pending') not in ('pending', 'accepted', 'rejected'):
            raise HTTPException(422, 'Invalid AI candidate')
    for term in project.get('glossary', []):
        if not isinstance(term.get('source'), str) or not isinstance(term.get('target'), str):
            raise HTTPException(422, 'Invalid glossary entry')
    for tx in project.get('revisions', []):
        if not isinstance(tx.get('changes'), list) or any(not isinstance(v, dict) or not all(k in v for k in ('segment_id', 'before', 'after')) for v in tx['changes']):
            raise HTTPException(422, 'Invalid revision history')
        for change in tx['changes']:
            for key in ('before', 'after'):
                state = change[key]
                if state is not None and (not isinstance(state, dict) or not isinstance(state.get('revision'), int) or not isinstance(state.get('source_revision'), int) or not isinstance(state.get('source_text'), str)):
                    raise HTTPException(422, 'Invalid revision snapshot')
                if state is not None:
                    validate_segment_annotations(state)
    for track in project.get('reference_tracks', []):
        if 'segments' in track:
            if not isinstance(track['segments'], list) or any(not isinstance(item, dict) for item in track['segments']):
                raise HTTPException(422, 'Invalid reference-track subtitles')
            for item in track['segments']:
                validate_segment_annotations(item)
    media = project.get('media')
    if media is not None:
        if not isinstance(media, dict) or not isinstance(media.get('sha256'), str) or len(media['sha256']) != 64 or any(c not in '0123456789abcdef' for c in media['sha256']):
            raise HTTPException(422, 'Invalid media fingerprint')
        if not isinstance(media.get('streams', []), list) or any(not isinstance(stream, dict) for stream in media.get('streams', [])):
            raise HTTPException(422, 'Invalid media stream metadata')
        if media.get('selected_audio_track') is not None and not isinstance(media['selected_audio_track'], int):
            raise HTTPException(422, 'Invalid selected audio-track index')
        if media.get('duration_ms') is not None and (not isinstance(media['duration_ms'], int) or media['duration_ms'] < 0):
            raise HTTPException(422, 'Invalid media duration')
        if media.get('preview') is not None and not isinstance(media['preview'], dict):
            raise HTTPException(422, 'Invalid media preview')
    seen = set()
    for item in project['segments']:
        if not isinstance(item, dict):
            raise HTTPException(422, 'Invalid project segment')
        validate_segment_annotations(item)
        try:
            sid = item['segment_id']
            if sid in seen or not isinstance(sid, str):
                raise ValueError('Duplicate segment identity')
            seen.add(sid)
            if not isinstance(item['revision'], int) or item['revision'] < 1 or not isinstance(item['source_revision'], int) or item['source_revision'] < 1:
                raise ValueError('Invalid segment revisions')
            if not all(isinstance(item[key], int) for key in ('start_ms', 'end_ms')) or item['start_ms'] < 0 or item['end_ms'] <= item['start_ms']:
                raise ValueError('Invalid segment times')
            if not all(isinstance(item[key], str) for key in ('source_text', 'zh_text')):
                raise ValueError('Invalid subtitle text')
            if item['review_status'] not in ('unreviewed', 'needs_review', 'reviewed'):
                raise ValueError('Invalid review status')
        except (KeyError, ValueError, TypeError) as error:
            raise HTTPException(422, f'Invalid project segment: {error}') from error


@app.post('/api/projects/restore', status_code=201)
async def restore(file: UploadFile = File(...)):
    raw = await file.read(100 * 1024 * 1024 + 1)
    if len(raw) > 100 * 1024 * 1024:
        raise HTTPException(413, 'Project package exceeds 100 MiB')
    original = None
    try:
        if raw.startswith(b'PK'):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                info = archive.getinfo('project.json')
                if info.file_size > 100 * 1024 * 1024:
                    raise HTTPException(413, 'Expanded project exceeds 100 MiB')
                project = json.loads(archive.read(info))
                if 'original-subtitle' in archive.namelist():
                    original_info = archive.getinfo('original-subtitle')
                    if original_info.file_size <= 20 * 1024 * 1024:
                        original = archive.read(original_info)
        else:
            project = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile, KeyError) as error:
        raise HTTPException(422, 'Invalid project JSON/ZIP') from error
    validate_restore(project)
    original_id = project['project_id']
    pid = uid()
    project['project_id'] = pid
    project['restored_from_project_id'] = original_id
    project['name'] += ' (恢复)'
    project['updated_at'] = now()
    for key in ('revisions', 'candidates', 'glossary', 'jobs', 'reference_tracks', 'exports'):
        project.setdefault(key, [])
    project.setdefault('glossary_version', 0)
    if project.get('media'):
        project['media'].pop('path', None)
        if project['media'].get('preview'):
            project['media']['preview'].pop('path', None)
            project['media']['preview']['status'] = 'missing'
            project['media']['preview']['url'] = None
        audio_streams = [stream for stream in project['media'].get('streams', []) if isinstance(stream, dict) and stream.get('codec_type') == 'audio']
        project['media']['requires_audio_preview'] = len(audio_streams) > 1 or bool(project['media'].get('requires_audio_preview'))
        project['media']['audio_track_count'] = len(audio_streams)
        project['media']['status'] = 'missing'
        project['media']['url'] = f'/api/projects/{pid}/media'
    for job in project['jobs']:
        job['restored'] = True
        if job.get('status') in ('queued', 'waiting', 'running', 'pending'):
            job['status'] = 'cancelled'
            job['error'] = 'Project restored; start a new explicitly confirmed AI task'
    refresh_risks(project)
    if original:
        directory = data_dir() / 'projects' / pid
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'original-subtitle').write_bytes(original)
    return create_project(project)


@app.post('/api/projects/{pid}/reimport-preview')
async def reimport_preview(pid: str, subtitle: UploadFile = File(...), manifest: UploadFile | None = File(None)):
    project = read_project(pid)
    raw = await subtitle.read(20 * 1024 * 1024 + 1)
    incoming = parse_subtitles(raw, subtitle.filename or '')
    mode, reason = 'reference_track', 'SRT/VTT cue numbers and timing do not prove identity. Preserve this as a reference track; compare and copy changes manually.'
    verified = False
    if manifest:
        try:
            meta = json.loads(await manifest.read(5 * 1024 * 1024))
            verified = meta.get('project_id') == pid and meta.get('sha256') == hashlib.sha256(raw).hexdigest() and any(e.get('export_id') == meta.get('export_id') and e.get('sha256') == meta.get('sha256') for e in project.get('exports', []))
            if verified:
                reason = 'This is an unchanged verified export. No changes will be applied.'
        except (ValueError, AttributeError):
            reason = 'Manifest could not be verified; import as a new reference track.'
    old = live_segments(project)
    differences = [{'comparison_position': i + 1, 'existing': old[i] if i < len(old) else None, 'incoming': cue, 'identity_verified': False} for i, cue in enumerate(incoming) if i >= len(old) or any(cue[k] != old[i][k] for k in ('start_ms', 'end_ms', 'source_text'))]
    differences.extend({'comparison_position': i + 1, 'existing': old[i], 'incoming': None, 'identity_verified': False} for i in range(len(incoming), len(old)))
    return {'mode': mode, 'reason': reason, 'verified_unchanged_export': verified, 'segments': incoming, 'differences': differences, 'existing_count': len(old), 'incoming_count': len(incoming)}


@app.post('/api/projects/{pid}/reference-tracks')
async def reference_track(pid: str, subtitle: UploadFile = File(...), language: str = Form('unknown'), source_type: SourceType = Form('human_import')):
    raw = await subtitle.read(20 * 1024 * 1024 + 1)
    cues = parse_subtitles(raw, subtitle.filename or '')
    def change(project):
        track = {'track_id': uid(), 'filename': Path(subtitle.filename or 'reference.srt').name, 'language': language, 'source_type': source_type, 'sha256': hashlib.sha256(raw).hexdigest(), 'segments': cues, 'created_at': now()}
        project['reference_tracks'].append(track)
        return {'track_id': track['track_id']}
    return mutate_project(pid, 'human', 'import_reference_track', change, undoable=False)


@app.post('/api/backup')
def backup_database():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'workbench.sqlite3'
        consistent_backup(path)
        return attachment(path.read_bytes(), 'workbench-backup.sqlite3', 'application/vnd.sqlite3')


# Root agent adds AI implementation. Import errors should remain visible once present.
try:
    from .ai import router as ai_router
except ModuleNotFoundError as error:
    if error.name != 'app.ai':
        raise
else:
    app.include_router(ai_router)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
if (FRONTEND_DIST / 'assets').is_dir():
    app.mount('/assets', StaticFiles(directory=FRONTEND_DIST / 'assets'), name='assets')


@app.get('/{path:path}')
def frontend(path: str):
    if path.startswith('api/') or path == 'api':
        raise HTTPException(404, 'API endpoint not found')
    index = FRONTEND_DIST / 'index.html'
    if index.is_file():
        return FileResponse(index)
    return JSONResponse({'service': 'subtitle-workbench', 'message': 'Frontend not built. Run npm run build in frontend, or launch Vite on port 5173.'})
