export type Segment = {
  segment_id: string; start_ms: number; end_ms: number; source_text: string; zh_text: string;
  revision: number; source_revision: number; review_status: 'unreviewed' | 'needs_review' | 'reviewed';
  translation_stale: boolean; manual_zh: boolean; deleted: boolean; parent_ids: string[]; risk_flags: string[];
};
export type Media = { media_id: string; filename: string; sha256: string; duration_ms: number | null; selected_audio_track: number; requires_audio_preview?: boolean; audio_track_count?: number; status: string; url?: string; preview?: {status:string;url?:string;error?:string;verification?:string} };
export type Project = {
  project_id: string; name: string; document_revision: number; language: string; updated_at: string;
  media: Media | null; glossary_version: number; glossary: {source: string; target: string; note?: string}[];
  track: {source_type: string; filename: string; language: string; source_note?: string};
  segments: Segment[]; candidates: any[]; jobs: any[]; revisions: any[]; reference_tracks: any[];
};
export type ProjectSummary = { project_id: string; name: string; document_revision: number; segment_count: number; reviewed_count: number; updated_at: string; media: Media | null };
export type Draft = Pick<Segment, 'source_text' | 'zh_text' | 'review_status'> & {start: string; end: string};

export type TranscriptionStatus = {
  ready: boolean;
  engine?: string;
  model?: string;
  model_label?: string;
  reasons: string[];
  local: boolean;
};

export type TranscriptionTask = {
  task_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string;
  progress: number;
  filename: string;
  name: string;
  language: string;
  error?: string | null;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
};
