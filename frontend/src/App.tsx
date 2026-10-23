import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api, ApiError, Icon, Modal, parseTime, shortTime, timecode } from './ui';
import type { Draft, Project, ProjectSummary, Segment } from './types';
import { TranscriptionForm, TranscriptionTasks, useTranscriptions } from './Asr';

const statusLabels = { unreviewed: '未审阅', needs_review: '待复核', reviewed: '已审阅' };
const riskLabels: Record<string, string> = {invalid_time:'时间无效',out_of_bounds:'超出媒体',overlap:'时间重叠',long_text:'文本较长',numbers:'核对数字',proper_name:'核对专名',unclear:'原文存疑',missing_translation:'尚无译文',source_changed:'原文已变',timing_changed:'时间已变',context_changed:'上下文已变'};
const sourceLabels: Record<string, string> = {unknown:'来源未知',human_import:'人工导入',external_asr:'外部语音识别',local_asr:'本地语音识别',platform_regular:'平台普通字幕',platform_auto:'平台自动识别',auto_translation:'自动翻译（参考字幕）'};
const emptyDraft: Draft = { source_text: '', zh_text: '', start: '00:00:00.000', end: '00:00:00.000', review_status: 'unreviewed' };
const toDraft = (segment: Segment): Draft => ({source_text:segment.source_text,zh_text:segment.zh_text,start:timecode(segment.start_ms),end:timecode(segment.end_ms),review_status:segment.review_status});
const same = (a: unknown,b: unknown) => JSON.stringify(a) === JSON.stringify(b);
type Dialog = null | 'import' | 'settings' | 'shortcuts' | 'split' | 'merge' | 'export' | 'history' | 'glossary' | 'ai' | 'restore' | 'relink' | 'reimport';
type SaveStatus = 'saved' | 'dirty' | 'saving' | 'error' | 'conflict';

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const projectRef = useRef<Project | null>(null);
  const [selectedId, setSelectedId] = useState(''); const selectedRef = useRef('');
  const [draft, setDraft] = useState<Draft>(emptyDraft); const draftRef = useRef<Draft>(emptyDraft);
  const savedDraft = useRef<Draft>(emptyDraft);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('saved'); const saveStatusRef = useRef<SaveStatus>('saved');
  const saveInFlight = useRef<Promise<boolean> | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [importMode,setImportMode]=useState<'subtitle'|'transcribe'>('subtitle');
  const transcription=useTranscriptions();
  const completedTranscriptions=transcription.tasks.filter(t=>t.status==='completed'&&t.project_id).map(t=>t.project_id).sort().join(',');
  useEffect(()=>{if(completedTranscriptions)void refreshList().catch(()=>{});},[completedTranscriptions]);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState(''); const [filter, setFilter] = useState('all'); const [queuePage,setQueuePage]=useState(0);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [aiStatus, setAiStatus] = useState<any>(null); const [aiPreview, setAiPreview] = useState<any>(null);
  const [playing, setPlaying] = useState(false); const [loop, setLoop] = useState(true);
  const [margin, setMargin] = useState(0.3); const [speed, setSpeed] = useState(1); const [playhead, setPlayhead] = useState(0);
  const [mediaError, setMediaError] = useState(''); const [usePreview,setUsePreview] = useState(false);
  const loadEpoch=useRef(0);
  const video = useRef<HTMLVideoElement>(null);
  const [splitText, setSplitText] = useState({time:'',source1:'',source2:'',zh1:'',zh2:''});
  const [mergeText, setMergeText] = useState({source:'',zh:''});
  const [glossaryText, setGlossaryText] = useState('');
  const [reimportPreview, setReimportPreview] = useState<any>(null);
  const [conflictProject, setConflictProject] = useState<Project | null>(null);
  const sourceEditor = useRef<HTMLTextAreaElement>(null); const zhEditor = useRef<HTMLTextAreaElement>(null);
  const setSave = (status: SaveStatus) => {saveStatusRef.current = status; setSaveStatus(status);};
  const putProject = (p: Project) => {projectRef.current = p; setProject(p);};
  const putDraft = (d: Draft) => {draftRef.current = d; setDraft(d);};
  const live = useMemo(() => (project?.segments || []).filter(s => !s.deleted).sort((a,b) => a.start_ms - b.start_ms), [project]);
  const indexById=useMemo(()=>new Map(live.map((s,i)=>[s.segment_id,i])),[live]);
  const current = live.find(s => s.segment_id === selectedId);
  const currentIndex = live.findIndex(s => s.segment_id === selectedId);
  const reviewed = live.filter(s => s.review_status === 'reviewed').length;
  const needsReview = live.filter(s => s.review_status === 'needs_review').length;
  const candidates = (project?.candidates || []).filter(c => (c.segment_id || c.target_id) === selectedId && !['rejected','accepted'].includes(c.status));
  const filtered = useMemo(()=>live.filter(s => (!search || `${s.source_text}\n${s.zh_text}`.toLowerCase().includes(search.toLowerCase())) && (filter === 'all' || (filter === 'risk' ? s.risk_flags.some(r => r !== 'missing_translation') : s.review_status === filter))),[live,search,filter]);
  const pageCount=Math.max(1,Math.ceil(filtered.length/100));
  const pagedSegments=filtered.slice(Math.min(queuePage,pageCount-1)*100,(Math.min(queuePage,pageCount-1)+1)*100);
  useEffect(()=>{const index=filtered.findIndex(s=>s.segment_id===selectedId);setQueuePage(index>=0?Math.floor(index/100):0);},[selectedId,filtered]);
  const mustUsePreview=!!project?.media?.requires_audio_preview;
  const mediaBlocked=mustUsePreview&&project?.media?.status!=='missing'&&project?.media?.preview?.status!=='ready';
  const runningTasks = (project?.jobs || []).filter(t => ['queued','pending','waiting','running'].includes(t.status));

  async function refreshList() { const data = await api<{projects:ProjectSummary[]}>('/projects'); setProjects(data.projects); return data.projects; }
  function selectDraft(p: Project, id?: string) {
    const chosen = p.segments.find(s => !s.deleted && s.segment_id === id) || p.segments.find(s => !s.deleted);
    const next = chosen ? toDraft(chosen) : emptyDraft;
    selectedRef.current = chosen?.segment_id || ''; setSelectedId(selectedRef.current);
    putDraft(next); savedDraft.current = next; setSave('saved');
  }
  async function loadProject(id: string) {
    if (!await save()) return;
    const epoch=++loadEpoch.current;setBusy(true); setError('');
    try { const p = await api<Project>(`/projects/${id}`); if(epoch!==loadEpoch.current)return; putProject(p); selectDraft(p); setChecked(new Set()); setMediaError(''); setUsePreview(false); setPlaying(false); setPlayhead(0); localStorage.setItem('subtitle:last-project', id); }
    catch (e) { showError(e); } finally { setBusy(false); }
  }
  function showError(e: unknown) {setError(e instanceof Error ? e.message : String(e));}
  useEffect(() => {
    let active = true;
    Promise.allSettled([api<{projects:ProjectSummary[]}>('/projects'),api('/ai/status')]).then(results => {
      if (!active) return;
      const [ps,ai] = results;
      if (ps.status === 'fulfilled') {setProjects(ps.value.projects); const last = localStorage.getItem('subtitle:last-project'); if (last && ps.value.projects.some(p => p.project_id === last)) void loadProject(last);}
      else setError('本地服务未连接。请通过工作台启动脚本启动后重试。');
      if (ai.status === 'fulfilled') setAiStatus(ai.value);
      setLoading(false);
    });
    return () => {active = false;};
  }, []);
  useEffect(() => {if (!notice) return; const timer = setTimeout(() => setNotice(''), 5000); return () => clearTimeout(timer);}, [notice]);

  function edit(values: Partial<Draft>) {if(busy)return;putDraft({...draftRef.current,...values}); setSave(saveStatusRef.current==='conflict'?'conflict':'dirty');}
  async function save(): Promise<boolean> {
    if (saveInFlight.current) { if (!await saveInFlight.current) return false; return save(); }
    const p = projectRef.current; const id = selectedRef.current;
    if (!p || !id || same(draftRef.current, savedDraft.current)) return true;
    if (saveStatusRef.current === 'conflict') return false;
    const captured = {...draftRef.current}; const prior = savedDraft.current;
    const start = parseTime(captured.start), end = parseTime(captured.end);
    if (start === null || end === null || end <= start) {setSave('error'); setError('时间需使用 HH:MM:SS.mmm 格式，结束时间必须晚于开始时间。编辑内容仍保留在当前页面。'); return false;}
    const segment = p.segments.find(s => s.segment_id === id); if (!segment) return false;
    const body: Record<string, unknown> = {base_revision: segment.revision};
    for (const field of ['source_text','zh_text','review_status'] as const) if (captured[field] !== prior[field]) body[field] = captured[field];
    if (captured.start !== prior.start) body.start_ms = start;
    if (captured.end !== prior.end) body.end_ms = end;
    setSave('saving');
    const work = (async () => {
      try {
        const result = await api<{project:Project}>(`/projects/${p.project_id}/segments/${id}`,{method:'PATCH',body:JSON.stringify(body)});
        if (projectRef.current?.project_id === p.project_id) {
          putProject(result.project);
          if (selectedRef.current === id) {
            const persisted = result.project.segments.find(s => s.segment_id === id)!;
            savedDraft.current = toDraft(persisted);
            if (same(draftRef.current,captured)) {putDraft(toDraft(persisted)); setSave('saved');}
            else setSave('dirty');
          }
        }
        void refreshList().catch(() => {}); return true;
      } catch(e) {
        if (e instanceof ApiError && e.status === 409) {setSave('conflict'); setError('这条字幕已有新版本。你的编辑已保留，请比较当前已保存版本后处理冲突。'); api<Project>(`/projects/${p.project_id}`).then(setConflictProject).catch(() => {});}
        else {setSave('error'); showError(e);}
        return false;
      }
    })();
    saveInFlight.current = work;
    const result = await work; saveInFlight.current = null;
    if(result && projectRef.current?.project_id===p.project_id && selectedRef.current===id && !same(draftRef.current,savedDraft.current)) return save();
    return result;
  }
  useEffect(() => { if (saveStatus !== 'dirty') return; const timer = setTimeout(() => void save(), 650); return () => clearTimeout(timer); }, [draft,saveStatus]);
  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => {if (!same(draftRef.current,savedDraft.current) || saveStatusRef.current === 'saving') {e.preventDefault();}};
    window.addEventListener('beforeunload',onUnload); return () => window.removeEventListener('beforeunload',onUnload);
  }, []);
  useEffect(() => {
    if (!project || (!runningTasks.length && !['queued','running'].includes(project.media?.preview?.status||''))) return;
    const id = project.project_id;
    const timer = setInterval(async () => {
      try {
        const p = await api<Project>(`/projects/${id}`);
        if (projectRef.current?.project_id !== id || p.document_revision < projectRef.current.document_revision) return;
        if (saveStatusRef.current === 'saved' && !saveInFlight.current) {
          const next = p.segments.find(s => s.segment_id === selectedRef.current && !s.deleted);
          putProject(p);
          if (next && same(draftRef.current,savedDraft.current)) {const d = toDraft(next); savedDraft.current = d; putDraft(d);}
        } else {putProject({...projectRef.current, candidates:p.candidates, jobs:p.jobs, media:p.media});}
      } catch { /* A failed status poll must not replace local edits. */ }
    },2000);
    return () => clearInterval(timer);
  }, [project?.project_id, runningTasks.length, project?.media?.preview?.status]);
  useEffect(()=>{if(usePreview && project?.media?.preview?.status==='ready')setMediaError('');},[usePreview,project?.media?.preview?.status]);

  async function selectSegment(id: string, play = true) {
    if (!await save()) return;
    const p = projectRef.current; if (!p) return;
    const s = p.segments.find(s => s.segment_id === id); if (!s) return;
    selectedRef.current = id; setSelectedId(id); const d = toDraft(s); putDraft(d); savedDraft.current = d; setSave('saved');
    if (video.current) {video.current.currentTime = Math.max(0,s.start_ms / 1000 - margin); if (play) video.current.play().catch(() => {});}
  }
  const playCurrent = () => {
    if (!video.current || !current) return;
    if (playing) video.current.pause();
    else {video.current.currentTime = Math.max(0,current.start_ms / 1000 - margin); video.current.play().catch(() => setMediaError('浏览器无法播放此媒体。请检查文件编码或使用兼容的预览副本。'));}
  };
  function onTime() {
    const el = video.current; if (!el) return; setPlayhead(el.currentTime * 1000);
    if (current && !el.paused && el.currentTime >= current.end_ms / 1000 + margin) {if(loop)el.currentTime = Math.max(0,current.start_ms / 1000 - margin);else el.pause();}
  }
  async function mutate(path: string, body: unknown, pick?: string): Promise<any> {
    if (!await save()) return null;
    const p = projectRef.current; if (!p) return null;
    setBusy(true); setError('');
    try {const result = await api<{project:Project;result:any}>(`/projects/${p.project_id}${path}`,{method:'POST',body:JSON.stringify(body)}); putProject(result.project); selectDraft(result.project,pick || result.result?.segment_id || result.result?.segment_ids?.[0] || selectedRef.current); void refreshList().catch(()=>{}); return result;}
    catch(e) {showError(e); return null;} finally {setBusy(false);}
  }
  async function markReviewed() {if (!current || !await save()) return; edit({review_status:'reviewed'}); if (await save()) setNotice('当前字幕已标记为已审阅');}
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement; const typing = ['INPUT','TEXTAREA','SELECT'].includes(target.tagName) || target.isContentEditable;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {e.preventDefault(); void save(); return;}
      if (dialog || typing || e.altKey) return;
      if (e.code === 'Space') {e.preventDefault(); playCurrent();}
      else if (e.key === 'ArrowDown' || e.key === 'j') {e.preventDefault(); if (live[currentIndex+1]) void selectSegment(live[currentIndex+1].segment_id);}
      else if (e.key === 'ArrowUp' || e.key === 'k') {e.preventDefault(); if (live[currentIndex-1]) void selectSegment(live[currentIndex-1].segment_id);}
      else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {e.preventDefault(); void mutate('/undo',{});}
      else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {e.preventDefault(); void markReviewed();}
      else if (e.key.toLowerCase() === 'l') setLoop(v => !v);
      else if (e.key === '?') setDialog('shortcuts');
    }
    window.addEventListener('keydown',onKey); return () => window.removeEventListener('keydown',onKey);
  });
  const close = useCallback(() => {setDialog(null); setReimportPreview(null);},[]);
  function openTranscriptionCenter(){setImportMode('transcribe');setDialog('import');void transcription.refresh();}
  async function openTranscriptionProject(id:string){await loadProject(id);if(projectRef.current?.project_id===id)close();}
  async function importProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget); if (!await save()) return; const audio=data.get('audio_track');if(audio==='')data.delete('audio_track');const media = data.get('media'); if (media instanceof File && !media.size) data.delete('media');
    setBusy(true); setError('');
    try { const p = await api<Project>('/projects/import',{method:'POST',body:data}); putProject(p); selectDraft(p); setChecked(new Set()); setMediaError(''); localStorage.setItem('subtitle:last-project',p.project_id); await refreshList(); close(); setNotice('项目已导入，原始字幕与来源记录已保留'); }
    catch(e) {showError(e);} finally {setBusy(false);}
  }
  async function startSplit() {if (!current || !await save()) return; const s = projectRef.current!.segments.find(s=>s.segment_id===selectedRef.current)!; const index = sourceEditor.current?.selectionStart || 0; const zi = zhEditor.current?.selectionStart || 0; setSplitText({time:timecode(Math.round((s.start_ms+s.end_ms)/2)),source1:s.source_text.slice(0,index),source2:s.source_text.slice(index),zh1:s.zh_text.slice(0,zi),zh2:s.zh_text.slice(zi)}); setDialog('split');}
  async function startMerge() {if (!current || !live[currentIndex+1] || !await save()) return; const s=projectRef.current!.segments.find(s=>s.segment_id===selectedRef.current)!;const next=live[currentIndex+1]; setMergeText({source:s.source_text+'\n'+next.source_text,zh:[s.zh_text,next.zh_text].filter(Boolean).join('\n')}); setDialog('merge');}
  async function translate() {
    if (!await save() || !projectRef.current) return;
    const ids = checked.size ? [...checked].filter(id=>live.some(s=>s.segment_id===id)) : [selectedRef.current];
    if (!ids.length || !ids[0]) return;
    setBusy(true); setError('');
    try {const preview = await api(`/projects/${projectRef.current.project_id}/ai/preview`,{method:'POST',body:JSON.stringify({segment_ids:ids})}); setAiPreview({...preview, selected_ids:ids, requested_revision:preview.document_revision}); setDialog('ai');}
    catch(e){showError(e);}finally{setBusy(false);}
  }
  async function createJob() {
    const p = projectRef.current; if (!p || !aiPreview) return;
    setBusy(true);
    try {await api(`/projects/${p.project_id}/ai/jobs`,{method:'POST',body:JSON.stringify({segment_ids:aiPreview.selected_ids,base_document_revision:aiPreview.requested_revision,confirm_send:true})}); const next=await api<Project>(`/projects/${p.project_id}`);putProject(next);close();setNotice('翻译任务已提交。候选到达后需由你明确采用。');}
    catch(e){showError(e);}finally{setBusy(false);}
  }
  async function candidateAction(id:string,action:'accept'|'reject') {
    if (!await save()) return; const s=projectRef.current?.segments.find(s=>s.segment_id===selectedRef.current);if(!s)return;
    const result = await mutate(`/candidates/${id}/${action}`,{base_revision:s.revision}); if(result)setNotice(action==='accept'?'已采用候选，保留修改历史':'候选已归档，人工稿保留');
  }
  async function openGlossary(){if(!await save())return;setGlossaryText((projectRef.current?.glossary||[]).map(e=>[e.source,e.target,e.note||''].join('\t')).join('\n'));setDialog('glossary');}
  async function saveGlossary(event:FormEvent){event.preventDefault();const p=projectRef.current;if(!p)return;const entries=glossaryText.split('\n').filter(x=>x.trim()).map(line=>{const [source,target,...note]=line.split('\t');return {source:source?.trim(),target:target?.trim(),note:note.join('\t').trim()};});if(entries.some(e=>!e.source||!e.target)){setError('每行需有原文与译名两列，以 Tab 分隔。');return;}setBusy(true);try{const r=await api<{project:Project}>(`/projects/${p.project_id}/glossary`,{method:'PUT',body:JSON.stringify({base_document_revision:p.document_revision,entries})});putProject(r.project);selectDraft(r.project,selectedRef.current);close();setNotice('术语表已更新；受影响的候选需重新核对');}catch(e){showError(e);}finally{setBusy(false);}}
  async function fileAction(event:FormEvent<HTMLFormElement>, action:'restore'|'relink'|'reimport-preview'|'reference-tracks') {
    event.preventDefault();const data=new FormData(event.currentTarget); if(!await save())return;const p=projectRef.current;setBusy(true);setError('');
    try {const path=action==='restore'?'/projects/restore':`/projects/${p!.project_id}/${action}`;const manifest=data.get('manifest');if(manifest instanceof File&&!manifest.size)data.delete('manifest');const r=await api(path,{method:'POST',body:data});if(action==='reimport-preview'){setReimportPreview(r);return;}const next=action==='restore'?r:r.project;putProject(next);selectDraft(next,selectedRef.current);setMediaError('');localStorage.setItem('subtitle:last-project',next.project_id);await refreshList();close();setNotice(action==='restore'?'项目包已恢复为独立项目':action==='relink'?'媒体指纹校验通过，已重新关联':'外部字幕已保存为独立参考轨');}catch(e){showError(e);}finally{setBusy(false);}
  }
  async function download(path:string, fallback:string) {
    if(!await save())return;
    setBusy(true);
    try {
      const response=await fetch('/api'+path,{method:path==='/backup'?'POST':'GET'});
      if(!response.ok){const data=await response.json();throw new Error(typeof data.detail==='string'?data.detail:'导出失败');}
      const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;
      const disposition=response.headers.get('Content-Disposition')||'';const utf=disposition.match(/filename\*=UTF-8''([^;]+)/i);const basic=disposition.match(/filename="?([^";]+)/i);
      a.download=utf?decodeURIComponent(utf[1]):basic?.[1]||fallback;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);
      // Subtitle export records a new snapshot revision. Refresh before allowing
      // another document-level edit, without switching projects or replacing a draft.
      const exportedProjectId=path.match(/^\/projects\/([^/?]+)\/export(?:\?|$)/)?.[1];
      if(exportedProjectId){
        const latest=await api<Project>(`/projects/${exportedProjectId}`);
        const currentProject=projectRef.current;
        if(currentProject?.project_id===exportedProjectId && latest.document_revision>=currentProject.document_revision && saveStatusRef.current==='saved' && !saveInFlight.current && same(draftRef.current,savedDraft.current)){
          putProject(latest);
          const selected=latest.segments.find(s=>s.segment_id===selectedRef.current&&!s.deleted);
          if(selected){const next=toDraft(selected);savedDraft.current=next;putDraft(next);}
        }
        void refreshList().catch(()=>{});
      }
      setNotice('导出文件已生成');
    }catch(e){showError(e);}finally{setBusy(false);}
  }
  async function exportForm(e:FormEvent<HTMLFormElement>){e.preventDefault();const f=new FormData(e.currentTarget);await download(`/projects/${project!.project_id}/export?format=${f.get('format')}&mode=${f.get('mode')}&bundle=true`,`${project!.name}-subtitles.zip`);}

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e=>e.preventDefault()}><span className="brand-symbol"><i/><i/><i/><i/></span><span>字幕工作台</span></a>
      <button className="new-project" disabled={busy} onClick={()=>setDialog('import')}><Icon name="plus"/>新建项目</button>
      <div className="sidebar-label">项目 <span>{projects.length.toString().padStart(2,'0')}</span></div>
      <nav className="project-nav" aria-label="项目列表">{projects.map(p=><button key={p.project_id} className={`project-item ${project?.project_id===p.project_id?'active':''}`} onClick={()=>void loadProject(p.project_id)} disabled={busy}><Icon name="subtitle"/><span>{p.name}<small>{p.reviewed_count} / {p.segment_count} 已审阅</small></span>{project?.project_id===p.project_id&&<i/>}</button>)}{!projects.length&&<p className="sidebar-empty">暂无项目</p>}</nav>
      <div className="sidebar-tools"><button onClick={openTranscriptionCenter}><Icon name="sound"/>本地语音识别{transcription.tasks.some(t=>t.status==='queued'||t.status==='running')&&<span className="tiny-dot green"/>}</button><button onClick={()=>setDialog('restore')}><Icon name="upload"/>恢复项目包</button><button disabled={!project} onClick={()=>void openGlossary()}><Icon name="book"/>术语表{project&&<span>v{project.glossary_version}</span>}</button><button onClick={()=>setDialog('settings')}><Icon name="settings"/>服务与设置<span className={`tiny-dot ${aiStatus?.ready?'green':'amber'}`}/></button></div>

    </aside>
    <main className="main">
      <header className="topbar"><div className="breadcrumb"><Icon name="folder" size={16}/><span>工作空间</span><span className="slash">/</span><strong>{project?.name||'开始审阅'}</strong></div><div className="top-actions"><button className="icon-button" onClick={()=>setDialog('shortcuts')} aria-label="键盘快捷键" title="键盘快捷键"><Icon name="keyboard"/></button></div></header>
      <div className="content">
        {error&&<div className={`banner error ${saveStatus==='conflict'?'conflict':''}`} role="alert"><Icon name="alert"/><span>{error}</span>{saveStatus==='error'&&<button onClick={()=>void save()}>重试保存</button>}<button className="icon-button" aria-label="关闭提示" onClick={()=>setError('')}><Icon name="close" size={16}/></button></div>}
        {saveStatus==='conflict'&&<section className="conflict-panel"><h3>编辑冲突 · 当前输入尚未提交</h3><p>服务端已保存版本：</p><pre>{(()=>{const s=conflictProject?.segments.find(s=>s.segment_id===selectedId);return s?`版本 ${s.revision} · ${timecode(s.start_ms)} → ${timecode(s.end_ms)}\n原文：${s.source_text}\n中文：${s.zh_text||'（为空）'}`:'正在读取已保存版本…';})()}</pre><div className="button-row"><button onClick={()=>{const s=conflictProject?.segments.find(s=>s.segment_id===selectedId);if(s&&conflictProject){putProject(conflictProject);savedDraft.current=toDraft(s);setSave('dirty');setError('');setNotice('已载入最新版本作为基准，将保存你当前保留的输入');}}}>保留当前输入并基于新版本保存</button><button onClick={()=>{if(conflictProject){const local=JSON.stringify(draftRef.current);localStorage.setItem('subtitle:conflict-draft',local);putProject(conflictProject);selectDraft(conflictProject,selectedId);setError('');setNotice('已使用服务端版本；冲突输入已备份到本机浏览器');}}}>采用已保存版本</button></div></section>}
        <TranscriptionTasks controller={transcription} compact onOpen={id=>void openTranscriptionProject(id)} onShowAll={openTranscriptionCenter} currentProjectId={project?.project_id} opening={busy}/>
        {loading?<div className="loading-state"><span className="spinner"/>正在连接本地工作台…</div>:!project?<section className="welcome"><div className="welcome-mark"><Icon name="subtitle" size={42}/></div><h1>新建字幕项目</h1><p>导入字幕，或从视频、音频生成原语字幕。</p><button className="primary large" onClick={()=>setDialog('import')}><Icon name="plus"/>创建项目</button><span className="welcome-formats">视频 / 音频 <i/> SRT / VTT</span><button className="text-button" onClick={()=>setDialog('restore')}>恢复项目包 <Icon name="chevron" size={14}/></button></section>:<>
          <div className="project-heading"><div><h1>{project.name}</h1><div className="project-meta"><span>{project.language==='unknown'?'语言待确认':project.language.toUpperCase()} <span className="arrow">→</span> 简体中文</span><i/><span>{sourceLabels[project.track?.source_type]||project.track?.source_type||'来源未知'}</span><i/><span>{live.length} 条字幕</span></div></div><div className="heading-actions"><div className={`save-indicator ${saveStatus}`} role="status">{saveStatus==='saving'?<span className="spinner small"/>:<Icon name={saveStatus==='saved'?'check':saveStatus==='dirty'?'clock':'alert'} size={14}/>}{{saved:'所有更改已保存',dirty:'等待保存',saving:'正在保存…',error:'保存未完成',conflict:'版本冲突'}[saveStatus]}<small>v{project.document_revision}</small></div><button onClick={()=>setDialog('export')} disabled={busy}><Icon name="download"/>导出字幕</button></div></div>
          <section className="review-grid">
            <div className="player-panel panel"><div className="panel-heading"><span><Icon name="play" size={14}/>素材预览</span><button className="text-button" onClick={()=>setDialog('relink')} disabled={!project.media}><Icon name="link" size={13}/>{project.media?'关联媒体':'纯字幕项目'}</button>{project.media?.preview?.status==='ready'&&!mustUsePreview&&<select aria-label="媒体版本" value={usePreview?'preview':'original'} onChange={e=>{setUsePreview(e.target.value==='preview');setMediaError('');}}><option value="original">原媒体</option><option value="preview">兼容预览 · 待核对同步</option></select>}</div><div className={`player-stage ${!project.media?'no-media':''}`}>{project.media&&project.media.status!=='missing'&&!mediaBlocked?<video ref={video} key={project.project_id+project.media.media_id} src={`/api/projects/${project.project_id}/${(usePreview||mustUsePreview)&&project.media.preview?.status==='ready'?'preview-media':'media'}`} playsInline preload="metadata" onTimeUpdate={onTime} onPlay={()=>setPlaying(true)} onPause={()=>setPlaying(false)} onEnded={()=>{setPlaying(false);if(loop&&current&&video.current){video.current.currentTime=Math.max(0,current.start_ms/1000-margin);video.current.play().catch(()=>{});}}} onError={()=>setMediaError('媒体暂时无法播放。可重新关联原文件，或检查是否为浏览器支持的编码。')} onLoadedMetadata={()=>{if(video.current)video.current.playbackRate=speed;}}/>:<div className="media-placeholder"><div className="media-glyph"><Icon name={project.media?'link':'sound'} size={30}/></div><strong>{mediaBlocked?'多音轨媒体':project.media?'媒体需要重新关联':'纯字幕项目'}</strong><p>{mediaBlocked?`请生成所选音轨预览（轨道 #${project.media?.selected_audio_track}），确保试听对应音轨。`:project.media?'关联原媒体后可试听。':'可直接编辑和导出字幕。'}</p>{mediaBlocked&&project.media?.preview?.status==='failed'&&<p>{project.media.preview.error}</p>}{mediaBlocked?<button disabled={busy||['queued','running'].includes(project.media?.preview?.status||'')} onClick={()=>{setUsePreview(true);void mutate('/preview',{});}}>{['queued','running'].includes(project.media?.preview?.status||'')?'正在生成所选音轨预览…':'生成所选音轨预览'}</button>:project.media&&<button onClick={()=>setDialog('relink')}>重新关联原媒体</button>}</div>}{project.media&&current&&!mediaError&&!mediaBlocked&&playhead>=current.start_ms&&playhead<current.end_ms&&<div className="subtitle-overlay"><div>{draft.zh_text||draft.source_text}</div>{draft.zh_text&&<small>{draft.source_text}</small>}</div>}{mediaError&&<div className="media-warning"><Icon name="alert"/><p>{mediaError}</p><button disabled={busy||['queued','running'].includes(project.media?.preview?.status||'')} onClick={()=>{setUsePreview(true);void mutate('/preview',{});}}>{['queued','running'].includes(project.media?.preview?.status||'')?'正在生成兼容预览…':'生成兼容预览'}</button>{project.media?.preview?.status==='failed'&&<small>{project.media.preview.error}</small>}</div>}</div><div className="player-bottom"><div className="scrubber"><span style={{width:`${Math.min(100,project.media?.duration_ms?playhead/project.media.duration_ms*100:0)}%`}}/><input type="range" aria-label="媒体播放位置" min="0" max={project.media?.duration_ms||1} value={Math.min(playhead,project.media?.duration_ms||1)} disabled={!project.media||!!mediaError||mediaBlocked} onChange={e=>{if(video.current)video.current.currentTime=+e.target.value/1000;setPlayhead(+e.target.value);}}/></div><div className="player-controls"><div className="transport"><button className="icon-button" disabled={currentIndex<=0} onClick={()=>void selectSegment(live[currentIndex-1].segment_id)} aria-label="上一条"><Icon name="prev" size={17}/></button><button className="play-button" onClick={playCurrent} disabled={!project.media||!!mediaError||mediaBlocked} aria-label={playing?'暂停':'播放当前句'}><Icon name={playing?'pause':'play'} size={16}/></button><button className="icon-button" disabled={currentIndex<0||currentIndex>=live.length-1} onClick={()=>void selectSegment(live[currentIndex+1].segment_id)} aria-label="下一条"><Icon name="chevron" size={17}/></button><span className="time-display">{shortTime(playhead)} <span>/ {shortTime(project.media?.duration_ms||0)}</span></span></div><div className="playback-options"><button className={`icon-button ${loop?'active-text':''}`} onClick={()=>setLoop(v=>!v)} aria-label="循环当前句" aria-pressed={loop} title="循环当前句 (L)"><Icon name="loop" size={16}/></button><select aria-label="播放速度" value={speed} onChange={e=>{setSpeed(+e.target.value);if(video.current)video.current.playbackRate=+e.target.value;}}>{[0.5,0.75,1,1.25,1.5].map(v=><option key={v} value={v}>{v}×</option>)}</select></div></div><div className="player-context"><span><i className={loop?'green':'gray'}/>{loop?'逐句循环':'单句播放'}</span><label>前后余量 <select value={margin} onChange={e=>setMargin(+e.target.value)} aria-label="播放前后余量">{[0,0.3,0.5,1,2].map(v=><option key={v} value={v}>{v.toFixed(1)} s</option>)}</select></label><span className="filename" title={project.media?`${project.media.filename} · 音轨 ${project.media.selected_audio_track}`:''}>{project.media?.filename||'未绑定媒体'}</span></div></div></div>
            <div className="editor-panel panel"><div className="panel-heading"><span>当前字幕 <b className="cue-number">{String(currentIndex+1).padStart(3,'0')}</b><span className="muted">/ {String(live.length).padStart(3,'0')}</span></span><button className="text-button" disabled={!current||busy} onClick={()=>setDialog('history')}><Icon name="history" size={14}/>修订</button></div>{current?<><div className="cue-timing"><label><span>入点</span><input aria-label="字幕开始时间" value={draft.start} disabled={busy} onChange={e=>edit({start:e.target.value})} spellCheck={false}/></label><span className="timing-dash">—</span><label><span>出点</span><input aria-label="字幕结束时间" value={draft.end} disabled={busy} onChange={e=>edit({end:e.target.value})} spellCheck={false}/></label><span className="duration">{((current.end_ms-current.start_ms)/1000).toFixed(2)} s</span></div><div className="editor-source"><div className="field-heading"><label htmlFor="source-editor">原文 <span>{project.language.toUpperCase()}</span></label></div><textarea ref={sourceEditor} id="source-editor" readOnly={busy} value={draft.source_text} onChange={e=>edit({source_text:e.target.value})} placeholder="输入原语字幕" spellCheck={false}/></div><div className="editor-translation"><div className="field-heading"><label htmlFor="zh-editor">中文译文 <span>ZH</span></label><span>{draft.zh_text.length} 字</span></div><textarea ref={zhEditor} id="zh-editor" readOnly={busy} value={draft.zh_text} onChange={e=>edit({zh_text:e.target.value})} placeholder="输入中文译文" spellCheck={false}/></div><div className="editor-footer"><div className="edit-tools"><button className="icon-button" title="拆分字幕" aria-label="拆分字幕" disabled={busy} onClick={()=>void startSplit()}><Icon name="split" size={16}/></button><button className="icon-button" title="与下一条合并" aria-label="与下一条合并" disabled={busy||currentIndex>=live.length-1} onClick={()=>void startMerge()}><Icon name="merge" size={16}/></button><button className="icon-button" title="撤销上次项目修改" aria-label="撤销上次项目修改" disabled={busy} onClick={()=>void mutate('/undo',{})}><Icon name="undo" size={16}/></button><span className="divider"/><select aria-label="审阅状态" disabled={busy} value={draft.review_status} onChange={e=>edit({review_status:e.target.value as Draft['review_status']})}>{Object.entries(statusLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></div><button className="review-button" onClick={()=>void markReviewed()} disabled={busy}><Icon name="check" size={15}/>确认已审</button></div></>:<div className="small-empty">该项目暂无可编辑字幕</div>}</div>
          </section>
          <section className="ai-panel panel"><div className="ai-title"><span className="ai-icon"><Icon name="book" size={17}/></span><div><strong>中文翻译</strong><span>{candidates.length?`${candidates.length} 个待处理`:'暂无候选'}</span></div><span className={`service-status ${aiStatus?.ready?'ready':''}`}><i/>{aiStatus?.ready?'已配置':'未配置'}</span></div><div className="ai-copy">{candidates.length?'对比后采用候选':aiStatus?.ready?'翻译当前句或所选字幕':'配置服务后可生成中文候选'}</div><button className="ai-action" onClick={()=>aiStatus?.ready?void translate():setDialog('settings')} disabled={busy||!current}><Icon name="book" size={15}/>{aiStatus?.ready?(checked.size?`翻译所选 ${checked.size} 条`:'生成译文'):'配置翻译服务'}<Icon name="chevron" size={14}/></button></section>
          {candidates.length>0&&<div className="candidate-list">{candidates.map(c=><article key={c.candidate_id} className="candidate"><div><span className="candidate-meta">翻译候选 · {c.model||'翻译服务'}</span><p>{c.zh_text||c.text||c.translation||c.content||'（候选无文本）'}</p>{(c.stale||c.status==='stale')&&<span className="risk-chip">版本已变化，需重新核对</span>}{(c.uncertainties||c.issues||c.warnings||[]).length>0&&<small>{(c.uncertainties||c.issues||c.warnings).join(' · ')}</small>}</div><div className="button-row"><button onClick={()=>void candidateAction(c.candidate_id,'reject')} disabled={busy}>暂不采用</button><button className="primary" onClick={()=>void candidateAction(c.candidate_id,'accept')} disabled={busy}><Icon name="check" size={14}/>采用候选</button></div></article>)}</div>}
          {(project.jobs||[]).slice(-3).map(t=><div className={`task-line ${t.status}`} key={t.task_id||t.job_id}><Icon name={['failed','cancelled'].includes(t.status)?'alert':'book'} size={14}/><span>翻译任务 · {({queued:'等待中',waiting:'等待中',pending:'等待中',running:'处理中',completed:'已完成',failed:'失败',cancelled:'已取消'} as Record<string,string>)[t.status]||t.status}</span><small>{t.error||t.message||`${t.next_index??0} / ${(t.request?.segments||[]).length} 条`}</small>{['queued','waiting','pending','running'].includes(t.status)&&<button className="text-button" onClick={()=>void mutate(`/ai/jobs/${t.task_id||t.job_id}/cancel`,{})}>取消任务</button>}{['failed','cancelled'].includes(t.status)&&<button className="text-button" onClick={()=>void mutate(`/ai/jobs/${t.task_id||t.job_id}/retry`,{})}>重试</button>}</div>)}
          <section className="queue panel"><div className="queue-heading"><div className="queue-title"><h2>审阅队列</h2><span>{reviewed} / {live.length} 已完成</span><div className="progress-track"><span style={{width:`${live.length?reviewed/live.length*100:0}%`}}/></div></div><div className="queue-actions"><label className="search"><Icon name="search" size={15}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="搜索原文或译文" aria-label="搜索原文或译文"/>{search&&<button className="icon-button" onClick={()=>setSearch('')} aria-label="清空搜索"><Icon name="close" size={12}/></button>}</label><button className="icon-button" title="外部字幕回导" aria-label="外部字幕回导" onClick={()=>setDialog('reimport')}><Icon name="upload" size={17}/></button></div></div><div className="queue-filters">{[['all','全部',live.length],['unreviewed','未审阅',live.length-reviewed-needsReview],['needs_review','待复核',needsReview],['reviewed','已审阅',reviewed],['risk','风险提示',live.filter(s=>s.risk_flags.some(r=>r!=='missing_translation')).length]].map(([key,label,count])=><button key={key} className={filter===key?'active':''} onClick={()=>setFilter(String(key))}>{label}<span>{count}</span></button>)}<span className="queue-hint"><kbd>↑</kbd><kbd>↓</kbd> 切换字幕</span></div><div className="table-wrap"><table><thead><tr><th className="check-cell"><input type="checkbox" aria-label="选择筛选结果全部字幕" checked={!!filtered.length&&filtered.every(s=>checked.has(s.segment_id))} onChange={e=>setChecked(e.target.checked?new Set(filtered.map(s=>s.segment_id)):new Set())}/></th><th className="index-cell">#</th><th className="time-cell">时间轴</th><th>原文</th><th>中文译文</th><th className="status-cell">审阅状态</th></tr></thead><tbody>{pagedSegments.map(s=><tr key={s.segment_id} className={selectedId===s.segment_id?'selected':''} onClick={()=>void selectSegment(s.segment_id)} tabIndex={0} onKeyDown={e=>{if(e.key==='Enter'&&!e.metaKey&&!e.ctrlKey){e.preventDefault();void selectSegment(s.segment_id);}}} aria-selected={selectedId===s.segment_id}><td onClick={e=>e.stopPropagation()}><input type="checkbox" aria-label={`选择字幕 ${(indexById.get(s.segment_id)??0)+1}`} checked={checked.has(s.segment_id)} onChange={e=>setChecked(prev=>{const next=new Set(prev);if(e.target.checked)next.add(s.segment_id);else next.delete(s.segment_id);return next;})}/></td><td className="index-cell">{String((indexById.get(s.segment_id)??0)+1).padStart(2,'0')}</td><td className="time-cell"><span>{timecode(s.start_ms)}</span><small>{timecode(s.end_ms)}</small></td><td className="cue-text">{s.source_text}</td><td className={`cue-text ${!s.zh_text?'untranslated':''}`}>{s.zh_text||'等待翻译'}{s.translation_stale&&<span className="inline-risk">原文已变</span>}</td><td className="status-cell"><span className={`status ${s.review_status}`}><i/>{statusLabels[s.review_status]}</span>{s.risk_flags.filter(r=>r!=='missing_translation').length>0&&<span className="risk-note" title={s.risk_flags.map(r=>riskLabels[r]||r).join(' · ')}><Icon name="alert" size={11}/>{riskLabels[s.risk_flags.find(r=>r!=='missing_translation')!]||'需核对'}</span>}</td></tr>)}</tbody></table>{!filtered.length&&<div className="small-empty">没有符合条件的字幕<button className="text-button" onClick={()=>{setSearch('');setFilter('all');}}>清除筛选</button></div>}</div><footer className="queue-footer"><span>{checked.size?`已选择 ${checked.size} 条字幕`:`显示 ${filtered.length} 条字幕`}<span className="muted"> · 时间基于当前媒体</span></span><div className="pagination"><button className="icon-button" aria-label="上一页字幕" disabled={queuePage===0} onClick={()=>setQueuePage(v=>Math.max(0,v-1))}><Icon name="prev" size={12}/></button><span>{Math.min(queuePage,pageCount-1)+1} / {pageCount}</span><button className="icon-button" aria-label="下一页字幕" disabled={queuePage>=pageCount-1} onClick={()=>setQueuePage(v=>Math.min(pageCount-1,v+1))}><Icon name="chevron" size={12}/></button></div></footer></section>
          {project.reference_tracks?.length>0&&<section className="reference-list panel"><h3>外部参考轨 <span>{project.reference_tracks.length}</span></h3>{project.reference_tracks.map((track,i)=><details key={track.track_id||i}><summary>{track.filename||track.name||`参考轨 ${i+1}`} · {(track.segments||[]).length} 条</summary><div className="reference-cues">{(track.segments||[]).map((s:any,j:number)=><p key={s.segment_id||j}><span>{timecode(s.start_ms)} → {timecode(s.end_ms)}</span>{s.source_text||s.text}</p>)}</div></details>)}</section>}<footer className="page-footer"><button className="text-button" onClick={()=>setDialog('shortcuts')}>键盘快捷键 <kbd>?</kbd></button></footer>
        </>}
      </div>
    </main>
    {notice&&<div className="toast" role="status"><Icon name="check" size={16}/>{notice}</div>}
    {dialog&&<Modal title={{import:'创建字幕项目',settings:'设置',shortcuts:'键盘快捷键',split:'拆分当前字幕',merge:'与下一条合并',export:'导出与交付',history:'修订记录',glossary:'项目术语表',ai:'确认翻译请求',restore:'恢复项目包',relink:'重新关联媒体',reimport:'外部字幕回导'}[dialog]} close={close} wide={['split','merge','history','ai','reimport'].includes(dialog)}>
      {error&&<div className="modal-error" role="alert"><Icon name="alert" size={15}/>{error}</div>}
      {dialog==='import'&&<><div className="import-tabs" role="tablist" aria-label="创建项目方式"><button type="button" role="tab" aria-selected={importMode==='subtitle'} className={importMode==='subtitle'?'active':''} onClick={()=>setImportMode('subtitle')}><Icon name="subtitle" size={16}/>已有字幕</button><button type="button" role="tab" aria-selected={importMode==='transcribe'} className={importMode==='transcribe'?'active':''} onClick={()=>{setImportMode('transcribe');void transcription.refresh();}}><Icon name="sound" size={16}/>从视频识别</button></div>{importMode==='subtitle'?<form onSubmit={importProject}><p className="modal-intro">导入原语字幕，可同时关联视频或音频。</p><details className="import-guidance"><summary>没有原语字幕，或只有机翻字幕？</summary><p>没有字幕：选择「从视频识别」。机翻字幕可在项目中通过「外部字幕回导」加入参考轨。</p><p>也可使用 Subtitle Edit 的 Video → Speech to text，导出 UTF-8 SRT，再选择「外部语音识别」来源导入。</p></details><label className="form-field">项目名称<input name="name" placeholder="输入项目名称" maxLength={160}/></label><label className="file-picker"><Icon name="upload" size={25}/><strong>原语字幕 <span>必选</span></strong><span>SRT / VTT</span><input name="subtitle" type="file" accept=".srt,.vtt" required/></label><label className="form-field">视频或音频 <span className="muted">可选</span><input name="media" type="file" accept="video/*,audio/*,.mkv,.mov,.mp4,.mp3,.wav,.m4a"/></label><div className="form-grid"><label className="form-field">字幕语言<select name="language" defaultValue="unknown"><option value="unknown">尚未确认</option><option value="th">泰语</option><option value="en">英语</option><option value="th-en">泰英混合</option><option value="zh-Hans">简体中文</option><option value="ja">日语</option><option value="ko">韩语</option></select></label><label className="form-field">来源类型<select name="source_type" defaultValue="unknown">{Object.entries(sourceLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label></div><label className="form-field">选定音轨索引 <span className="muted">可选，默认首条音轨</span><input name="audio_track" type="number" min="0" step="1" placeholder="留空使用首条音轨"/></label><label className="form-field">来源说明<input name="source_note" placeholder="可填写来源网址、识别工具或中间语说明"/></label><p className="fine-print">来源不确定时选择「来源未知」。人工导入不代表人工撰写。</p><div className="modal-actions"><button type="button" onClick={close}>取消</button><button className="primary" disabled={busy} type="submit">{busy?'正在导入…':'创建项目'}<Icon name="chevron" size={15}/></button></div></form>:<><TranscriptionForm controller={transcription} onSubmitted={()=>setNotice('本地转写任务已提交，可继续审阅当前项目')}/><TranscriptionTasks controller={transcription} onOpen={id=>void openTranscriptionProject(id)} currentProjectId={project?.project_id} opening={busy}/><p className="asr-background-note">任务完成后，点击「打开项目」开始审阅。</p></>}</>}
      {dialog==='settings'&&<div className="settings-content"><section className="settings-section"><div className="settings-section-heading"><Icon name="sound" size={17}/><h3>本地语音识别</h3><span className={`setting-state ${transcription.status?.ready?'ready':''}`}>{transcription.loading?'检查中':transcription.status?.ready?'可用':'未就绪'}</span></div><div className="settings-row"><span>模型</span><strong>{transcription.status?.model_label||transcription.status?.model||'尚未配置'}</strong></div><button className="settings-link" onClick={openTranscriptionCenter}>从视频或音频识别字幕<Icon name="chevron" size={15}/></button></section><section className="settings-section"><div className="settings-section-heading"><Icon name="book" size={17}/><h3>翻译服务</h3><span className={`setting-state ${aiStatus?.ready?'ready':''}`}>{aiStatus?.ready?'已配置':'未配置'}</span></div><div className="settings-details"><span>服务</span><strong>{aiStatus?.provider||'OpenAI 兼容服务'}</strong><span>模型</span><strong>{aiStatus?.model||'尚未选择'}</strong></div><p className="settings-note">在本地配置文件中设置密钥、模型和费用授权，重启后刷新。</p>{aiStatus?.reasons?.length>0&&<details className="settings-config"><summary>查看配置状态</summary><ul>{aiStatus.reasons.map((reason:string)=><li key={reason}>{reason}</li>)}</ul></details>}<button className="settings-link" onClick={()=>api('/ai/status').then(s=>{setAiStatus(s);setNotice('服务状态已刷新');}).catch(showError)}><Icon name="refresh" size={14}/>刷新服务状态</button></section><section className="settings-section"><div className="settings-section-heading"><Icon name="folder" size={17}/><h3>数据备份</h3></div><div className="settings-backup"><p>备份全部项目与修订记录。</p><button onClick={()=>void download('/backup','subtitle-workbench-backup.sqlite')} disabled={busy}><Icon name="download" size={14}/>备份数据库</button></div></section></div>}

      {dialog==='shortcuts'&&<><p className="modal-intro">在输入框内保留常规文字编辑行为；保存快捷键始终可用。</p><div className="shortcut-list">{[['Space','播放 / 暂停当前句'],['↑ / K','上一条字幕'],['↓ / J','下一条字幕'],['L','切换逐句循环'],['⌘ S','立即保存'],['⌘ Enter','标记当前句已审阅'],['⌘ Z','撤销上次项目操作（输入框外）'],['?','打开快捷键说明'],['Esc','关闭弹窗']].map(([key,label])=><div key={key}><span>{label}</span><kbd>{key}</kbd></div>)}</div></>}
      {dialog==='split'&&current&&<form onSubmit={async e=>{e.preventDefault();const split=parseTime(splitText.time);if(split===null||split<=current.start_ms||split>=current.end_ms){setError('拆分点必须位于当前字幕的开始与结束之间。');return;}const r=await mutate('/split',{segment_id:current.segment_id,base_revision:current.revision,parts:[{start_ms:current.start_ms,end_ms:split,source_text:splitText.source1,zh_text:splitText.zh1},{start_ms:split,end_ms:current.end_ms,source_text:splitText.source2,zh_text:splitText.zh2}]});if(r){close();setNotice('字幕已拆分，原条目保留在修订历史中');}}}><p className="modal-intro">确认两部分文字与拆分时间。默认时间为中点，需试听校准。</p><label className="form-field">拆分时间<input value={splitText.time} onChange={e=>setSplitText({...splitText,time:e.target.value})}/></label><div className="form-grid">{[1,2].map(n=><div key={n}><h3>第 {n} 部分</h3><label className="form-field">原文<textarea required value={splitText[`source${n}` as 'source1'|'source2']} onChange={e=>setSplitText({...splitText,[`source${n}`]:e.target.value})}/></label><label className="form-field">中文<textarea value={splitText[`zh${n}` as 'zh1'|'zh2']} onChange={e=>setSplitText({...splitText,[`zh${n}`]:e.target.value})}/></label></div>)}</div><div className="modal-actions"><button type="button" onClick={close}>取消</button><button className="primary" disabled={busy}>确认拆分</button></div></form>}
      {dialog==='merge'&&current&&live[currentIndex+1]&&<form onSubmit={async e=>{e.preventDefault();const next=live[currentIndex+1];const r=await mutate('/merge',{segment_ids:[current.segment_id,next.segment_id],base_revisions:{[current.segment_id]:current.revision,[next.segment_id]:next.revision},source_text:mergeText.source,zh_text:mergeText.zh});if(r){close();setNotice('相邻字幕已合并，可通过撤销恢复');}}}><p className="modal-intro">合并第 {currentIndex+1} 与第 {currentIndex+2} 条。请确认合并后的完整文字。</p><div className="info-box mono">{timecode(current.start_ms)} → {timecode(live[currentIndex+1].end_ms)}</div><label className="form-field">合并后的原文<textarea required value={mergeText.source} onChange={e=>setMergeText({...mergeText,source:e.target.value})}/></label><label className="form-field">合并后的中文<textarea value={mergeText.zh} onChange={e=>setMergeText({...mergeText,zh:e.target.value})}/></label><div className="modal-actions"><button type="button" onClick={close}>取消</button><button className="primary" disabled={busy}>确认合并</button></div></form>}
      {dialog==='export'&&project&&<><div className="export-summary"><h3>{project.name}</h3><p>{reviewed} / {live.length} 条已审阅 · 文档版本 {project.document_revision}</p></div>{reviewed<live.length&&<div className="info-box amber-box"><Icon name="alert" size={16}/>包含未审阅字幕，将标记为草稿。</div>}<form onSubmit={exportForm}><div className="form-grid"><label className="form-field">导出内容<select name="mode"><option value="bilingual">双语 · 原文 + 中文</option><option value="zh">仅中文</option><option value="source">仅原文</option></select></label><label className="form-field">字幕格式<select name="format"><option value="srt">SRT</option><option value="vtt">WebVTT</option></select></label></div><p className="fine-print">包含字幕与版本清单，使用导出时的项目版本。</p><button className="primary full-width" disabled={busy}><Icon name="download" size={16}/>导出字幕与来源清单</button></form><div className="export-package"><div><strong>可恢复项目包</strong><p>包含字幕、修订、候选与术语，不包含媒体。</p></div><button disabled={busy} onClick={()=>void download(`/projects/${project.project_id}/backup`,`${project.name}-project.zip`)}>下载项目包</button></div></>}
      {dialog==='history'&&<><p className="modal-intro">查看修改记录，或撤销最近一次操作。</p><div className="history-list">{[...(project?.revisions||[])].reverse().slice(0,80).map((r,i)=><article key={r.revision_id||r.transaction_id||i}><div><strong>{r.reason||r.operation||'项目修改'}</strong><small>{r.actor||'human'} · {r.created_at||r.timestamp||r.at}</small></div><span className="mono">{(r.transaction_id||'').slice(0,8)}</span><details><summary>查看修改内容</summary><pre>{JSON.stringify(r.changes||r,null,2)}</pre></details></article>)}{!project?.revisions?.length&&<div className="small-empty">尚无修订记录</div>}</div><div className="modal-actions"><button disabled={busy} onClick={()=>void mutate('/undo',{})}><Icon name="undo" size={15}/>撤销最近可撤销操作</button></div></>}
      {dialog==='glossary'&&<form onSubmit={saveGlossary}><p className="modal-intro">每行一条，以 Tab 分隔原文、中文与备注。支持从表格粘贴。</p><label className="form-field">术语 · 版本 {project?.glossary_version}<textarea className="glossary-editor" value={glossaryText} onChange={e=>setGlossaryText(e.target.value)} placeholder={'原文\t中文译名\t备注（可选）'} onKeyDown={e=>{if(e.key==='Tab'){e.preventDefault();const t=e.currentTarget;const next=glossaryText.slice(0,t.selectionStart)+'\t'+glossaryText.slice(t.selectionEnd);const pos=t.selectionStart+1;setGlossaryText(next);requestAnimationFrame(()=>{t.selectionStart=t.selectionEnd=pos;});}}}/></label><p className="fine-print">更新后，相关旧候选需重新核对。</p><div className="modal-actions"><button type="button" onClick={close}>取消</button><button className="primary" disabled={busy}>保存术语表</button></div></form>}
      {dialog==='ai'&&aiPreview&&<><p className="modal-intro">发送 {aiPreview.selected_ids.length} 条字幕、上下文及术语表。不上传媒体，调用可能产生费用。</p><div className="info-box">服务：{aiStatus?.provider||'已配置服务'} · 模型：{aiStatus?.model||'配置模型'}。结果保存为待采用候选。</div><details open className="request-preview"><summary>查看完整请求</summary><pre>{JSON.stringify(aiPreview.payload||aiPreview.request||aiPreview,null,2)}</pre></details><div className="modal-actions"><button onClick={close}>取消</button><button className="primary" disabled={busy||!aiStatus?.ready} onClick={()=>void createJob()}><Icon name="book" size={15}/>确认并发送</button></div></>}
      {dialog==='restore'&&<form onSubmit={e=>void fileAction(e,'restore')}><p className="modal-intro">导入 ZIP 或 JSON，恢复为独立项目并保留修订记录。</p><label className="file-picker"><Icon name="upload" size={25}/><strong>选择项目包</strong><input name="file" type="file" accept=".zip,.json" required/></label><div className="modal-actions"><button type="button" onClick={close}>取消</button><button className="primary" disabled={busy}>{busy?'正在恢复…':'恢复项目'}</button></div></form>}
      {dialog==='relink'&&<form onSubmit={e=>void fileAction(e,'relink')}><p className="modal-intro">选择原媒体文件，指纹一致后重新关联。</p><div className="info-box"><strong>{project?.media?.filename}</strong><code>{project?.media?.sha256}</code></div><label className="form-field">原媒体文件<input type="file" name="media" required accept="video/*,audio/*,.mkv,.mov,.mp4"/></label><div className="modal-actions"><button type="button" onClick={close}>取消</button><button className="primary" disabled={busy}>校验并关联</button></div></form>}
      {dialog==='reimport'&&<form onSubmit={e=>void fileAction(e,reimportPreview?'reference-tracks':'reimport-preview')}><p className="modal-intro">检查字幕差异后保存为参考轨，不覆盖当前字幕。</p><label className="form-field">外部字幕<input name="subtitle" type="file" accept=".srt,.vtt" required onChange={()=>setReimportPreview(null)}/></label><label className="form-field">导出清单 <span className="muted">可选</span><input name="manifest" type="file" accept=".json" onChange={()=>setReimportPreview(null)}/></label>{reimportPreview&&<div className="request-preview"><div className="info-box">{reimportPreview.reason||'当前字幕无法验证完整身份映射，将作为独立参考轨保存。'}</div><h3>差异预览 · {reimportPreview.segments?.length||0} 条字幕</h3><pre>{JSON.stringify(reimportPreview.differences||reimportPreview.segments,null,2)}</pre></div>}<div className="modal-actions"><button type="button" onClick={close}>取消</button><button className="primary" disabled={busy}>{reimportPreview?'保存为参考轨':'检查差异'}</button></div></form>}
    </Modal>}
  </div>;
}
