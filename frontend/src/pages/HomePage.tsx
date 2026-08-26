import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { DndContext, DragOverlay, useDraggable, useDroppable } from '@dnd-kit/core'
import type { DragEndEvent, DragStartEvent } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { FolderPlus, GripVertical, Layers3 } from 'lucide-react'
import {
  acceptProjectProposal, createProject, createTutorSession, listProjects,
  recordLearningEvent,
} from '../services/api'
import type { ProjectProposal } from '../services/api'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'

interface ProjectSummary {
  id: number
  name: string
  description: string
  source_count: number
  checkpoint_count: number
  completed_count: number
  verification_due_count?: number
  created_at: string
}

function ProjectDropZone({ children, active }: { children: ReactNode; active: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: 'learning-projects-drop-zone' })
  return (
    <section
      ref={setNodeRef}
      className={`min-w-0 border-2 border-transparent p-1 transition-colors rounded-lg ${
        active ? (isOver ? 'border-indigo-500 bg-indigo-50' : 'border-indigo-200') : ''
      }`}
      data-testid="learning-projects-drop-zone"
    >
      {children}
    </section>
  )
}

function PendingProposal({
  proposal, busy, onAccept,
}: { proposal: ProjectProposal; busy: boolean; onAccept: () => void }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `proposal:${proposal.id}`,
    data: { kind: 'project-proposal', proposalId: proposal.id, title: proposal.artifact.title },
    disabled: busy,
  })
  return (
    <article ref={setNodeRef} style={{ transform: CSS.Translate.toString(transform) }} className={`border border-gray-200 bg-white p-3 rounded-lg ${isDragging ? 'z-50 opacity-50' : ''}`}>
      <div className="flex items-start gap-2">
        <button {...attributes} {...listeners} title="拖入项目区创建" className="flex h-7 w-7 shrink-0 cursor-grab items-center justify-center text-gray-400 hover:bg-gray-100 rounded"><GripVertical size={16} /></button>
        <div className="min-w-0 flex-1"><h3 className="text-sm font-semibold text-gray-900">{proposal.artifact.title}</h3><p className="mt-1 line-clamp-3 text-xs leading-5 text-gray-500">{proposal.artifact.learning_goal}</p></div>
      </div>
      <button onClick={onAccept} disabled={busy} className="mt-3 w-full bg-gray-900 px-3 py-2 text-xs font-medium text-white hover:bg-gray-800 disabled:bg-gray-300 rounded-lg">{proposal.action_type === 'enter_existing' ? '继续已有项目' : '创建项目'}</button>
    </article>
  )
}

