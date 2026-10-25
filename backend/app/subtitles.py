"""Loss-conscious SRT/VTT parsing and millisecond serialization."""
from __future__ import annotations
import hashlib
import re
from fastapi import HTTPException
from .store import ANNOTATION_DEFAULTS, uid

TIMING = re.compile(r'^\s*((?:\d+:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*((?:\d+:)?\d{2}:\d{2}[.,]\d{3})(?:\s+.*)?$')


def time_ms(value: str) -> int:
    parts = value.replace(',', '.').split(':')
    hours, minutes, seconds = (['0'] + parts) if len(parts) == 2 else parts
    second, millis = seconds.split('.')
    if int(minutes) > 59 or int(second) > 59:
        raise ValueError('minutes/seconds must be 00–59')
    return ((int(hours) * 60 + int(minutes)) * 60 + int(second)) * 1000 + int(millis)


def parse_subtitles(raw: bytes, filename: str) -> list[dict]:
    try:
        text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    except UnicodeDecodeError as error:
        raise HTTPException(422, 'Subtitle must be UTF-8 (BOM is supported). Convert its encoding and retry.') from error
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Subtitle exceeds 20 MiB')
    is_vtt = text.lstrip().startswith('WEBVTT')
    if not is_vtt and not filename.lower().endswith(('.srt', '.vtt')):
        raise HTTPException(422, 'Choose an SRT or WebVTT subtitle')
    blocks = re.split(r'\n[ \t]*\n', text.strip())
    result = []
    for block_number, block in enumerate(blocks, 1):
        lines = block.splitlines()
        if not lines:
            continue
        if is_vtt and (lines[0].startswith(('WEBVTT', 'NOTE', 'STYLE', 'REGION'))):
            continue
        timing_index = next((i for i, line in enumerate(lines[:2]) if '-->' in line), None)
        if timing_index is None:
            raise HTTPException(422, f'Block {block_number}: missing subtitle timing line')
        match = TIMING.match(lines[timing_index])
        if match is None:
            raise HTTPException(422, f'Block {block_number}: invalid timing format; expected HH:MM:SS.mmm')
        try:
            start, end = time_ms(match[1]), time_ms(match[2])
        except (ValueError, TypeError) as error:
            raise HTTPException(422, f'Block {block_number}: invalid time ({error})') from error
        if start < 0 or end <= start:
            raise HTTPException(422, f'Block {block_number}: end must be later than start')
        content = '\n'.join(lines[timing_index + 1:]).strip()
        if not content:
            raise HTTPException(422, f'Block {block_number}: empty cue')
        result.append(new_segment(start, end, content))
    if not result:
        raise HTTPException(422, 'No subtitle cues found')
    return result


def new_segment(start: int, end: int, source: str, zh: str = '', parents: list[str] | None = None) -> dict:
    return {'segment_id': uid(), 'start_ms': start, 'end_ms': end, 'source_text': source, 'zh_text': zh, 'revision': 1, 'source_revision': 1, 'review_status': 'unreviewed', 'translation_stale': False, 'timing_changed': False, 'manual_zh': bool(zh), 'deleted': False, 'parent_ids': parents or [], 'risk_flags': [], **ANNOTATION_DEFAULTS}


def live_segments(project: dict) -> list[dict]:
    return sorted((s for s in project['segments'] if not s.get('deleted')), key=lambda s: (s['start_ms'], s['end_ms'], s['segment_id']))


