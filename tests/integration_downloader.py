"""Offline integration using installed yt-dlp/FFmpeg and synthetic local media.

The shim only replaces URL extraction with --load-info-json. Downloading,
subtitle conversion, independent phases, metadata stages and moves use the real tools.
Run: python3 tests/integration_downloader.py
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.name == 'nt':
        sys.path.insert(0, str(ROOT / 'scripts'))
        from windows_environment import configure_tools
        configure_tools()
    actual_ytdlp = shutil.which("yt-dlp")
    assert actual_ytdlp and shutil.which("ffmpeg") and shutil.which("ffprobe")
    with tempfile.TemporaryDirectory(prefix="subtitle-real-integration-") as scratch:
        base = Path(scratch)
        media = base / "input.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=128x72:r=10:d=2",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(media),
        ], check=True)
        shim = base / "bin"
        shim.mkdir()
        wrapper = shim / "yt_dlp_fixture.py"
        wrapper.write_text("""#!/usr/bin/env python3
import os, sys, subprocess
args = sys.argv[1:]
if '--version' not in args:
    if '--load-info-json' in args:
        args = ['--ignore-config', '--enable-file-urls'] + args
    else:
        assert args[-2] == '--', args
        args = ['--ignore-config', '--enable-file-urls', '--load-info-json', os.environ['FIXTURE_JSON']] + args[:-2]
sys.exit(subprocess.run([os.environ['REAL_YTDLP']] + args).returncode)
""", encoding="utf-8")
        fixture = base / "fixture.json"
        output = base / "output"
        output.mkdir()
        def subtitle(text, query):
            return {"ext": "vtt", "url": "https://www.youtube.com/api/timedtext?" + query,
                    "data": "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\n" + text + "\n"}
        info = {
            "id": "offline001", "title": "离线 ไทย [test]", "extractor_key": "Youtube",
            "webpage_url": "https://www.youtube.com/watch?v=offline001&tracking=remove-me",
            "duration": 2, "ext": "mp4", "url": media.as_uri(),
            "vcodec": "h264", "acodec": "aac", "format_id": "local",
            "subtitles": {"th": [subtitle("English despite the Thai label", "lang=th")]},
            "automatic_captions": {
                "th": [subtitle("สวัสดี", "lang=th&kind=asr")],
                "th-orig": [subtitle("สวัสดี", "lang=th&kind=asr")],
                "en": [subtitle("Hello", "lang=en&kind=asr")],
                "zh-Hans": [subtitle("你好", "lang=th&tlang=zh-Hans&kind=asr")],
            },
        }
        def run(simulate="no", allow_translated="no", languages="th.*,zh.*,en.*", expected_status=0):
            fixture.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
            env = dict(os.environ, YOUTUBE_DOWNLOAD_DIR=str(output), PROXY_URL="",
                       REAL_YTDLP=actual_ytdlp, FIXTURE_JSON=str(fixture),
                       PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                       ALLOW_TRANSLATED_SUBS=allow_translated, SUB_LANGS=languages,
                       NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
            driver = """import sys
