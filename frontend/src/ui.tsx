import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    plus: <path d="M12 5v14M5 12h14"/>,
    play: <path d="m8 5 11 7-11 7Z"/>, pause: <><path d="M8 5v14M16 5v14"/></>,
    folder: <path d="M3 7V5h6l2 3h10v12H3Zm0 1h18"/>,
    subtitle: <><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M6 12h5m2 0h5M6 16h3m3 0h6"/></>,
    settings: <><path d="m10 3-1 3-3 1-3 3 2 2-1 4 3 1 2 4h4l2-3 4-1 2-4-3-2V7l-4-1-1-3Z"/><circle cx="12" cy="12" r="3"/></>,
    download: <><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/></>,
    upload: <><path d="M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    chevron: <path d="m9 5 7 7-7 7"/>, prev: <path d="m15 5-7 7 7 7"/>,
    close: <path d="m5 5 14 14M19 5 5 19"/>,
    search: <><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></>,
    sparkles: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/><path d="M20 2v4m-2-2h4"/></>,
    loop: <><path d="m17 2 4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4m14-1v2a3 3 0 0 1-3 3H3"/></>,
    split: <><path d="M12 3v18M5 8l-3 4 3 4m14-8 3 4-3 4M3 12h6m6 0h6"/></>,
    merge: <><path d="m4 4 8 8 8-8M12 12v9m-4-4 4 4 4-4"/></>,
    undo: <><path d="m8 4-5 5 5 5M3 9h12a6 6 0 0 1 0 12h-5"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/></>,
    alert: <><path d="m12 3 10 18H2Z"/><path d="M12 9v5m0 3v.1"/></>,
    history: <><path d="M3 10a9 9 0 1 1 2 8M3 4v6h6M12 7v5l4 2"/></>,
    link: <><path d="m9 15 6-6M8 7l2-2a5 5 0 0 1 7 7l-2 2m1 3-2 2a5 5 0 0 1-7-7l2-2"/></>,
    book: <><path d="M12 5v16M3 4c4-1 6 0 9 2 3-2 5-3 9-2v15c-4-1-6 0-9 2-3-2-5-3-9-2Z"/></>,
    sound: <><path d="M3 10v4h4l5 5V5L7 10Zm12-2a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/></>,
    keyboard: <><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M5 9h1m3 0h1m3 0h1m3 0h1M5 12h1m3 0h1m3 0h1m3 0h1M7 16h10"/></>,
    refresh: <><path d="M20 8a8 8 0 1 0 0 8m0-14v6h-6"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.subtitle}</svg>;
}

export function Modal({ title, children, close, wide = false }: { title: string; children: ReactNode; close: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>('button, input, select, textarea')?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') close();
      if (event.key === 'Tab') {
        const els = [...(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input, select, textarea, a[href]') || [])];
        if (!els.length) return;
        if (event.shiftKey && document.activeElement === els[0]) { event.preventDefault(); els.at(-1)?.focus(); }
        else if (!event.shiftKey && document.activeElement === els.at(-1)) { event.preventDefault(); els[0].focus(); }
      }
    }
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); previous?.focus(); };
  }, [close]);
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) close(); }}><div ref={ref} className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}><header><div><h2>{title}</h2></div><button className="icon-button" aria-label="关闭" onClick={close}><Icon name="close"/></button></header>{children}</div></div>;
}

export function timecode(ms: number) { const n = Math.max(0, Math.round(ms)); return `${String(Math.floor(n / 3600000)).padStart(2, '0')}:${String(Math.floor(n / 60000) % 60).padStart(2, '0')}:${String(Math.floor(n / 1000) % 60).padStart(2, '0')}.${String(n % 1000).padStart(3, '0')}`; }
export function parseTime(value: string): number | null { const m = value.trim().match(/^(\d{1,3}):(\d{2}):(\d{2})[.,](\d{3})$/); if (!m || +m[2] > 59 || +m[3] > 59) return null; return (+m[1] * 3600 + +m[2] * 60 + +m[3]) * 1000 + +m[4]; }
export function shortTime(ms: number) { return `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`; }

export class ApiError extends Error { status: number; constructor(message: string, status: number) { super(message); this.status = status; } }
export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api${path}`, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    let detail = body.detail || body.message || `请求失败（${response.status}）`;
    if (typeof detail !== 'string') detail = Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('；') : detail.message || JSON.stringify(detail);
    throw new ApiError(detail, response.status);
  }
  return response.status === 204 ? undefined as T : response.json();
}
