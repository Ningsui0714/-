import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertTriangle, ArrowRight, Brain, CalendarClock, CheckCircle2, ChevronRight,
  Clock3, Code2, Eye, Filter, History, Pause, Play, RotateCcw, Search,
  ShieldCheck, SkipForward, Sparkles, X,
} from 'lucide-react'
import RemediationPanel from '../components/exercise/RemediationPanel'
import { useWorkspace, useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import {
  getReviewHistory, getReviewSummary, listReviewItems, manageReviewItem,
  submitReviewItem,
} from '../services/api'


type ReviewBucket = 'due' | 'wrong' | 'upcoming' | 'stable' | 'suspended'

interface ReviewItem {
  id: number
  version: number
  project_id?: number
  checkpoint_id: number
  item_type: 'concept' | 'exercise'
  item_id: number
  title: string
  project_name: string
  checkpoint_title: string
  subject_key: string
  phase: 'active' | 'remediation' | 'suspended'
  bucket: string
  due_at: string
  interval_level: number
  interval_days: number
  lapse_count: number
  defer_count: number
  last_grade: string
  attempt_state: string
  remediation_state: string
  evidence_state: string
  wrong_state: string
  wrong_count: number
  reason_codes: string[]
  source_href: string
  remediation?: any
  presentation: {
    question_form: 'original' | 'validated_variant'
    version: string
    payload: Record<string, any>
  }
}

interface ReviewSummary {
  total: number
  due: number
  overdue: number
  wrong: number
  remediation: number
  upcoming: number
  stable: number
  suspended: number
}

const EMPTY_SUMMARY: ReviewSummary = {
  total: 0, due: 0, overdue: 0, wrong: 0, remediation: 0, upcoming: 0, stable: 0, suspended: 0,
}

const BUCKETS: Array<{ id: ReviewBucket; label: string; count: keyof ReviewSummary }> = [
  { id: 'due', label: '今日复习', count: 'due' },
  { id: 'wrong', label: '错题本', count: 'wrong' },
  { id: 'upcoming', label: '即将复习', count: 'upcoming' },
  { id: 'stable', label: '稳定项目', count: 'stable' },
  { id: 'suspended', label: '已暂停', count: 'suspended' },
]

const STATE_LABELS: Record<string, string> = {
  incorrect: '答错',
  unknown: '不会',
  correct_with_support: '辅助答对',
  correct_independent: '独立答对',
  explaining: '待重做',
  variant_ready: '待变式',
  completed: '纠错完成',
  spaced_stable: '间隔稳定',
  transfer_verified: '迁移验证',
  verified_once: '单次验证',
  assisted_success: '辅助成功',
  repeated_error: '反复出错',
  first_error: '首次错误',
  relapsed: '重新遗忘',
  corrected_due_review: '已纠正待复查',
  corrected: '已纠正',
}

function requestId(prefix: string) {
  const suffix = typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${suffix}`
}

function formatDue(value: string) {
  const date = new Date(value)
  const diff = date.getTime() - Date.now()
  if (Math.abs(diff) < 60 * 60 * 1000) return diff <= 0 ? '现在到期' : '1 小时内'
  if (diff < 0) return `逾期 ${Math.max(1, Math.floor(Math.abs(diff) / 86400000))} 天`
  if (diff < 86400000) return `${Math.ceil(diff / 3600000)} 小时后`
  return `${Math.ceil(diff / 86400000)} 天后`
}

function MetricCard({ icon, label, value, tone }: {
  icon: ReactNode
  label: string
  value: number
  tone: string
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${tone}`}>{icon}</div>
      <p className="mt-3 text-2xl font-semibold tabular-nums text-slate-950">{value}</p>
      <p className="text-[11px] text-slate-500">{label}</p>
    </div>
  )
}

