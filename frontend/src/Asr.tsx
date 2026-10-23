import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api, Icon } from './ui';
import type { TranscriptionStatus, TranscriptionTask } from './types';

const active = (task: TranscriptionTask) => task.status === 'queued' || task.status === 'running';
const taskLabels: Record<TranscriptionTask['status'], string> = {
  queued: '排队等待', running: '正在识别', completed: '识别完成', failed: '识别失败', cancelled: '已取消',
};

export function useTranscriptions() {
  const [status, setStatus] = useState<TranscriptionStatus | null>(null);
  const [tasks, setTasks] = useState<TranscriptionTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [cancelling, setCancelling] = useState<string[]>([]);
  const submitting = useRef(false);

  const mergeTasks = useCallback((incoming: TranscriptionTask[]) => {
    setTasks(previous => {
      const merged = new Map(previous.map(task => [task.task_id, task]));
      for (const task of incoming) {
        const old = merged.get(task.task_id);
        // A poll started before cancellation must not restore a running state.
        if (old && ((!active(old) && active(task)) || Date.parse(old.updated_at) > Date.parse(task.updated_at))) continue;
        merged.set(task.task_id, task);
      }
      return [...merged.values()].sort((a,b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    });
  }, []);

  const refreshTasks = useCallback(async () => {
    try {
      const result = await api<{tasks: TranscriptionTask[]}>('/transcriptions');
      mergeTasks(result.tasks);
      setPollError('');
    } catch {
      setPollError('暂时无法刷新本地转写任务。已保存的项目不受影响。');
    }
  }, [mergeTasks]);

  const refresh = useCallback(async () => {
    setLoading(true);
    const results = await Promise.allSettled([api<TranscriptionStatus>('/asr/status'), refreshTasks()]);
    if (results[0].status === 'fulfilled') setStatus(results[0].value);
    else setStatus({ready: false, local: true, reasons: ['本地识别服务尚未连接，请检查服务启动状态后重新检查。']});
    setLoading(false);
  }, [refreshTasks]);

  useEffect(() => { void refresh(); }, [refresh]);
  const hasActive = tasks.some(active);
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(() => void refreshTasks(), 2000);
    return () => clearInterval(timer);
  }, [hasActive, refreshTasks]);

  async function submit(data: FormData) {
    if (submitting.current || !status?.ready) return null;
    submitting.current = true;
    setUploading(true);
    setError('');
    if (data.get('audio_track') === '') data.delete('audio_track');
    try {
      const task = await api<TranscriptionTask>('/transcriptions', {method: 'POST', body: data});
      mergeTasks([task]);
      return task;
    } catch (e) {
      setError(e instanceof Error ? e.message : '提交本地转写失败，请重试。');
      return null;
    } finally {
      submitting.current = false;
      setUploading(false);
    }
  }

  async function cancel(taskId: string) {
    setCancelling(ids => [...ids, taskId]);
    setError('');
    try {
      const task = await api<TranscriptionTask>(`/transcriptions/${taskId}/cancel`, {method: 'POST'});
      mergeTasks([task]);
    } catch (e) {
      setError(e instanceof Error ? e.message : '取消失败，请刷新任务状态后重试。');
    } finally {
      setCancelling(ids => ids.filter(id => id !== taskId));
    }
  }

  return {status, tasks, loading, uploading, error, pollError, cancelling, refresh, refreshTasks, submit, cancel};
}

type Controller = ReturnType<typeof useTranscriptions>;

