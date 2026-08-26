import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Loader2, Square, Upload } from 'lucide-react'
import {
  applyLocalAgentRun, cancelLocalAgentRun, getLocalAgentRun,
  getLocalAgentRunEvents, type LocalAgentRun,
} from '../../services/api'

const terminal = new Set(['completed', 'failed', 'canceled', 'stale', 'applied'])

export default function LocalAgentRunCard({ runId }: { runId: number }) {
  const [run, setRun] = useState<LocalAgentRun | null>(null)
  const [events, setEvents] = useState<any[]>([])
  const [expanded, setExpanded] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    let timer: number | null = null
    const poll = async () => {
      try {
        const [latest, latestEvents] = await Promise.all([
          getLocalAgentRun(runId), getLocalAgentRunEvents(runId),
        ])
        if (!active) return
        setRun(latest)
        setEvents(latestEvents)
        if (!terminal.has(latest.status)) timer = window.setTimeout(poll, 1200)
      } catch (e: any) {
        if (active) setError(e?.response?.data?.detail?.message || '无法读取本地 Agent 状态')
      }
    }
    poll()
    return () => { active = false; if (timer) window.clearTimeout(timer) }
  }, [runId])

  const guarded = useMemo(() => (run?.changed_files || []).filter(item => (
    item.operation === 'delete' || item.operation === 'move'
  )), [run])

  const toggleGuarded = (path: string) => setSelected(previous => {
    const next = new Set(previous)
    if (next.has(path)) next.delete(path)
    else next.add(path)
    return next
  })

  const cancel = async () => {
    setBusy(true)
    try { setRun(await cancelLocalAgentRun(runId)) }
    catch (e: any) { setError(e?.response?.data?.detail?.message || '取消失败') }
    finally { setBusy(false) }
  }

  const apply = async () => {
    if (!run || guarded.some(item => !selected.has(item.path))) return
    setBusy(true)
    setError('')
    try {
      setRun(await applyLocalAgentRun(run.id, {
        confirm_apply: true,
        confirmed_deletions: guarded.filter(item => item.operation === 'delete').map(item => item.path),
        confirmed_moves: guarded.filter(item => item.operation === 'move').map(item => item.path),
        idempotency_key: globalThis.crypto?.randomUUID?.() || `apply-${run.id}-${Date.now()}`,
      }))
      window.dispatchEvent(new CustomEvent('learnflow:workspace-changed'))
    } catch (e: any) {
      setError(e?.response?.data?.detail?.message || '应用失败；真实工作区未被部分覆盖')
      try { setRun(await getLocalAgentRun(run.id)) } catch {}
    } finally { setBusy(false) }
  }

  if (!run) return <div className="mt-2 border border-slate-200 bg-white p-3 text-xs text-slate-500 rounded-lg">正在载入本地 Agent...</div>

  const awaiting = run.status === 'queued' || run.status === 'running'
  const canApply = run.status === 'completed' && guarded.every(item => selected.has(item.path))
  return (
    <div className="mt-2 overflow-hidden border border-slate-200 bg-white rounded-lg" data-testid="local-agent-run-card">
      <div className="flex items-start justify-between gap-3 px-3 py-2.5">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-900">
            {awaiting ? <Loader2 size={13} className="animate-spin text-indigo-600" /> : <CheckCircle2 size={13} className={run.status === 'completed' || run.status === 'applied' ? 'text-emerald-600' : 'text-amber-600'} />}
            本地 Agent · {run.status}
          </p>
          <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-slate-500">{run.goal}</p>
          <p className="mt-1 text-[10px] text-slate-400">
            {run.result?.profile?.name || `Profile ${run.profile_id}`} · 沙箱 {run.result?.sandbox_policy || 'workspace_write'} · 联网 {run.result?.network_policy || 'unmanaged'}
            {run.result?.network_boundary_enforced === false ? '（未受管）' : ''}
          </p>
        </div>
        {awaiting && <button type="button" onClick={cancel} disabled={busy} className="flex items-center gap-1 px-2 py-1 text-[10px] text-red-600 hover:bg-red-50 rounded"><Square size={10} />取消</button>}
      </div>

      {events.length > 0 && (
        <div className="border-t border-slate-100 px-3 py-2 text-[10px] text-slate-500">
          最近事件：{events.slice(-3).map(item => item.event_type).join(' → ')}
        </div>
      )}

      {(run.status === 'completed' || run.status === 'applied' || run.status === 'stale') && (
        <>
          <button type="button" onClick={() => setExpanded(value => !value)} className="flex w-full items-center gap-1 border-t border-slate-100 px-3 py-2 text-left text-[11px] font-medium text-slate-700 hover:bg-slate-50">
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {run.changed_files.length} 个文件修改 · 查看完整 diff
          </button>
          {expanded && (
            <div className="max-h-72 overflow-auto border-t border-slate-100 bg-slate-950 p-3">
              <pre className="whitespace-pre-wrap break-words font-mono text-[10px] leading-4 text-slate-200">{run.diff_text || '没有文件差异'}</pre>
            </div>
          )}
          {guarded.length > 0 && run.status === 'completed' && (
            <div className="space-y-1 border-t border-amber-100 bg-amber-50 px-3 py-2">
              <p className="flex items-center gap-1 text-[10px] font-medium text-amber-900"><AlertTriangle size={11} />删除和移动必须逐项确认</p>
              {guarded.map(item => (
                <label key={`${item.operation}:${item.path}`} className="flex items-center gap-2 text-[10px] text-amber-900">
                  <input type="checkbox" checked={selected.has(item.path)} onChange={() => toggleGuarded(item.path)} />
                  {item.operation} · {item.path}{item.destination_path ? ` → ${item.destination_path}` : ''}
                </label>
              ))}
            </div>
          )}
          {run.status === 'completed' && (
            <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-3 py-2">
              <p className="text-[10px] text-slate-500">第二次确认后才写回；应用前会重新校验全部基础 hash。</p>
              <button type="button" onClick={apply} disabled={!canApply || busy} className="flex shrink-0 items-center gap-1 bg-emerald-700 px-2.5 py-1.5 text-[10px] font-medium text-white disabled:bg-slate-300 rounded"><Upload size={11} />确认写回</button>
            </div>
          )}
        </>
      )}
      {run.status === 'applied' && <p className="border-t border-emerald-100 bg-emerald-50 px-3 py-2 text-[10px] text-emerald-800">已通过文件服务写回真实工作区。</p>}
      {run.status === 'stale' && <p className="border-t border-amber-100 bg-amber-50 px-3 py-2 text-[10px] text-amber-800">真实工作区已变化，这份结果已失效，不能覆盖。</p>}
      {(error || run.error?.message) && <p className="border-t border-red-100 bg-red-50 px-3 py-2 text-[10px] text-red-700">{error || run.error.message}</p>}
    </div>
  )
}
