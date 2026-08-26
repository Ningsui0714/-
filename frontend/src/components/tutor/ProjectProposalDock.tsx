import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  DndContext, KeyboardSensor, PointerSensor, closestCenter,
  useDraggable, useSensor, useSensors,
} from '@dnd-kit/core'
import {
  SortableContext, arrayMove, sortableKeyboardCoordinates,
  useSortable, verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  Check, ChevronDown, ChevronUp, ExternalLink, FolderPlus, GripVertical,
  Lock, Pencil, RefreshCw, Save, Unlock, X,
} from 'lucide-react'
import type { ProjectProposal, ProjectProposalMilestone } from '../../services/api'


interface Props {
  proposals: ProjectProposal[]
  dragEnabled?: boolean
  busy?: boolean
  onAccept: (proposal: ProjectProposal) => Promise<void>
  onDismiss: (proposal: ProjectProposal) => Promise<void>
  onRefreshSources: (proposal: ProjectProposal) => Promise<void>
  onUpdate: (
    proposal: ProjectProposal,
    patch: Record<string, any>,
    lockFields?: string[],
    unlockFields?: string[],
  ) => Promise<void>
}


const typeLabels: Record<ProjectProposal['proposal_type'], string> = {
  build: '动手构建',
  mastery: '系统掌握',
  exam: '备考计划',
  research: '研究复现',
}

const qualityLabels: Record<'excellent' | 'strong' | 'relevant', string> = {
  excellent: '高度匹配',
  strong: '强相关',
  relevant: '可参考',
}


function SortableMilestoneRow({
  proposalId, milestone, index,
}: { proposalId: number; milestone: ProjectProposalMilestone; index: number }) {
  const sortableId = `milestone:${proposalId}:${milestone.id}`
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: sortableId })
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`flex items-start gap-2 border-t border-gray-100 py-2 first:border-t-0 ${isDragging ? 'bg-indigo-50 opacity-80' : ''}`}
    >
      <button
        type="button"
        title="调整阶段顺序"
        aria-label={`调整阶段 ${milestone.title}`}
        className="mt-0.5 flex h-6 w-6 shrink-0 cursor-grab items-center justify-center text-gray-400 hover:text-gray-700 active:cursor-grabbing"
        {...attributes}
        {...listeners}
      >
        <GripVertical size={15} />
      </button>
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gray-900 text-[10px] font-semibold text-white">
        {index + 1}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-gray-800">{milestone.title}</p>
        {milestone.purpose && <p className="mt-0.5 text-[11px] leading-4 text-gray-500">{milestone.purpose}</p>}
      </div>
      {milestone.estimated_effort && (
        <span className="shrink-0 text-[10px] text-gray-400">{milestone.estimated_effort}</span>
      )}
    </div>
  )
}


function DraggableProposal({
  proposal, enabled, children,
}: { proposal: ProjectProposal; enabled: boolean; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `proposal:${proposal.id}`,
    data: { kind: 'project-proposal', proposalId: proposal.id, title: proposal.artifact.title },
    disabled: !enabled,
  })
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform) }}
      className={`relative ${isDragging ? 'z-50 opacity-60' : ''}`}
    >
      {enabled && (
        <button
          type="button"
          title="拖入学习项目区创建"
          aria-label={`拖动项目提案 ${proposal.artifact.title}`}
          className="absolute left-3 top-3 z-10 flex h-7 w-7 cursor-grab items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-700 active:cursor-grabbing rounded"
          {...attributes}
          {...listeners}
        >
          <GripVertical size={17} />
        </button>
      )}
      {children}
    </div>
  )
}


