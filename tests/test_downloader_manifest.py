"""Offline checks: python3 -m unittest discover -s tests -p 'test_downloader_manifest.py' -v"""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid
import sys
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import downloader


class DownloaderManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='downloader-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scratch = self.root / 'snapshots'
        self.scratch.mkdir()
        self.output = self.root / 'output'
        self.output.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.commands = {}
        self.executable('ffprobe', 'import json\nprint(json.dumps({"streams":[{"index":0,"codec_type":"video","codec_name":"h264"},{"index":1,"codec_type":"audio","codec_name":"aac"},{"index":2,"codec_type":"subtitle","codec_name":"subrip","tags":{"language":"tha"}}]}))\n')
        self.media = self.output / 'Example [video123].mkv'
        self.media.write_bytes(b'fake-media')
        self.before = {'id': 'video123', 'title': 'Example', 'extractor_key': 'Youtube',
                       'webpage_url': 'https://www.youtube.com/watch?v=video123&signature=PRIVATE',
                       '_filename': str(self.media), 'subtitles': {}, 'automatic_captions': {},
                       'requested_subtitles': {}}
        self.final = {'id': 'video123', 'filepath': str(self.media), 'requested_subtitles': {}}

    def executable(self, name, content):
        path = self.bin / (name + ".py")
        path.write_text(content, encoding="utf-8")
        self.commands[name] = [sys.executable, "-X", "utf8", str(path)]

    def track(self, language, catalog, query, saved=True):
        track = {'ext': 'vtt', 'url': 'https://caption.example/timedtext?' + query + '&signature=PRIVATE'}
        self.before[catalog].setdefault(language, []).append(track.copy())
        self.before['requested_subtitles'][language] = track.copy()
        path = self.output / ('Example [video123].current-run.' + language + '.srt')
        if saved:
            path.write_text('1\n00:00:00,000 --> 00:00:01,000\nSubtitle\n')
        self.final['requested_subtitles'][language] = {'ext': 'srt', 'filepath': str(path)}
        return track

    def invoke(self, operation, *args, env=None):
        output, errors = io.StringIO(), io.StringIO()
        environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", **(env or {})}
        with patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            if operation == "manifest":
                code = downloader.write_source_manifest(*args, ffprobe_command=self.commands['ffprobe'])
            elif operation == "subtitles":
                code = downloader.download_subtitle_phase(*args, ytdlp_command=self.commands['yt-dlp'])
            else:
                tools = downloader.DownloadTools(self.commands['yt-dlp'], self.commands['ffprobe'], [])
                code = downloader.download_video(args[0], args[1], args[2] == 'yes', tools=tools)
        return subprocess.CompletedProcess(operation, code, output.getvalue(), errors.getvalue())

    def manifest(self, status=0, enabled='yes', final=True, downloaded=None, run_id=None, allow_translated='no'):
        (self.scratch / 'selected.jsonl').write_text(json.dumps(self.before) + '\n', encoding='utf-8')
        if final:
            (self.scratch / 'after_move.jsonl').write_text(json.dumps(self.final) + '\n', encoding='utf-8')
        if downloaded:
            (self.scratch / 'before_dl.jsonl').write_text(json.dumps(downloaded) + '\n', encoding='utf-8')
        result = self.invoke('manifest', str(self.scratch),
                            'https://www.youtube.com/watch?v=video123', enabled, 'th.*,zh.*,en.*', str(status),
                            '2026.08.19-test', run_id or 'test-' + uuid.uuid4().hex, allow_translated)
        suffix = '.sources.json' if status == 0 and final else '.sources.failed.json'
        path = self.media.with_suffix(suffix)
        document = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        return result, document

    def test_sources_use_selected_catalog_and_explicit_evidence(self):
        regular = self.track('th', 'subtitles', 'lang=th')
        self.before['automatic_captions']['th'] = [{'url': 'https://caption.example/?lang=th&kind=asr', 'ext': 'vtt'}]
        self.track('th-orig', 'automatic_captions', 'lang=th&kind=asr')
        self.track('zh-Hans', 'automatic_captions', 'lang=th&kind=asr&tlang=zh-Hans')
        self.track('en', 'automatic_captions', 'lang=en')
        result, doc = self.manifest()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        sources = {item['language']: item['source'] for item in doc['subtitles']['files']}
        self.assertEqual(sources['th']['category'], 'platform_subtitles')
        self.assertTrue(sources['th']['same_language_regular_preferred'])
        self.assertEqual(sources['th-orig']['category'], 'platform_automatic_asr')
        self.assertEqual(sources['zh-Hans']['category'], 'platform_automatic_translation')
        self.assertEqual(sources['en']['category'], 'unknown')
        self.assertFalse(any(source['original_audio_language_verified'] for source in sources.values()))
        self.assertNotIn('PRIVATE', json.dumps(doc))
        self.assertNotIn('caption.example', json.dumps(doc))
        self.assertEqual(doc['media']['tracks']['subtitle'][0]['language'], 'tha')
        self.assertEqual(doc['subtitles']['saved_srt_count'], 4)
        self.assertEqual(doc['tools']['yt_dlp'], '2026.08.19-test')
        self.assertEqual(json.loads(Path(doc['history_path']).read_text(encoding='utf-8')), doc)
        self.assertEqual(regular['ext'], 'vtt')

    def test_selected_track_not_matching_catalog_stays_unknown(self):
        self.track('th', 'subtitles', 'lang=th')
        self.before['requested_subtitles']['th']['url'] = 'https://different.example/?kind=asr&lang=th'
        _, doc = self.manifest()
        self.assertEqual(doc['subtitles']['files'][0]['source']['category'], 'unknown')

    def test_old_or_missing_subtitle_not_counted(self):
        self.track('th', 'subtitles', 'lang=th', saved=False)
        (self.output / 'Example [video123].old-run.th.srt').write_text('old/manual edit')
        result, doc = self.manifest()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(doc['subtitles']['saved_srt_count'], 0)
        self.assertEqual(doc['subtitles']['status'], 'not_ready')
        self.assertIsNone(doc['subtitles']['files'][0]['path'])

    def test_no_match_and_disabled_are_distinct(self):
        _, doc = self.manifest()
        self.assertEqual(doc['subtitles']['status'], 'no_matching_subtitles')
        first_history = Path(doc['history_path'])
        _, doc = self.manifest(enabled='no')
        self.assertEqual(doc['subtitles']['status'], 'disabled')
        self.assertEqual(doc['media']['tracks']['subtitle'][0]['codec_name'], 'subrip')
        self.assertEqual(json.loads(first_history.read_text(encoding='utf-8'))['subtitles']['status'], 'no_matching_subtitles')
        self.assertEqual(len(list((self.output / 'sources-history').glob('*.json'))), 2)

    def test_converted_subtitle_resolves_captured_move_mapping(self):
        self.track('th', 'subtitles', 'lang=th')
        saved_srt = self.final['requested_subtitles']['th']['filepath']
        old_vtt = str(self.scratch / 'Example [video123].th.vtt')
        self.final['requested_subtitles']['th']['filepath'] = str(Path(old_vtt).with_suffix('.srt'))
        downloaded = {'id': 'video123', 'requested_subtitles': {'th': {'ext': 'vtt', 'filepath': old_vtt}},
                      '__files_to_move': {old_vtt: str(Path(saved_srt).with_suffix('.vtt'))}}
        result, doc = self.manifest(downloaded=downloaded)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(doc['subtitles']['files'][0]['path'], saved_srt)
        self.assertEqual(doc['subtitles']['saved_srt_count'], 1)

    def test_missing_move_evidence_does_not_guess_same_named_srt(self):
        self.track('th', 'subtitles', 'lang=th')
        self.final['requested_subtitles']['th']['filepath'] = str(self.scratch / 'Example [video123].th.srt')
        _, doc = self.manifest()
        self.assertEqual(doc['subtitles']['saved_srt_count'], 0)

    def test_failure_preserves_success_record_and_reports_unconverted_source(self):
        self.track('th', 'automatic_captions', 'lang=th&kind=asr', saved=False)
        success = self.media.with_suffix('.sources.json')
        success.write_text('{"previous_success": true}')
        vtt = self.output / 'Example [video123].current-run.th.vtt'
        vtt.write_text('WEBVTT\n')
        downloaded = {'id': 'video123', 'requested_subtitles': {'th': {'ext': 'vtt', 'filepath': str(vtt)}}}
        result, doc = self.manifest(status=1, final=False, downloaded=downloaded)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(success.read_text(encoding='utf-8')), {'previous_success': True})
        self.assertFalse(doc['media']['exists'])
        self.assertEqual(doc['subtitles']['files'][0]['status'], 'downloaded_conversion_or_embedding_not_confirmed')
        self.assertEqual(doc['subtitles']['saved_srt_count'], 0)
        self.assertEqual(doc['subtitles']['files'][0]['path'], str(vtt))

    def test_zero_exit_without_after_move_is_not_success(self):
        result, doc = self.manifest(final=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(doc['download']['status'], 'failed_or_incomplete')

    def test_ffprobe_failure_keeps_media_and_records_uncertainty(self):
        self.executable('ffprobe', 'import sys\nsys.exit(1)\n')
        result, doc = self.manifest()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(doc['media']['probe_status'], 'failed')
        self.assertTrue(self.media.exists())

    def test_simulate_does_not_request_snapshots_or_write_artifacts(self):
        capture = self.root / 'args.json'
        self.executable('yt-dlp', '#!/usr/bin/env python3\nimport json, os, sys\nopen(os.environ["TEST_ARGS"], "w").write(json.dumps(sys.argv[1:]))\n')
        result = self.invoke('download', 'https://www.youtube.com/watch?v=video123', 'yes', 'yes',
                            env={'TEST_ARGS': str(capture), 'YOUTUBE_DOWNLOAD_DIR': str(self.output)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        args = json.loads(capture.read_text(encoding='utf-8'))
        self.assertIn('--simulate', args)
        self.assertNotIn('--print-to-file', args)
        self.assertIn('--no-write-subs', args)
        self.assertIn('--no-write-auto-subs', args)
        self.assertIn('youtube:skip=translated_subs', args)
        self.assertNotIn('--load-info-json', args)
        self.assertEqual([path.name for path in self.output.iterdir()], [self.media.name])

    def test_download_uses_separate_run_paths_and_cleans_private_metadata(self):
        capture = self.root / 'args.json'
        self.executable('yt-dlp', '#!/usr/bin/env python3\nimport json, os, sys\nopen(os.environ["TEST_ARGS"], "w").write(json.dumps(sys.argv[1:]))\nsys.exit(9)\n')
        result = self.invoke('download', 'https://www.youtube.com/watch?v=video123', 'yes', 'no',
                            env={'TEST_ARGS': str(capture), 'YOUTUBE_DOWNLOAD_DIR': str(self.output)})
        self.assertEqual(result.returncode, 9)
        args = json.loads(capture.read_text(encoding='utf-8'))
        templates = [args[index + 1] for index, value in enumerate(args) if value == '-o']
        self.assertFalse(any(template.startswith('subtitle:') for template in templates))
        self.assertEqual(templates[0], '%(title)s [%(id)s]/%(title)s [%(id)s].%(ext)s')
        self.assertIn('--no-write-subs', args)
        self.assertIn('--no-write-auto-subs', args)
        self.assertIn('--no-embed-subs', args)
        directories = [args[index + 1] for index, value in enumerate(args) if value == '-P']
        self.assertIn('home:' + str(self.output), directories)
        self.assertTrue(any(path.startswith('temp:') and '.yt-dlp-work' in Path(path[5:]).parts for path in directories))
        for index, arg in enumerate(args):
            if arg == '--print-to-file':
                self.assertFalse(Path(args[index + 2]).parent.exists())


    def fake_subtitle_tool(self):
        self.executable('yt-dlp', """#!/usr/bin/env python3
import json, os
from pathlib import Path
import sys
args=sys.argv[1:]
info=json.loads(Path(args[args.index('--load-info-json')+1]).read_text(encoding='utf-8'))
tracks={**info.get('automatic_captions',{}),**info.get('subtitles',{})}
language=next(iter(tracks))
with open(os.environ['CALLS'], 'a') as handle: handle.write(json.dumps({'language':language,'args':args})+'\\n')
mode=json.loads(os.environ.get('BEHAVIORS','{}')).get(language,'success')
if mode in ('429','failure'):
    print('ERROR: Unable to download subtitles: HTTP Error '+('429: Too Many Requests' if mode=='429' else '403: Forbidden'), file=sys.stderr)
    sys.exit(1)
template=args[args.index('-o')+1]
path=Path(template.replace('%(title)s',info['title']).replace('%(id)s',info['id']).replace('%(ext)s',language+'.srt'))
path.write_text('1\\n00:00:00,000 --> 00:00:01,000\\nnew caption\\n')
actual={'id':info['id'],'requested_subtitles':{language:{'ext':'srt','filepath':str(path)}}}
if mode!='missing_stage':
    for index,arg in enumerate(args):
        if arg=='--print-to-file': Path(args[index+2]).write_text(json.dumps(actual)+'\\n')
""")

    def run_subtitle_phase(self, allow='no', patterns='th.*,zh.*,en.*', behaviors=None):
        (self.scratch / 'media-info.jsonl').write_text(json.dumps(self.before) + '\n', encoding='utf-8')
        (self.scratch / 'after_move.jsonl').write_text(json.dumps(self.final) + '\n', encoding='utf-8')
        calls = self.root / 'calls.jsonl'
        result = self.invoke('subtitles', str(self.scratch), str(self.output), patterns,
                            allow, 'current-run', '',
                            env={'CALLS': str(calls), 'BEHAVIORS': json.dumps(behaviors or {})})
        rows = [json.loads(line) for line in calls.read_text(encoding='utf-8').splitlines()] if calls.exists() else []
        return result, json.loads((self.scratch / 'subtitle-results.json').read_text(encoding='utf-8')), rows

    def test_default_policy_keeps_distinct_original_asr_and_excludes_translation_duplicates(self):
        self.fake_subtitle_tool()
        self.track('th', 'subtitles', 'lang=th')
        self.track('th-orig', 'automatic_captions', 'lang=th&kind=asr')
        self.track('zh-Hans-th', 'automatic_captions', 'lang=th&tlang=zh-Hans')
        self.track('en-orig', 'automatic_captions', 'lang=en&kind=asr')
        self.track('en', 'automatic_captions', 'lang=en&kind=asr')
        result, phase, calls = self.run_subtitle_phase()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([row['language'] for row in calls], ['th','th-orig','en-orig'])
        self.assertTrue(all(row['phase_confirmed'] for row in phase['files']))
        for row in calls:
            self.assertIn('--skip-download', row['args'])
            self.assertEqual(row['args'][row['args'].index('--retries')+1], '0')
            self.assertIn('current-run', row['args'][row['args'].index('-o')+1])
        _, doc = self.manifest(run_id='current-run')
        self.assertEqual(doc['subtitles']['saved_srt_count'], 3)
        self.assertEqual(doc['download']['status'], 'completed')
        self.assertFalse(doc['subtitles']['allow_translated_subs'])
        self.assertNotIn('PRIVATE', json.dumps(doc))

    def test_429_retains_prior_success_stops_remaining_and_preserves_media_status(self):
        self.fake_subtitle_tool()
        for language in ('th','en','zh-Hans'):
            self.track(language, 'subtitles', 'lang='+language)
        result, phase, calls = self.run_subtitle_phase(patterns='th,en,zh-Hans', behaviors={'en':'429'})
        self.assertEqual(result.returncode, 0)
        self.assertEqual([row['language'] for row in calls], ['th','en'])
        self.assertEqual([row['status'] for row in phase['files']], ['saved_srt','rate_limited','not_attempted_rate_limit'])
        result, doc = self.manifest(run_id='current-run')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(doc['download']['status'], 'completed')
        self.assertEqual(doc['subtitles']['status'], 'partial')
        self.assertTrue(doc['subtitles']['rate_limited'])
        self.assertEqual(doc['subtitles']['attempted_count'], 2)
        self.assertTrue(self.media.is_file())

    def test_missing_stage_and_old_matching_files_never_count_as_success(self):
        self.fake_subtitle_tool()
        self.track('th', 'subtitles', 'lang=th')
        result, phase, calls = self.run_subtitle_phase(behaviors={'th':'missing_stage'})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(phase['files'][0]['status'], 'download_or_conversion_failed')
        # A failed request must not inherit the original helper's existing SRT.
        _, doc = self.manifest(run_id='current-run')
        self.assertEqual(doc['subtitles']['saved_srt_count'], 0)
        self.assertIsNone(doc['subtitles']['files'][0]['path'])

    def test_explicit_translation_opt_in_records_actual_source(self):
        self.fake_subtitle_tool()
        self.track('zh-Hans-th', 'automatic_captions', 'lang=th&tlang=zh-Hans')
        result, phase, calls = self.run_subtitle_phase(allow='yes')
        self.assertEqual(result.returncode, 0)
        self.assertEqual([row['language'] for row in calls], ['zh-Hans-th'])
        _, doc = self.manifest(run_id='current-run', allow_translated='yes')
        self.assertTrue(doc['subtitles']['allow_translated_subs'])
        self.assertEqual(doc['subtitles']['files'][0]['source']['category'], 'platform_automatic_translation')

    def test_non429_failure_allows_independent_later_tracks_without_retry(self):
        self.fake_subtitle_tool()
        for language in ('th','en'):
            self.track(language, 'subtitles', 'lang='+language)
        _, phase, calls = self.run_subtitle_phase(patterns='th,en', behaviors={'th':'failure'})
        self.assertEqual([row['language'] for row in calls], ['th','en'])
        self.assertFalse(phase['rate_limited'])
        self.assertEqual(phase['files'][1]['status'], 'saved_srt')
        _, doc = self.manifest(run_id='current-run')
        self.assertEqual(doc['subtitles']['status'], 'partial')
        self.assertEqual(doc['subtitles']['saved_srt_count'], 1)

    def test_unicode_paths_and_metadata_survive_subtitles_and_manifest(self):
        self.fake_subtitle_tool()
        self.output = self.root / '中文 ไทย output'
        self.output.mkdir()
        self.media = self.output / '标题 สวัสดี [video123].mkv'
        self.media.write_bytes(b'fake-media')
        self.before.update(title='标题 สวัสดี', _filename=str(self.media))
        self.final['filepath'] = str(self.media)
        self.track('th', 'subtitles', 'lang=th')
        result, phase, _ = self.run_subtitle_phase()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        saved_path = Path(phase['files'][0]['path'])
        self.assertEqual(saved_path.parent, self.output)
        self.assertIn('标题 สวัสดี', saved_path.name)
        result, doc = self.manifest(run_id='current-run')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(doc['source']['title'], '标题 สวัสดี')
        self.assertEqual(doc['subtitles']['saved_srt_count'], 1)


if __name__ == '__main__':
    unittest.main()
