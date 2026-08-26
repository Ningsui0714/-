import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { BookOpen } from 'lucide-react'
import {
  getProject, addSource, uploadSource, listSources, processAllSources, processSource, getRoadmap,
  startImageCaptioning, getTaskStatus, setSourceRole, reconcileSources, applyReconcile,
  getAcceptedProjectProposal, getProjectProposal, refreshProjectProposalSources,
} from '../services/api'
import type { ProjectProposal, ProjectProposalSource } from '../services/api'
import CheckpointGraph from '../components/checkpoint/CheckpointGraph'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import { publishWorkspaceAgentContext } from '../components/workspace/workspaceAgentContext'

interface CheckpointNode {
  id: number
  title: string
  description: string
  order: number
  prerequisites: number[]
  completed: boolean
  chunk_ids: number[]
  archived?: boolean
  progress?: any
  learning_status?: 'not_started' | 'in_progress' | 'verification_due' | 'blocked' | 'completed'
}

export default function ProjectPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const pid = Number(projectId)

  const [project, setProject] = useState<any>(null)
  const [sources, setSources] = useState<any[]>([])
  const [chunks, setChunks] = useState<any[]>([])
  const [checkpoints, setCheckpoints] = useState<CheckpointNode[]>([])
  const [showAddSource, setShowAddSource] = useState(false)
  const [sourceType, setSourceType] = useState('url')
  const [sourceUrl, setSourceUrl] = useState('')
  const [sourceFile, setSourceFile] = useState<File | null>(null)
  const [processing, setProcessing] = useState(false)
  const [captioningSource, setCaptioningSource] = useState<number | null>(null)
  const [visionEnhanceEnabled, setVisionEnhanceEnabled] = useState(false)
  const [reconcileSuggestion, setReconcileSuggestion] = useState<any>(null)
  const [reconcileLoading, setReconcileLoading] = useState(false)
  const [projectProposal, setProjectProposal] = useState<ProjectProposal | null>(null)
  const [addingCandidateUrl, setAddingCandidateUrl] = useState<string | null>(null)
  const [refreshingCandidates, setRefreshingCandidates] = useState(false)

  // Check whether paid API enhance is allowed (settings)
  useEffect(() => {
    fetch('/api/settings').then(r => r.json()).then((s: any) => {
      setVisionEnhanceEnabled(!!s.vision_api_enhance)
    }).catch(() => {})
  }, [])
  const [notification, setNotification] = useState<string | null>(null)

  useWorkspaceTitle(project?.name || `学习项目 ${pid}`, { kind: 'project', projectId: pid })

  // T10: source main/aux role + reconcile
  const handleSetRole = async (sourceId: number, role: 'main' | 'auxiliary') => {
    try {
      await setSourceRole(pid, sourceId, role)
      await load()
      setNotification(`已设为${role === 'main' ? '主' : '辅助'}来源`)
    } catch (e: any) {
      setNotification('❌ ' + (e?.response?.data?.detail || e.message))
    }
    setTimeout(() => setNotification(null), 3000)
  }

  const handleReconcile = async () => {
    setReconcileLoading(true)
    setNotification('正在分析新来源与路线的契合度...')
    try {
      const res = await reconcileSources(pid)
      setReconcileSuggestion(res.suggestion)
      setNotification(null)
    } catch (e: any) {
      setNotification('❌ ' + (e?.response?.data?.detail || e.message))
    }
    setReconcileLoading(false)
  }

  const handleApplyReconcile = async () => {
    if (!reconcileSuggestion) return
    setReconcileLoading(true)
    try {
      const res = await applyReconcile(pid, reconcileSuggestion)
      setNotification(`✅ 已整合：新增 ${res.inserted} 关，扩展 ${res.extended} 关`)
      setReconcileSuggestion(null)
      await load()
      window.dispatchEvent(new CustomEvent('learnflow:roadmap-changed', { detail: { projectId: pid } }))
    } catch (e: any) {
      setNotification('❌ ' + (e?.response?.data?.detail || e.message))
    }
    setReconcileLoading(false)
  }
  const handleCaption = async (sourceId: number, mode: 'free' | 'api' = 'free') => {
    setCaptioningSource(sourceId)
    setNotification(mode === 'api' ? '正在用 API 增强图片描述...' : '正在分析图片...')
    try {
      const res = await startImageCaptioning(pid, sourceId, undefined, mode)
      setNotification('任务已启动，正在生成图片描述...')
      // Poll task status
      const deadline = Date.now() + 10 * 60 * 1000  // max 10 min
      const poll = async () => {
        try {
          const t = await getTaskStatus(res.task_id)
          if (t.status === 'completed') {
            const r = t.result || {}
            const parts: string[] = []
            if (r.captioned) parts.push(`${r.captioned} 张新描述`)
            if (r.skipped) parts.push(`${r.skipped} 张已有描述跳过`)
            if (r.failed) parts.push(`${r.failed} 张失败`)
            setNotification(`✅ 图片描述完成：${parts.join('，') || '无需处理（全部已有描述）'}`)
            setCaptioningSource(null)
          } else if (t.status === 'failed') {
            setNotification('❌ 图片描述任务失败: ' + (t.error?.message || ''))
            setCaptioningSource(null)
          } else if (Date.now() < deadline) {
            setTimeout(poll, 5000)
          } else {
            setNotification('⏳ 任务仍在后台进行，可稍后查看')
            setCaptioningSource(null)
          }
        } catch {
          setCaptioningSource(null)
          setNotification('任务状态查询失败，后台任务可能仍在运行')
        }
      }
      setTimeout(poll, 5000)
    } catch (e: any) {
      setNotification('❌ 启动失败: ' + (e?.response?.data?.detail || e.message))
      setCaptioningSource(null)
    }
  }

  useEffect(() => { load() }, [pid])

  const load = async () => {
    try {
      // NOTE: chunks are NOT loaded into the UI anymore (huge repos have
      // 100k+ chunks — rendering them froze the page). Only counts are shown.
      const [p, s, proposal] = await Promise.all([
        getProject(pid).catch(() => null),
        listSources(pid).catch(() => []),
        getAcceptedProjectProposal(pid).catch(() => null),
      ])
      setProject(p)
      setSources(s)
      setProjectProposal(proposal)
      setChunks([])
      loadRoadmap()
    } catch (e) {
      console.error('Failed to load project', e)
    }
  }

  const loadRoadmap = async () => {
    try {
      const rm = await getRoadmap(pid)
      setCheckpoints(rm.checkpoints || [])
    } catch {
      // No roadmap yet
    }
  }

  const handleAddSource = async () => {
    if (sourceType === 'file' && !sourceFile) return
    if (sourceType !== 'file' && !sourceUrl.trim()) return
    try {
      if (sourceType === 'file' && sourceFile) {
        await uploadSource(pid, sourceFile)
      } else {
        await addSource(pid, { type: sourceType, url: sourceUrl.trim() })
      }
      setSourceUrl('')
      setSourceFile(null)
      setShowAddSource(false)
      load()
    } catch (e: any) {
      setNotification('❌ ' + (e?.response?.data?.detail || e.message || '添加来源失败'))
    }
  }

  const handleAddCandidateSource = async (candidate: ProjectProposalSource) => {
    if (addingCandidateUrl) return
    setAddingCandidateUrl(candidate.url)
    setNotification('正在添加并处理候选来源...')
    try {
      const source = await addSource(pid, { type: candidate.type || 'url', url: candidate.url })
      await processSource(pid, source.id)
      setNotification('候选来源已添加并处理完成')
      await load()
    } catch (error: any) {
      setNotification(error?.response?.data?.detail || '候选来源处理失败，可稍后重试')
    } finally {
      setAddingCandidateUrl(null)
      setTimeout(() => setNotification(null), 4000)
    }
  }

  const handleRefreshCandidateSources = async () => {
    if (!projectProposal || refreshingCandidates) return
    setRefreshingCandidates(true)
    setNotification('正在重新检索并排序候选来源...')
    try {
      let latest = await refreshProjectProposalSources(projectProposal.id)
      setProjectProposal(latest)
      const deadline = Date.now() + 45_000
      while (['queued', 'searching'].includes(latest.source_status) && Date.now() < deadline) {
        await new Promise(resolve => window.setTimeout(resolve, 1500))
        latest = await getProjectProposal(projectProposal.id)
        setProjectProposal(latest)
      }
      if (latest.source_status === 'failed') {
        throw new Error(latest.artifact.source_search_last_error || '候选来源检索失败')
      }
      if (['queued', 'searching'].includes(latest.source_status)) {
        setNotification('检索仍在后台进行，稍后会显示最新结果')
      } else {
        const selected = latest.artifact.candidate_sources?.length || 0
        const discovered = latest.artifact.source_search_discovered_count || selected
        setNotification(
          latest.artifact.source_search_result_changed
            ? `已从 ${discovered} 个仓库中更新 ${selected} 个候选来源`
            : `已重新检索 ${discovered} 个仓库，当前最佳候选未变化`,
        )
      }
    } catch (error: any) {
      setNotification(error?.response?.data?.detail || error?.message || '候选来源检索失败，可稍后重试')
    } finally {
      setRefreshingCandidates(false)
      window.setTimeout(() => setNotification(null), 5000)
    }
  }

  const handleProcessAll = async () => {
    setProcessing(true)
    try {
      const result = await processAllSources(pid)
      if (result.errors?.length) {
        setNotification(`处理完成，${result.processed} 个成功，${result.errors.length} 个失败`)
      } else {
        setNotification(`✅ 处理完成！`)
      }
      await load()
    } catch (e: any) {
      console.error('Failed to process', e)
      setNotification('❌ 处理失败: ' + (e?.response?.data?.detail || e?.message || '未知错误'))
    } finally {
      setProcessing(false)
      setTimeout(() => setNotification(null), 4000)
    }
  }

  const handleRoadmapUpdate = useCallback((roadmap: any) => {
    if (roadmap.checkpoints) {
      setCheckpoints(roadmap.checkpoints)
      window.dispatchEvent(new CustomEvent('learnflow:roadmap-changed', { detail: { projectId: pid } }))
    }
  }, [pid])

  const handleCheckpointClick = (checkpointId: number) => {
    import('../services/api').then(({ recordLearningEvent }) => recordLearningEvent({
      client_event_id: `checkpoint-open-${checkpointId}-${Date.now()}`,
      event_type: 'checkpoint_entered',
      project_id: pid,
      checkpoint_id: checkpointId,
      payload: {},
    })).catch(() => {})
    navigate(`/projects/${pid}/checkpoints/${checkpointId}`)
  }

  useEffect(() => {
    publishWorkspaceAgentContext({
      kind: 'project_tutor',
      projectId: pid,
      projectProposal,
      projectSources: sources,
      candidateSourcesRefreshing: refreshingCandidates,
      addingCandidateUrl,
      onRefreshCandidateSources: handleRefreshCandidateSources,
      onAddCandidateSource: handleAddCandidateSource,
      onRoadmapUpdate: handleRoadmapUpdate,
    })
  }, [
    addingCandidateUrl, handleRoadmapUpdate, pid, projectProposal,
    refreshingCandidates, sources,
  ])

  if (!project) return <div className="p-8 text-gray-400">加载中...</div>

  const hasSources = sources.length > 0
  const hasProcessedChunks = sources.some(s => s.status === 'processed')
  const hasRoadmap = checkpoints.length > 0

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      {notification && (
        <div className="px-6 py-2 text-sm bg-primary-50 text-primary-700 border-b border-primary-200 shrink-0">
          {notification}
        </div>
      )}
      <div className="bg-white border-b border-gray-200 px-4 py-4 sm:px-6 shrink-0">
        <button onClick={() => navigate('/')} className="text-sm text-gray-400 hover:text-gray-600 mb-1">
          ← 返回
        </button>
        <h1 className="text-2xl font-bold text-gray-900">{project.name}</h1>
        {project.description && (
          <p className="text-gray-500 text-sm mt-0.5">{project.description}</p>
        )}
      </div>

      {projectProposal && (
        <div className="flex shrink-0 items-start gap-2 border-b border-gray-200 bg-gray-50 px-4 py-2.5 sm:px-6">
          <BookOpen size={14} className="mt-0.5 shrink-0 text-indigo-600" />
          <div className="min-w-0 text-xs">
            <p className="font-medium text-gray-600">学习目标</p>
            <p className="mt-0.5 leading-5 text-gray-800">{projectProposal.artifact.learning_goal}</p>
          </div>
        </div>
      )}

      <div className="flex flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
        {/* Left sidebar: Sources */}
        <div className="max-h-72 w-full shrink-0 overflow-y-auto border-b border-gray-200 bg-white p-4 md:max-h-none md:w-72 md:border-b-0 md:border-r">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-sm">参考资料</h2>
            <button
              onClick={() => setShowAddSource(!showAddSource)}
              className="text-primary-600 text-xs hover:text-primary-700"
            >
              + 添加
            </button>
          </div>

          {showAddSource && (
            <div className="mb-3 p-2.5 bg-gray-50 rounded-lg text-sm">
              <select
                value={sourceType}
                onChange={e => setSourceType(e.target.value)}
                className={`w-full border rounded px-2 py-1 text-xs mb-2 ${
                  sourceType === 'github' ? 'border-purple-300 bg-purple-50' : 'border-gray-300'
                }`}
              >
                <option value="url">🌐 网页链接</option>
                <option value="github">📦 GitHub 仓库</option>
                <option value="file">📄 上传文件</option>
              </select>
              {sourceType === 'github' && (
                <div className="text-[10px] text-purple-500 mb-1.5 -mt-1">
                  ⚡ 检测到 GitHub 链接，自动切换为仓库模式
                </div>
              )}
              {sourceType === 'file' ? (
                <input
                  type="file"
                  accept=".md,.markdown,.txt,.rst,.csv,.py,.ipynb,.yaml,.yml,.toml,.json,.xml,.html,.css,.js,.sh,.bash,.c,.cpp,.h,.hpp,.java,.rs,.go,.rb,.php,.swift,.tex,.bib,.pdf,.docx"
                  onChange={e => setSourceFile(e.target.files?.[0] || null)}
                  className="w-full text-[10px] mb-2"
                />
              ) : (
                <input
                  type="text"
                  placeholder="URL"
                  value={sourceUrl}
                  onChange={e => {
                    setSourceUrl(e.target.value)
                    // Auto-detect GitHub URLs
                    if (e.target.value.includes('github.com')) {
                      setSourceType('github')
                    }
                  }}
                  className="w-full border border-gray-300 rounded px-2 py-1 text-xs mb-2"
                  onKeyDown={e => e.key === 'Enter' && handleAddSource()}
                />
              )}
              <div className="flex gap-1.5">
                <button
                  onClick={handleAddSource}
                  className="bg-primary-600 text-white px-2.5 py-1 text-xs rounded hover:bg-primary-700"
                >
                  添加
                </button>
                <button
                  onClick={() => setShowAddSource(false)}
                  className="text-gray-500 text-xs px-2"
                >
                  取消
                </button>
              </div>
            </div>
          )}

          {sources.length === 0 && (
            <p className="text-gray-400 text-xs text-center py-6">暂无来源</p>
          )}

          <div className="space-y-1.5 mb-3">
            {sources.map(s => (
              <div key={s.id} className="text-xs p-2 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    s.status === 'processed' ? 'bg-green-400' :
                    s.status === 'processing' ? 'bg-yellow-400' :
                    s.status === 'failed' ? 'bg-red-400' : 'bg-gray-300'
                  }`} />
                  <span className="truncate flex-1 text-gray-700">
                    {s.type === 'github' ? '📦' : s.type === 'file' ? '📄' : '🔗'} {s.url?.slice(0, 35)}
                  </span>
                  <span className="text-gray-400">{s.chunk_count || '-'}</span>
                </div>
                {s.status === 'failed' && s.error && (
                  <p className="text-red-400 mt-1 text-[10px] leading-tight">{s.error.slice(0, 80)}</p>
                )}
                {s.type === 'github' && s.status === 'processed' && (
                  <div className="mt-1.5 flex gap-1">
                    <button
                      onClick={() => handleCaption(s.id, 'free')}
                      disabled={captioningSource === s.id}
                      className="flex-1 text-[10px] bg-purple-50 text-purple-600 py-1 rounded
                                 hover:bg-purple-100 disabled:opacity-50 transition-colors"
                    >
                      {captioningSource === s.id ? '⏳ 处理中...' : '🖼 免费描述'}
                    </button>
                    {visionEnhanceEnabled && (
                      <button
                        onClick={() => handleCaption(s.id, 'api')}
                        disabled={captioningSource === s.id}
                        title="仅处理免费管线无法理解的纯图形/照片"
                        className="flex-1 text-[10px] bg-amber-50 text-amber-600 py-1 rounded
                                   hover:bg-amber-100 disabled:opacity-50 transition-colors"
                      >
                        ✨ API 增强
                      </button>
                    )}
                  </div>
                )}
                {/* T10: main/auxiliary role */}
                {s.status === 'processed' && (
                  <div className="mt-1 flex gap-1">
                    <button
                      onClick={() => handleSetRole(s.id, 'main')}
                      title="主来源：决定路线骨架"
                      className={`flex-1 text-[10px] py-0.5 rounded transition-colors ${
                        s.role !== 'auxiliary'
                          ? 'bg-indigo-600 text-white'
                          : 'bg-gray-50 text-gray-400 hover:bg-gray-100'
                      }`}
                    >
                      主来源
                    </button>
                    <button
                      onClick={() => handleSetRole(s.id, 'auxiliary')}
                      title="辅助来源：仅补充检索，不决定路线"
                      className={`flex-1 text-[10px] py-0.5 rounded transition-colors ${
                        s.role === 'auxiliary'
                          ? 'bg-indigo-600 text-white'
                          : 'bg-gray-50 text-gray-400 hover:bg-gray-100'
                      }`}
                    >
                      辅助
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>

          {hasSources && (
            <button
              onClick={handleProcessAll}
              disabled={processing}
              className="w-full text-xs bg-primary-50 text-primary-700 py-2 rounded-lg
                         hover:bg-primary-100 disabled:opacity-50 transition-colors mb-3"
            >
              {processing ? '处理中...' : '🔄 处理所有来源'}
            </button>
          )}
          {hasProcessedChunks && (
            <button
              onClick={handleReconcile}
              disabled={reconcileLoading}
              className="w-full text-xs bg-indigo-50 text-indigo-700 py-2 rounded-lg
                         hover:bg-indigo-100 disabled:opacity-50 transition-colors mb-3"
            >
              {reconcileLoading ? '分析中...' : '🧩 整合新来源到路线'}
            </button>
          )}

          {/* Chunk stats (list removed — 100k+ chunks froze the page) */}
          {hasProcessedChunks && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 mb-1.5 uppercase tracking-wider">
                切片统计
              </h3>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {sources.filter(s => s.status === 'processed').map(s => (
                  <div key={s.id} className="text-[11px] p-1.5 bg-gray-50 rounded">
                    <span className="text-gray-500">📦 {s.url?.slice(0, 30)}</span>
                    <span className="text-primary-600 ml-1 font-medium">{s.chunk_count || 0} 块</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Main content */}
        <div className="flex min-h-[540px] flex-1 overflow-hidden md:min-h-0">
          <div className="flex flex-1 flex-col overflow-hidden">
            <div className="flex shrink-0 items-center border-b border-gray-200 bg-white px-4 py-2.5">
              <h2 className="text-sm font-medium text-primary-600">🗺️ 学习路线</h2>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {hasRoadmap ? (
                <div>
                  <div className="mb-3 flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-gray-700">
                      已验证 {checkpoints.filter(c => c.learning_status === 'completed').length}/{checkpoints.length} 关
                    </h2>
                  </div>
                  <p className="mb-3 text-xs leading-5 text-gray-500">
                    这张路线图会随着你的反馈迭代；已产生学习记录的关卡会保留，避免丢失证据。
                  </p>
                  <CheckpointGraph
                    checkpoints={checkpoints}
                    onCheckpointClick={handleCheckpointClick}
                  />
                </div>
              ) : (
                <div className="flex h-64 items-center justify-center text-center text-sm text-gray-400">
                  <div>
                    <p>尚未生成正式学习路线</p>
                    <p className="mt-2 text-xs">请在右侧 Tutor 中确认路线，确认后这里会直接显示关卡。</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* T10: reconcile suggestion modal */}
      {reconcileSuggestion && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
             onClick={() => setReconcileSuggestion(null)}>
          <div className="bg-white rounded-xl shadow-xl w-[520px] max-h-[75vh] flex flex-col"
               onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 shrink-0">
              <h3 className="font-semibold text-gray-800">🧩 新来源整合建议</h3>
              <button onClick={() => setReconcileSuggestion(null)}
                      className="text-gray-400 hover:text-gray-600 text-sm px-1">✕</button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 text-sm space-y-3">
              <p className="text-xs text-gray-500">{reconcileSuggestion.reason || ''}</p>
              {(reconcileSuggestion.insert || []).length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-700 mb-1">📥 建议新增关卡</p>
                  {reconcileSuggestion.insert.map((ins: any, i: number) => (
                    <div key={i} className="border border-indigo-100 bg-indigo-50/50 rounded-lg p-2.5 mb-1.5">
                      <p className="font-medium text-gray-800">
                        {ins.after_order ? `插在第 ${ins.after_order} 关之后 · ` : ''}{ins.title}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5">{ins.description}</p>
                      {ins.files?.length > 0 && (
                        <p className="text-[10px] text-gray-400 mt-1 truncate">📄 {ins.files.join(', ')}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {(reconcileSuggestion.extend || []).length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-700 mb-1">📎 建议扩展已有关卡</p>
                  {reconcileSuggestion.extend.map((ex: any, i: number) => (
                    <div key={i} className="border border-amber-100 bg-amber-50/50 rounded-lg p-2.5 mb-1.5">
                      <p className="font-medium text-gray-800">关卡 {ex.checkpoint_order} 补充 {ex.files?.length || 0} 个文件</p>
                      <p className="text-[10px] text-gray-400 mt-1 truncate">📄 {(ex.files || []).join(', ')}</p>
                    </div>
                  ))}
                </div>
              )}
              {reconcileSuggestion.ignore && (
                <p className="text-xs text-gray-400">🤷 建议忽略该来源（与现有路线契合度低）</p>
              )}
            </div>
            <div className="flex gap-2 px-5 py-3 border-t border-gray-100 shrink-0">
              <button onClick={() => setReconcileSuggestion(null)}
                      className="bg-gray-100 text-gray-600 px-4 py-2 rounded-lg text-sm hover:bg-gray-200">
                取消
              </button>
              <button onClick={handleApplyReconcile} disabled={reconcileLoading}
                      className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-indigo-700 disabled:opacity-50">
                {reconcileLoading ? '应用中...' : '✅ 确认整合'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
