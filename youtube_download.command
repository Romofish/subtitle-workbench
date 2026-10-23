#!/bin/bash

# 可调整的下载设置
FORMAT="bv*+ba/b"
DOWNLOAD_SUBS="${DOWNLOAD_SUBS-yes}"
SUB_LANGS="${SUB_LANGS-th.*,zh.*,en.*}"
# 默认只取平台普通字幕与有原语 ASR 证据的轨；显式 yes 才允许自动翻译。
ALLOW_TRANSLATED_SUBS="${ALLOW_TRANSLATED_SUBS-no}"
CONTAINER="mkv"
CONCURRENT_FRAGMENTS=8
DOWNLOAD_DIR="${YOUTUBE_DOWNLOAD_DIR-$HOME/Downloads/YouTube}"
# 每个视频独立目录；加入 ID 避免同名视频混放。旧文件不自动移动。
SAVE_PATH="%(title)s [%(id)s]/%(title)s [%(id)s].%(ext)s"

# 默认不显式指定代理，由 yt-dlp 的环境变量、配置文件和系统网络路由决定。
# 如需本地代理，例如：PROXY_URL="http://127.0.0.1:7897" ./youtube_download.command
PROXY_URL="${PROXY_URL-}"

# 兼容 Apple Silicon / Intel Homebrew，以及用户级安装。
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

check_dependencies() {
    local missing=0
    local tool
    for tool in yt-dlp ffmpeg ffprobe python3; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            echo "[缺少依赖] 找不到 ${tool}，请先安装并确保它在 PATH 中。"
            missing=1
        fi
    done
    if [ "$missing" -ne 0 ]; then
        echo "Homebrew 安装命令：brew install yt-dlp ffmpeg python deno"
        return 1
    fi

    if command -v deno >/dev/null 2>&1; then
        JS_ARGS=(--js-runtimes deno)
    else
        JS_ARGS=()
        echo "[提示] 未找到 deno，部分 YouTube 视频可能解析失败。"
        echo "可安装 JavaScript 运行时：brew install deno"
    fi
}

show_settings() {
    echo "yt-dlp：$(command -v yt-dlp)"
    YTDLP_VERSION=$(yt-dlp --version)
    echo "版本：$YTDLP_VERSION"
    echo "ffmpeg：$(command -v ffmpeg)"
    if [ -n "$PROXY_URL" ]; then
        echo "代理：$PROXY_URL"
    else
        echo "代理：未显式指定，使用环境与 yt-dlp 默认配置。"
    fi
    echo "保存到：$DOWNLOAD_DIR/视频标题 [视频ID]/（每个视频独立文件夹）"
    echo "字幕语言：${SUB_LANGS}；字幕下载：${DOWNLOAD_SUBS}；允许自动翻译：${ALLOW_TRANSLATED_SUBS}"
    echo "字幕交付：独立 SRT；本次不新增内嵌轨。媒体下载与字幕下载分别报告。"
}