function StateBadge({ value, tone = 'slate' }: { value: string; tone?: string }) {
  const colors: Record<string, string> = {
    slate: 'border-slate-200 bg-slate-50 text-slate-600',
    amber: 'border-amber-200 bg-amber-50 text-amber-700',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    violet: 'border-violet-200 bg-violet-50 text-violet-700',
  }
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${colors[tone]}`}>
      {STATE_LABELS[value] || value}
    </span>
  )
}

function ReviewCard({ item, active, onOpen }: {
  item: ReviewItem
  active: boolean
  onOpen: () => void
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`w-full rounded-xl border p-3 text-left transition ${
        active
          ? 'border-indigo-300 bg-indigo-50/70 shadow-sm'
          : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
      }`}
    >
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
          item.item_type === 'concept' ? 'bg-sky-50 text-sky-700' : 'bg-violet-50 text-violet-700'
        }`}>
          {item.item_type === 'concept' ? <Brain size={16} /> : <Code2 size={16} />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block line-clamp-2 text-xs font-semibold leading-5 text-slate-800">{item.title}</span>
          <span className="mt-1 block truncate text-[10px] text-slate-400">
            {item.project_name} · {item.checkpoint_title}
          </span>
        </span>
        <ChevronRight size={15} className="mt-2 shrink-0 text-slate-300" />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {item.phase === 'remediation' ? <StateBadge value={item.remediation_state} tone="amber" /> : null}
        {item.wrong_count > 1 ? <StateBadge value="repeated_error" tone="amber" /> : null}
        <StateBadge value={item.evidence_state} tone={item.evidence_state === 'spaced_stable' ? 'emerald' : 'slate'} />
        <span className={`ml-auto text-[10px] font-medium ${item.bucket === 'overdue' ? 'text-rose-600' : 'text-slate-400'}`}>
          {formatDue(item.due_at)}
        </span>
      </div>
    </button>
  )
}

