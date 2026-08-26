import { useEffect, useMemo, useState } from 'react'
import { Bot, ChevronLeft, ChevronRight, Settings2, Sparkles } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import TutorPanel from '../tutor/TutorPanel'
import LocalAgentProfilesDialog from '../tutor/LocalAgentProfilesDialog'
import { getDesktopRuntime } from '../../services/desktopRuntime'
import { useWorkspace } from './WorkspaceContext'
import {
  subscribeWorkspaceAgentContext, type WorkspaceAgentContext,
} from './workspaceAgentContext'

function deriveConversation(pathname: string) {
  const exercise = pathname.match(/^\/projects\/(\d+)\/checkpoints\/(\d+)\/exercises$/)
  if (exercise) {
    return {
      projectId: Number(exercise[1]),
      checkpointId: Number(exercise[2]),
      title: '关卡 Tutor',
      scope: `关卡 ${exercise[2]} · 当前练习`,
    }
  }
  const checkpoint = pathname.match(/^\/projects\/(\d+)\/checkpoints\/(\d+)$/)
  if (checkpoint) {
    return {
      projectId: Number(checkpoint[1]),
      checkpointId: Number(checkpoint[2]),
      title: '关卡 Tutor',
      scope: `关卡 ${checkpoint[2]} · 当前讲义`,
    }
  }
  const workspaceFile = pathname.match(/^\/projects\/(\d+)\/workspace$/)
  if (workspaceFile) {
    return {
      projectId: Number(workspaceFile[1]),
      checkpointId: undefined,
      title: '项目 Tutor',
      scope: `项目 ${workspaceFile[1]} · 项目文件`,
    }
  }
  const project = pathname.match(/^\/projects\/(\d+)$/)
  if (project) {
    return {
      projectId: Number(project[1]),
      checkpointId: undefined,
      title: '项目 Tutor',
      scope: `项目 ${project[1]}`,
    }
  }
  return {
    projectId: undefined,
    checkpointId: undefined,
    title: '主 Agent',
    scope: pathname === '/agent' ? '全局会话' : '学习者全局',
  }
}

function checkpointTurnContext(
  context: WorkspaceAgentContext | null,
  checkpointId?: number,
): Record<string, any> {
  if (!checkpointId || !context || context.kind === 'project_tutor' || context.checkpointId !== checkpointId) {
    return {}
  }
  if (context.kind === 'learning_design') {
    return {
      surface: 'lecture',
      resource_kind: 'managed_lecture',
      title: context.title,
      section_index: context.sectionIndex,
      selected_text: context.selection || '',
    }
  }
  return {
    surface: 'exercise',
    resource_kind: 'managed_exercise',
    resource_id: context.exerciseId,
    title: context.title,
    selected_text: context.selection || '',
    language: 'python',
  }
}