export default function ProjectProposalDock({
  proposals, dragEnabled = false, busy = false,
  onAccept, onDismiss, onRefreshSources, onUpdate,
}: Props) {
  const [selectedId, setSelectedId] = useState<number | null>(proposals[0]?.id ?? null)
  const [expanded, setExpanded] = useState(true)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const selected = proposals.find(item => item.id === selectedId) || proposals[0]
  const milestoneIds = useMemo(
    () => (selected?.artifact.milestones || []).map(item => `milestone:${selected.id}:${item.id}`),
    [selected],
  )
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  useEffect(() => {
    if (!selected && proposals[0]) setSelectedId(proposals[0].id)
    if (selectedId && !proposals.some(item => item.id === selectedId)) {
      setSelectedId(proposals[0]?.id ?? null)
    }
  }, [proposals, selected, selectedId])

  useEffect(() => {
    if (!selected) return
    setDraft({
      title: selected.artifact.title || '',
      learning_goal: selected.artifact.learning_goal || '',
      practice_goal: selected.artifact.practice_goal || '',
      estimated_effort: selected.artifact.estimated_effort || '',
    })
  }, [selected?.id, selected?.revision])

  if (!selected) return null

  const save = async () => {
    const patch = {
      title: draft.title.trim(),
      learning_goal: draft.learning_goal.trim(),
      practice_goal: draft.practice_goal.trim(),
      estimated_effort: draft.estimated_effort.trim(),
    }
    await onUpdate(selected, patch, Object.keys(patch))
    setEditing(false)
  }

  const reorderMilestones = async (activeId: string, overId: string) => {
    if (activeId === overId) return
    const milestones = selected.artifact.milestones || []
    const oldIndex = milestoneIds.indexOf(activeId)
    const newIndex = milestoneIds.indexOf(overId)
    if (oldIndex < 0 || newIndex < 0) return
    await onUpdate(selected, { milestones: arrayMove(milestones, oldIndex, newIndex) }, ['milestone_order'])
  }

  const sources = selected.artifact.candidate_sources || []
  const sourceSearching = ['queued', 'searching'].includes(selected.source_status)
  const searchGeneration = selected.artifact.source_search_generation || 0
  const refreshedAt = selected.artifact.source_search_refreshed_at
  const locked = selected.locked_fields || []
  const stack = Array.isArray(selected.artifact.details?.stack) ? selected.artifact.details.stack : []

  return (
    <div className="shrink-0 border-b border-gray-200 bg-white" data-testid="project-proposal-dock">
      <div className="flex min-h-10 items-center gap-1 overflow-x-auto border-b border-gray-100 px-3">
        {proposals.map(proposal => (
          <button
            key={proposal.id}
            type="button"
            onClick={() => setSelectedId(proposal.id)}
            className={`shrink-0 border-b-2 px-2 py-2 text-xs font-medium ${
              proposal.id === selected.id
                ? 'border-indigo-600 text-indigo-700'
                : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            {proposal.artifact.title}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setExpanded(value => !value)}
          title={expanded ? '收起项目提案' : '展开项目提案'}
          className="ml-auto flex h-7 w-7 shrink-0 items-center justify-center text-gray-500 hover:bg-gray-100 rounded"
        >
          {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </button>
      </div>

      {expanded && (
        <DraggableProposal proposal={selected} enabled={dragEnabled && !editing && !busy}>
          <div className={`max-h-[330px] overflow-y-auto px-4 py-3 ${dragEnabled ? 'pl-11' : ''}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="text-[10px] font-semibold uppercase text-indigo-600">{typeLabels[selected.proposal_type]}</span>
                  <span className="text-[10px] text-gray-400">v{selected.revision}</span>
                  {locked.length > 0 && <Lock size={11} className="text-gray-400" />}
                </div>
                {!editing && <h3 className="text-sm font-semibold text-gray-900">{selected.artifact.title}</h3>}
              </div>
              <div className="flex shrink-0 gap-1">
                {locked.length > 0 && !editing && (
                  <button
                    type="button"
                    onClick={() => onUpdate(selected, {}, [], locked)}
                    title="允许 Tutor 继续优化已编辑字段"
                    className="flex h-7 w-7 items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-700 rounded"
                  >
                    <Unlock size={14} />
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setEditing(value => !value)}
                  title={editing ? '取消编辑' : '编辑项目提案'}
                  className="flex h-7 w-7 items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-700 rounded"
                >
                  {editing ? <X size={14} /> : <Pencil size={14} />}
                </button>
                <button
                  type="button"
                  onClick={() => onDismiss(selected)}
                  title="关闭项目提案"
                  className="flex h-7 w-7 items-center justify-center text-gray-400 hover:bg-red-50 hover:text-red-600 rounded"
                >
                  <X size={15} />
                </button>
              </div>
            </div>

            {editing ? (
              <div className="mt-2 space-y-2">
                <input
                  value={draft.title || ''}
                  onChange={event => setDraft(value => ({ ...value, title: event.target.value }))}
                  aria-label="项目标题"
                  className="w-full border border-gray-300 px-2 py-1.5 text-sm outline-none focus:border-indigo-500 rounded"
                />
                <textarea
                  value={draft.learning_goal || ''}
                  onChange={event => setDraft(value => ({ ...value, learning_goal: event.target.value }))}
                  aria-label="学习目标"
                  rows={2}
                  className="w-full resize-none border border-gray-300 px-2 py-1.5 text-xs outline-none focus:border-indigo-500 rounded"
                />
                <textarea
                  value={draft.practice_goal || ''}
                  onChange={event => setDraft(value => ({ ...value, practice_goal: event.target.value }))}
                  aria-label="实践目标"
                  rows={2}
                  className="w-full resize-none border border-gray-300 px-2 py-1.5 text-xs outline-none focus:border-indigo-500 rounded"
                />
                <input
                  value={draft.estimated_effort || ''}
                  onChange={event => setDraft(value => ({ ...value, estimated_effort: event.target.value }))}
                  aria-label="预计投入"
                  className="w-full border border-gray-300 px-2 py-1.5 text-xs outline-none focus:border-indigo-500 rounded"
                />
                <button
                  type="button"
                  onClick={save}
                  disabled={busy || !draft.title?.trim()}
                  className="inline-flex items-center gap-1.5 bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:bg-gray-300 rounded"
                >
                  <Save size={13} /> 保存
                </button>
              </div>
            ) : (
              <>
                <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
                  <div>
                    <p className="font-medium text-gray-500">学习目标</p>
                    <p className="mt-0.5 leading-5 text-gray-800">{selected.artifact.learning_goal}</p>
                  </div>
                  <div>
                    <p className="font-medium text-gray-500">实践产物</p>
                    <p className="mt-0.5 leading-5 text-gray-800">{selected.artifact.practice_goal}</p>
                  </div>
                </div>

                {selected.last_change_summary && (
                  <p className="mt-2 border-l-2 border-indigo-300 pl-2 text-[11px] leading-4 text-indigo-700">
                    {selected.last_change_summary}
                  </p>
                )}

                {(selected.artifact.learner_start || []).length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {selected.artifact.learner_start.map(item => (
                      <span key={item} className="bg-gray-100 px-2 py-0.5 text-[10px] text-gray-600 rounded">{item}</span>
                    ))}
                    {selected.artifact.estimated_effort && (
                      <span className="bg-indigo-50 px-2 py-0.5 text-[10px] text-indigo-700 rounded">{selected.artifact.estimated_effort}</span>
                    )}
                  </div>
                )}

                {(stack.length > 0 || (selected.artifact.risks || []).length > 0) && (
                  <div className="mt-2 grid gap-2 text-[11px] sm:grid-cols-2">
                    {stack.length > 0 && (
                      <div>
                        <p className="font-medium text-gray-500">技术栈</p>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {stack.map((item: string) => (
                            <span key={item} className="border border-gray-200 px-1.5 py-0.5 text-gray-700 rounded">{item}</span>
                          ))}
                        </div>
                      </div>
                    )}
                    {(selected.artifact.risks || []).length > 0 && (
                      <div>
                        <p className="font-medium text-gray-500">当前风险</p>
                        <p className="mt-1 leading-4 text-gray-600">{selected.artifact.risks[0]}</p>
                      </div>
                    )}
                  </div>
                )}

                <div className="mt-3">
                  <p className="mb-1 text-xs font-semibold text-gray-700">阶段预览</p>
                  <DndContext
                    sensors={sensors}
                    collisionDetection={closestCenter}
                    onDragEnd={event => {
                      if (event.over) reorderMilestones(String(event.active.id), String(event.over.id))
                    }}
                  >
                    <SortableContext items={milestoneIds} strategy={verticalListSortingStrategy}>
                      {(selected.artifact.milestones || []).map((milestone, index) => (
                        <SortableMilestoneRow
                          key={milestone.id}
                          proposalId={selected.id}
                          milestone={milestone}
                          index={index}
                        />
                      ))}
                    </SortableContext>
                  </DndContext>
                </div>

                {(sources.length > 0 || selected.source_status !== 'idle') && (
                  <div className="mt-3 border-t border-gray-100 pt-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-gray-700">候选来源</p>
                      {selected.source_status !== 'idle' && (
                        <button
                          type="button"
                          onClick={() => onRefreshSources(selected)}
                          disabled={sourceSearching}
                          title="重新搜索候选来源"
                          aria-label="重新搜索候选来源"
                          className="flex h-6 w-6 items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-700 disabled:cursor-wait disabled:text-indigo-500 rounded"
                        >
                          <RefreshCw size={13} className={sourceSearching ? 'animate-spin' : ''} />
                        </button>
                      )}
                    </div>
                    {sourceSearching && (
                      <p className="mt-1 text-[11px] text-indigo-600">
                        正在重新检索并排序，{sources.length ? '当前候选暂时保留。' : '完成后会自动更新。'}
                      </p>
                    )}
                    {selected.source_status === 'failed' && (
                      <p className="mt-1 text-[11px] text-amber-700">来源搜索暂时失败，提案仍可正常创建。</p>
                    )}
                    {selected.source_status === 'completed' && (
                      <p className="mt-1 text-[10px] text-gray-400">
                        第 {searchGeneration} 次检索 · 从 {selected.artifact.source_search_discovered_count || sources.length} 个仓库中选出 {sources.length} 个
                        {refreshedAt ? ` · ${new Date(refreshedAt).toLocaleString()}` : ''}
                      </p>
                    )}
                    <div className="mt-1 divide-y divide-gray-100">
                      {sources.map(source => (
                        <a
                          key={source.url}
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-start gap-2 py-2 text-xs text-gray-700 hover:text-indigo-700"
                        >
                          <ExternalLink size={12} className="mt-0.5 shrink-0" />
                          <span className="min-w-0 flex-1">
                            <span className="flex min-w-0 items-center gap-1.5">
                              <span className="truncate font-medium">{source.title}</span>
                              {source.quality && (
                                <span className="shrink-0 bg-indigo-50 px-1.5 py-0.5 text-[9px] text-indigo-700 rounded">
                                  {qualityLabels[source.quality]}
                                </span>
                              )}
                            </span>
                            {source.reason && <span className="mt-0.5 block line-clamp-2 text-[10px] leading-4 text-gray-500">{source.reason}</span>}
                          </span>
                          {!!source.stars && <span className="shrink-0 text-[10px] text-gray-400">{source.stars.toLocaleString()} stars</span>}
                        </a>
                      ))}
                    </div>
                  </div>
                )}

                <div className="mt-3 flex items-center justify-between gap-2 border-t border-gray-100 pt-3">
                  <div className="flex items-center gap-1 text-[10px] text-gray-400">
                    <Check size={12} /> {selected.artifact.acceptance_criteria?.length || 0} 项验收标准
                  </div>
                  <button
                    type="button"
                    onClick={() => onAccept(selected)}
                    disabled={busy}
                    className="inline-flex items-center gap-1.5 bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:bg-indigo-300 rounded"
                  >
                    <FolderPlus size={14} />
                    {selected.action_type === 'enter_existing' ? '进入已有项目' : '创建项目'}
                  </button>
                </div>
              </>
            )}
          </div>
        </DraggableProposal>
      )}
    </div>
  )
}
