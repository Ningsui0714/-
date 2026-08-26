import { useState, useEffect, useCallback, useRef } from 'react'
import { useLocation, useParams, useNavigate } from 'react-router-dom'
import {
  getLecture, saveLecture,
  createLectureTask, getActiveLectureTask, cancelTask, subscribeTaskEvents, type TaskEventSubscription,
  listLectureVersions, rollbackLecture,
  recordLearningEvent, listNotes, createNote, updateNote, deleteNote,
} from '../services/api'
import LectureRenderer, { type LectureNote } from '../components/lecture/LectureRenderer'
import ConceptGraphModal from '../components/lecture/ConceptGraphModal'
import TutorPanel from '../components/tutor/TutorPanel'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import { publishWorkspaceAgentContext } from '../components/workspace/workspaceAgentContext'

interface Section {
  title: string
  content: string
  keywords?: string[]
  questions?: string[]
}

export default function CheckpointPage() {
  const { projectId, checkpointId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const cid = Number(checkpointId)
  const pid = Number(projectId)

  const [sections, setSections] = useState<Section[]>([])
  const [animations, setAnimations] = useState<Record<number, any>>({})
  const [status, setStatus] = useState<'loading' | 'none' | 'draft' | 'published'>('loading')
  const [generating, setGenerating] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const [taskError, setTaskError] = useState<any>(null)  // structured {code, message, guidance}
  const [taskId, setTaskId] = useState<number | null>(null)
  const [checkpointTitle, setCheckpointTitle] = useState('')
  const [selectedText, setSelectedText] = useState('')
  const [selectedSection, setSelectedSection] = useState(0)
  const [notes, setNotes] = useState<LectureNote[]>([])
  const [lectureVersion, setLectureVersion] = useState(0)
  const [editingLecture, setEditingLecture] = useState(false)
  const [editSections, setEditSections] = useState<Section[]>([])
  const [showVersions, setShowVersions] = useState(false)
  const [versions, setVersions] = useState<any[]>([])
  const [versionLoading, setVersionLoading] = useState(false)
  const [showGraph, setShowGraph] = useState(false)
  const [conceptGraph, setConceptGraph] = useState<any>(null)
  const [feedback, setFeedback] = useState('')
  const [showTutor, setShowTutor] = useState(false)
  const esRef = useRef<TaskEventSubscription | null>(null)
  const embedded = new URLSearchParams(location.search).get('embed') === '1'

  useWorkspaceTitle(checkpointTitle || `讲义 · 关卡 ${cid}`, {
    kind: 'lecture', projectId: pid, checkpointId: cid,
  })

  const refreshNotes = useCallback(async () => {
    try {
      setNotes(await listNotes(cid) || [])
    } catch {
      setNotes([])
    }
  }, [cid])

  useEffect(() => {
    refreshNotes()
  }, [refreshNotes])

  useEffect(() => {
    publishWorkspaceAgentContext({
      kind: 'learning_design',
      checkpointId: cid,
      title: checkpointTitle || `关卡 ${cid}`,
      selection: selectedText,
      sectionIndex: selectedSection,
    })
  }, [cid, checkpointTitle, selectedSection, selectedText])

  // ── Load lecture on mount ──
  useEffect(() => {
    loadLecture()
    // Recover: if a generation task is still running, re-subscribe
    getActiveLectureTask(cid).then((snap: any) => {
      if (snap?.task_id && ['queued', 'running'].includes(snap.status)) {
        setTaskId(snap.task_id)
        setGenerating(true)
        setProgress(snap.progress?.message || '生成中...')
        if (snap.sections?.length) setSections(snap.sections)
        subscribeTask(snap.task_id)
      } else if (snap?.status === 'failed' && snap.sections?.length) {
        setTaskError(snap.error)
        setError(snap.error?.message || '上次生成失败')
      }
    }).catch(() => {})
    return () => closeEventSource()
  }, [cid])

  const closeEventSource = () => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
  }

  const loadLecture = async () => {
    setStatus('loading')
    setError('')
    try {
      try {
        const rmResp = await fetch(`/api/projects/${pid}/roadmap`)
        const rm = await rmResp.json()
        const cp = (rm.checkpoints || []).find((c: any) => c.id === cid)
        if (cp) {
          setCheckpointTitle(`#${cp.order} ${cp.title}`)
        }
      } catch {}

      const data = await getLecture(cid)
      setLectureVersion(Number(data.version || 0))
      if (data.sections && data.sections.length > 0) {
        setSections(data.sections)
        setStatus(data.status || 'published')
        if (data.concept_graph?.nodes?.length) setConceptGraph(data.concept_graph)
        if (!embedded) {
          recordLearningEvent({
            client_event_id: `lecture-view-${cid}-${data.id || 'draft'}`,
            event_type: 'lecture_viewed',
            project_id: pid,
            checkpoint_id: cid,
            payload: { lecture_id: data.id, sections_count: data.sections.length },
          }).catch(() => {})
        }
      } else {
        setSections([])
        setStatus('none')
      }
      // process-animator: 讲义内嵌动画映射 {id -> animation}
      if (data.animations?.length) {
        const map: Record<number, any> = {}
        data.animations.forEach((a: any) => { map[a.id] = a })
        setAnimations(map)
      }
    } catch {
      setStatus('none')
    }
  }

  // ── Task subscription ──
  const subscribeTask = (id: number) => {
    closeEventSource()
    esRef.current = subscribeTaskEvents(id, snap => {
      if (snap.type !== 'snapshot') return
      if (snap.sections) {
        setSections(snap.sections)
        // Partial sections are already valid draft content and should be
        // rendered while later sections are still being generated.
        if (snap.sections.length > 0) setStatus('draft')
      }
      if (snap.progress?.message) setProgress(snap.progress.message)

      if (snap.status === 'completed') {
        setGenerating(false)
        setTaskError(null)
        setError('')
        setProgress(`✅ ${snap.progress?.message || '完成！'}`)
        setStatus('published')
        closeEventSource()
      } else if (snap.status === 'failed') {
        setGenerating(false)
        setTaskError(snap.error)
        setError(snap.error?.message || '生成失败')
        setProgress(`❌ ${snap.error?.guidance || '生成失败'}`)
        if (snap.sections?.length) setStatus('draft')
        closeEventSource()
      } else if (snap.status === 'canceled') {
        setGenerating(false)
        setProgress('已取消')
        setStatus(snap.sections?.length ? 'draft' : 'none')
        closeEventSource()
      }
    }, message => {
      setGenerating(false)
      setError(`讲义状态同步失败：${message}`)
      setProgress('❌ 无法连接生成任务，请刷新后重试')
      void loadLecture()
      closeEventSource()
    })
  }

  const handleGenerate = (mode: 'fresh' | 'resume' = 'fresh') => {
    setGenerating(true)
    setError('')
    setTaskError(null)
    if (mode === 'fresh') {
      setSections([])
      setProgress('排队中...')
    } else {
      setProgress('从上次进度续生成...')
    }

    createLectureTask(cid, mode, feedback)
      .then((res: any) => {
        setTaskId(res.task_id)
        if (res.already_running) {
          setProgress('检测到进行中的任务，正在恢复...')
        }
        subscribeTask(res.task_id)
      })
      .catch((e: any) => {
        setGenerating(false)
        const msg = e?.response?.data?.detail || e.message
        setError(msg)
        setProgress(`❌ ${msg}`)
      })
  }

  const handleCancel = async () => {
    if (!taskId) return
    try {
      await cancelTask(taskId)
      setProgress('正在取消...')
    } catch {}
  }

  // ── T5: version history + rollback ──
  const openVersions = async () => {
    setShowVersions(true)
    setVersionLoading(true)
    try {
      const data = await listLectureVersions(cid)
      setVersions(data || [])
    } catch {
      setVersions([])
    }
    setVersionLoading(false)
  }

  const handleRollback = async (versionId: number, preview: string) => {
    if (!window.confirm(`确定回滚到版本「${preview || versionId}」？当前讲义会被存档后替换。`)) return
    setVersionLoading(true)
    try {
      await rollbackLecture(cid, versionId)
      await loadLecture()
      setShowVersions(false)
      setProgress('✅ 已回滚到历史版本')
    } catch (e: any) {
      setError('回滚失败: ' + (e?.response?.data?.detail || e.message))
    }
    setVersionLoading(false)
  }

  const handleTextSelect = useCallback((text: string, sectionIndex: number = 0) => {
    setSelectedText(text)
    setSelectedSection(sectionIndex)
  }, [])

  const handleAskSelection = useCallback((text: string, sectionIndex: number = 0) => {
    setSelectedText(text)
    setSelectedSection(sectionIndex)
    publishWorkspaceAgentContext({
      kind: 'learning_design',
      checkpointId: cid,
      title: checkpointTitle || `关卡 ${cid}`,
      selection: text,
      sectionIndex,
    })
    window.dispatchEvent(new CustomEvent('learnflow:agent-open'))
  }, [checkpointTitle, cid])

  const handleCreateAnchoredNote = useCallback(async (selection: string, sectionIndex: number, note: string) => {
    try {
      await createNote(cid, { section_index: sectionIndex, selection: selection.slice(0, 500), note })
      await refreshNotes()
    } catch (error: any) {
      alert('保存笔记失败：' + (error?.response?.data?.detail || error.message))
      throw error
    }
  }, [cid, refreshNotes])

  const handleUpdateAnchoredNote = useCallback(async (noteId: number, note: string) => {
    try {
      await updateNote(noteId, note)
      await refreshNotes()
    } catch (error: any) {
      alert('修改笔记失败：' + (error?.response?.data?.detail || error.message))
      throw error
    }
  }, [refreshNotes])

  const handleDeleteAnchoredNote = useCallback(async (noteId: number) => {
    try {
      await deleteNote(noteId)
      await refreshNotes()
    } catch (error: any) {
      alert('删除笔记失败：' + (error?.response?.data?.detail || error.message))
      throw error
    }
  }, [refreshNotes])

  // T6: delete an image from a section (removes the markdown reference, then saves)
  const handleDeleteImage = useCallback(async (sectionIndex: number, src: string) => {
    if (!window.confirm('删除这张图片？（可从版本历史回滚）')) return
    const esc = src.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const mdRe = new RegExp(`!\\[[^\\]]*\\]\\(${esc}\\)`)
    const htmlRe = new RegExp(`<img[^>]*src=[\"']${esc}[\"'][^>]*/?>`)
    setSections(prev => {
      const next = prev.map((s, i) => {
        if (i !== sectionIndex) return s
        let content = s.content.replace(mdRe, '').replace(htmlRe, '')
        content = content.replace(/\n{3,}/g, '\n\n')
        return { ...s, content }
      })
      saveLecture(cid, next, lectureVersion, crypto.randomUUID()).then(result => {
        setLectureVersion(Number(result.version || lectureVersion + 1))
        setProgress('✅ 已删除图片')
      }).catch((e: any) => {
        const detail = e?.response?.data?.detail
        setError('保存失败: ' + (detail?.message || detail || e.message))
        void loadLecture()
      })
      return next
    })
  }, [cid, lectureVersion])

  const beginLectureEdit = () => {
    setEditSections(sections.map(section => ({ ...section })))
    setEditingLecture(true)
  }

  const saveLectureEdit = async () => {
    setVersionLoading(true)
    try {
      const result = await saveLecture(cid, editSections, lectureVersion, crypto.randomUUID())
      setSections(editSections)
      setLectureVersion(Number(result.version || lectureVersion + 1))
      setEditingLecture(false)
      setProgress(`✅ 讲义 v${result.version} 已保存，旧版本已归档`)
      await refreshNotes()
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      if (e?.response?.status === 409) {
        setError(detail?.message || '讲义已有新版本，已重新载入；请重新编辑。')
        setEditingLecture(false)
        await loadLecture()
      } else {
        setError('保存失败: ' + (detail?.message || detail || e.message))
      }
    }
    setVersionLoading(false)
  }

  const canResume = status === 'draft' && sections.length > 0 && !generating
  const anchoredNotes = notes.filter(note => note.status !== 'orphaned')
  const orphanedNotes = notes.filter(note => note.status === 'orphaned')

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-3 shrink-0 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowTutor(true)}
            className="border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 rounded-lg"
          >
            Tutor
          </button>
          <button onClick={() => navigate(`/projects/${pid}`)}
            className="text-sm text-gray-400 hover:text-gray-600">
            ← 返回项目
          </button>
          <span className="text-gray-300">|</span>
          <h1 className="text-lg font-semibold text-gray-900">
            {checkpointTitle || `关卡 ${checkpointId}`}
          </h1>
        </div>

        <div className="flex items-center gap-3">
          {!generating && (
            <>
              <input
                type="text"
                value={feedback}
                onChange={e => setFeedback(e.target.value)}
                placeholder="生成偏好提示词（可选），如：方案要中国大陆可用"
                className="w-64 text-sm border border-gray-200 rounded-lg px-3 py-1.5
                           focus:outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-200
                           placeholder:text-gray-400"
                title="重新生成讲义时，这个提示词会被注入到生成 prompt 中"
              />
              <button
                onClick={() => handleGenerate('fresh')}
                className="bg-primary-600 text-white px-4 py-1.5 rounded-lg text-sm
                           hover:bg-primary-700 transition-colors"
              >
                {status === 'published' ? '🔄 重新生成' : '📝 生成讲义'}
              </button>
              {canResume && (
                <button
                  onClick={() => handleGenerate('resume')}
                  className="bg-amber-500 text-white px-4 py-1.5 rounded-lg text-sm
                             hover:bg-amber-600 transition-colors"
                >
                  ⏯ 续生成（{sections.length} 节）
                </button>
              )}
            </>
          )}
          {generating && (
            <button
              onClick={handleCancel}
              className="bg-red-50 text-red-600 px-4 py-1.5 rounded-lg text-sm
                         hover:bg-red-100 transition-colors"
            >
              ⏹ 取消
            </button>
          )}
          <button
            onClick={() => navigate(`/projects/${pid}/checkpoints/${cid}/exercises`)}
            className="bg-gray-100 text-gray-700 px-4 py-1.5 rounded-lg text-sm
                       hover:bg-gray-200 transition-colors"
          >
            💻 练习
          </button>
          {sections.length > 0 && !generating && (
            <>
              <span className="text-xs text-gray-400">v{lectureVersion}</span>
              <button
                onClick={beginLectureEdit}
                className="bg-gray-100 text-gray-700 px-4 py-1.5 rounded-lg text-sm hover:bg-gray-200 transition-colors"
              >
                ✏️ 编辑讲义
              </button>
              <button
                onClick={() => setShowGraph(true)}
                className="bg-gray-100 text-gray-700 px-4 py-1.5 rounded-lg text-sm
                           hover:bg-gray-200 transition-colors"
              >
                🕸 概念图谱
              </button>
              <button
                onClick={openVersions}
                className="bg-gray-100 text-gray-700 px-4 py-1.5 rounded-lg text-sm
                           hover:bg-gray-200 transition-colors"
              >
                🕘 版本
              </button>
            </>
          )}
          {selectedText && (
            <button
              onClick={() => handleAskSelection(selectedText, selectedSection)}
              className="bg-primary-50 text-primary-700 px-3 py-1.5 rounded-lg text-sm
                         hover:bg-primary-100 transition-colors"
            >
              💬 在右侧追问
            </button>
          )}
        </div>
      </div>

      {showTutor && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/20" onClick={() => setShowTutor(false)}>
          <div className="h-full w-full max-w-md bg-white p-3 shadow-xl" onClick={event => event.stopPropagation()}>
            <div className="mb-2 flex justify-end">
              <button onClick={() => setShowTutor(false)} className="h-8 w-8 text-gray-500 hover:bg-gray-100 rounded">×</button>
            </div>
            <TutorPanel projectId={pid} checkpointId={cid} className="h-[calc(100%_-_2.5rem)]" />
          </div>
        </div>
      )}

      {/* Progress / error bar */}
      {(generating || progress) && (
        <div className={`px-6 py-2 text-sm border-b shrink-0 ${
          error ? 'bg-red-50 text-red-700 border-red-200' :
          generating ? 'bg-primary-50 text-primary-700 border-primary-200' :
          progress.includes('❌') || progress.includes('已取消') ? 'bg-amber-50 text-amber-700 border-amber-200' :
          'bg-green-50 text-green-700 border-green-200'
        }`}>
          <div className="flex items-center gap-2">
            {generating && !error && (
              <span className="w-2 h-2 rounded-full bg-primary-400 animate-pulse" />
            )}
            {progress}
          </div>
        </div>
      )}

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-4xl mx-auto">
            {/* Empty state */}
            {status === 'none' && sections.length === 0 && !error && (
              <div className="text-center text-gray-400 py-20">
                <p className="text-5xl mb-4">📖</p>
                <p className="text-lg mb-2">此关卡还没有讲义</p>
                <p className="text-sm">点击右上角「📝 生成讲义」，AI 将根据参考资料生成结构化讲义</p>
              </div>
            )}

            {/* Persistent error in content area */}
            {error && sections.length === 0 && (
              <div className="text-center py-16">
                <p className="text-4xl mb-3">⚠️</p>
                <p className="text-red-600 font-medium mb-2">讲义生成失败</p>
                <p className="text-gray-500 text-sm mb-2">{error}</p>
                {taskError?.guidance && (
                  <p className="text-gray-400 text-xs mb-4">{taskError.guidance}</p>
                )}
                <button
                  onClick={() => handleGenerate('fresh')}
                  className="mt-4 bg-primary-600 text-white px-5 py-2 rounded-lg text-sm
                             hover:bg-primary-700 transition-colors"
                >
                  重新生成
                </button>
              </div>
            )}

            {/* Partial failure banner (some sections saved) */}
            {error && sections.length > 0 && (
              <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-800">
                <p className="font-medium mb-1">⚠️ 生成中断：已保留 {sections.length} 节内容</p>
                <p className="text-xs text-amber-700 mb-2">{taskError?.guidance || error}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleGenerate('resume')}
                    className="bg-amber-500 text-white px-3 py-1 rounded text-xs hover:bg-amber-600"
                  >
                    ⏯ 续生成
                  </button>
                  <button
                    onClick={() => handleGenerate('fresh')}
                    className="bg-white border border-amber-300 text-amber-700 px-3 py-1 rounded text-xs hover:bg-amber-50"
                  >
                    重新生成
                  </button>
                </div>
              </div>
            )}

            {/* Loading */}
            {status === 'loading' && sections.length === 0 && (
              <div className="text-center text-gray-400 py-20">
                <span className="animate-pulse">加载中...</span>
              </div>
            )}

            {/* Lecture content */}
            {orphanedNotes.length > 0 && !editingLecture && (
              <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
                <p className="text-sm font-semibold text-amber-800">未定位笔记（{orphanedNotes.length}）</p>
                <p className="mb-3 text-xs text-amber-700">正文已变化，原锚点无法唯一定位；笔记仍保留，可修改或删除。</p>
                <div className="space-y-2">
                  {orphanedNotes.map(note => (
                    <button key={note.id} onClick={() => void handleUpdateAnchoredNote(note.id, window.prompt('修改笔记', note.note) ?? note.note)} className="block w-full rounded-lg border border-amber-100 bg-white p-2 text-left text-xs hover:bg-amber-50">
                      <span className="block truncate text-[10px] text-amber-500">{note.selection || '原文已不存在'}</span>
                      <span className="mt-1 block whitespace-pre-wrap text-gray-700">{note.note}</span>
                      <span onClick={event => { event.stopPropagation(); void handleDeleteAnchoredNote(note.id) }} className="mt-1 inline-block text-[10px] text-gray-400 hover:text-red-500">删除</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {sections.length > 0 && !editingLecture && (
              <LectureRenderer
                sections={sections}
                animations={animations}
                onSelect={handleTextSelect}
                onAskSelection={handleAskSelection}
                notes={anchoredNotes}
                onCreateNote={handleCreateAnchoredNote}
                onUpdateNote={handleUpdateAnchoredNote}
                onDeleteNote={handleDeleteAnchoredNote}
                onDeleteImage={handleDeleteImage}
              />
            )}
            {editingLecture && (
              <div className="space-y-4">
                <div className="sticky top-0 z-10 flex items-center justify-between rounded-xl border border-primary-100 bg-white p-3 shadow-sm">
                  <div><p className="text-sm font-semibold text-gray-800">版本化编辑讲义</p><p className="text-xs text-gray-500">基于 v{lectureVersion} 保存；如版本已变化会拒绝覆盖。</p></div>
                  <div className="flex gap-2"><button onClick={() => setEditingLecture(false)} className="rounded-lg border px-3 py-1.5 text-sm text-gray-600">取消</button><button onClick={() => void saveLectureEdit()} disabled={versionLoading} className="rounded-lg bg-primary-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">{versionLoading ? '保存中…' : '保存新版本'}</button></div>
                </div>
                {editSections.map((section, index) => (
                  <div key={index} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                    <div className="mb-2 flex gap-2"><span className="pt-2 text-xs text-gray-400">{index + 1}</span><input value={section.title} onChange={event => setEditSections(current => current.map((value, i) => i === index ? { ...value, title: event.target.value } : value))} className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm font-semibold outline-none focus:border-primary-400" /></div>
                    <textarea value={section.content} onChange={event => setEditSections(current => current.map((value, i) => i === index ? { ...value, content: event.target.value } : value))} rows={14} className="w-full resize-y rounded-lg border border-gray-200 p-3 font-mono text-xs leading-6 outline-none focus:border-primary-400" />
                    <button onClick={() => setEditSections(current => current.filter((_, i) => i !== index))} className="mt-2 text-xs text-red-500 hover:text-red-700">删除小节</button>
                  </div>
                ))}
                <button onClick={() => setEditSections(current => [...current, { title: '新小节', content: '' }])} className="w-full rounded-xl border border-dashed border-gray-300 py-3 text-sm text-gray-500 hover:border-primary-400 hover:text-primary-600">＋ 添加小节</button>
              </div>
            )}
          </div>
        </div>

      </div>

      {/* Concept graph modal */}
      {showGraph && (
        <ConceptGraphModal
          checkpointId={cid}
          graph={conceptGraph}
          sections={sections}
          onClose={() => setShowGraph(false)}
          onGraphUpdate={g => { setConceptGraph(g); setShowGraph(false) }}
        />
      )}

      {/* Version history modal (T5) */}
      {showVersions && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
             onClick={() => setShowVersions(false)}>
          <div className="bg-white rounded-xl shadow-xl w-[480px] max-h-[70vh] flex flex-col"
               onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 shrink-0">
              <h3 className="font-semibold text-gray-800">🕘 讲义版本历史</h3>
              <button onClick={() => setShowVersions(false)}
                      className="text-gray-400 hover:text-gray-600 text-sm px-1">✕</button>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {versionLoading && <p className="text-gray-400 text-sm text-center py-6">加载中...</p>}
              {!versionLoading && versions.length === 0 && (
                <p className="text-gray-400 text-sm text-center py-6">
                  暂无历史版本。重新生成讲义时会自动保存上一版。
                </p>
              )}
              {versions.map((v: any, i: number) => (
                <div key={v.id} className="border border-gray-100 rounded-lg p-3 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm text-gray-800 font-medium truncate">
                      {v.preview || `版本 #${v.id}`}
                    </p>
                    <p className="text-xs text-gray-400">
                      {v.sections_count} 节 · {v.reason === 'regenerate_before' ? '重新生成前自动存档' : v.reason === 'before_rollback' ? '回滚前存档' : v.reason}
                      {v.created_at ? ` · ${new Date(v.created_at).toLocaleString('zh-CN')}` : ''}
                    </p>
                  </div>
                  <button
                    onClick={() => handleRollback(v.id, v.preview)}
                    disabled={versionLoading}
                    className="bg-amber-50 text-amber-700 border border-amber-200 px-3 py-1 rounded-lg text-xs
                               hover:bg-amber-100 disabled:opacity-50 shrink-0"
                  >
                    回滚
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
