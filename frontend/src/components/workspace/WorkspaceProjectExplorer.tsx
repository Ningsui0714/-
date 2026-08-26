import { useEffect, useMemo, useState } from 'react'
import {
  BookOpen, Braces, CalendarClock, ChevronDown, ChevronRight, FileText, Folder, FolderKanban,
  GitBranch, Plus, Route, UserRound,
} from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { getCheckpointWorkspaceArtifacts, getRoadmap, listProjects } from '../../services/api'
import { useAuth } from '../../contexts/AuthContext'
import { useWorkspace } from './WorkspaceContext'
import WorkspaceFileExplorer from './WorkspaceFileExplorer'

interface ProjectSummary {
  id: number
  name: string
  description?: string
  checkpoint_count?: number
  completed_count?: number
  verification_due_count?: number
}

interface CheckpointSummary {
  id: number
  title: string
  order: number
  completed?: boolean
  learning_status?: 'not_started' | 'in_progress' | 'verification_due' | 'blocked' | 'completed'
}

export default function WorkspaceProjectExplorer({ onNavigate }: { onNavigate?: () => void }) {
  const { user } = useAuth()
  const location = useLocation()
  const { openPath, activeTabId } = useWorkspace()
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [expandedIds, setExpandedIds] = useState<number[]>([])
  const [roadmaps, setRoadmaps] = useState<Record<number, CheckpointSummary[]>>({})
  const [artifacts, setArtifacts] = useState<Record<number, any>>({})
  const [loadingIds, setLoadingIds] = useState<number[]>([])

  const current = useMemo(() => {
    const match = location.pathname.match(/^\/projects\/(\d+)(?:\/checkpoints\/(\d+))?/)
    return {
      projectId: match ? Number(match[1]) : undefined,
      checkpointId: match?.[2] ? Number(match[2]) : undefined,
    }
  }, [location.pathname])

  const refreshProjects = async () => {
    try {
      setProjects(await listProjects())
    } catch {
      setProjects(previous => previous)
    }
  }

  useEffect(() => {
    refreshProjects()
    const refresh = () => refreshProjects()
    window.addEventListener('learnflow:projects-changed', refresh)
    window.addEventListener('learnflow:roadmap-changed', refresh)
    return () => {
      window.removeEventListener('learnflow:projects-changed', refresh)
      window.removeEventListener('learnflow:roadmap-changed', refresh)
    }
  }, [])

  const loadRoadmap = async (projectId: number, force = false) => {
    if ((!force && roadmaps[projectId]) || loadingIds.includes(projectId)) return
    setLoadingIds(previous => [...previous, projectId])
    try {
      const data = await getRoadmap(projectId)
      const checkpoints = data.checkpoints || []
      setRoadmaps(previous => ({ ...previous, [projectId]: checkpoints }))
      const artifactRows = await Promise.all(checkpoints.map(async (checkpoint: CheckpointSummary) => {
        try { return [checkpoint.id, await getCheckpointWorkspaceArtifacts(checkpoint.id)] as const }
        catch { return [checkpoint.id, null] as const }
      }))
      setArtifacts(previous => ({ ...previous, ...Object.fromEntries(artifactRows) }))
    } catch {
      setRoadmaps(previous => ({ ...previous, [projectId]: [] }))
    } finally {
      setLoadingIds(previous => previous.filter(id => id !== projectId))
    }
  }

  useEffect(() => {
    if (!current.projectId) return
    setExpandedIds(previous => previous.includes(current.projectId!) ? previous : [...previous, current.projectId!])
    loadRoadmap(current.projectId)
  }, [current.projectId])

  useEffect(() => {
    const refresh = () => {
      if (current.projectId) loadRoadmap(current.projectId, true)
    }
    window.addEventListener('learnflow:roadmap-changed', refresh)
    return () => window.removeEventListener('learnflow:roadmap-changed', refresh)
  }, [current.projectId, roadmaps])

  const open = (path: string, patch?: Parameters<typeof openPath>[1]) => {
    openPath(path, patch)
    onNavigate?.()
  }

  const toggleProject = (project: ProjectSummary) => {
    setExpandedIds(previous => previous.includes(project.id)
      ? previous.filter(id => id !== project.id)
      : [...previous, project.id])
    loadRoadmap(project.id)
    open(`/projects/${project.id}`, { title: project.name, kind: 'project', projectId: project.id })
  }

  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-white">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-slate-200 px-3">
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">Explorer</p>
          <h2 className="truncate text-xs font-semibold text-slate-700">项目与学习路径</h2>
        </div>
        <button
          type="button"
          onClick={() => {
            open('/agent', { title: '学习工作台', kind: 'home' })
          }}
          className="flex h-8 items-center gap-1 rounded-md bg-emerald-700 px-2.5 text-[11px] font-semibold text-white hover:bg-emerald-800"
        >
          <Plus size={13} /> 新建
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        <button
          type="button"
          onClick={() => open('/projects', { title: '学习项目', kind: 'projects' })}
          className={`mb-1 flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs ${
            activeTabId === '/projects' ? 'bg-emerald-50 font-semibold text-emerald-800' : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <FolderKanban size={14} /> 全部学习项目
        </button>

        <div className="mb-1 mt-3 flex items-center gap-1.5 px-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">
          <Folder size={12} /> Workspace
        </div>

        {projects.length === 0 && (
          <div className="mx-1 rounded-lg border border-dashed border-slate-300 px-3 py-7 text-center text-xs leading-5 text-slate-400">
            还没有学习项目<br />从右侧主 Agent 创建第一个项目
          </div>
        )}

        {projects.map(project => {
          const expanded = expandedIds.includes(project.id)
          const checkpoints = roadmaps[project.id] || []
          const completed = project.completed_count || 0
          const total = project.checkpoint_count || checkpoints.length
          const progress = total ? Math.round(completed * 100 / total) : 0
          return (
            <section key={project.id} className={`mb-1 overflow-visible rounded-lg ${expanded ? 'bg-slate-50' : ''}`}>
              <button
                type="button"
                onClick={() => toggleProject(project)}
                className="flex w-full items-center gap-1.5 px-2 py-2 text-left text-xs text-slate-700 hover:bg-slate-100"
              >
                {expanded ? <ChevronDown size={13} className="text-slate-400" /> : <ChevronRight size={13} className="text-slate-400" />}
                <Folder size={14} className="text-emerald-700" />
                <span className="min-w-0 flex-1 truncate font-semibold">{project.name}</span>
                <span className="text-[10px] tabular-nums text-slate-400">{progress}%</span>
              </button>

              {expanded && (
                <div className="pb-2 pl-6 pr-1.5">
                  <button
                    type="button"
                    onClick={() => open(`/projects/${project.id}`, { title: project.name, kind: 'project', projectId: project.id })}
                    className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[11px] ${
                      current.projectId === project.id && !current.checkpointId ? 'bg-emerald-100 text-emerald-800' : 'text-slate-500 hover:bg-slate-100'
                    }`}
                  >
                    <Route size={12} />
                    <span className="min-w-0 flex-1 truncate">学习路线、参考资料</span>
                  </button>

                  <p className="mb-1 mt-2 flex items-center gap-1.5 px-2 text-[9px] font-bold uppercase tracking-[0.12em] text-slate-400">
                    <Route size={10} /> 关卡资料
                  </p>
                  {loadingIds.includes(project.id) && (
                    <p className="px-2 py-2 text-[10px] text-slate-400">正在读取路径…</p>
                  )}
                  {!loadingIds.includes(project.id) && checkpoints.length === 0 && (
                    <p className="px-2 py-2 text-[10px] leading-4 text-slate-400">尚未生成正式路线</p>
                  )}
                  <div className="space-y-0.5">
                    {checkpoints.map(checkpoint => {
                      const lecturePath = `/projects/${project.id}/checkpoints/${checkpoint.id}`
                      const exercisePath = `${lecturePath}/exercises`
                      const active = current.projectId === project.id && current.checkpointId === checkpoint.id
                      const status = checkpoint.learning_status || (checkpoint.completed ? 'completed' : 'not_started')
                      const managed = artifacts[checkpoint.id]
                      return (
                        <div key={checkpoint.id} className={`rounded-md px-1 py-0.5 ${active ? 'bg-emerald-100' : 'hover:bg-slate-100'}`}>
                          <div className="flex items-center gap-1 px-1 py-1 text-[10px] font-semibold text-slate-500">
                            <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[8px] ${status === 'completed' ? 'bg-emerald-600 text-white' : status === 'verification_due' ? 'bg-amber-500 text-white' : status === 'in_progress' ? 'bg-sky-600 text-white' : 'border border-slate-300 text-slate-400'}`}>{status === 'completed' ? '✓' : checkpoint.order}</span>
                            <span className="truncate">{checkpoint.title}</span>
                          </div>
                          <button type="button" onDoubleClick={() => open(lecturePath, { title: checkpoint.title, kind: 'lecture', projectId: project.id, checkpointId: checkpoint.id })} onClick={() => open(lecturePath, { title: checkpoint.title, kind: 'lecture', projectId: project.id, checkpointId: checkpoint.id })} className="flex w-full items-center gap-1.5 rounded px-5 py-1 text-left font-mono text-[10px] text-slate-600 hover:bg-white" title="双击打开讲义播放器">
                            <FileText size={11} className="text-emerald-600" /><span className="truncate">{managed?.managed_lecture?.logical_filename || `${String(checkpoint.order).padStart(2, '0')}-${checkpoint.title}.lflecture`}</span>
                          </button>
                          {(managed?.managed_exercises || []).map((exercise: any) => (
                            <button key={exercise.id} type="button" onDoubleClick={() => open(`${exercisePath}?exercise=${exercise.id}`, { title: exercise.title, kind: 'exercise', projectId: project.id, checkpointId: checkpoint.id })} onClick={() => open(`${exercisePath}?exercise=${exercise.id}`, { title: exercise.title, kind: 'exercise', projectId: project.id, checkpointId: checkpoint.id })} className="flex w-full items-center gap-1.5 rounded px-5 py-1 text-left font-mono text-[10px] text-slate-600 hover:bg-white" title="双击打开练习播放器">
                              <Braces size={11} className="text-violet-600" /><span className="truncate">{exercise.logical_filename}</span>
                            </button>
                          ))}
                        </div>
                      )
                    })}
                  </div>
                  <WorkspaceFileExplorer
                    projectId={project.id}
                    projectName={project.name}
                    onOpen={workspacePath => open(
                      `/projects/${project.id}/workspace?path=${encodeURIComponent(workspacePath)}`,
                      {
                        title: workspacePath.split('/').pop() || '项目文件',
                        kind: 'file',
                        projectId: project.id,
                        workspacePath,
                      },
                    )}
                  />
                </div>
              )}
            </section>
          )
        })}

        <div className="mb-1 mt-4 flex items-center gap-1.5 px-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">
          <BookOpen size={12} /> Learner
        </div>
        <button
          type="button"
          onClick={() => open('/review', { title: '全局复习台', kind: 'review' })}
          className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-slate-600 hover:bg-slate-100"
        >
          <CalendarClock size={14} className="text-indigo-600" /> 复习与错题
        </button>
        <button
          type="button"
          onClick={() => open('/memory', { title: '五核记忆', kind: 'memory' })}
          className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-slate-600 hover:bg-slate-100"
        >
          <GitBranch size={14} className="text-indigo-600" /> 五核记忆与证据
        </button>
        <button
          type="button"
          onClick={() => open('/profile', { title: '个人画像', kind: 'profile' })}
          className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-slate-600 hover:bg-slate-100"
        >
          <UserRound size={14} className="text-indigo-600" /> 个人画像与旅程
        </button>
      </div>

      <footer className="shrink-0 border-t border-slate-200 p-3">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-100 text-xs font-bold text-emerald-800">
            {(user?.display_name || '学').slice(0, 1)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-semibold text-slate-700">{user?.display_name || '学习者'}</p>
            <p className="truncate text-[10px] text-slate-400">五核证据持续同步</p>
          </div>
        </div>
      </footer>
    </aside>
  )
}