write_source_manifest() {
    python3 - "$@" <<'PY'
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

scratch, input_url, with_subs, patterns, exit_code, ytdlp_version, run_id = sys.argv[1:8]
allow_translated = len(sys.argv) > 8 and sys.argv[8] == 'yes'
exit_code = int(exit_code)

def snapshot(name):
    path = Path(scratch, name + '.jsonl')
    if not path.is_file():
        return {}
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(rows) > 1:
        raise ValueError('本次返回多个视频，无法安全生成单视频来源记录')
    return rows[0] if rows else {}

def safe_url(value):
    """Only persist a public page URL; never media/caption signatures or cookies."""
    parts = urlsplit(value or '')
    host = (parts.hostname or '').lower()
    if parts.scheme not in ('http', 'https') or not host:
        return None
    query = parse_qs(parts.query)
    keep = {'v': query['v'][-1]} if host in ('youtube.com', 'www.youtube.com', 'm.youtube.com') and query.get('v') else {}
    return urlunsplit((parts.scheme, host, parts.path, urlencode(keep), ''))

def params(track):
    query = parse_qs(urlsplit(track.get('url') or '').query)
    # Whitelist tiny, meaningful fields rather than exposing the signed URL.
    return {key: values[-1] for key, values in query.items()
            if key in ('lang', 'tlang', 'kind') and values
            and re.fullmatch(r'[A-Za-z0-9_-]{1,40}', values[-1])}

def same_track(selected, candidate):
    if selected.get('url'):
        return selected.get('url') == candidate.get('url') and selected.get('ext') == candidate.get('ext')
    return bool(selected.get('data')) and selected.get('data') == candidate.get('data') and selected.get('ext') == candidate.get('ext')

def source_of(language, selected, info):
    ordinary = any(same_track(selected, candidate) for candidate in (info.get('subtitles') or {}).get(language, []))
    automatic = any(same_track(selected, candidate) for candidate in (info.get('automatic_captions') or {}).get(language, []))
    query = params(selected)
    catalog = 'subtitles' if ordinary else ('automatic_captions' if automatic else 'unknown')
    if catalog == 'unknown':
        category = 'unknown'
    elif query.get('tlang'):
        category = 'platform_automatic_translation'
    elif ordinary:
        category = 'platform_subtitles'
    elif query.get('kind') == 'asr':
        category = 'platform_automatic_asr'
    else:
        category = 'unknown'
    return {
        'category': category,
        'catalog': catalog,
        'evidence': query,
        'same_language_regular_preferred': ordinary and language in (info.get('automatic_captions') or {}),
        'original_audio_language_verified': False,
    }

def existing_path(raw):
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw).expanduser().absolute()
    return path if path.is_file() else None

def resolved_subtitle_path(language, actual, downloaded):
    path = existing_path(actual.get('filepath'))
    if path:
        return path
    # MoveFiles changes the media filepath but leaves requested_subtitles paths
    # at their old temp locations. Resolve only the captured move mapping plus
    # the converter-confirmed extension; never glob nearby/older subtitle files.
    original = ((downloaded.get('requested_subtitles') or {}).get(language) or {}).get('filepath')
    destination = (downloaded.get('__files_to_move') or {}).get(original)
    extension = actual.get('ext')
    reported_path = actual.get('filepath')
    if not (original and destination and reported_path and isinstance(extension, str)
            and re.fullmatch(r'[A-Za-z0-9]+', extension)):
        return None
    converted_original = Path(original).with_suffix('.' + extension).absolute()
    if Path(reported_path).absolute() != converted_original:
        return None
    return existing_path(str(Path(destination).with_suffix('.' + extension)))

def inspect_media(path):
    result = {'path': str(path) if path else None, 'exists': bool(path),
              'probe_status': 'not_available', 'tracks': {'video': [], 'audio': [], 'subtitle': []}}
    if not path:
        return result
    result['size_bytes'] = path.stat().st_size
    try:
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)],
                               capture_output=True, text=True, check=True, timeout=30)
        for stream in json.loads(probe.stdout).get('streams', []):
            kind = stream.get('codec_type')
            if kind not in result['tracks']:
                continue
            item = {key: stream[key] for key in ('index', 'codec_name', 'width', 'height', 'sample_rate', 'channels') if key in stream}
            item['language'] = (stream.get('tags') or {}).get('language')
            result['tracks'][kind].append(item)
        result['probe_status'] = 'ok'
    except (OSError, ValueError, subprocess.SubprocessError):
        result['probe_status'] = 'failed'
    return result

def ffprobe_version():
    try:
        result = subprocess.run(['ffprobe', '-version'], capture_output=True, text=True, check=True, timeout=5)
        first_line = result.stdout.splitlines()[0]
        return first_line.split(' Copyright')[0] if first_line.startswith('ffprobe version ') else 'unknown'
    except (OSError, IndexError, subprocess.SubprocessError):
        return 'unknown'

def write_json_atomic(destination, document):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=destination.parent,
                                         prefix='.' + destination.name + '.', delete=False) as output:
            temporary = output.name
            json.dump(document, output, ensure_ascii=False, indent=2)
            output.write('\n')
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)

