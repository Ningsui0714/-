import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, ExternalLink, FilePenLine, MessageSquarePlus, Plus, RefreshCw } from 'lucide-react'
import {
  createTutorSession, sendTutorTurn, confirmTutorAction, cancelTutorAction,
  getTutorAction, acceptProjectProposal, dismissProjectProposal,
  getProjectProposal, refreshProjectProposalSources, updateProjectProposal,
  createLearningTaskPlan,
} from '../../services/api'
import type { LearningTaskPlanRun, ProjectProposal, ProjectProposalSource } from '../../services/api'
import { shouldSendMessageOnEnter } from '../../utils/keyboard'
import ProjectProposalDock from './ProjectProposalDock'
import LocalAgentRunCard from './LocalAgentRunCard'

interface Message {
  id?: number
  role: 'user' | 'assistant'
  content: string
  meta_data?: Record<string, any>
}

interface Props {
  projectId?: number
  checkpointId?: number
  turnContext?: Record<string, any>
  quickPrompts?: string[]
  className?: string
  onProjectChange?: (project: any) => void
  onRoadmapUpdate?: (roadmap: any) => void
  onCheckpointChange?: (checkpoint: { id: number; title?: string }) => void
  onProposalAccepted?: (project: any) => void
  proposalDragEnabled?: boolean
  projectProposal?: ProjectProposal | null
  projectSources?: Array<{ url?: string }>
  candidateSourcesRefreshing?: boolean
  addingCandidateUrl?: string | null
  onRefreshCandidateSources?: () => void | Promise<void>
  onAddCandidateSource?: (candidate: ProjectProposalSource) => void | Promise<void>
  learningTaskGenerationEnabled?: boolean
  onLearningTaskPlanCreated?: (result: LearningTaskPlanRun) => void
}

const terminal = new Set(['completed', 'failed', 'canceled'])

const sourceQualityLabels: Record<'excellent' | 'strong' | 'relevant', string> = {
  excellent: '高度匹配',
  strong: '强相关',
  relevant: '可参考',
}

