import {
  AlertTriangle, ArrowLeft, ArrowRight, Braces, CheckCircle2,
  Loader2, Network, RotateCcw, Send, Sparkles,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import {
  getPersonalizedLearningKnowledgeEntry,
  launchPersonalizedLearningKnowledgeEntry,
  submitPersonalizedLearningFeedback,
  submitPersonalizedLearningResult,
  type PersonalizedLearningKnowledgeEntry,
  type PersonalizedLearningLaunchResult,
  type PersonalizedLearningResultPayload,
} from '../services/api'

function errorMessage(error: any) {
  return error?.response?.data?.detail || error?.message || '个性化学习交接数据读取失败。'
}

function displaySituation(value: unknown) {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object') return ''
  const item = value as Record<string, unknown>
  return String(item.description || item.name || item.title || '')
}

const EMBEDDED_PROJECT_DESIGN_WIDTH = 1180

function ResponsiveEmbeddedProject({
  src,
  title,
  revision,
  onLoad,
  onFrame,
}: {
  src: string
  title: string
  revision: number
  onLoad: () => void
  onFrame: (frame: HTMLIFrameElement | null) => void
}) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)

  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return undefined
    const resize = () => {
      const nextScale = viewport.clientWidth > 0
        ? Math.min(1, viewport.clientWidth / EMBEDDED_PROJECT_DESIGN_WIDTH)
        : 1
      setScale(current => Math.abs(current - nextScale) < 0.002 ? current : nextScale)
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(viewport)
    return () => observer.disconnect()
  }, [])

  const inverseScale = 1 / scale
  return (
    <div ref={viewportRef} className="h-full min-h-0 w-full overflow-hidden bg-white">
      <iframe
        key={`${revision}:${src}`}
        src={src}
        title={title}
        className="block border-0 bg-white"
        style={{
          width: `${inverseScale * 100}%`,
          height: `${inverseScale * 100}%`,
          transform: `scale(${scale})`,
          transformOrigin: 'left top',
        }}
        allow="clipboard-read; clipboard-write"
        referrerPolicy="strict-origin"
        onLoad={onLoad}
        ref={onFrame}
      />
    </div>
  )
}