try:
    before = snapshot('selected')
    downloaded = snapshot('before_dl')
    final = snapshot('after_move')
    if not before:
        print('[来源记录] 未取得素材元数据，无法生成记录；不把本次视为成功。')
        sys.exit(1)
    if any(info and info.get('id') != before.get('id') for info in (downloaded, final)):
        raise ValueError('下载前后的素材 ID 不一致')

    final_path = existing_path(final.get('filepath'))
    expected = before.get('_filename') or before.get('filename')
    manifest_base = Path(final.get('filepath') or expected or '').expanduser().absolute()
    if not (final.get('filepath') or expected):
        raise ValueError('无法确定来源记录保存位置')
    # Failure records have a different name, preserving an earlier successful record.
    completed = exit_code == 0 and bool(final_path)
    suffix = '.sources.json' if completed else '.sources.failed.json'
    destination = manifest_base.with_suffix(suffix)
    safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', str(before.get('id') or 'unknown'))[:80]
    safe_run = re.sub(r'[^A-Za-z0-9_-]', '_', run_id)
    history_path = destination.parent / 'sources-history' / (safe_id + '.' + safe_run + '.json')
    media = inspect_media(final_path)
    selected = before.get('requested_subtitles') or {}
    phase_path = Path(scratch, 'subtitle-results.json')
    phase = json.loads(phase_path.read_text()) if phase_path.is_file() else None
    plan_path = Path(scratch, 'subtitle-plan.json')
    plan = json.loads(plan_path.read_text()) if plan_path.is_file() else None
    if plan is not None:
        selected = {item['language']: item['track'] for item in plan['selected']}
    after_subs = final.get('requested_subtitles') or {}
    downloaded_subs = downloaded.get('requested_subtitles') or {}
    subtitles = []
    if with_subs == 'yes':
        for language, track in selected.items():
            actual = after_subs.get(language) if final else downloaded_subs.get(language)
            actual = actual or {}
            path = resolved_subtitle_path(language, actual, downloaded) if final else existing_path(actual.get('filepath'))
            saved_srt = bool(final and path and path.stat().st_size > 0 and actual.get('ext') == 'srt' and path.suffix.lower() == '.srt')
            status = 'saved_srt' if saved_srt else ('saved_other_format' if path else 'not_saved_or_not_confirmed')
            if path and not final:
                status = 'downloaded_conversion_or_embedding_not_confirmed'
            subtitles.append({
                'language': language,
                'source': source_of(language, track, before),
                'status': status,
                'path': str(path) if path else None,
                'format': actual.get('ext') if path else None,
            })
    if phase is not None:
        # Per-track completion evidence is authoritative; do not guess paths from old files.
        subtitles = []
        for result in phase.get('files', []):
            language = result['language']
            track = selected.get(language, {})
            path = existing_path(result.get('path'))
            confirmed = result.get('status') == 'saved_srt' and result.get('phase_confirmed') and result.get('yt_dlp_exit_code') == 0 and path and path.stat().st_size > 0 and path.suffix.lower() == '.srt' and run_id in path.name
            status = 'saved_srt' if confirmed else result.get('status', 'not_saved_or_not_confirmed')
            if status == 'saved_srt' and not confirmed:
                status = 'not_saved_or_not_confirmed'
                path = None
            subtitles.append({'language': language, 'source': source_of(language, track, before),
                              'status': status, 'path': str(path) if path else None,
                              'format': path.suffix[1:] if path else None,
                              'yt_dlp_exit_code': result.get('yt_dlp_exit_code'),
                              'phase_confirmed': bool(confirmed), 'error': result.get('error')})
    saved_count = sum(item['status'] == 'saved_srt' for item in subtitles)
    if with_subs != 'yes':
        subtitle_status = 'disabled'
    elif phase and phase.get('status') in ('selection_failed', 'not_attempted_media_failed'):
        subtitle_status = phase['status']
    elif not selected:
        subtitle_status = 'no_matching_subtitles'
    elif saved_count == len(subtitles):
        subtitle_status = 'saved_srt'
    elif saved_count:
        subtitle_status = 'partial'
    else:
        subtitle_status = 'not_ready'

    document = {
        'schema_version': 2,
        'run_id': run_id,
        'history_path': str(history_path),
        'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'tools': {'yt_dlp': ytdlp_version, 'ffprobe': ffprobe_version(), 'python': sys.version.split()[0]},
        'source': {'id': before.get('id'), 'title': before.get('title'),
                   'page_url': safe_url(before.get('webpage_url') or input_url),
                   'extractor': before.get('extractor_key'),
                   'audio_language_reported_by_extractor': before.get('language')},
        'download': {'status': 'completed' if completed else 'failed_or_incomplete',
                     'yt_dlp_exit_code': exit_code, 'after_move_confirmed': bool(final)},
        'media': media,
        'subtitles': {'enabled': with_subs == 'yes', 'requested_language_patterns': patterns,
                      'allow_translated_subs': allow_translated, 'delivery': 'sidecar_only_no_new_embedded_tracks',
                      'rate_limited': bool(phase and phase.get('rate_limited')),
                      'phase_exit_code': phase.get('exit_code') if phase else None,
                      'attempted_count': phase.get('attempted_count') if phase else None,
                      'excluded_by_policy': (plan or {}).get('excluded', []),
                      'status': subtitle_status, 'selected_count': len(subtitles),
                      'saved_srt_count': saved_count,
                      'available_languages': {
                          'platform_subtitles': sorted((before.get('subtitles') or {}).keys()),
                          'platform_automatic_captions': sorted((before.get('automatic_captions') or {}).keys()),
                      }, 'files': subtitles},
        'notes': [
            'platform_subtitles 表示平台普通字幕，不保证官方、人工制作或原语。',
            '自动翻译依据所选字幕 URL 的 tlang；自动识别依据 automatic_captions 与 kind=asr；不足以确认则标 unknown。',
            '语言代码、文件名及平台字幕类别均不能单独证明字幕与原始音频语言相同。',
            '仅记录本次逐轨阶段确认存在的独立字幕；内嵌轨道来自 ffprobe，不据此反推本次字幕成功或来源。',
            '本次不新增内嵌字幕，避免重写已完成媒体；独立 SRT 可直接导入工作台。',
            '字幕 429 可能是平台自动翻译接口限制，不保证延时或升级能解决；遇到 429 立即停止余下字幕请求。',
            '字幕复用媒体阶段元数据；长视频下载后签名地址可能过期，失败不自动刷新元数据或高频重试。',
        ],
    }
    # Keep each run's provenance even when a later subtitle-disabled run updates latest.
    write_json_atomic(history_path, document)
    write_json_atomic(destination, document)

    print('[视频完成] ' + str(final_path) if completed else '[下载未完成] 见 yt-dlp 错误；来源记录不将现存旧视频视为本次成功。')
    if final_path and media['probe_status'] == 'ok':
        print('[轨道] 视频 {} / 音频 {} / 内嵌字幕 {}'.format(*(len(media['tracks'][kind]) for kind in ('video', 'audio', 'subtitle'))))
    elif final_path:
        print('[轨道] ffprobe 读取失败；已保留视频，轨道类型尚未确认。')
    labels = {'disabled': '本次关闭字幕', 'no_matching_subtitles': '未取得匹配语言字幕，不代表平台没有字幕',
              'saved_srt': '已确认保存 {} 份 SRT'.format(saved_count), 'partial': '仅部分 SRT 已确认保存',
              'not_ready': '字幕下载、转换或保存未完成，不能视为原文字幕已就绪',
              'selection_failed': '字幕选择或阶段执行失败，媒体结果单独报告',
              'not_attempted_media_failed': '媒体阶段未完成，本次未请求字幕'}
    print('[字幕] ' + labels[subtitle_status])
    print('[字幕交付] 独立 SRT；本次不新增内嵌轨。')
    if phase and phase.get('rate_limited'):
        print('[字幕限流] 收到 HTTP 429，已停止剩余字幕请求；已成功媒体和字幕保留。此问题可能来自平台接口限制，不保证延时或升级能解决。')
    source_labels = {'platform_subtitles': '平台普通字幕（不保证官方或人工制作）', 'platform_automatic_asr': '平台自动识别',
                     'platform_automatic_translation': '平台自动翻译', 'unknown': '来源类型无法确认'}
    for item in subtitles:
        print('  {}：{}；{}'.format(item['language'], source_labels[item['source']['category']], item['path'] or item['status']))
    print('[来源记录] ' + str(destination))
    if completed and subtitle_status in ('partial', 'not_ready'):
        print('[提示] 视频已保存，但字幕尚未齐备；请先检查来源记录再决定是否进行语音识别。')
    sys.exit(0 if completed else 1)
