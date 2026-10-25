> **已退役 · 2026-10-25**：本文保留旧 Studio 方案与当时记录，不再作为实施依据。旧文中的“必须”“唯一主计划”“下一步”均已失效。当前决策与任务以 [SE 主流程实施计划](../../../se-workflow-plan.md) 为准。仅允许为读取、备份、导出旧项目参考运行步骤；不要据此重新启动 Studio 开发。

# Workbench API contract (v1)

Base `/api`. JSON UTF-8. Errors use FastAPI `{detail: string|object}`. Conflicts return 409 `{detail:{message, current_revision?}}`. Project detail is the project object itself (not wrapped); its `segments`, `candidates`, `jobs`, `glossary`, `revisions`, `reference_tracks` are arrays. Deleted segments stay in storage; front end hides `deleted: true`. All content mutations return `{project: <full project>, result: <operation result>}` unless specified.

## Project shape

```
{project_id,name,schema_version:1,document_revision,created_at,updated_at,target_language:'zh-Hans',language,glossary_version:0,glossary:[],media:null|{media_id,filename,sha256,duration_ms,selected_audio_track,audio_track_count,requires_audio_preview,streams,status,url},track:{track_id,language,source_type,filename,sha256,media_id},segments:[{segment_id,start_ms,end_ms,source_text,zh_text,revision,source_revision,review_status:'unreviewed'|'needs_review'|'reviewed',translation_stale,manual_zh,deleted,parent_ids:[],risk_flags:[]}],candidates:[],jobs:[],revisions:[],reference_tracks:[],exports:[]}
```

## Routes

- `GET /health` → status, service, ffmpeg/ffprobe availability.
- `GET /projects` → `{projects:[{project_id,name,document_revision,updated_at,segment_count,reviewed_count,media}]}`.
- `POST /projects/import` multipart: `subtitle` required SRT/VTT, `media` optional; `name`, `language` (default unknown), `source_type` (default human_import), optional `source_note`, `audio_track` (ffprobe stream index; default first audio stream). → full project (201). Subtitle invalid times rejected (422); warnings surfaced as risk_flags.
- `GET /asr/status` → `{ready,engine,model,model_label,local:true,reasons}`. Local whisper.cpp and model must be installed separately; no API charges or runtime network downloads.
- `POST /transcriptions` multipart: `media` required (up to 20 GiB), optional `name`, `language=auto|th|en`, `audio_track` absolute ffprobe stream index → queued task (202). A local worker extracts the selected audio on the media timeline and runs original-language transcription.
- `GET /transcriptions` → `{tasks:[...]}` (latest 100); `GET /transcriptions/{task_id}` → task. Status: queued/running/completed/failed/cancelled; stage is display text, progress 0–100 is approximate, completed includes project_id.
- `POST /transcriptions/{task_id}/cancel` → task; idempotent for terminal tasks. A running process is stopped by the worker; final project creation and task completion are one SQLite transaction, so cancellation cannot publish half a project.
- Local ASR completion creates a separate project with track.source_type=`local_asr`, empty Chinese translations and every segment marked needs_review. Raw SRT, full engine JSON and original media are retained in its project directory. Existing projects are never overwritten. Incomplete tasks after worker restart require explicit resubmission.
- `GET /projects/{pid}` → full project.
- `PATCH /projects/{pid}/segments/{sid}` JSON `{base_revision,source_text?,zh_text?,start_ms?,end_ms?,review_status?}` → mutation response. Revision compares segment version. zh_text means explicit manual edit.
- `POST /projects/{pid}/split` JSON `{segment_id,base_revision,parts:[{start_ms,end_ms,source_text,zh_text?},...]}` → mutation response. At least 2 parts, inside parent range, nonoverlapping; texts are explicit user decisions. Result `{segment_ids}`.
- `POST /projects/{pid}/merge` JSON `{segment_ids:[...],base_revisions:{sid:revision,...},source_text,zh_text}` → mutation response. Must be consecutive live segments. Result `{segment_id}`.
- `POST /projects/{pid}/undo` JSON `{transaction_id?}` → mutation response. Defaults latest undoable transaction. Subsequent changed associated segments cause 409. Result transaction_id.
- `GET /projects/{pid}/media` → media with HTTP range support.
- `POST /projects/{pid}/preview` → mutation response; launches an H.264/AAC browser copy in the API background. `media.preview.status` is queued/running/ready/failed; `preview.url` points to `/api/projects/{pid}/preview-media`. Poll project detail. Startup marks interrupted conversions failed so they may be retried. Original media is never overwritten; first/middle/last sync, color and orientation need human review.
- `GET /projects/{pid}/preview-media` → range streaming once ready.
- `POST /projects/{pid}/relink` multipart `media`: accepts only stored sha256 matching media; 409 for mismatch. → mutation response.
- `GET /projects/{pid}/export?format=srt|vtt&mode=source|zh|bilingual&bundle=true|false` → download subtitle, or ZIP containing subtitle + manifest. Default bundle=false. Unreviewed drafts permitted; manifest says draft and includes revision/hashes/id mapping.
- `GET /projects/{pid}/backup` → portable ZIP with project.json and original subtitle (media excluded); imported media must be relinked. Includes full history and candidates.
- `GET /projects/{pid}/json` → project JSON attachment.
- `POST /projects/restore` multipart `file`: project JSON or ZIP. Creates a fresh project ID; stable segment IDs and revisions preserved. Media needs relink.
- `POST /projects/{pid}/reimport-preview` multipart `subtitle`, optional `manifest` → `{mode:'reference_track',reason,segments,differences}`. Never overwrites original; identity cannot be proven from edited SRT line numbers.
- `POST /projects/{pid}/reference-tracks` multipart `subtitle`, optional `language`, `source_type` → mutation response with new reference track IDs.
- `POST /backup` → SQLite consistent backup download.