export default function WorkspaceAgentRail({
  expanded, onToggle,
}: {
  expanded: boolean
  onToggle: () => void
}) {
  const location = useLocation()
  const { openPath } = useWorkspace()
  const state = useMemo(() => deriveConversation(location.pathname), [location.pathname])
  const [operationContext, setOperationContext] = useState<WorkspaceAgentContext | null>(null)
  const [showAgentProfiles, setShowAgentProfiles] = useState(false)
  const desktop = getDesktopRuntime()

  useEffect(() => subscribeWorkspaceAgentContext(setOperationContext), [])

  const projectContext = operationContext?.kind === 'project_tutor'
    && operationContext.projectId === state.projectId
    ? operationContext
    : null
  const turnContext = checkpointTurnContext(operationContext, state.checkpointId)
  const quickPrompts = state.checkpointId
    ? (turnContext.surface === 'exercise'
      ? ['分析当前错误', '给下一步提示', '解释选中代码']
      : ['换种讲法', '看步骤', '看示例'])
    : []

  if (!expanded) {
    return (
      <aside className="flex h-full w-full flex-col items-center border-l border-slate-200 bg-white py-2" aria-label={`${state.title} 对话已收起`}>
        <button type="button" onClick={onToggle} title={`展开 ${state.title} 对话`} className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-700 text-white">
          <Bot size={17} />
        </button>
        <button type="button" onClick={onToggle} className="mt-3 flex min-h-0 flex-1 items-start justify-center text-[10px] font-semibold tracking-[0.14em] text-slate-500 hover:text-slate-900" style={{ writingMode: 'vertical-rl' }}>
          {state.title} · 点击展开对话
        </button>
        <button type="button" onClick={onToggle} title="展开对话" className="flex h-8 w-8 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700">
          <ChevronLeft size={16} />
        </button>
      </aside>
    )
  }

  return (
    <aside className="relative flex h-full min-h-0 w-full flex-col border-l border-slate-200 bg-white shadow-xl 2xl:shadow-none" aria-label={`${state.title} 对话窗口`}>
      <header className="flex h-14 shrink-0 items-center gap-2.5 border-b border-slate-200 bg-white px-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-700 text-white"><Bot size={16} /></span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <h2 className="truncate text-xs font-semibold text-slate-900">{state.title}</h2>
            <Sparkles size={11} className="shrink-0 text-amber-500" />
          </div>
          <p className="truncate text-[10px] text-slate-500">{state.scope} · 同一关讲义、练习与文件协作</p>
        </div>
        <button type="button" onClick={onToggle} title="收起 Agent 对话" className="flex h-8 w-8 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700">
          <ChevronRight size={16} />
        </button>
        {desktop.available && desktop.ready && state.checkpointId && (
          <button type="button" onClick={() => setShowAgentProfiles(true)} title="配置本地代码 Agent" className="flex h-8 w-8 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <Settings2 size={15} />
          </button>
        )}
      </header>

      <TutorPanel
        key={`tutor:${state.projectId || 'global'}:${state.checkpointId || 'project'}`}
        projectId={state.projectId}
        checkpointId={state.checkpointId}
        turnContext={turnContext}
        quickPrompts={quickPrompts}
        className="min-h-0 flex-1 rounded-none border-0"
        onProjectChange={project => project?.id && openPath(`/projects/${project.id}`, { title: project.name || `项目 ${project.id}`, kind: 'project', projectId: project.id })}
        onProposalAccepted={project => project?.id && openPath(`/projects/${project.id}`, { title: project.name || `项目 ${project.id}`, kind: 'project', projectId: project.id })}
        onCheckpointChange={checkpoint => state.projectId && openPath(`/projects/${state.projectId}/checkpoints/${checkpoint.id}`, { title: checkpoint.title || `关卡 ${checkpoint.id}`, kind: 'lecture', projectId: state.projectId, checkpointId: checkpoint.id })}
        onRoadmapUpdate={roadmap => {
          projectContext?.onRoadmapUpdate?.(roadmap)
          window.dispatchEvent(new CustomEvent('learnflow:roadmap-changed'))
        }}
        projectProposal={state.checkpointId ? null : projectContext?.projectProposal}
        projectSources={state.checkpointId ? [] : projectContext?.projectSources}
        candidateSourcesRefreshing={state.checkpointId ? false : projectContext?.candidateSourcesRefreshing}
        addingCandidateUrl={state.checkpointId ? null : projectContext?.addingCandidateUrl}
        onRefreshCandidateSources={state.checkpointId ? undefined : projectContext?.onRefreshCandidateSources}
        onAddCandidateSource={state.checkpointId ? undefined : projectContext?.onAddCandidateSource}
        learningTaskGenerationEnabled
        onLearningTaskPlanCreated={planned => openPath(
          planned.workspace_path,
          {
            title: '学习型任务 Plan',
            kind: 'wf03',
          },
        )}
      />
      {showAgentProfiles && <LocalAgentProfilesDialog onClose={() => setShowAgentProfiles(false)} />}
    </aside>
  )
}