except (OSError, ValueError, TypeError, KeyError) as error:
    print('[来源记录失败] {}；已下载媒体保留，请勿据此认定字幕齐备。'.format(error))
    sys.exit(1)
PY
}

download_subtitle_phase() {
    python3 - "$@" <<'PY'
"""Isolate each caption download from media and from every other caption.

Private extraction snapshots stay in the temporary directory. Only the small
sanitized results ledger is consumed by write_source_manifest; signed URLs are
never copied into public provenance records.
"""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

scratch, output, patterns, allow_translated, run_id, proxy = sys.argv[1:7]
root, destination = Path(scratch), Path(output).expanduser().absolute()
results = {'status': 'completed', 'exit_code': 0, 'rate_limited': False,
           'attempted_count': 0, 'files': []}

def save_results():
    (root / 'subtitle-results.json').write_text(json.dumps(results, ensure_ascii=False))

def one_snapshot(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError('Expected exactly one video snapshot')
    return rows[0]

def query(track):
    return parse_qs(urlsplit(track.get('url') or '').query)

def acceptable(track, catalog, language):
    if allow_translated == 'yes':
        return True
    params = query(track)
    if params.get('tlang'):
        return False
    return catalog == 'subtitles' or params.get('kind') == ['asr'] or language.endswith('-orig')

def pick_format(tracks):
    for extension in ('vtt', 'srt'):
        matches = [track for track in tracks if track.get('ext') == extension]
        if matches:
            return matches[-1]
    return tracks[-1]

try:
    info = one_snapshot(root / 'media-info.jsonl')
    completed_media = one_snapshot(root / 'after_move.jsonl')
    media_path = Path(completed_media['filepath']).expanduser().absolute()
    if completed_media.get('id') != info.get('id') or not media_path.is_file():
        raise ValueError('Media completion does not match subtitle source')
    # Follow yt-dlp's actual sanitized directory, never reconstruct it from title.
    media_path.relative_to(destination)
    destination = media_path.parent
    available, excluded = {}, []
    normal = info.get('subtitles') or {}
    automatic = info.get('automatic_captions') or {}
    # Platform ordinary subtitles take precedence for an identical language.
    # Keep a distinct -orig ASR resource even when an ordinary same-language track
    # exists: language labels do not verify actual content. Deduplicate exact resources only.
    # Prefer the -orig ASR alias before its duplicate URL without the suffix.
    automatic_languages = sorted(automatic, key=lambda key: not key.endswith('-orig'))
    for catalog, values, languages in (('subtitles', normal, list(normal)),
                                      ('automatic_captions', automatic, automatic_languages)):
        for language in languages:
            if language in available:
                continue
            tracks = [track for track in values[language] if acceptable(track, catalog, language)]
            if not tracks:
                excluded.append({'language': language, 'reason': 'translated_or_unconfirmed_automatic_track'})
                continue
            available[language] = {'language': language, 'catalog': catalog, 'track': pick_format(tracks)}
    chosen = []
    for expression in patterns.split(','):
        expression = expression.strip()
        if not expression:
            continue
        negative = expression.startswith('-')
        pattern = expression[1:] if negative else expression
        matches = list(available) if pattern == 'all' else [language for language in available if re.fullmatch(pattern, language)]
        if negative:
            chosen = [language for language in chosen if language not in matches]
        else:
            chosen.extend(language for language in matches if language not in chosen)
    selected, seen = [], set()
    for language in chosen:
        item = available[language]
        track = item['track']
        fingerprint = (track.get('url'), track.get('data'), track.get('ext'))
        if fingerprint in seen:
            excluded.append({'language': language, 'reason': 'duplicate_caption_resource'})
            continue
        seen.add(fingerprint)
        selected.append(item)
    plan = {'allow_translated_subs': allow_translated == 'yes', 'selected': selected, 'excluded': excluded}
    (root / 'subtitle-plan.json').write_text(json.dumps(plan, ensure_ascii=False))
    if not selected:
        results['status'] = 'no_matching_subtitles'
    print('[字幕阶段] 已完成媒体；将独立请求 {} 条字幕，逐轨转换为 SRT。'.format(len(selected)), flush=True)
    for index, item in enumerate(selected):
        language = item['language']
        result = {'language': language, 'status': 'not_attempted', 'path': None,
                  'yt_dlp_exit_code': None, 'phase_confirmed': False, 'error': None}
        results['files'].append(result)
        if results['rate_limited']:
            result.update(status='not_attempted_rate_limit', error='Stopped after an earlier HTTP 429')
            save_results()
            continue
        selected_info = copy.deepcopy(info)
        # Do not re-use stale per-download paths or selection state from the media phase.
        for key in ('requested_downloads', 'requested_subtitles', 'filepath', '_filename', 'filename', '__files_to_move'):
            selected_info.pop(key, None)
        selected_info['subtitles'] = {language: [item['track']]} if item['catalog'] == 'subtitles' else {}
        selected_info['automatic_captions'] = {language: [item['track']]} if item['catalog'] == 'automatic_captions' else {}
        source = root / f'caption-{index}.info.json'
        source.write_text(json.dumps(selected_info, ensure_ascii=False))
        before = root / f'caption-{index}.before.jsonl'
        after = root / f'caption-{index}.after.jsonl'
        # Every media and sidecar template includes this run's random identity.
        # No globbing, inferred filenames, or old neighboring files count as evidence.
        template = str(destination / ('%(title)s [%(id)s].' + run_id + '.%(ext)s'))
        args = ['yt-dlp', '--load-info-json', str(source), '--skip-download', '--no-playlist',
                '--write-subs', '--write-auto-subs', '--no-embed-subs', '--no-embed-metadata',
                '--sub-langs', '^' + re.escape(language) + '$', '--sub-format', 'vtt/srt/best',
                '--convert-subs', 'srt', '--retries', '0', '--fragment-retries', '0',
                '--socket-timeout', '20', '--no-simulate', '-P', 'home:' + str(destination),
                '-o', template, '-o', 'subtitle:' + template,
                '--print-to-file', 'before_dl:%(.{id,requested_subtitles,__files_to_move})j', str(before),
                '--print-to-file', 'after_video:%(.{id,requested_subtitles,requested_downloads})j', str(after)]
        if proxy:
            args += ['--proxy', proxy]
        results['attempted_count'] += 1
        print('[字幕请求] ' + language, flush=True)
        response = subprocess.run(args, capture_output=True, text=True)
        if response.stdout:
            print(response.stdout, end='', flush=True)
        if response.stderr:
            print(response.stderr, end='', file=sys.stderr, flush=True)
        result['yt_dlp_exit_code'] = response.returncode
        final_info = one_snapshot(after) if after.is_file() else {}
        actual = (final_info.get('requested_subtitles') or {}).get(language) or {}
        for downloaded in final_info.get('requested_downloads') or []:
            if (downloaded.get('requested_subtitles') or {}).get(language):
                actual = downloaded['requested_subtitles'][language]
        path = Path(actual.get('filepath') or '')
        valid_path = bool(actual.get('filepath') and path.is_file() and path.stat().st_size > 0 and run_id in path.name and path.absolute().parent == destination)
        if response.returncode == 0 and final_info.get('id') == info.get('id') and valid_path and actual.get('ext') == 'srt' and path.suffix.lower() == '.srt':
            result.update(status='saved_srt', path=str(path.absolute()), phase_confirmed=True)
        else:
            result.update(status='download_or_conversion_failed', error='Caption request/conversion did not finish; cached signed URL may have expired. No automatic retry.')
            results['exit_code'] = response.returncode or 1
            # Preserve independently downloaded source captions even when conversion fails.
            # This is partial evidence, never a successfully completed SRT.
            if before.is_file():
                downloaded = one_snapshot(before)
                raw = (downloaded.get('requested_subtitles') or {}).get(language) or {}
                raw_path = Path(raw.get('filepath') or '')
                if raw.get('filepath') and raw_path.is_file() and raw_path.stat().st_size > 0 and run_id in raw_path.name and raw_path.absolute().parent == destination:
                    result['path'] = str(raw_path.absolute())
                    result['status'] = 'downloaded_conversion_not_confirmed'
        if re.search(r'(?i)(?:HTTP(?:\s+Error)?|status(?:\s+code)?)[^\n]{0,24}\b429\b|Too Many Requests', response.stdout + '\n' + response.stderr):
            results.update(rate_limited=True, status='rate_limited', exit_code=response.returncode or 1)
            result.update(status='rate_limited', error='HTTP 429; remaining subtitle requests were stopped')
        save_results()
    save_results()
except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
    results.update(status='selection_failed', exit_code=1)
    save_results()
    # Exception details can contain a signed URL; keep public diagnostics bounded.
    print('[字幕阶段失败] 无法完成字幕选择或逐轨处理；媒体保留，详情已记录为未完成。', file=sys.stderr)
    sys.exit(1)
PY
}

download_video() (
    local url="$1"
    local with_subs="$2"
    local simulate="$3"
    local metadata_dir="" media_temp_dir="" run_id="" yt_status=0 record_status=0
    local args=(
        --no-playlist
        -f "$FORMAT"
        --embed-metadata
        --merge-output-format "$CONTAINER"
        --concurrent-fragments "$CONCURRENT_FRAGMENTS"
        --retries 3
        --fragment-retries 3
        --socket-timeout 20
        -P "home:$DOWNLOAD_DIR"
        -o "$SAVE_PATH"
        --no-write-subs --no-write-auto-subs --no-embed-subs
    )
    if [ "$ALLOW_TRANSLATED_SUBS" != "yes" ]; then
        args+=(--extractor-args 'youtube:skip=translated_subs')
    elif [ "$with_subs" = "yes" ]; then
        # --list-subs enables translation catalog extraction. --no-simulate below
        # still downloads media, with all subtitle writes explicitly disabled.
        args+=(--list-subs)
    fi
    if [ -n "$PROXY_URL" ]; then
        args+=(--proxy "$PROXY_URL")
    fi
    if [ "$simulate" = "yes" ]; then
        # Native dry run: no temp paths, metadata snapshots, caption requests or writes.
        args+=(--simulate --no-quiet)
        yt-dlp "${JS_ARGS[@]}" "${args[@]}" -- "$url"
        return $?
    fi

    metadata_dir=$(mktemp -d "${TMPDIR:-/tmp}/subtitle-sources.XXXXXX") || return 1
    trap 'rm -rf "$metadata_dir"; if [ -n "$media_temp_dir" ]; then find "$media_temp_dir" -depth -type d -empty -delete 2>/dev/null; rmdir "$DOWNLOAD_DIR/.yt-dlp-work" 2>/dev/null || true; fi' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    run_id="$(date -u +%Y%m%dT%H%M%SZ)-${metadata_dir##*.}"
    media_temp_dir="$DOWNLOAD_DIR/.yt-dlp-work/$run_id"
    args+=(
        -P "temp:$media_temp_dir"
        --print-to-file 'video:%(.{id,title,webpage_url,extractor_key,language,subtitles,automatic_captions,requested_subtitles,_filename,filename,ext})j' "$metadata_dir/selected.jsonl"
        --print-to-file 'video:%()j' "$metadata_dir/media-info.jsonl"
        --print-to-file 'before_dl:%(.{id,requested_subtitles,__files_to_move})j' "$metadata_dir/before_dl.jsonl"
        --print-to-file 'after_move:%(.{id,filepath,requested_subtitles})j' "$metadata_dir/after_move.jsonl"
        --no-simulate
    )
    echo "[媒体阶段] 先下载媒体；字幕失败不会阻断媒体。"
    yt-dlp "${JS_ARGS[@]}" "${args[@]}" -- "$url"
    yt_status=$?
    if [ "$with_subs" = "yes" ]; then
        if [ "$yt_status" -eq 0 ] && [ -s "$metadata_dir/after_move.jsonl" ]; then
            download_subtitle_phase "$metadata_dir" "$DOWNLOAD_DIR" "$SUB_LANGS" "$ALLOW_TRANSLATED_SUBS" "$run_id" "$PROXY_URL" || true
        else
            printf '%s\n' '{"status":"not_attempted_media_failed","exit_code":null,"rate_limited":false,"attempted_count":0,"files":[]}' > "$metadata_dir/subtitle-results.json"
        fi
    fi
    write_source_manifest "$metadata_dir" "$url" "$with_subs" "$SUB_LANGS" "$yt_status" "${YTDLP_VERSION-unknown}" "$run_id" "$ALLOW_TRANSLATED_SUBS"
    record_status=$?
    if [ "$yt_status" -ne 0 ]; then
        return "$yt_status"
    fi
    if [ "$record_status" -ne 0 ]; then
        echo "[注意] yt-dlp 媒体阶段已结束，但来源记录/结果核对未完成；已下载文件保留。"
        return 1
    fi
)

# 允许离线测试仅载入函数，不启动下载交互。
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
    return 0
fi

MODE="${1-}"
case "$MODE" in
    ""|--check)
        if [ "$#" -gt 1 ]; then
            echo "用法：$0 [视频链接 | --check | --simulate 视频链接]"
            exit 2
        fi
        ;;
    --simulate)
        if [ "$#" -ne 2 ] || [ -z "$2" ]; then
            echo "用法：$0 --simulate 视频链接"
            exit 2
        fi
        ;;
    http://*|https://*)
        if [ "$#" -ne 1 ]; then
            echo "用法：$0 视频链接"
            exit 2
        fi
        MODE="download"
        ;;
    *)
        echo "用法：$0 [视频链接 | --check | --simulate 视频链接]"
        exit 2
        ;;