function CandidateSourcesAttachment({
  proposal, projectSources, refreshing, addingUrl, completed, busy, onRefresh, onAdd, onDone,
}: {
  proposal: ProjectProposal
  projectSources: Array<{ url?: string }>
  refreshing: boolean
  addingUrl?: string | null
  completed: boolean
  busy: boolean
  onRefresh?: () => void | Promise<void>
  onAdd?: (candidate: ProjectProposalSource) => void | Promise<void>
  onDone?: () => void | Promise<void>
}) {
  const candidates = proposal.artifact.candidate_sources || []
  const searching = refreshing || ['queued', 'searching'].includes(proposal.source_status)
  const discovered = proposal.artifact.source_search_discovered_count || candidates.length
  return (
    <div className="mt-2 overflow-hidden border border-gray-200 bg-white rounded-lg" data-testid="tutor-candidate-sources">
      <div className="flex items-start justify-between gap-3 border-b border-gray-100 px-3 py-2.5">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-gray-900">候选学习来源</p>
          <p className="mt-0.5 text-[10px] text-gray-400">
            第 {proposal.artifact.source_search_generation || 0} 次检索
            {' · '}从 {discovered} 个仓库中选出 {candidates.length} 个
          </p>
        </div>
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            disabled={searching}
            title="重新搜索候选来源"
            aria-label="重新搜索候选来源"
            className="flex h-7 w-7 shrink-0 items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-800 disabled:cursor-wait disabled:text-indigo-500 rounded"
          >
            <RefreshCw size={14} className={searching ? 'animate-spin' : ''} />
          </button>
        )}
      </div>
      {searching && (
        <p className="border-b border-gray-100 bg-indigo-50 px-3 py-2 text-[11px] text-indigo-700">
          正在重新检索并排序，当前候选暂时保留。
        </p>
      )}
      {proposal.source_status === 'failed' && (
        <p className="border-b border-gray-100 bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
          本次检索失败，可以点击刷新重试。
        </p>
      )}
      <div className="divide-y divide-gray-100 px-3">
        {candidates.map(candidate => {
          const alreadyAdded = projectSources.some(source => source.url === candidate.url)
          return (
            <div key={candidate.url} className="flex items-start gap-2 py-2.5">
              <a
                href={candidate.url}
                target="_blank"
                rel="noreferrer"
                className="flex min-w-0 flex-1 items-start gap-2 text-gray-700 hover:text-indigo-700"
              >
                <ExternalLink size={13} className="mt-0.5 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="truncate text-xs font-medium">{candidate.title}</span>
                    {candidate.quality && (
                      <span className="shrink-0 bg-indigo-50 px-1.5 py-0.5 text-[9px] text-indigo-700 rounded">
                        {sourceQualityLabels[candidate.quality]}
                      </span>
                    )}
                  </span>
                  {candidate.reason && (
                    <span className="mt-0.5 block text-[10px] leading-4 text-gray-500">{candidate.reason}</span>
                  )}
                </span>
                {!!candidate.stars && (
                  <span className="shrink-0 text-[10px] text-gray-400">{candidate.stars.toLocaleString()} stars</span>
                )}
              </a>
              {onAdd && (
                <button
                  type="button"
                  disabled={alreadyAdded || !!addingUrl}
                  onClick={() => onAdd(candidate)}
                  title={alreadyAdded ? '已添加到项目' : '添加并处理来源'}
                  aria-label={alreadyAdded ? `已添加 ${candidate.title}` : `添加来源 ${candidate.title}`}
                  className="flex h-7 w-7 shrink-0 items-center justify-center text-indigo-600 hover:bg-indigo-50 disabled:text-gray-300 rounded"
                >
                  <Plus size={14} />
                </button>
              )}
            </div>
          )
        })}
        {candidates.length === 0 && proposal.source_status === 'completed' && (
          <p className="py-3 text-xs text-gray-400">暂未找到达到相关性门槛的仓库。</p>
        )}
      </div>
      <div className="flex flex-col gap-2 border-t border-gray-100 bg-gray-50 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[10px] leading-4 text-gray-500">
          资料选好后，Tutor 会整理路线骨架和需要确认的点。
        </p>
        <button
          type="button"
          onClick={onDone}
          disabled={completed || busy || searching || !onDone}
          className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 self-end bg-gray-900 px-3 text-xs font-medium text-white hover:bg-gray-700 disabled:cursor-default disabled:bg-gray-200 disabled:text-gray-500 rounded sm:self-auto"
        >
          <Check size={14} />
          {completed ? '已完成来源选择' : busy ? '正在提交' : '添加完毕'}
        </button>
      </div>
    </div>
  )
}

function normalizeTutorContent(content: unknown): string {
  if (typeof content !== 'string') return String(content ?? '')
  const original = content.trim()
  // Older sessions may contain the verbose pre-configuration fallback. Keep
  // the history intact, but present the same explicit status as new turns.
  if (
    original === '未接入模型。'
    || original === '我可以继续帮你整理学习问题；要进行 AI 讲解，请先在设置页配置 LLM API Key。'
  ) {
    return '主 Agent 对话模型尚未配置；项目、复习、讲义、练习与文件功能仍可正常使用。'
  }
  let text = original
  if (text.startsWith('```')) {
    const lines = text.split('\n')
    const hasClosingFence = lines.length > 1 && lines[lines.length - 1].trim() === '```'
    text = lines.slice(1, hasClosingFence ? -1 : undefined).join('\n').trim()
  }
  try {
    const parsed = JSON.parse(text)
    if (parsed && typeof parsed === 'object' && typeof parsed.reply === 'string') {
      return parsed.reply.trim()
    }
  } catch {
    const objectStart = text.indexOf('{')
    if (objectStart > 0) {
      try {
        const parsed = JSON.parse(text.slice(objectStart))
        if (parsed && typeof parsed === 'object' && typeof parsed.reply === 'string') {
          return parsed.reply.trim()
        }
      } catch {
        // Keep non-JSON model output as-is.
      }
    }
  }
  return original
}

