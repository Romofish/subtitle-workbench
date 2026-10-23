from __future__ import annotations
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from .store import uid


def probe(path: Path) -> dict:
    if not shutil.which('ffprobe'):
        return {'duration_ms': None, 'streams': [], 'probe_error': 'ffprobe not installed'}
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], capture_output=True, timeout=40, check=True)
        data = json.loads(result.stdout)
        duration = data.get('format', {}).get('duration')
        streams = [{key: stream[key] for key in ('index', 'codec_type', 'codec_name', 'width', 'height', 'sample_rate', 'channels', 'start_time', 'duration', 'tags') if key in stream} for stream in data.get('streams', [])]
        return {'duration_ms': round(float(duration) * 1000) if duration is not None else None, 'streams': streams, 'probe_error': None}
    except (subprocess.SubprocessError, ValueError, OSError):
        return {'duration_ms': None, 'streams': [], 'probe_error': 'Media inspection failed; verify file format'}


def describe(path: Path, filename: str, project_id: str, sha256: str) -> dict:
    details = probe(path)
    audio_streams = [stream for stream in details['streams'] if stream['codec_type'] == 'audio']
    audio = audio_streams[0]['index'] if audio_streams else None
    return {'requires_audio_preview': len(audio_streams) > 1, 'audio_track_count': len(audio_streams), 'media_id': uid(), 'filename': filename, 'sha256': sha256, 'path': str(path), 'status': 'available', 'selected_audio_track': audio, 'source': 'local_import', 'url': f'/api/projects/{project_id}/media', **details}


def stream_file(path: Path, request: Request) -> StreamingResponse:
    if not path.is_file():
        raise HTTPException(404, 'Media is missing. Relink the original file with the matching hash.')
    size = path.stat().st_size
    start, end, status = 0, max(0, size - 1), 200
    value = request.headers.get('range')
    if value:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
        if not match or not any(match.groups()):
            raise HTTPException(416, 'Unsupported byte range', headers={'Content-Range': f'bytes */{size}'})
        if match[1]:
            start = int(match[1])
            end = min(int(match[2]), size - 1) if match[2] else size - 1
        else:
            start = max(0, size - int(match[2]))
        if start >= size or end < start:
            raise HTTPException(416, 'Range outside file', headers={'Content-Range': f'bytes */{size}'})
        status = 206
    length = max(0, end - start + 1) if size else 0
    def chunks():
        remaining = length
        with path.open('rb') as handle:
            handle.seek(start)
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
    headers = {'Accept-Ranges': 'bytes', 'Content-Length': str(length)}
    if status == 206:
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    return StreamingResponse(chunks(), status_code=status, media_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream', headers=headers)


def generate_preview(project_id: str, preview_id: str) -> None:
    """Create an optional browser copy; originals and subtitle times are immutable."""
    from .store import read_project, mutate_project, data_dir, now
    source = read_project(project_id)['media']
    def transition(status, **values):
        def update(project):
            preview = project['media'].get('preview') or {}
            if preview.get('preview_id') != preview_id:
                return {'ignored': True}
            preview.update(status=status, updated_at=now(), **values)
            return {'preview_id': preview_id, 'status': status}
        return mutate_project(project_id, 'system', 'preview_' + status, update, undoable=False)
    transition('running')
    target = data_dir() / 'projects' / project_id / f'preview-{preview_id}.mp4'
    arguments = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-copyts', '-start_at_zero', '-i', source['path'], '-map', '0:v:0?']
    audio = source.get('selected_audio_track')
    if audio is not None:
        arguments += ['-map', f'0:{audio}?']
    arguments += ['-sn', '-dn', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-vf', "scale=w='min(1280,iw)':h=-2", '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(target)]
    try:
        subprocess.run(arguments, capture_output=True, check=True, timeout=3600)
        details = probe(target)
        if not target.is_file() or not target.stat().st_size or details.get('probe_error'):
            raise ValueError('Generated media could not be inspected')
        digest = hashlib.sha256()
        with target.open('rb') as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        difference = None
        if details['duration_ms'] is not None and source.get('duration_ms') is not None:
            difference = details['duration_ms'] - source['duration_ms']
        transition('ready', path=str(target), sha256=digest.hexdigest(), duration_ms=details['duration_ms'], duration_difference_ms=difference, sync_check_required=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        target.unlink(missing_ok=True)
        transition('failed', error='Preview conversion failed or exceeded one hour. Original media and subtitles are unchanged. Check media format and FFmpeg installation.')