function HistoryDrawer({ item, onClose }: { item: ReviewItem; onClose: () => void }) {
  const [history, setHistory] = useState<any>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    getReviewHistory(item.id)
      .then(data => { if (active) setHistory(data) })
      .catch(requestError => { if (active) setError(requestError?.response?.data?.detail || requestError.message) })
    return () => { active = false }
  }, [item.id])

  return (
    <aside className="absolute inset-y-0 right-0 z-40 w-[min(92vw,430px)] overflow-y-auto border-l border-slate-200 bg-white shadow-2xl">
      <header className="sticky top-0 z-10 flex h-12 items-center justify-between border-b border-slate-200 bg-white px-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-800"><History size={16} /> 学习证据时间线</div>
        <button type="button" onClick={onClose} aria-label="关闭详情" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={16} /></button>
      </header>
      <div className="space-y-5 p-4">
        <div>
          <p className="text-sm font-semibold text-slate-900">{item.title}</p>
          <p className="mt-1 text-xs text-slate-500">{item.project_name} · {item.checkpoint_title}</p>
        </div>
        {!history && !error ? <p className="text-xs text-slate-400">正在读取 Attempt、纠错与事件证据…</p> : null}
        {error ? <p className="rounded-lg bg-rose-50 p-3 text-xs text-rose-700">{error}</p> : null}
        {history ? (
          <>
            <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-400">调度依据</h3>
              <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-6 text-slate-600">
                <p>策略：{history.schedule.policy_version}</p>
                <p>间隔阶梯：第 {history.schedule.interval_level + 1} 级 · {history.schedule.interval_days} 天</p>
                <p>遗忘次数：{history.schedule.lapse_count} · 最近评级：{history.schedule.last_grade || '无'}</p>
                <p>入队原因：{item.reason_codes.join(' / ') || '常规到期'}</p>
              </div>
            </section>
            <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-400">作答记录</h3>
              <div className="mt-2 space-y-2">
                {(history.attempts || []).map((attempt: any) => (
                  <div key={attempt.id} className="rounded-xl border border-slate-200 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs font-semibold text-slate-700">Attempt #{attempt.id}</span>
                      <span className={`text-[10px] font-medium ${attempt.passed ? 'text-emerald-700' : 'text-rose-600'}`}>{attempt.passed ? '通过' : attempt.status === 'abstained' ? '不会' : '未通过'}</span>
                    </div>
                    <p className="mt-1 text-[10px] text-slate-400">{attempt.attempt_role} · {attempt.assistance_level} · {attempt.evaluated_at ? new Date(attempt.evaluated_at).toLocaleString() : ''}</p>
                  </div>
                ))}
              </div>
            </section>
            {(history.remediation_cases || []).length ? (
              <section>
                <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-400">错题与纠错</h3>
                <div className="mt-2 space-y-2">
                  {history.remediation_cases.map((item: any) => (
                    <div key={item.id} className="rounded-xl border border-amber-200 bg-amber-50/60 p-3 text-xs text-amber-900">
                      <p className="font-semibold">{item.misconception_tag}</p>
                      <p className="mt-1 text-[10px] text-amber-700">{item.error_class} · {item.status} · 当前讲法 {item.current_delivery_mode || '未记录'}</p>
                      <p className="mt-1 text-[10px] text-amber-700">无效讲法：{item.ineffective_modes?.join('、') || '无'} · 讲解 {item.explanation_count || 0} 次</p>
                      <p className="mt-1 text-[10px] text-amber-700">重做 Attempt #{item.retry_attempt_id || '—'} · 变式 Attempt #{item.variant_attempt_id || '—'}</p>
                      <p className="mt-1 break-all font-mono text-[10px] text-amber-700">Evidence #{item.evidence_event_ids?.join(', #') || '—'}</p>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}
          </>
        ) : null}
      </div>
    </aside>
  )
}

function QuestionRunner({ item, onRefresh, onOpenSource }: {
  item: ReviewItem
  onRefresh: () => Promise<void>
  onOpenSource: () => void
}) {
  const payload = item.presentation.payload || {}
  const [answers, setAnswers] = useState<number[]>([])
  const [answerText, setAnswerText] = useState('')
  const [code, setCode] = useState('')
  const [files, setFiles] = useState<Array<Record<string, any>>>([])
  const [assisted, setAssisted] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)
  const runnerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setAnswers([])
    setAnswerText('')
    setCode(payload.starter_code || '')
    setFiles((payload.files || []).map((file: any) => ({ ...file })))
    setAssisted(false)
    setBusy('')
    setError('')
    setResult(null)
  }, [item.id, item.version, payload.files, payload.starter_code])

  const toggleAnswer = (index: number) => {
    if (payload.multiple) {
      setAnswers(current => current.includes(index)
        ? current.filter(value => value !== index)
        : [...current, index])
    } else {
      setAnswers([index])
    }
  }

  const submit = async (status: 'answered' | 'unknown' | 'skipped') => {
    setBusy(status)
    setError('')
    try {
      const response = await submitReviewItem(item.id, {
        expected_version: item.version,
        client_submission_id: requestId(status),
        response_status: status,
        answer_indexes: answers,
        answer_text: answerText,
        code,
        files,
        assistance_level: assisted ? 'hint' : 'none',
        presentation_version: item.presentation.version,
      })
      setResult(response)
      if (status === 'skipped' || response.passed) await onRefresh()
      else await onRefresh()
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message || '提交失败')
    } finally {
      setBusy('')
    }
  }

  const actionable = payload.type === 'concept_choice'
    ? answers.length > 0
    : payload.type === 'predict_output'
      ? Boolean(answerText.trim())
      : Boolean(code.trim() || files.some(file => String(file.content || '').trim()))
  const waitingVariant = item.remediation?.status === 'variant_ready'

  return (
    <div ref={runnerRef} id="review-question-runner" className="space-y-4">
      {item.remediation ? (
        <RemediationPanel
          remediation={item.remediation}
          onChange={() => { void onRefresh() }}
          onRetry={() => runnerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
        />
      ) : null}

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <StateBadge value={item.attempt_state} />
              <StateBadge value={item.presentation.question_form === 'validated_variant' ? '迁移变式' : '原题检索'} tone="violet" />
              <span className="text-[10px] text-slate-400">第 {item.interval_level + 1} 级 · {item.interval_days} 天间隔</span>
            </div>
            <p className="mt-2 text-xs text-slate-500">{item.subject_key}</p>
          </div>
          <button type="button" onClick={onOpenSource} className="flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50">
            返回来源 <ArrowRight size={13} />
          </button>
        </header>

        <div className="p-5">
          <h2 className="text-base font-semibold leading-7 text-slate-950">{payload.prompt || payload.title || item.title}</h2>
          {payload.input ? <pre className="mt-3 overflow-x-auto rounded-xl bg-slate-950 p-3 text-xs text-slate-100">输入：{payload.input}</pre> : null}

          {payload.type === 'concept_choice' ? (
            <div className="mt-4 grid gap-2">
              {(payload.options || []).map((option: string, index: number) => (
                <label key={`${option}-${index}`} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm transition ${answers.includes(index) ? 'border-indigo-300 bg-indigo-50' : 'border-slate-200 hover:bg-slate-50'}`}>
                  <input type={payload.multiple ? 'checkbox' : 'radio'} checked={answers.includes(index)} onChange={() => toggleAnswer(index)} className="mt-0.5" />
                  <span>{option}</span>
                </label>
              ))}
            </div>
          ) : null}

          {payload.type === 'predict_output' ? (
            <textarea value={answerText} onChange={event => setAnswerText(event.target.value)} rows={4} placeholder="输入你的预测结果" className="mt-4 w-full rounded-xl border border-slate-200 p-3 font-mono text-sm outline-none focus:border-indigo-400" />
          ) : null}

          {payload.type === 'code' && files.length === 0 ? (
            <textarea value={code} onChange={event => setCode(event.target.value)} rows={14} spellCheck={false} className="mt-4 w-full rounded-xl border border-slate-800 bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-100 outline-none focus:border-indigo-500" />
          ) : null}

          {payload.type === 'code' && files.length > 0 ? (
            <div className="mt-4 space-y-3">
              {files.map((file, index) => (
                <div key={file.name || index} className="overflow-hidden rounded-xl border border-slate-200">
                  <div className="border-b border-slate-200 bg-slate-50 px-3 py-2 font-mono text-[11px] text-slate-600">{file.name}</div>
                  <textarea
                    value={String(file.content || '')}
                    readOnly={Boolean(file.read_only)}
                    onChange={event => setFiles(current => current.map((entry, entryIndex) => entryIndex === index ? { ...entry, content: event.target.value } : entry))}
                    rows={10}
                    spellCheck={false}
                    className="w-full bg-slate-950 p-3 font-mono text-xs leading-6 text-slate-100 outline-none read-only:opacity-70"
                  />
                </div>
              ))}
            </div>
          ) : null}

          {!waitingVariant ? (
            <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
              <label className="mr-auto flex cursor-pointer items-center gap-2 text-[11px] text-slate-500">
                <input type="checkbox" checked={assisted} onChange={event => setAssisted(event.target.checked)} />
                本题使用过提示或辅助
              </label>
              <button type="button" onClick={() => submit('skipped')} disabled={Boolean(busy)} className="flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"><SkipForward size={14} /> 跳过</button>
              <button type="button" onClick={() => submit('unknown')} disabled={Boolean(busy)} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 hover:bg-amber-100 disabled:opacity-50">不会</button>
              <button type="button" onClick={() => submit('answered')} disabled={Boolean(busy) || !actionable} className="flex items-center gap-1 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-40"><ShieldCheck size={14} /> {busy === 'answered' ? '判定中…' : '提交检索'}</button>
            </div>
          ) : null}
          {waitingVariant ? <p className="mt-4 rounded-xl bg-violet-50 p-3 text-xs text-violet-800">原题重做已通过，请在上方完成变式验证后进入下一轮间隔复习。</p> : null}
          {result ? <p className={`mt-3 rounded-xl p-3 text-xs font-medium ${result.passed ? 'bg-emerald-50 text-emerald-700' : result.outcome === 'skipped' ? 'bg-slate-50 text-slate-600' : 'bg-amber-50 text-amber-800'}`}>{result.passed ? '检索成功，下一次复习时间已更新。' : result.outcome === 'unknown' ? '已记录“不会”，不会把它误判为具体误解。' : result.outcome === 'skipped' ? '已跳过，本题仍保持到期。' : '已进入纠错闭环，先修正错误再做迁移验证。'}</p> : null}
          {error ? <p className="mt-3 rounded-xl bg-rose-50 p-3 text-xs text-rose-700">{error}</p> : null}
        </div>
      </section>
    </div>
  )
}

export default function ReviewPage() {
  useWorkspaceTitle('全局复习台', { kind: 'review' })
  const { openPath } = useWorkspace()
  const [bucket, setBucket] = useState<ReviewBucket>('due')
  const [summary, setSummary] = useState<ReviewSummary>(EMPTY_SUMMARY)
  const [items, setItems] = useState<ReviewItem[]>([])
  const [allItems, setAllItems] = useState<ReviewItem[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [projectId, setProjectId] = useState('')
  const [checkpointId, setCheckpointId] = useState('')
  const [itemType, setItemType] = useState('')
  const [remediationStatus, setRemediationStatus] = useState('')
  const [subject, setSubject] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)

  const params = useMemo(() => ({
    project_id: projectId ? Number(projectId) : undefined,
    checkpoint_id: checkpointId ? Number(checkpointId) : undefined,
    item_type: itemType || undefined,
    remediation_status: remediationStatus || undefined,
    subject: subject.trim() || undefined,
  }), [checkpointId, itemType, projectId, remediationStatus, subject])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [nextSummary, queue, complete] = await Promise.all([
        getReviewSummary(params),
        listReviewItems({ ...params, bucket, limit: 100 }),
        listReviewItems({ bucket: 'all', limit: 100 }),
      ])
      const nextItems = queue.items || []
      setSummary(nextSummary)
      setItems(nextItems)
      setAllItems(complete.items || [])
      setActiveId(current => nextItems.some((item: ReviewItem) => item.id === current)
        ? current
        : nextItems[0]?.id || null)
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message || '复习队列读取失败')
    } finally {
      setLoading(false)
    }
  }, [bucket, params])

  useEffect(() => { void load() }, [load])

  const activeItem = items.find(item => item.id === activeId) || null
  const projects = useMemo(() => Array.from(new Map(allItems.filter(item => item.project_id).map(item => [item.project_id, item.project_name])).entries()), [allItems])
  const checkpoints = useMemo(() => Array.from(new Map(allItems.filter(item => !projectId || String(item.project_id) === projectId).map(item => [item.checkpoint_id, item.checkpoint_title])).entries()), [allItems, projectId])

  const act = async (action: 'defer' | 'suspend' | 'resume') => {
    if (!activeItem) return
    setError('')
    try {
      await manageReviewItem(activeItem.id, action, {
        expected_version: activeItem.version,
        client_event_id: requestId(action),
      })
      await load()
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message)
    }
  }

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-slate-50">
      <header className="shrink-0 border-b border-slate-200 bg-white px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-indigo-700"><RotateCcw size={18} /><span className="text-[11px] font-bold uppercase tracking-[0.18em]">Review Workbench</span></div>
            <h1 className="mt-1 text-xl font-semibold text-slate-950">全局复习台</h1>
            <p className="mt-1 text-xs text-slate-500">错题纠正、检索练习与 1/3/7/14/30/60 天可解释间隔</p>
          </div>
          <div className="flex items-center gap-2 rounded-xl border border-indigo-100 bg-indigo-50 px-3 py-2 text-[11px] text-indigo-800"><Sparkles size={14} /> 调度器只安排复习，掌握仍由五核证据裁决</div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          <MetricCard icon={<CalendarClock size={16} />} label="今日到期" value={summary.due} tone="bg-indigo-50 text-indigo-700" />
          <MetricCard icon={<Clock3 size={16} />} label="已逾期" value={summary.overdue} tone="bg-rose-50 text-rose-700" />
          <MetricCard icon={<AlertTriangle size={16} />} label="待纠错" value={summary.remediation} tone="bg-amber-50 text-amber-700" />
          <MetricCard icon={<RotateCcw size={16} />} label="即将复习" value={summary.upcoming} tone="bg-sky-50 text-sky-700" />
          <MetricCard icon={<CheckCircle2 size={16} />} label="稳定项目" value={summary.stable} tone="bg-emerald-50 text-emerald-700" />
          <MetricCard icon={<Pause size={16} />} label="已暂停" value={summary.suspended} tone="bg-slate-100 text-slate-600" />
        </div>
      </header>

      <nav className="flex shrink-0 gap-1 overflow-x-auto border-b border-slate-200 bg-white px-5">
        {BUCKETS.map(tab => (
          <button key={tab.id} type="button" onClick={() => setBucket(tab.id)} className={`border-b-2 px-3 py-3 text-xs font-medium ${bucket === tab.id ? 'border-indigo-600 text-indigo-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`}>{tab.label}<span className="ml-1.5 rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] text-slate-500">{summary[tab.count]}</span></button>
        ))}
      </nav>

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-5 py-2.5">
        <Filter size={14} className="text-slate-400" />
        <select value={projectId} onChange={event => { setProjectId(event.target.value); setCheckpointId('') }} className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] text-slate-600"><option value="">全部项目</option>{projects.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select>
        <select value={checkpointId} onChange={event => setCheckpointId(event.target.value)} className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] text-slate-600"><option value="">全部关卡</option>{checkpoints.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select>
        <select value={itemType} onChange={event => setItemType(event.target.value)} className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] text-slate-600"><option value="">全部题型</option><option value="concept">概念题</option><option value="exercise">代码题</option></select>
        <select value={remediationStatus} onChange={event => setRemediationStatus(event.target.value)} className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] text-slate-600"><option value="">全部纠错状态</option><option value="none">无纠错</option><option value="explaining">待重做</option><option value="variant_ready">待变式</option><option value="completed">已闭环</option></select>
        <label className="flex min-w-40 flex-1 items-center gap-2 rounded-lg border border-slate-200 px-2.5 py-1.5 sm:max-w-xs"><Search size={13} className="text-slate-400" /><input value={subject} onChange={event => setSubject(event.target.value)} placeholder="筛选知识点" className="min-w-0 flex-1 bg-transparent text-[11px] outline-none" /></label>
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="w-[300px] shrink-0 overflow-y-auto border-r border-slate-200 bg-slate-100/70 p-3">
          {loading ? <p className="p-4 text-center text-xs text-slate-400">正在编排复习队列…</p> : null}
          {!loading && items.length === 0 ? <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-center"><CheckCircle2 className="mx-auto text-emerald-500" /><p className="mt-2 text-sm font-semibold text-slate-700">当前队列已清空</p><p className="mt-1 text-xs leading-5 text-slate-400">完成正式判题后，题目会自动进入分层复习。</p></div> : null}
          <div className="space-y-2">{items.map(item => <ReviewCard key={item.id} item={item} active={item.id === activeId} onOpen={() => setActiveId(item.id)} />)}</div>
        </aside>

        <main className="min-w-0 flex-1 overflow-y-auto p-5">
          {error ? <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">{error}</div> : null}
          {activeItem ? (
            <div className="mx-auto max-w-4xl">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <button type="button" onClick={() => setHistoryOpen(true)} className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50"><Eye size={13} /> 证据详情</button>
                {activeItem.phase !== 'remediation' && activeItem.phase !== 'suspended' ? <button type="button" onClick={() => act('defer')} className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50"><Clock3 size={13} /> 稍后一天</button> : null}
                {activeItem.phase === 'suspended' ? <button type="button" onClick={() => act('resume')} className="flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[11px] text-emerald-700"><Play size={13} /> 恢复复习</button> : <button type="button" onClick={() => act('suspend')} className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50"><Pause size={13} /> 暂停此题</button>}
                <span className="ml-auto text-[10px] text-slate-400">错题 {activeItem.wrong_count} 次 · 遗忘 {activeItem.lapse_count} 次</span>
              </div>
              {activeItem.phase !== 'suspended' ? <QuestionRunner item={activeItem} onRefresh={load} onOpenSource={() => openPath(activeItem.source_href, { title: activeItem.checkpoint_title, kind: 'exercise', projectId: activeItem.project_id, checkpointId: activeItem.checkpoint_id })} /> : <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center"><Pause className="mx-auto text-slate-400" /><p className="mt-3 text-sm font-semibold text-slate-700">这道题已暂停</p><p className="mt-1 text-xs text-slate-400">恢复后会立即回到复习队列，原间隔阶梯不会丢失。</p></div>}
            </div>
          ) : null}
        </main>
      </div>
      {historyOpen && activeItem ? <HistoryDrawer item={activeItem} onClose={() => setHistoryOpen(false)} /> : null}
    </div>
  )
}