export function TranscriptionForm({controller, onSubmitted}: {controller: Controller; onSubmitted: () => void}) {
  const {status, uploading, loading, error} = controller;
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const task = await controller.submit(data);
    if (task) { form.reset(); onSubmitted(); }
  }
  return <form onSubmit={onSubmit} className="transcription-form">
    <p className="modal-intro">选择视频或音频，生成原语字幕项目。</p>
    <div className={`asr-engine ${status?.ready ? 'ready' : ''}`}>
      <Icon name="sound" size={22}/>
      <div><strong>{loading ? '正在检查本地模型…' : status?.ready ? '识别服务可用' : '识别服务未就绪'}</strong><span>{status?.model_label || status?.model || '等待模型配置'}{status?.local && ' · 本地运行'}</span></div>
      <button type="button" className="text-button" disabled={loading} onClick={() => void controller.refresh()}><Icon name="refresh" size={13}/>重新检查</button>
    </div>
    {!loading && !status?.ready && <div className="info-box amber-box"><Icon name="alert" size={16}/><span>{status?.reasons?.join('；') || '请确认本地模型与识别引擎已安装。'}</span></div>}
    {error && <div className="modal-error" role="alert"><Icon name="alert" size={15}/>{error}</div>}
    <fieldset disabled={uploading}>
      <label className="file-picker"><Icon name="upload" size={25}/><strong>视频或音频 <span>必选</span></strong><span>无需字幕文件</span><input type="file" name="media" accept="video/*,audio/*,.mp4,.mkv,.mov,.mp3,.wav,.m4a,.flac,.webm" required/></label>
      <label className="form-field">项目名称<input name="name" placeholder="留空使用媒体文件名" maxLength={160}/></label>
      <div className="form-grid">
        <label className="form-field">原音语言<select name="language" defaultValue="auto"><option value="auto">自动检测</option><option value="th">泰语</option><option value="en">英语</option></select></label>
        <label className="form-field">选定音轨索引 <span className="muted">可选</span><input name="audio_track" type="number" min="0" step="1" placeholder="留空使用首条音轨"/></label>
      </div>
    </fieldset>
    <p className="fine-print">泰英混说可选自动检测，识别结果需试听复核。</p>
    <div className="asr-submit-row"><span>按顺序识别，可继续审阅其他项目。</span><button className="primary" disabled={uploading || loading || !status?.ready} type="submit">{uploading ? <span className="spinner small"/> : <Icon name="sound" size={16}/>} {uploading ? '正在上传至本机…' : '开始本地识别'}</button></div>
  </form>;
}

export function TranscriptionTasks({controller, onOpen, onShowAll, currentProjectId, opening, compact = false}: {
  controller: Controller;
  onOpen: (projectId: string) => void;
  onShowAll?: () => void;
  currentProjectId?: string;
  opening?: boolean;
  compact?: boolean;
}) {
  const {tasks, pollError, error, cancelling} = controller;
  const ordered = [...tasks].sort((a,b) => Number(active(b)) - Number(active(a)) || Date.parse(b.created_at) - Date.parse(a.created_at));
  const shown = compact ? ordered.filter(active).slice(0,1) : ordered;
  if (!shown.length) return null;
  return <section className={`transcription-tasks ${compact ? 'compact panel' : ''}`} aria-label="本地转写任务">
    <header><div><Icon name="sound" size={16}/><h3>本地转写任务</h3><span>{tasks.filter(active).length ? `${tasks.filter(active).length} 项进行中` : `${tasks.length} 项任务`}</span></div>{onShowAll && <button className="text-button" onClick={onShowAll}>全部任务<Icon name="chevron" size={13}/></button>}</header>
    {pollError && <div className="asr-task-warning" role="status"><span>{pollError}</span><button className="text-button" onClick={() => void controller.refreshTasks()}>重试刷新</button></div>}
    {compact && error && <div className="asr-task-warning" role="alert">{error}</div>}
    <div className="transcription-task-list">{shown.map(task => {
      const progress = Math.max(0,Math.min(100,Number(task.progress) || 0));
      return <article key={task.task_id} className={`transcription-task ${task.status}`}>
        <div className="asr-task-main"><div className="asr-task-title"><strong title={task.filename}>{task.name || task.filename}</strong><span className={`asr-task-state ${task.status}`}>{taskLabels[task.status]}</span></div><div className="asr-task-detail"><span>{task.stage || taskLabels[task.status]}</span>{active(task) && <small>约 {Math.round(progress)}%</small>}</div>{active(task) && <div className="asr-task-progress" role="progressbar" aria-label={`${task.name || task.filename} 识别进度`} aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100}><span style={{width:`${progress}%`}}/></div>}{task.error && <p className="asr-task-error">{task.error}</p>}{task.status === 'completed' && <p className="asr-task-complete">字幕已生成 · 待审阅</p>}</div>
        <div className="asr-task-actions">{active(task) && <button disabled={cancelling.includes(task.task_id)} onClick={() => void controller.cancel(task.task_id)}>{cancelling.includes(task.task_id) ? '正在取消…' : '取消任务'}</button>}{task.status === 'completed' && task.project_id && <button className="primary" disabled={opening || task.project_id === currentProjectId} onClick={() => onOpen(task.project_id!)}>{task.project_id === currentProjectId ? '当前项目' : '打开项目'}<Icon name="chevron" size={13}/></button>}{task.status === 'failed' && <span>可重新选择媒体提交</span>}</div>
      </article>;
    })}</div>
  </section>;
}