export default function TutorPanel({
  projectId, checkpointId, turnContext = {}, quickPrompts = [], className = '', onProjectChange, onRoadmapUpdate, onCheckpointChange,
  onProposalAccepted, proposalDragEnabled = false, projectProposal,
  projectSources = [], candidateSourcesRefreshing = false, addingCandidateUrl,
  onRefreshCandidateSources, onAddCandidateSource,
  learningTaskGenerationEnabled = false, onLearningTaskPlanCreated,
}: Props) {
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [action, setAction] = useState<any>(null)
  const [summary, setSummary] = useState<any>(null)
  const [proposals, setProposals] = useState<ProjectProposal[]>([])
  const [proposalBusy, setProposalBusy] = useState(false)
  const [milestoneNotice, setMilestoneNotice] = useState<any>(null)
  const [learningTaskMode, setLearningTaskMode] = useState(() => (
    learningTaskGenerationEnabled
    && new URLSearchParams(window.location.search).get('tool') === 'learning-task-conversion'
  ))
  const [startingConversation, setStartingConversation] = useState(false)
  const messagesRef = useRef<HTMLDivElement>(null)
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    let active = true
    setSessionId(null)
    setMessages([])
    setAction(null)
    setProposals([])
    createTutorSession({
      session_type: checkpointId ? 'checkpoint' : projectId ? 'project' : 'global',
      project_id: projectId,
      checkpoint_id: checkpointId,
    }).then(data => {
      if (!active) return
      setSessionId(data.id)
      setMessages((data.messages || [])
        .filter((m: any) => m.role === 'user' || m.role === 'assistant')
        .map((m: any) => ({ ...m, content: normalizeTutorContent(m.content) })))
      setAction(data.action_card || null)
      setSummary(data.state_summary || null)
      setProposals(data.project_proposals || [])
    }).catch(() => {})
    return () => {
      active = false
      if (pollRef.current) window.clearTimeout(pollRef.current)
    }
  }, [projectId, checkpointId])

  useEffect(() => {
    const pending = proposals.find(item => ['queued', 'searching'].includes(item.source_status))
    if (!pending) return
    const timer = window.setTimeout(async () => {
      try {
        const latest = await getProjectProposal(pending.id)
        setProposals(items => items.map(item => item.id === latest.id ? latest : item))
      } catch {}
    }, 1800)
    return () => window.clearTimeout(timer)
  }, [proposals])

  useEffect(() => {
    const element = messagesRef.current
    if (!element) return
    const projectOpening = Boolean(
      projectId
      && messages.length > 0
      && !messages.some(message => message.role === 'user')
      && messages.some(message => message.meta_data?.message_kind === 'project_welcome')
    )
    element.scrollTop = projectOpening ? 0 : element.scrollHeight
  }, [messages, action, projectId])

  const applyResult = (data: any) => {
    if (data.message) {
      setMessages(prev => [...prev, { role: 'assistant', content: normalizeTutorContent(data.message) }])
    }
    setSummary((previous: any) => data.state_summary || previous)
    if (Array.isArray(data.project_proposals)) setProposals(data.project_proposals)
    if (data.awarded_badges?.length) setMilestoneNotice(data.awarded_badges[0])
    const nextAction = data.action_card || data.executed_action || null
    setAction(nextAction)
    const result = data.executed_action?.result || nextAction?.result || {}
    if (result.project && result.navigate_to_project) onProjectChange?.(result.project)
    if (result.updated_roadmap) onRoadmapUpdate?.(result.updated_roadmap)
    if (result.checkpoint) onCheckpointChange?.(result.checkpoint)
    if (nextAction?.status === 'running') pollAction(nextAction.id)
  }

  const updateProposal = async (
    proposal: ProjectProposal,
    patch: Record<string, any>,
    lockFields: string[] = [],
    unlockFields: string[] = [],
  ) => {
    setProposalBusy(true)
    try {
      const latest = await updateProjectProposal(proposal.id, {
        patch,
        lock_fields: lockFields,
        unlock_fields: unlockFields,
        client_event_id: globalThis.crypto?.randomUUID?.() || `proposal-edit-${proposal.id}-${Date.now()}`,
      })
      setProposals(items => items.map(item => item.id === latest.id ? latest : item))
    } finally {
      setProposalBusy(false)
    }
  }

  const acceptProposal = async (proposal: ProjectProposal) => {
    if (proposalBusy) return
    setProposalBusy(true)
    try {
      const data = await acceptProjectProposal(
        proposal.id,
        globalThis.crypto?.randomUUID?.() || `proposal-accept-${proposal.id}-${Date.now()}`,
      )
      applyResult(data)
      const project = data.executed_action?.result?.project
      if (project) onProposalAccepted?.(project)
    } catch (e: any) {
      setMessages(prev => [...prev, {
        role: 'assistant', content: e?.response?.data?.detail || '项目提案没有创建成功。',
      }])
    } finally {
      setProposalBusy(false)
    }
  }

  const dismissProposal = async (proposal: ProjectProposal) => {
    try {
      await dismissProjectProposal(proposal.id)
      setProposals(items => items.filter(item => item.id !== proposal.id))
    } catch {}
  }

  const refreshProposalSources = async (proposal: ProjectProposal) => {
    try {
      const latest = await refreshProjectProposalSources(proposal.id)
      setProposals(items => items.map(item => item.id === latest.id ? latest : item))
    } catch (e: any) {
      setMessages(prev => [...prev, {
        role: 'assistant', content: e?.response?.data?.detail || '候选来源刷新失败，可以稍后重试。',
      }])
    }
  }

  const pollAction = (actionId: number) => {
    if (pollRef.current) window.clearTimeout(pollRef.current)
    const poll = async () => {
      try {
        const latest = await getTutorAction(actionId)
        setAction(latest)
        if (terminal.has(latest.status)) {
          const result = latest.result || {}
          if (result.project) onProjectChange?.(result.project)
          if (result.updated_roadmap) onRoadmapUpdate?.(result.updated_roadmap)
          return
        }
      } catch { return }
      pollRef.current = window.setTimeout(poll, 1800)
    }
    pollRef.current = window.setTimeout(poll, 900)
  }

  const candidateSourcesCompleted = Boolean(
    projectProposal
    && messages.some(message => (
      message.role === 'user'
      && message.meta_data?.interaction === 'candidate_sources_completed'
      && Number(message.meta_data?.proposal_id) === projectProposal.id
    )),
  )

  const finishCandidateSources = async () => {
    if (!sessionId || loading || !projectProposal || candidateSourcesCompleted) return
    const content = '候选来源选择完毕，请继续安排下一步。'
    const context = {
      interaction: 'candidate_sources_completed',
      proposal_id: projectProposal.id,
    }
    setMessages(previous => [...previous, { role: 'user', content, meta_data: context }])
    setLoading(true)
    try {
      const data = await sendTutorTurn(sessionId, {
        message: content,
        project_id: projectId,
        checkpoint_id: checkpointId,
        client_turn_id: globalThis.crypto?.randomUUID?.() || `sources-done-${projectProposal.id}-${Date.now()}`,
        context,
      })
      applyResult(data)
    } catch (e: any) {
      setMessages(previous => [...previous, {
        role: 'assistant',
        content: e?.response?.data?.detail || '来源选择状态没有提交成功，请稍后再试。',
      }])
    } finally {
      setLoading(false)
    }
  }

  const startNewConversation = async () => {
    if (loading || startingConversation) return
    setStartingConversation(true)
    try {
      const data = await createTutorSession({
        session_type: checkpointId ? 'checkpoint' : projectId ? 'project' : 'global',
        project_id: projectId,
        checkpoint_id: checkpointId,
        force_new: true,
      })
      setSessionId(data.id)
      setMessages((data.messages || [])
        .filter((message: any) => message.role === 'user' || message.role === 'assistant')
        .map((message: any) => ({ ...message, content: normalizeTutorContent(message.content) })))
      setAction(data.action_card || null)
      setSummary(data.state_summary || null)
      setProposals(data.project_proposals || [])
      setInput('')
      setLearningTaskMode(false)
    } catch (error: any) {
      setMessages(previous => [...previous, {
        role: 'assistant',
        content: error?.response?.data?.detail || '新对话创建失败，请稍后重试。',
      }])
    } finally {
      setStartingConversation(false)
    }
  }

  const send = async (selectedActionId?: number, presetText?: string, forceTutor = false) => {
    if (!sessionId || loading) return
    const text = (presetText ?? input).trim()
    if (!text && !selectedActionId) return
    if (text) {
      setMessages(prev => [...prev, { role: 'user', content: text }])
      setInput('')
    }
    setLoading(true)
    try {
      if (learningTaskGenerationEnabled && learningTaskMode && text && !selectedActionId && !forceTutor) {
        const clientTurnId = globalThis.crypto?.randomUUID?.() || `learning-task-${Date.now()}-${Math.random()}`
        const planned = await createLearningTaskPlan(text, sessionId, clientTurnId)
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: planned.message,
          meta_data: {
            message_kind: 'learning_task_plan',
            plan_run_id: planned.run_id,
          },
        }])
        onLearningTaskPlanCreated?.(planned)
        setLearningTaskMode(false)
        return
      }
      const data = await sendTutorTurn(sessionId, {
        message: text || '确认',
        project_id: projectId,
        checkpoint_id: checkpointId,
        selected_action_id: selectedActionId,
        client_turn_id: globalThis.crypto?.randomUUID?.() || `turn-${Date.now()}-${Math.random()}`,
        context: turnContext,
      })
      applyResult(data)
    } catch (e: any) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: e?.response?.data?.detail || '这次没有执行成功，请稍后再试。',
      }])
    } finally {
      // The generation branches return as soon as they have handed the task
      // page to the workspace. Keep loading cleanup in finally so navigation,
      // clarification and revision responses cannot leave the global Agent
      // composer permanently disabled.
      setLoading(false)
    }
  }

  const confirm = async () => {
    if (!action?.id || loading) return
    setLoading(true)
    try {
      const data = await confirmTutorAction(action.id)
      applyResult(data)
    } catch (e: any) {
      setMessages(prev => [...prev, {
        role: 'assistant', content: e?.response?.data?.detail || '行动没有执行成功。',
      }])
    }
    setLoading(false)
  }

  const cancel = async () => {
    if (!action?.id) return
    try {
      await cancelTutorAction(action.id)
      setAction(null)
    } catch {}
  }

  return (
    <section className={`flex min-h-0 flex-col overflow-hidden border border-gray-200 bg-white rounded-lg ${className}`}>
      <header className="flex min-h-14 items-center justify-between border-b border-gray-200 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-gray-900">{checkpointId ? '关卡 Tutor' : projectId ? '学习 Tutor' : '主 Agent'}</h2>
          <p className="truncate text-xs text-gray-500">
            {checkpointId
              ? (summary?.active_checkpoint?.title || '正在接入本关讲义、练习与文件上下文...')
              : projectId
              ? (summary?.active_checkpoint?.title
                || (summary?.active_project?.name
                  ? `负责「${summary.active_project.name}」的路线、来源与课前后答疑`
                  : '正在接入项目上下文...'))
              : '学习方向、目标澄清、简要答疑与学习状态支持'}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {projectId && summary?.progress?.total > 0 && (
            <span className="text-xs tabular-nums text-gray-500">
              {summary.progress.completed}/{summary.progress.total} 已验证
            </span>
          )}
          <button
            type="button"
            onClick={startNewConversation}
            disabled={loading || startingConversation || !sessionId}
            title="新建对话"
            aria-label="新建对话"
            className="flex h-8 items-center gap-1 rounded-md border border-gray-200 bg-white px-2 text-[11px] font-medium text-gray-600 hover:border-gray-300 hover:bg-gray-50 disabled:cursor-wait disabled:opacity-50"
          >
            <MessageSquarePlus size={13} /> {startingConversation ? '新建中' : '新建对话'}
          </button>
        </div>
      </header>

      <ProjectProposalDock
        proposals={proposals}
        dragEnabled={proposalDragEnabled}
        busy={proposalBusy}
        onAccept={acceptProposal}
        onDismiss={dismissProposal}
        onRefreshSources={refreshProposalSources}
        onUpdate={updateProposal}
      />

      <div ref={messagesRef} className="flex-1 space-y-3 overflow-x-hidden overflow-y-auto p-4">
        {milestoneNotice && (
          <div className="flex items-start justify-between gap-3 border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 rounded-lg">
            <div><p className="font-semibold">学习路径新增里程碑</p><p className="mt-1">{milestoneNotice.title}</p></div>
            <button onClick={() => setMilestoneNotice(null)} title="关闭" className="text-amber-700 hover:text-amber-950">×</button>
          </div>
        )}
        {messages.length === 0 && (
          <div className="py-8 text-center text-sm text-gray-400">
            {checkpointId ? '本关讲义和练习共用这段 Tutor 会话。' : projectId ? '正在接入项目上下文...' : '今天想聊哪件学习上的事？'}
          </div>
        )}
        {messages.map((message, index) => {
          const attachment = message.meta_data?.attachment
          const showCandidateSources = Boolean(
            message.role === 'assistant'
            && projectProposal
            && attachment?.type === 'candidate_sources'
            && Number(attachment.proposal_id) === projectProposal.id
          )
          return (
            <div key={message.id ? `stored-${message.id}` : `local-${index}`} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`min-w-0 ${message.role === 'user' ? 'max-w-[88%]' : 'w-full max-w-[94%]'}`}>
                <div className={`px-3 py-2 text-sm leading-6 rounded-lg ${
                  message.role === 'user'
                    ? 'whitespace-pre-wrap bg-gray-900 text-white'
                    : 'tutor-markdown border border-gray-200 bg-gray-50 text-gray-800'
                }`}>
                  {message.role === 'assistant' ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{normalizeTutorContent(message.content)}</ReactMarkdown>
                  ) : message.content}
                </div>
                {showCandidateSources && projectProposal && (
                  <CandidateSourcesAttachment
                    proposal={projectProposal}
                    projectSources={projectSources}
                    refreshing={candidateSourcesRefreshing}
                    addingUrl={addingCandidateUrl}
                    completed={candidateSourcesCompleted}
                    busy={loading || !!addingCandidateUrl}
                    onRefresh={onRefreshCandidateSources}
                    onAdd={onAddCandidateSource}
                    onDone={finishCandidateSources}
                  />
                )}
                {message.meta_data?.local_agent_run_id && (
                  <LocalAgentRunCard runId={Number(message.meta_data.local_agent_run_id)} />
                )}
              </div>
            </div>
          )
        })}

        {action && (
          <div className={`border p-3 rounded-lg ${
            action.status === 'failed' ? 'border-red-200 bg-red-50' :
            action.status === 'completed' ? 'border-emerald-200 bg-emerald-50' :
            'border-indigo-200 bg-indigo-50'
          }`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-900">{action.title}</p>
                {action.reason && <p className="mt-1 text-xs leading-5 text-gray-600">{action.reason}</p>}
                {action.expected_result && <p className="mt-1 text-xs text-gray-500">{action.expected_result}</p>}
                {action.target_summary?.task_type && (
                  <div className="mt-2 space-y-0.5 border border-indigo-100 bg-white/70 p-2 text-[10px] text-slate-600 rounded">
                    <p>Agent：{action.target_summary.profile_name} · {action.target_summary.adapter}</p>
                    <p>任务：{action.target_summary.task_type}</p>
                    <p>沙箱：{action.target_summary.sandbox_policy} · 联网：{action.target_summary.network_policy}{action.target_summary.network_boundary_enforced === false ? '（未受管）' : ''}</p>
                    {Array.isArray(action.target_summary.excluded_paths) && <p>排除：{action.target_summary.excluded_paths.join('、')}</p>}
                  </div>
                )}
                {action.status === 'running' && (
                  <div className="mt-2 text-xs text-indigo-700">
                    <p>{action.task?.progress?.message || '正在执行...'}</p>
                    {action.task?.progress?.total > 0 && (
                      <div className="mt-2 h-1.5 overflow-hidden bg-indigo-100 rounded">
                        <div
                          className="h-full bg-indigo-600 transition-all"
                          style={{ width: `${Math.min(100, Math.round(100 * (action.task.progress.current || 0) / action.task.progress.total))}%` }}
                        />
                      </div>
                    )}
                  </div>
                )}
                {action.status === 'completed' && (
                  <p className="mt-2 text-xs text-emerald-700">
                    {action.result?.user_message || '已完成'}
                  </p>
                )}
                {action.status === 'failed' && <p className="mt-2 text-xs text-red-700">{action.error?.message || '执行失败'}</p>}
              </div>
              {action.status === 'pending_confirmation' && (
                <div className="flex shrink-0 gap-2">
                  <button onClick={cancel} className="px-2.5 py-1.5 text-xs text-gray-600 hover:bg-white rounded">暂不</button>
                  <button onClick={confirm} className="bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 rounded">{action.primary_label || '确认'}</button>
                </div>
              )}
            </div>
          </div>
        )}
        {action?.result?.local_agent_run?.id && !messages.some(message => (
          Number(message.meta_data?.local_agent_run_id) === Number(action.result.local_agent_run.id)
        )) && (
          <LocalAgentRunCard runId={Number(action.result.local_agent_run.id)} />
        )}

        {loading && (
          <div className="flex justify-start">
            <div className="border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-500 rounded-lg">
              {learningTaskMode
                ? '正在锁定任务契约并生成可检查的 Agent Plan…'
                : '正在思考...'}
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-gray-200 p-3">
        {quickPrompts.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {quickPrompts.map(prompt => (
              <button
                key={prompt}
                type="button"
                onClick={() => send(undefined, prompt, true)}
                disabled={loading || !sessionId}
                className="rounded-full border border-gray-200 bg-white px-2.5 py-1 text-[10px] text-gray-600 hover:border-gray-300 hover:bg-gray-50 disabled:opacity-50"
              >
                {prompt}
              </button>
            ))}
          </div>
        )}
        {learningTaskGenerationEnabled && (
          <div className="mb-2 flex min-w-0 items-center gap-2" aria-label="Agent 扩展工具">
            <span className="shrink-0 text-[10px] font-semibold text-slate-500">扩展工具</span>
            <button
              type="button"
              onClick={() => setLearningTaskMode(value => !value)}
              disabled={loading}
              aria-pressed={learningTaskMode}
              title={learningTaskMode ? '退出任务规划，返回主 Agent' : '创建学习型任务 Plan'}
              className={`flex h-7 min-w-0 items-center gap-1.5 rounded-full border px-2.5 text-[10px] font-medium transition-colors ${
                learningTaskMode
                  ? 'border-emerald-700 bg-emerald-700 text-white'
                  : 'border-emerald-200 bg-emerald-50 text-emerald-800 hover:border-emerald-500'
              }`}
            >
              <FilePenLine size={12} className="shrink-0" />
              <span className="truncate">{learningTaskMode ? '任务规划已启用' : '学习型任务规划'}</span>
            </button>
            {learningTaskMode && (
              <span className="min-w-0 truncate text-[10px] text-slate-500">再次点击可返回主 Agent</span>
            )}
          </div>
        )}
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={event => setInput(event.target.value)}
            onKeyDown={event => {
              if (shouldSendMessageOnEnter(event)) {
                event.preventDefault()
                send()
              }
            }}
            rows={2}
            placeholder={learningTaskMode ? '输入一个企业真实工作任务，先生成可检查的任务 Plan…' : '问一个问题，或直接告诉我下一步要做什么'}
            className="min-w-0 flex-1 resize-none border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 rounded-lg"
          />
          <button
            onClick={() => send()}
            disabled={!input.trim() || loading || !sessionId}
            className="h-10 shrink-0 bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-800 disabled:bg-gray-300 rounded-lg"
          >
            发送
          </button>
        </div>
      </div>
    </section>
  )
}