export default function HomePage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [showNew, setShowNew] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [creating, setCreating] = useState(false)
  const [dragTitle, setDragTitle] = useState('')
  const [acceptingProposal, setAcceptingProposal] = useState(false)
  const [proposals, setProposals] = useState<ProjectProposal[]>([])
  const navigate = useNavigate()
  useWorkspaceTitle('学习项目', { kind: 'projects' })

  useEffect(() => {
    loadProjects()
    createTutorSession({ session_type: 'global' }).then(data => setProposals(data.project_proposals || [])).catch(() => {})
  }, [])

  const loadProjects = async () => {
    try { setProjects(await listProjects()) } catch {}
  }

  const openProject = async (project: ProjectSummary) => {
    recordLearningEvent({
      client_event_id: `project-open-${project.id}-${Date.now()}`,
      event_type: 'project_selected',
      project_id: project.id,
      payload: { project_id: project.id, name: project.name },
    }).catch(() => {})
    navigate(`/projects/${project.id}`)
  }

  const handleDeleteProject = async (id: number, projectName: string) => {
    if (!confirm(`确定删除项目「${projectName}」？所有切片、路线图和讲义将被永久删除。`)) return
    try {
      await import('../services/api').then(module => module.default.delete(`/projects/${id}`))
      setProjects(previous => previous.filter(project => project.id !== id))
      window.dispatchEvent(new CustomEvent('learnflow:projects-changed'))
    } catch (error: any) {
      alert('删除失败: ' + (error?.response?.data?.detail || error.message))
    }
  }

  const handleCreate = async () => {
    if (!name.trim() || creating) return
    setCreating(true)
    try {
      const project = await createProject({ name: name.trim(), description })
      setShowNew(false)
      setName('')
      setDescription('')
      await loadProjects()
      window.dispatchEvent(new CustomEvent('learnflow:projects-changed'))
      navigate(`/projects/${project.id}`)
    } catch (error: any) {
      alert(error?.response?.data?.detail || '创建失败')
    }
    setCreating(false)
  }

  const handleProposalDragStart = (event: DragStartEvent) => {
    if (event.active.data.current?.kind === 'project-proposal') {
      setDragTitle(String(event.active.data.current?.title || '项目提案'))
    }
  }

  const acceptProposal = async (proposalId: number) => {
    if (!proposalId || acceptingProposal) return
    setAcceptingProposal(true)
    try {
      const data = await acceptProjectProposal(
        proposalId,
        globalThis.crypto?.randomUUID?.() || `proposal-drop-${proposalId}-${Date.now()}`,
      )
      const project = data.executed_action?.result?.project
      setProposals(items => items.filter(item => item.id !== proposalId))
      await loadProjects()
      window.dispatchEvent(new CustomEvent('learnflow:projects-changed'))
      if (project?.id) navigate(`/projects/${project.id}`)
    } catch (error: any) {
      alert(error?.response?.data?.detail || '项目提案没有创建成功')
    } finally {
      setAcceptingProposal(false)
    }
  }

  const handleProposalDrop = async (event: DragEndEvent) => {
    setDragTitle('')
    if (event.over?.id !== 'learning-projects-drop-zone') return
    if (event.active.data.current?.kind !== 'project-proposal' || acceptingProposal) return
    const proposalId = Number(event.active.data.current?.proposalId)
    await acceptProposal(proposalId)
  }

  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-4 sm:p-6">
      <DndContext
        onDragStart={handleProposalDragStart}
        onDragCancel={() => setDragTitle('')}
        onDragEnd={handleProposalDrop}
      >
        <div className="mx-auto grid min-h-[calc(100vh-7rem)] max-w-7xl gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
          <aside>
            <div className="mb-4 flex items-center gap-2"><Layers3 size={18} className="text-indigo-600" /><div><h2 className="text-sm font-semibold text-gray-900">待创建提案</h2><p className="text-xs text-gray-500">来自主 Agent 的长期目标</p></div></div>
            <div className="space-y-3">
              {proposals.map(proposal => <PendingProposal key={proposal.id} proposal={proposal} busy={acceptingProposal} onAccept={() => acceptProposal(proposal.id)} />)}
              {proposals.length === 0 && <div className="border border-dashed border-gray-300 bg-white px-4 py-8 text-center text-xs leading-5 text-gray-400 rounded-lg">在主 Agent 中提出长期学习目标后，项目提案会停靠在这里。</div>}
            </div>
          </aside>

          <ProjectDropZone active={!!dragTitle}>
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h1 className="text-xl font-semibold text-gray-900">学习项目</h1>
              <p className="mt-1 text-sm text-gray-500">{projects.length} 个项目</p>
            </div>
            <button
              onClick={() => setShowNew(current => !current)}
              className="shrink-0 border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:border-gray-400 hover:bg-gray-50 rounded-lg"
            >
              新建项目
            </button>
          </div>

          {showNew && (
            <div className="mb-4 border border-gray-200 bg-white p-4 rounded-lg">
              <label className="mb-1 block text-xs font-medium text-gray-600">项目名称</label>
              <input
                value={name}
                onChange={event => setName(event.target.value)}
                placeholder="例如：深度学习基础"
                autoFocus
                className="mb-3 w-full border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 rounded-lg"
              />
              <label className="mb-1 block text-xs font-medium text-gray-600">目标或说明</label>
              <textarea
                value={description}
                onChange={event => setDescription(event.target.value)}
                rows={3}
                placeholder="可选"
                className="w-full resize-none border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 rounded-lg"
              />
              <div className="mt-3 flex justify-end gap-2">
                <button onClick={() => setShowNew(false)} className="px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">取消</button>
                <button
                  onClick={handleCreate}
                  disabled={!name.trim() || creating}
                  className="bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:bg-gray-300 rounded-lg"
                >
                  {creating ? '创建中...' : '创建'}
                </button>
              </div>
            </div>
          )}

          <div className="space-y-3">
            {projects.length === 0 && !showNew && (
              <div className="border border-dashed border-gray-300 bg-white px-6 py-12 text-center text-sm text-gray-400 rounded-lg">
                还没有学习项目
              </div>
            )}
            {projects.map(project => (
              <article key={project.id} className="group relative border border-gray-200 bg-white p-4 hover:border-gray-400 rounded-lg">
                <button onClick={() => openProject(project)} className="w-full text-left">
                  <div className="flex items-start justify-between gap-4 pr-7">
                    <div className="min-w-0">
                      <h2 className="truncate text-sm font-semibold text-gray-900">{project.name}</h2>
                      {project.description && <p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">{project.description}</p>}
                    </div>
                    <div className="shrink-0 text-right text-xs tabular-nums text-gray-500">
                      <p>{project.completed_count}/{project.checkpoint_count} 已验证</p>
                      {!!project.verification_due_count && (
                        <p className="mt-1 text-amber-600">{project.verification_due_count} 待验证</p>
                      )}
                    </div>
                  </div>
                  <div className="mt-3 flex gap-3 text-xs text-gray-400">
                    <span>{project.source_count} 个来源</span>
                    <span>{project.checkpoint_count} 个检查点</span>
                  </div>
                </button>
                <button
                  onClick={() => handleDeleteProject(project.id, project.name)}
                  title="删除项目"
                  className="absolute right-3 top-3 h-7 w-7 text-gray-300 opacity-0 hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 rounded"
                >
                  ×
                </button>
              </article>
            ))}
          </div>
          </ProjectDropZone>
        </div>
        <DragOverlay>
          {dragTitle ? (
            <div className="flex max-w-sm items-center gap-2 border border-indigo-300 bg-white px-4 py-3 text-sm font-medium text-gray-900 shadow-lg rounded-lg">
              <FolderPlus size={16} className="text-indigo-600" />
              <span className="truncate">{dragTitle}</span>
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  )
}