esac

echo "========================================================"
echo "              YouTube 高画质下载器（Mac 版）"
echo "========================================================"
if ! check_dependencies; then
    if [ -z "$MODE" ] && [ -t 0 ]; then
        IFS= read -r -p "按回车退出。" _
    fi
    exit 1
fi
show_settings

if [ "$MODE" = "--check" ]; then
    echo "[检查完成] 必需命令已找到；此检查不会验证代理或连接 YouTube。"
    exit 0
fi
if [ "$MODE" = "--simulate" ]; then
    echo "[诊断] 仅解析视频和格式，不下载文件。"
    download_video "$2" "$DOWNLOAD_SUBS" "yes"
    exit $?
fi
if [ "$MODE" = "download" ]; then
    download_video "$1" "$DOWNLOAD_SUBS" "no"
    exit $?
fi

while true; do
    echo ""
    if ! IFS= read -r -p "请粘贴 YouTube 视频链接（输入 q 退出）: " URL; then
        echo ""
        break
    fi
    case "$URL" in
        q|Q) break ;;
        "") echo "[提示] 链接不能为空。"; continue ;;
    esac

    echo "[正在解析并下载，请稍候...]"
    if download_video "$URL" "$DOWNLOAD_SUBS" "no"; then
        continue
    fi

    echo "[失败] 请查看上方 yt-dlp 的具体错误。原因可能涉及代理、"
    echo "链接或访问权限、视频解析、字幕下载、磁盘或 ffmpeg 后处理。"
    if [ "$DOWNLOAD_SUBS" = "yes" ]; then
        echo "若上方错误与字幕有关，可关闭字幕后重试本视频。"
        if ! IFS= read -r -p "输入 r 仅重试视频（不下载字幕），回车换链接，q 退出: " REPLY; then
            echo ""
            break
        fi
        case "$REPLY" in
            q|Q) break ;;
            r|R)
                if download_video "$URL" "no" "no"; then
                    echo "[成功] 本次视频处理完成；字幕下载已关闭，现有内嵌轨道请见来源记录。"
                else
                    echo "[失败] 无字幕重试仍未完成，请查看上方具体错误。"
                fi
                ;;
        esac
    fi
done