def refresh_risks(project: dict) -> None:
    ordered = live_segments(project)
    duration = (project.get('media') or {}).get('duration_ms')
    maximum_prior_end = 0
    for index, item in enumerate(ordered):
        flags = []
        source = item['source_text']
        target = item['zh_text']
        if item['start_ms'] < 0 or item['end_ms'] <= item['start_ms']:
            flags.append('invalid_time')
        if duration and item['end_ms'] > duration:
            flags.append('out_of_bounds')
        if index and maximum_prior_end > item['start_ms']:
            flags.append('overlap')
        if item.get('overlap', False):
            flags.append('speaker_overlap')
        if max((len(line) for line in (target or source).splitlines()), default=0) > 48:
            flags.append('long_text')
        if re.search(r'\d', source):
            flags.append('numbers')
        if re.search(r'\b[A-Z][a-z]+(?: [A-Z][a-z]+)+\b', source):
            flags.append('proper_name')
        if item.get('unclear', False) or re.search(r'(?i)\b(?:inaudible|unclear|unintelligible)\b|听不清|ไม่ชัด|\?\?\?', source):
            flags.append('unclear')
        if 'asr_warnings' in item:
            # Retain original ASR warnings as provenance, but evaluate the current
            # human-edited text and timing so resolved issues do not remain flagged.
            from .asr_quality import asr_quality_warnings
            flags.extend(asr_quality_warnings(source, item['end_ms'] - item['start_ms']))
            if 'asr_timing_repaired' in item['asr_warnings'] and not item.get('asr_timing_reviewed', False):
                flags.append('asr_timing_repaired')
        if not target.strip():
            flags.append('missing_translation')
        if item.get('translation_stale'):
            flags.append('source_changed')
        if item.get('context_changed'):
            flags.append('context_changed')
        if item.get('timing_changed'):
            flags.append('timing_changed')
        item['risk_flags'] = flags
        maximum_prior_end = max(maximum_prior_end, item['end_ms'])


def timestamp(value: int, format: str) -> str:
    h, rem = divmod(value, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f'{h:02}:{m:02}:{s:02}{"," if format == "srt" else "."}{ms:03}'


def serialize(project: dict, format: str, mode: str, include_speakers: bool = False) -> tuple[bytes, list[dict]]:
    if format not in ('srt', 'vtt') or mode not in ('source', 'zh', 'bilingual'):
        raise HTTPException(422, 'format must be srt/vtt; mode must be source/zh/bilingual')
    blocks = []
    mapping = []
    for item in live_segments(project):
        if item['start_ms'] < 0 or item['end_ms'] <= item['start_ms']:
            raise HTTPException(422, f'Invalid timing on subtitle {item["segment_id"]}')
        selected = [item['source_text']] if mode == 'source' else [item['zh_text']] if mode == 'zh' else [item['source_text'], item['zh_text']]
        text = '\n'.join(x for x in selected if x.strip())
        # Blank lines delimit cues in both formats. Normalize them explicitly and
        # record the change in the identity manifest rather than emit malformed files.
        original_text = text
        text = '\n'.join(line for line in text.splitlines() if line.strip())
        normalizations = ['empty_lines_removed_or_line_endings_normalized'] if text != original_text else []
        # Empty targets cannot form valid cues: record skipped identity in manifest.
        if not text.strip():
            mapping.append({'segment_id': item['segment_id'], 'revision': item['revision'], 'cue_number': None, 'omitted': 'empty_translation'})
            continue
        speaker = item.get('speaker', '').strip()
        if include_speakers and speaker:
            text = '\n'.join(f'[{speaker}] ' + '\n'.join(line for line in block.splitlines() if line.strip())
                             for block in selected if block.strip())
        n = len(blocks) + 1
        blocks.append(f'{n}\n{timestamp(item["start_ms"], format)} --> {timestamp(item["end_ms"], format)}\n{text}')
        mapping.append({'cue_number': n, 'segment_id': item['segment_id'], 'revision': item['revision'], 'start_ms': item['start_ms'], 'end_ms': item['end_ms'], 'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'normalizations': normalizations})
    if not blocks:
        raise HTTPException(422, 'No non-empty subtitles to export for this mode')
    output = ('WEBVTT\n\n' if format == 'vtt' else '') + '\n\n'.join(blocks) + '\n'
    return output.encode('utf-8'), mapping