export default function PersonalizedLearningEntryPage() {
  const { taskCardId = '', knowledgeId = '' } = useParams()
  const location = useLocation()
  const initialEntry = (location.state as { entry?: PersonalizedLearningKnowledgeEntry } | null)?.entry
  const loadRequestRef = useRef(0)
  const activeEntryKeyRef = useRef(`${taskCardId}:${knowledgeId}`)
  const loadedEntryKeyRef = useRef(initialEntry ? `${taskCardId}:${knowledgeId}` : '')
  const embeddedFrameRef = useRef<HTMLIFrameElement | null>(null)
  const resultReceiptsRef = useRef(new Set<string>())
  const [entry, setEntry] = useState<PersonalizedLearningKnowledgeEntry | null>(initialEntry || null)
  const [loading, setLoading] = useState(!initialEntry)
  const [error, setError] = useState('')
  const [launching, setLaunching] = useState(false)
  const [launched, setLaunched] = useState<PersonalizedLearningLaunchResult | null>(null)
  const [frameLoading, setFrameLoading] = useState(false)
  const [frameRevision, setFrameRevision] = useState(0)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [feedbackCode, setFeedbackCode] = useState('step_mapping_mismatch')
  const [feedbackMessage, setFeedbackMessage] = useState('')
  const [feedbackCorrection, setFeedbackCorrection] = useState('')
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false)
  const [feedbackStatus, setFeedbackStatus] = useState('')
  const [resultSyncStatus, setResultSyncStatus] = useState('')
  useWorkspaceTitle(entry?.focus.knowledge_point.name || '个性化学习交接', { kind: 'wf03' })

  const load = useCallback(async () => {
    if (!taskCardId || !knowledgeId) return
    const entryKey = `${taskCardId}:${knowledgeId}`
    activeEntryKeyRef.current = entryKey
    const requestId = ++loadRequestRef.current
    setLoading(true)
    if (loadedEntryKeyRef.current !== entryKey) setError('')
    try {
      const nextEntry = await getPersonalizedLearningKnowledgeEntry(taskCardId, knowledgeId)
      if (activeEntryKeyRef.current !== entryKey) return
      loadedEntryKeyRef.current = entryKey
      setEntry(nextEntry)
      setError('')
      setLoading(false)
    } catch (failure) {
      if (
        requestId !== loadRequestRef.current
        || activeEntryKeyRef.current !== entryKey
        || loadedEntryKeyRef.current === entryKey
      ) return
      setError(errorMessage(failure))
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false)
    }
  }, [knowledgeId, taskCardId])

  useEffect(() => {
    if (!initialEntry) load()
  }, [initialEntry, load])

  useEffect(() => {
    const storageKey = `personalized-learning-launch:${taskCardId}:${knowledgeId}`
    try {
      const stored = window.sessionStorage.getItem(storageKey)
      setLaunched(stored ? JSON.parse(stored) as PersonalizedLearningLaunchResult : null)
    } catch {
      setLaunched(null)
      window.sessionStorage.removeItem(storageKey)
    }
  }, [knowledgeId, taskCardId])

  useEffect(() => {
    if (!launched) return undefined
    let expectedOrigin = ''
    try {
      expectedOrigin = new URL(launched.redirect_url).origin
    } catch {
      return undefined
    }
    const receiveResult = (event: MessageEvent) => {
      if (
        event.origin !== expectedOrigin
        || event.source !== embeddedFrameRef.current?.contentWindow
        || event.data?.type !== 'learnflow:personalized-learning-result'
      ) return
      const payload = event.data?.payload as PersonalizedLearningResultPayload | undefined
      if (
        !payload
        || payload.entry_id !== launched.entry_id
        || payload.project_id !== launched.project_id
        || payload.knowledge_point_id !== knowledgeId
        || payload.formal_evidence !== false
        || payload.summary?.assessment_type !== 'provisional_self_check'
        || !payload.result_id
        || resultReceiptsRef.current.has(payload.result_id)
      ) return
      resultReceiptsRef.current.add(payload.result_id)
      setResultSyncStatus('正在回传练习结果…')
      submitPersonalizedLearningResult(taskCardId, knowledgeId, payload)
        .then(() => setResultSyncStatus('练习结果已回传，仅作连续学习参考，不作为正式掌握证据。'))
        .catch(failure => {
          resultReceiptsRef.current.delete(payload.result_id)
          setResultSyncStatus(`练习结果回传失败：${errorMessage(failure)}`)
        })
    }
    window.addEventListener('message', receiveResult)
    return () => window.removeEventListener('message', receiveResult)
  }, [knowledgeId, launched, taskCardId])

  const sourceStepCount = useMemo(() => entry?.focus.source_steps.length || 0, [entry])

  const launch = async () => {
    if (!entry || launching) return
    setLaunching(true)
    setError('')
    try {
      const result = await launchPersonalizedLearningKnowledgeEntry(
        entry.source.task_card_id,
        entry.focus.knowledge_point.knowledge_id,
      )
      window.sessionStorage.setItem(
        `personalized-learning-launch:${taskCardId}:${knowledgeId}`,
        JSON.stringify(result),
      )
      setLaunched(result)
      setFrameLoading(true)
      setLaunching(false)
    } catch (failure) {
      setError(errorMessage(failure))
      setLaunching(false)
    }
  }

  const closeEmbeddedProject = () => {
    setLaunched(null)
    setFrameLoading(false)
    setFeedbackOpen(false)
    setResultSyncStatus('')
  }

  const submitFeedback = async () => {
    if (!entry || !feedbackMessage.trim() || feedbackSubmitting) return
    const relation = entry.focus.relationships[0] || {}
    const sourceStep = entry.focus.source_steps[0]
    const skillIds = Array.isArray(relation.skill_ids) ? relation.skill_ids : []
    const correlationId = globalThis.crypto?.randomUUID?.() || `personalized-review-${Date.now()}`
    setFeedbackSubmitting(true)
    setFeedbackStatus('')
    try {
      await submitPersonalizedLearningFeedback({
        schema_version: 'personalized-learning-to-task-conversion-feedback-v1',
        task_card_id: entry.source.task_card_id,
        correlation_id: correlationId,
        source_system: '个性化自适应学习功能',
        status: 'accepted_with_feedback',
        issues: [{
          issue_id: `issue_${correlationId.replace(/[^A-Za-z0-9]/g, '').slice(0, 24)}`,
          feedback_code: feedbackCode,
          severity: 'warning',
          relation_id: String(relation.relation_id || ''),
          step_id: String(relation.step_id || sourceStep?.step_id || ''),
          knowledge_id: entry.focus.knowledge_point.knowledge_id,
          skill_id: String(skillIds[0] || ''),
          message: feedbackMessage.trim(),
          suggested_correction: feedbackCorrection.trim(),
        }],
        summary: feedbackMessage.trim(),
      })
      setFeedbackStatus('已回传任务关系复核，原任务事实不会被直接覆盖。')
      setFeedbackMessage('')
      setFeedbackCorrection('')
    } catch (failure) {
      setFeedbackStatus(errorMessage(failure))
    } finally {
      setFeedbackSubmitting(false)
    }
  }

  if (loading) {
    return <div className="flex h-full items-center justify-center bg-slate-50 text-sm text-slate-500"><Loader2 size={18} className="mr-2 animate-spin text-indigo-600" />正在准备知识点交接 JSON…</div>
  }

  if (!entry) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 p-8">
        <div className="max-w-md border border-red-200 bg-white p-6 text-center shadow-sm">
          <p className="text-sm font-semibold text-slate-900">个性化学习入口无法打开</p>
          <p className="mt-2 text-xs leading-5 text-red-600">{error}</p>
          <button type="button" onClick={load} className="mt-4 bg-slate-900 px-4 py-2 text-xs font-semibold text-white">重新读取</button>
        </div>
      </div>
    )
  }

  const knowledge = entry.focus.knowledge_point
  if (launched) {
    return (
      <main className="flex h-full min-h-0 flex-col bg-slate-100">
        <header className="shrink-0 border-b border-slate-200 bg-white px-4 py-3 shadow-sm">
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={closeEmbeddedProject} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-medium text-slate-600 hover:bg-slate-50">
              <ArrowLeft size={13} /> 返回交接说明
            </button>
            <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold text-emerald-700">
              <CheckCircle2 size={11} className="mr-1 inline" />知识点交接已锁定
            </span>
            <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${launched.content_generation?.configured ? 'bg-indigo-50 text-indigo-700' : 'bg-amber-50 text-amber-700'}`}>
              {launched.content_generation?.configured
                ? `${launched.content_generation.provider === 'deepseek' ? 'DeepSeek' : '兼容模型'} ${launched.content_generation.model}`
                : '本地确定性模板'}
            </span>
            <span className="rounded-full bg-sky-50 px-2.5 py-1 text-[10px] font-semibold text-sky-700">
              {launched.assessment?.status === 'ready' ? '练习型初测已就绪' : '正在准备练习型初测'}
            </span>
            <span className="min-w-0 flex-1 truncate text-xs text-slate-500">
              {knowledge.name} · {launched.project_id}
            </span>
            <button type="button" onClick={() => setFeedbackOpen(value => !value)} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 text-xs font-medium text-amber-800 hover:bg-amber-100">
              <AlertTriangle size={13} /> 回传映射问题
            </button>
            <button type="button" onClick={() => { setFrameLoading(true); setFrameRevision(value => value + 1) }} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-medium text-slate-600 hover:bg-slate-50">
              <RotateCcw size={13} /> 刷新
            </button>
          </div>
          {feedbackOpen && (
            <div className="mt-3 grid gap-2 rounded-xl border border-amber-200 bg-amber-50/70 p-3 md:grid-cols-[180px_1fr_1fr_auto]">
              <select value={feedbackCode} onChange={event => setFeedbackCode(event.target.value)} className="h-9 rounded-lg border border-amber-200 bg-white px-2 text-xs text-slate-700">
                <option value="step_mapping_mismatch">步骤映射不一致</option>
                <option value="weak_relation">关系较弱</option>
                <option value="incorrect_knowledge_scope">知识点范围不准</option>
                <option value="incorrect_skill_scope">技能范围不准</option>
                <option value="missing_prerequisite">缺少前置知识</option>
                <option value="unsupported_task_fact">任务事实缺少依据</option>
                <option value="other">其他</option>
              </select>
              <input value={feedbackMessage} onChange={event => setFeedbackMessage(event.target.value)} placeholder="说明哪个关系不准确" className="h-9 rounded-lg border border-amber-200 bg-white px-3 text-xs outline-none focus:border-amber-500" />
              <input value={feedbackCorrection} onChange={event => setFeedbackCorrection(event.target.value)} placeholder="建议如何修正（可选）" className="h-9 rounded-lg border border-amber-200 bg-white px-3 text-xs outline-none focus:border-amber-500" />
              <button type="button" onClick={submitFeedback} disabled={!feedbackMessage.trim() || feedbackSubmitting} className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg bg-amber-700 px-3 text-xs font-semibold text-white disabled:opacity-50">
                {feedbackSubmitting ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}提交复核
              </button>
            </div>
          )}
          {feedbackStatus && <p className="mt-2 text-[11px] text-slate-600">{feedbackStatus}</p>}
          {resultSyncStatus && <p className="mt-2 text-[11px] text-indigo-700">{resultSyncStatus}</p>}
        </header>
        <div className="relative min-h-0 flex-1 bg-white">
          {frameLoading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-white text-sm text-slate-500">
              <Loader2 size={17} className="mr-2 animate-spin text-indigo-600" />正在打开个性化学习项目…
            </div>
          )}
          <ResponsiveEmbeddedProject
            src={launched.redirect_url}
            title={`个性化学习：${knowledge.name}`}
            revision={frameRevision}
            onLoad={() => setFrameLoading(false)}
            onFrame={frame => { embeddedFrameRef.current = frame }}
          />
        </div>
      </main>
    )
  }

  return (
    <main className="h-full overflow-y-auto bg-slate-100 px-5 py-6 sm:px-8">
      <div className="mx-auto max-w-5xl pb-16">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Link to={entry.navigation.return_path} className="inline-flex h-9 items-center gap-1.5 border border-slate-200 bg-white px-3 text-xs font-medium text-slate-600 hover:border-slate-400">
            <ArrowLeft size={13} /> 返回学习型任务
          </Link>
          <span className="text-[11px] text-slate-500">JSON 由系统直接交接，无需下载或重新上传。</span>
        </div>

        <header className="border border-indigo-200 bg-white p-7 shadow-sm sm:p-9">
          <div className="flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em]">
            <span className="bg-indigo-50 px-2 py-1 text-indigo-700">个性化学习生成入口</span>
            <span className="bg-emerald-50 px-2 py-1 text-emerald-700"><CheckCircle2 size={11} className="mr-1 inline" />JSON 已校验</span>
            <span className="font-mono text-slate-400">{entry.entry_id}</span>
          </div>
          <h1 className="mt-4 text-2xl font-bold tracking-tight text-slate-950 sm:text-3xl">{knowledge.name}</h1>
          <p className="mt-3 text-sm leading-7 text-slate-600">{knowledge.scope || knowledge.description || '本知识点由学习型任务的已校验步骤显式引用。'}</p>
          <div className="mt-5 border-l-2 border-indigo-500 pl-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">来源任务</p>
            <p className="mt-1 text-sm font-semibold text-slate-800">{entry.task_context.enterprise_task_name}</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">{entry.task_context.enterprise_task_description}</p>
          </div>
          <button
            type="button"
            onClick={launch}
            disabled={launching}
            className="mt-6 inline-flex h-11 items-center gap-2 bg-indigo-600 px-5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-70"
          >
            {launching ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {launching ? '正在创建个性化学习项目…' : '开始生成个性化学习'}
            {!launching && <ArrowRight size={15} />}
          </button>
          <p className="mt-2 text-[11px] leading-5 text-slate-500">
            将当前知识点、{sourceStepCount} 个来源步骤及强关联技能安全交接给个性化学习。
          </p>
          {error && (
            <div className="mt-4 border border-red-200 bg-red-50 px-4 py-3 text-xs leading-5 text-red-700">
              {error}
            </div>
          )}
        </header>

        <section className="mt-5 grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center gap-2"><Network size={16} className="text-indigo-600" /><h2 className="text-sm font-bold text-slate-900">知识—步骤—技能强关系</h2></div>
            <div className="mt-4 space-y-3">
              {entry.focus.source_steps.map((step, index) => (
                <article key={step.step_id} className="border border-slate-200 bg-slate-50 p-4">
                  <p className="text-[10px] font-semibold text-indigo-600">来源步骤 {String(index + 1).padStart(2, '0')}</p>
                  <h3 className="mt-1 text-sm font-semibold text-slate-900">{step.name}</h3>
                  <p className="mt-2 text-xs leading-6 text-slate-600">{step.action}</p>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <div className="border-l-2 border-sky-400 bg-white px-3 py-2 text-[11px] leading-5 text-slate-600"><b className="text-slate-800">产物：</b>{step.deliverable}</div>
                    <div className="border-l-2 border-emerald-500 bg-white px-3 py-2 text-[11px] leading-5 text-slate-600"><b className="text-slate-800">检查：</b>{step.check}</div>
                  </div>
                </article>
              ))}
            </div>
          </div>

          <aside className="space-y-5">
            <section className="border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-sm font-bold text-slate-900">强相关技能</h2>
              <div className="mt-3 space-y-2">
                {entry.focus.strongly_related_skills.map(skill => (
                  <div key={skill.skill_id} className="border border-amber-200 bg-amber-50 px-3 py-3">
                    <p className="text-xs font-semibold text-amber-900">{skill.name}</p>
                    <p className="mt-1 text-[11px] leading-5 text-amber-800">{skill.observable_action || skill.description || '通过对应任务产物验证。'}</p>
                  </div>
                ))}
              </div>
            </section>
            <section className="border border-slate-200 bg-white p-6 shadow-sm">
              <div className="flex items-center gap-2"><Braces size={15} className="text-slate-500" /><h2 className="text-sm font-bold text-slate-900">生成边界</h2></div>
              <p className="mt-3 text-xs leading-6 text-slate-600">{entry.generation_contract.purpose}</p>
              <p className="mt-3 text-[11px] leading-5 text-slate-500">下游可生成学习目标、内容、顺序、练习和评价；不得改写企业任务、作业步骤和强关系。</p>
            </section>
          </aside>
        </section>

        {displaySituation(entry.task_context.work_situation) && (
          <section className="mt-5 border border-slate-200 bg-white p-5 text-xs leading-6 text-slate-600 shadow-sm">
            <b className="text-slate-900">工作情境：</b>{displaySituation(entry.task_context.work_situation)}
          </section>
        )}
      </div>
    </main>
  )
}
