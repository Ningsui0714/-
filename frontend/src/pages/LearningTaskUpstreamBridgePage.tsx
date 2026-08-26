import { ArrowRight, Braces, CheckCircle2, Loader2, Network, UploadCloud } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import {
  generateLearningTaskConversion,
  submitCompetencyGraphHandoff,
} from '../services/api'

type UpstreamHandoff = Record<string, any> & {
  schema_version: 'competency-graph-learning-task-handoff-v1'
  upstream_task_id: string
  correlation_id: string
  task_name: string
  task_brief?: string
}

function errorMessage(error: any) {
  return error?.response?.data?.detail || error?.message || '上游任务接入失败。'
}

function validateHandoff(value: unknown): UpstreamHandoff {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('交接内容必须是 JSON 对象。')
  }
  const handoff = value as UpstreamHandoff
  if (handoff.schema_version !== 'competency-graph-learning-task-handoff-v1') {
    throw new Error('上游交接协议版本不正确。')
  }
  for (const key of ['upstream_task_id', 'correlation_id', 'task_name'] as const) {
    if (typeof handoff[key] !== 'string' || !handoff[key].trim()) {
      throw new Error(`上游交接缺少 ${key}。`)
    }
  }
  return handoff
}

export default function LearningTaskUpstreamBridgePage() {
  const location = useLocation()
  const navigate = useNavigate()
  const autoHandledRef = useRef(false)
  const [jsonText, setJsonText] = useState('')
  const [processing, setProcessing] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  useWorkspaceTitle('岗位任务接入', { kind: 'wf03' })

  const processHandoff = useCallback(async (raw: unknown) => {
    if (processing) return
    setProcessing(true)
    setError('')
    try {
      const handoff = validateHandoff(raw)
      setJsonText(JSON.stringify(handoff, null, 2))
      setStatus('已校验岗位任务，正在锁定上游关系…')
      const accepted = await submitCompetencyGraphHandoff(handoff)
      const acceptedTaskCardId = String(accepted?.task_card_id || '').trim()
      if (acceptedTaskCardId) {
        navigate(`/wf03/tasks/${encodeURIComponent(acceptedTaskCardId)}`)
        return
      }
      setStatus('上游关系已锁定，正在生成学习型任务…')
      const generated = await generateLearningTaskConversion(
        [handoff.task_name, handoff.task_brief].filter(Boolean).join('：'),
        undefined,
        `upstream-${handoff.correlation_id}`.slice(0, 120),
      )
      if (generated.status === 'success' && generated.task_card_id) {
        navigate(`/wf03/tasks/${encodeURIComponent(generated.task_card_id)}`)
        return
      }
      setStatus('')
      setError(generated.message || '任务已接收，但还需要补充信息才能生成。')
    } catch (failure) {
      setStatus('')
      setError(errorMessage(failure))
    } finally {
      setProcessing(false)
    }
  }, [navigate, processing])

  useEffect(() => {
    if (autoHandledRef.current) return
    const stateHandoff = (location.state as { handoff?: unknown } | null)?.handoff
    const handoffKey = new URLSearchParams(location.search).get('handoff_key')
    let storedHandoff: unknown
    if (handoffKey) {
      try {
        storedHandoff = JSON.parse(
          sessionStorage.getItem(`learnflow.upstream-handoff:${handoffKey}`) || 'null',
        )
      } catch {
        storedHandoff = null
      }
    }
    const initial = stateHandoff || storedHandoff
    if (!initial) return
    autoHandledRef.current = true
    void processHandoff(initial)
  }, [location.search, location.state, processHandoff])

  useEffect(() => {
    const receiveTask = (event: MessageEvent) => {
      if (
        event.origin !== window.location.origin
        || event.data?.type !== 'learnflow:competency-task-selected'
      ) return
      void processHandoff(event.data.handoff)
    }
    window.addEventListener('message', receiveTask)
    return () => window.removeEventListener('message', receiveTask)
  }, [processHandoff])

  const submitText = () => {
    try {
      void processHandoff(JSON.parse(jsonText))
    } catch {
      setError('JSON 格式无法解析，请检查逗号、引号和括号。')
    }
  }

  return (
    <main className="h-full overflow-y-auto bg-slate-100 px-5 py-7 sm:px-8">
      <div className="mx-auto max-w-5xl">
        <header className="border border-slate-200 bg-white p-7 shadow-sm sm:p-9">
          <div className="flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-indigo-700">
            <span className="bg-indigo-50 px-2 py-1"><Network size={12} className="mr-1 inline" />岗位能力图谱交接</span>
            <span className="bg-emerald-50 px-2 py-1 text-emerald-700"><CheckCircle2 size={12} className="mr-1 inline" />稳定 ID 锁定</span>
          </div>
          <h1 className="mt-4 text-2xl font-bold tracking-tight text-slate-950 sm:text-3xl">将选中的岗位任务转为学习型任务</h1>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-600">上游点击任务节点后，可以通过页面跳转状态、同源窗口消息或临时交接键传入 JSON。系统会先校验任务身份和关系，再进入生成。</p>
        </header>

        <section className="mt-5 grid gap-5 lg:grid-cols-[0.78fr_1.22fr]">
          <div className="border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-sm font-bold text-slate-900">自动接入顺序</h2>
            <ol className="mt-4 space-y-3 text-xs leading-6 text-slate-600">
              {['接收单个岗位任务节点', '校验 Schema 与稳定 ID', '锁定知识—技能关系', '调用学习型任务生成', '在中央工作区打开任务网页'].map((item, index) => (
                <li key={item} className="flex gap-3 border-l-2 border-indigo-200 pl-3">
                  <b className="text-indigo-700">{String(index + 1).padStart(2, '0')}</b><span>{item}</span>
                </li>
              ))}
            </ol>
            {status && <p className="mt-5 border border-indigo-200 bg-indigo-50 px-3 py-3 text-xs leading-5 text-indigo-700"><Loader2 size={13} className="mr-1.5 inline animate-spin" />{status}</p>}
            {error && <p className="mt-5 border border-red-200 bg-red-50 px-3 py-3 text-xs leading-5 text-red-700">{error}</p>}
          </div>

          <div className="border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center gap-2"><Braces size={16} className="text-indigo-600" /><h2 className="text-sm font-bold text-slate-900">交接 JSON 测试区</h2></div>
            <p className="mt-2 text-[11px] leading-5 text-slate-500">正常对接时由上游页面自动传入；这里保留手动粘贴，用于联调和验收。</p>
            <textarea
              value={jsonText}
              onChange={event => setJsonText(event.target.value)}
              placeholder='{"schema_version":"competency-graph-learning-task-handoff-v1", ...}'
              className="mt-4 h-72 w-full resize-y border border-slate-200 bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-100 outline-none focus:border-indigo-500"
              spellCheck={false}
            />
            <button type="button" onClick={submitText} disabled={processing || !jsonText.trim()} className="mt-4 inline-flex h-10 items-center gap-2 bg-indigo-600 px-4 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
              {processing ? <Loader2 size={15} className="animate-spin" /> : <UploadCloud size={15} />}
              校验并生成 <ArrowRight size={14} />
            </button>
          </div>
        </section>
      </div>
    </main>
  )
}