sys.path.insert(0, sys.argv[1])
import downloader
settings = downloader.DownloadSettings.from_environment()
tools = downloader.DownloadTools([sys.executable, '-X', 'utf8', sys.argv[2]], ['ffprobe'], [], 'offline-integration')
sys.exit(downloader.download_video('https://www.youtube.com/watch?v=offline001', 'yes', sys.argv[3] == 'yes', settings=settings, tools=tools))
"""
            result = subprocess.run([sys.executable, '-X', 'utf8', '-c', driver,
                                     str(ROOT / 'scripts'), str(wrapper), simulate],
                                    env=env, cwd=base, text=True, encoding='utf-8', capture_output=True)
            assert result.returncode == expected_status, result.stdout + result.stderr
            return result

        first = run()
        records = list(output.rglob("*.sources.json"))
        assert len(records) == 1, first.stdout + first.stderr + repr(list(output.rglob("*")))
        record = json.loads(records[0].read_text(encoding='utf-8'))
        final_path = Path(record["media"]["path"])
        assert final_path.name == info["title"] + " [offline001].mp4", final_path
        assert final_path.parent == output / (info["title"] + " [offline001]"), final_path
        assert records[0].parent == final_path.parent
        assert Path(record["history_path"]).parent == final_path.parent / "sources-history"
        assert not (output / ".yt-dlp-work").exists()
        assert record["download"]["status"] == "completed", record
        assert record["subtitles"]["saved_srt_count"] == 3, record
        assert record["subtitles"]["allow_translated_subs"] is False
        assert any(row["language"] == "zh-Hans" for row in record["subtitles"]["excluded_by_policy"])
        assert [len(record["media"]["tracks"][kind]) for kind in ("video", "audio", "subtitle")] == [1, 1, 0], record
        saved = {row["language"]: row for row in record["subtitles"]["files"]}
        assert saved["th"]["source"]["category"] == "platform_subtitles"
        assert saved["th"]["source"]["same_language_regular_preferred"] is True
        assert saved["th-orig"]["source"]["category"] == "platform_automatic_asr"
        assert "English despite" in Path(saved["th"]["path"]).read_text(encoding='utf-8')
        assert "สวัสดี" in Path(saved["th-orig"]["path"]).read_text(encoding='utf-8')
        assert all(not row["source"]["original_audio_language_verified"] for row in saved.values())
        assert saved["en"]["source"]["category"] == "platform_automatic_asr"
        assert "zh-Hans" not in saved
        assert all(Path(row["path"]).is_file() and Path(row["path"]).parent == final_path.parent for row in saved.values())
        assert "tracking=remove-me" not in records[0].read_text(encoding='utf-8')
        assert "timedtext" not in records[0].read_text(encoding='utf-8')
        print("PASS real yt-dlp media-first conversion, default translation exclusion, Thai provenance and final paths")

        # Changing an old sidecar must not make it the source for a new run.
        old_thai = Path(saved["th"]["path"])
        old_thai.write_text("人工修改稿，不得覆盖\n", encoding="utf-8")
        repeated = run()
        again = json.loads(records[0].read_text(encoding='utf-8'))
        new_thai = next(row for row in again["subtitles"]["files"] if row["language"] == "th")
        assert old_thai.read_text(encoding='utf-8') == "人工修改稿，不得覆盖\n"
        assert Path(new_thai["path"]) != old_thai
        assert "English despite" in Path(new_thai["path"]).read_text(encoding='utf-8')
        assert again["media"]["path"] == str(final_path)
        assert "already been downloaded" in repeated.stdout, repeated.stdout
        assert len(list(output.rglob("*.mp4"))) == 1, list(output.rglob("*.mp4"))
        print("PASS repeated download reuses stable media and preserves previous subtitle edits")

        run(allow_translated="yes")
        widened = json.loads(records[0].read_text(encoding='utf-8'))
        assert widened["subtitles"]["allow_translated_subs"] is True
        assert widened["subtitles"]["saved_srt_count"] == 4
        assert next(row for row in widened["subtitles"]["files"] if row["language"] == "zh-Hans")["source"]["category"] == "platform_automatic_translation"
        assert len(widened["media"]["tracks"]["subtitle"]) == 0
        print("PASS explicit translated-subtitle opt-in keeps independent sidecars and source evidence")

        before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in output.rglob("*") if p.is_file()}
        run("yes")
        after = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in output.rglob("*") if p.is_file()}
        assert before == after
        print("PASS real simulation does not create or modify output files")

        info["id"] = "offline002"
        info["subtitles"] = {}
        info["automatic_captions"] = {}
        run()
        no_subs = next(json.loads(p.read_text(encoding='utf-8')) for p in output.rglob("*.sources.json")
                       if json.loads(p.read_text(encoding='utf-8'))["source"]["id"] == "offline002")
        assert Path(no_subs["media"]["path"]).parent != final_path.parent
        assert no_subs["subtitles"]["status"] == "no_matching_subtitles"
        assert no_subs["subtitles"]["files"] == []
        assert len(no_subs["media"]["tracks"]["subtitle"]) == 0
        print("PASS no-subtitle download stays successful and records an explicit empty result")

        video, audio = base / "video.mp4", base / "audio.m4a"
        for path, selected_stream in ((video, "0:v:0"), (audio, "0:a:0")):
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-map", selected_stream,
                            "-c", "copy", str(path)], check=True)
        for key in ("url", "ext", "vcodec", "acodec", "format_id"):
            info.pop(key, None)
        info.update(id="offline003", formats=[
            {"url": video.as_uri(), "format_id": "video", "ext": "mp4", "vcodec": "h264", "acodec": "none"},
            {"url": audio.as_uri(), "format_id": "audio", "ext": "m4a", "vcodec": "none", "acodec": "aac"},
        ], subtitles={"th": [subtitle("สวัสดี", "lang=th")]})
        run()
        merged = next(json.loads(p.read_text(encoding='utf-8')) for p in output.rglob("*.sources.json")
                      if json.loads(p.read_text(encoding='utf-8'))["source"]["id"] == "offline003")
        assert Path(merged["media"]["path"]).name == info["title"] + " [offline003].mkv", merged
        assert [len(merged["media"]["tracks"][kind]) for kind in ("video", "audio", "subtitle")] == [1, 1, 0], merged
        assert merged["subtitles"]["saved_srt_count"] == 1
        print("PASS separate video/audio streams merge to stable MKV plus independent Thai SRT")

        requests = []
        class CaptionHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                if self.path.startswith('/en.vtt'):
                    self.send_response(429)
                    self.end_headers()
                    self.wfile.write(b'Too Many Requests')
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/vtt')
                self.end_headers()
                self.wfile.write('WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nสวัสดี\n'.encode())
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), CaptionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            info.update(id='offline429', subtitles={language: [{'ext': 'vtt', 'url': f'http://127.0.0.1:{server.server_port}/{route}.vtt?lang={language}'}] for language, route in [('th', 'th'), ('en', 'en'), ('zh-Hans', 'zh')]}, automatic_captions={})
            failed_caption = run(languages='th,en,zh-Hans')
            partial = next(json.loads(p.read_text(encoding='utf-8')) for p in output.rglob('*.sources.json') if json.loads(p.read_text(encoding='utf-8'))['source']['id'] == 'offline429')
            assert partial['download']['status'] == 'completed'
            assert partial['subtitles']['status'] == 'partial', (partial, failed_caption.stdout, failed_caption.stderr)
            assert partial['subtitles']['rate_limited'] is True
            assert partial['subtitles']['attempted_count'] == 2
            assert partial['subtitles']['saved_srt_count'] == 1
            assert [row['status'] for row in partial['subtitles']['files']] == ['saved_srt', 'rate_limited', 'not_attempted_rate_limit']
            assert len(requests) == 2 and requests[0].startswith('/th.vtt') and requests[1].startswith('/en.vtt'), requests
            assert Path(partial['media']['path']).is_file()
            assert Path(partial['subtitles']['files'][0]['path']).is_file()
            assert 'HTTP 429' in failed_caption.stdout
            assert '127.0.0.1:' not in json.dumps(partial)
            print('PASS real local HTTP 429: media completes, first SRT survives, remaining request is skipped without retry')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