AI API supplied by app/ai.py separately; front end can initially feature-detect `/api/ai/status`. Use server `risk_flags` for warnings. Basic flags: invalid_time, out_of_bounds, overlap, long_text, numbers, proper_name, unclear, missing_translation, source_changed, timing_changed, context_changed. These are heuristics, not language-quality findings.

## Python storage hooks for AI

`from .store import read_project, mutate_project, create_project, list_projects, Conflict, data_dir, now, uid`

`read_project(project_id)` returns a detached project dict; raises HTTPException 404.
`mutate_project(project_id, actor, reason, callback, undoable=True)` opens SQLite BEGIN IMMEDIATE, reads project, callback(project) mutates in place and returns operation result; raises to abort. It increments document_revision, computes segment changes, adds one revision record and persists atomically. Returns `{project, result}`. Candidate/task-only updates should use `undoable=False`. Do not mutate revisions directly. IDs via `uid()`; timestamps via `now()`. `refresh_risks(project)` in `.subtitles` recomputes flags. `.store.segment(project,sid)` finds a live segment; `.store.check_revision(segment,base_revision)` throws Conflict on mismatch. Preserve human edits by comparing request segment revision and source_revision, manual_zh and empty zh before fill. Increment segment revision for any changed segment.

## AI and terminology

- `GET /ai/status`: configuration readiness, missing configuration reasons, model, provider, limits and cost notice. Never returns a key. Configuration readiness does not mean real-service acceptance passed.
- `POST /projects/{pid}/ai/preview` `{segment_ids}` → `{document_revision,payload,configuration,notice}`. Payload includes frozen original text, existing Chinese, two neighboring cues on either side, glossary/version, base revisions and fingerprints. No media is sent.
- `POST /projects/{pid}/ai/jobs` `{segment_ids,base_document_revision,confirm_send:true}` → mutation result `{job_id}`. Requires configured key/model, explicit payment opt-in and matching preview document revision.
- `GET /projects/{pid}/ai/jobs` → `{jobs}`. States: queued/running/completed/failed/cancelled. `next_index` is committed cue count; total is `request.segments.length`.
- `POST /projects/{pid}/ai/jobs/{jid}/cancel` or `/retry` → mutation response. A cancelled batch cannot commit. Retry preserves committed progress; max 3 attempts per current batch. Interrupted in-flight requests need explicit retry because they may already have been billed.
- `POST /projects/{pid}/candidates/{cid}/accept` `{base_revision}` → mutation response. Candidate must be pending, not stale, and match current revision + fingerprint. Adoption marks Chinese as manually owned and needs_review. No automatic fill exists in this version.
- `POST /projects/{pid}/candidates/{cid}/reject` `{base_revision}` → mutation response, preserves history.
- `PUT /projects/{pid}/glossary` `{base_document_revision,entries:[{source,target,note}]}` → mutation response. Version increments; previous terms retained in `glossary_history`; current translations/candidates marked for recheck.

Project `jobs` contains frozen request and provider/model (no key). `candidates` contain `candidate_id,segment_id,job_id,base_revision,source_revision,fingerprint,source_text,zh_text,uncertainties,glossary_version,provider,model,created_at,status,stale`. Candidate status is pending/accepted/rejected; stale is independent. All external service output is treated as untrusted and ID-validated before whole-batch commit.

## Import/export and recovery boundaries

- UTF-8 and UTF-8 BOM supported. Invalid times and invalid encodings reject with block-specific messages. This is a plain subtitle text/time workbench: VTT positioning, STYLE/REGION/NOTE metadata and rich styling are not preserved as editable layout. Inline tag text is retained literally.
- Blank lines in edited text would make invalid SRT/VTT cues. Export removes empty lines only in the exported copy and records per-cue `normalizations`; saved human text is unchanged. Empty Chinese targets are omitted from Chinese-only output and mapped with `cue_number:null` plus the omission reason. If every target is empty, export returns 422.
- Source edits invalidate candidates and mark translated neighbors within two positions `context_changed`/`needs_review`. Manually editing targets invalidates pending context candidates; candidates are never automatically adopted.
- Undo checks segment versions and associated candidate snapshots atomically. Successful repeated undo rebases only legitimate undo expectations while retaining monotonically increasing versions. Active later edits remain conflicts.
- Restored projects get a new project ID, retaining stable subtitle IDs/history. Original and preview local paths are removed; both must be relinked/regenerated. Imported jobs are marked `restored:true`; queued/running tasks are cancelled and cannot auto-resume.
- Local origins are restricted to localhost/127.0.0.1 ports 5173, 8765 and optional validated `SUBTITLE_PORT`. Host headers are restricted to loopback. Use `--host 127.0.0.1` only.

Backend regression evidence: `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_workbench.py -q` verifies 14 tests including a real FFmpeg-generated two-second synthetic AV source, preview playback byte ranges, duration within 100 ms, selected audio index, unchanged original SHA-256, and interrupted-preview recovery. This does not assert human language quality or real-media visual/sync acceptance.

Media with more than one audio stream sets `requires_audio_preview:true` and exposes `audio_track_count`/`selected_audio_track`. The UI must block direct original playback for these files and use the selected-track preview, because HTML media cannot reliably select a particular input audio stream. Real synthetic dual-audio regression verifies the resulting single preview track decodes the explicitly selected 880 Hz stream, rather than the default 440 Hz stream. Relinking re-probes stream metadata after exact hash validation.
