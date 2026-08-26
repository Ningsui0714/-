import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import SplitPane from "../components/layout/SplitPane"
import Editor from '@monaco-editor/react'
import {
  listExercises, runCode, reviewCode, submitExercise, getExerciseTask, subscribeTaskEvents, type TaskEventSubscription,
  runProject, submitProject, getExerciseEnv, getExerciseDraft, saveExerciseDraft,
  recordLearningEvent, listRemediationCases, listArtifactAnnotations,
  createArtifactAnnotation, updateArtifactAnnotation, deleteArtifactAnnotation,
  type ArtifactAnnotation,
} from '../services/api'
import ConceptQuestions from '../components/exercise/ConceptQuestions'
import RemediationPanel from '../components/exercise/RemediationPanel'
import { useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import { publishWorkspaceAgentContext } from '../components/workspace/workspaceAgentContext'

interface CodeMsg {
  role: 'user' | 'assistant'
  content: string
}

export default function ExercisePage() {
  const { projectId, checkpointId } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const pid = Number(projectId)
  const cid = Number(checkpointId)

  const [exercises, setExercises] = useState<any[]>([])
  const [activeEx, setActiveEx] = useState<any>(null)
  const [code, setCode] = useState('')
  // ── Project-mode (multi-file) ──
  const [files, setFiles] = useState<any[]>([])
  const [activeFileName, setActiveFileName] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [envReady, setEnvReady] = useState<boolean | null>(null)
  const [stdout, setStdout] = useState('')
  const [stderr, setStderr] = useState('')
  const [running, setRunning] = useState(false)
  const [loading, setLoading] = useState(true)
  const [annotations, setAnnotations] = useState<ArtifactAnnotation[]>([])
  const [descriptionSelection, setDescriptionSelection] = useState('')

  // Code workspace
  const [wsMessages, setWsMessages] = useState<CodeMsg[]>([])
  const [wsLoading, setWsLoading] = useState(false)
  const [selectedCode, setSelectedCode] = useState('')
  const [showDesc, setShowDesc] = useState(true)
  const [revealedHints, setRevealedHints] = useState(0)
  const [assistanceLevel, setAssistanceLevel] = useState<'none' | 'hint' | 'guided'>('none')
  const [tab, setTab] = useState<'concepts' | 'code'>('code')
  const [submitResult, setSubmitResult] = useState<any>(null)
  const [activeRemediation, setActiveRemediation] = useState<any>(null)
  const [remediationCases, setRemediationCases] = useState<Record<number, any>>({})
  const [submitting, setSubmitting] = useState(false)
  const [genTaskId, setGenTaskId] = useState<number | null>(null)
  const [genProgress, setGenProgress] = useState('')
  const [genError, setGenError] = useState('')
  // IDE extras
  const editorRef = useRef<any>(null)
  const vimDisposeRef = useRef<any>(null)
  const [vimEnabled, setVimEnabled] = useState(false)
  const [darkTheme, setDarkTheme] = useState(true)
  const [fontSize, setFontSize] = useState(13)
  const [vimLoading, setVimLoading] = useState(false)
  const wsEndRef = useRef<HTMLDivElement>(null)
  const genTaskSubscriptionRef = useRef<TaskEventSubscription | null>(null)

  useWorkspaceTitle(activeEx?.title ? `练习 · ${activeEx.title}` : `练习 · 关卡 ${cid}`, {
    kind: 'exercise', projectId: pid, checkpointId: cid,
  })

  useEffect(() => {
    loadExercises()
    // Recover a task that was started before a page reload or a transient
    // desktop-sidecar disconnect.
    getExerciseTask(cid).then((snap: any) => {
      if (snap?.task_id && ['queued', 'running'].includes(snap.status)) {
        setGenTaskId(snap.task_id)
        setGenProgress(snap.progress?.message || '生成中...')
        subscribeExerciseTask(snap.task_id)
      } else if (snap?.status === 'failed') {
        setGenError(snap.error?.guidance || snap.error?.message || '生成失败')
      }
    }).catch(() => {})
    return () => genTaskSubscriptionRef.current?.close()
  }, [cid])

  useEffect(() => {
    wsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [wsMessages])

  const loadExercises = async () => {
    setLoading(true)
    try {
      const [data, cases] = await Promise.all([
        listExercises(cid),
        listRemediationCases(cid).catch(() => []),
      ])
      const latestByExercise: Record<number, any> = {}
      for (const item of cases || []) {
        if (item.item_type === 'exercise' && !latestByExercise[item.item_id]) {
          latestByExercise[item.item_id] = item
        }
      }
      setExercises(data)
      setRemediationCases(latestByExercise)
      if (data.length > 0) {
        const requestedId = Number(searchParams.get('exercise'))
        selectExercise(data.find((item: any) => item.id === requestedId) || data[0], latestByExercise)
      }
    } catch { /* no exercises yet */ }
    setLoading(false)
  }

  const selectExercise = (ex: any, knownCases: Record<number, any> = remediationCases) => {
    setActiveEx(ex)
    setStdout('')
    setStderr('')
    setWsMessages([])
    setSelectedCode('')
    setSubmitResult(null)
    setActiveRemediation(knownCases[ex.id] || null)
    setSaveMsg('')
    setRevealedHints(0)
    setAssistanceLevel('none')
    setDescriptionSelection('')
    setAnnotations([])
    getExerciseDraft(ex.id).then(draft => {
      if (ex.files && ex.files.length > 0) {
        setFiles(draft.files || ex.files)
        setActiveFileName((draft.files || ex.files)[0]?.name || '')
        setCode('')
        getExerciseEnv(ex.id).then(env => setEnvReady(env.ready)).catch(() => setEnvReady(null))
      } else {
        setFiles([])
        setActiveFileName('')
        setCode(draft.code ?? ex.starter_code ?? '')
        setEnvReady(null)
      }
    }).catch(() => {
      setFiles(ex.files || [])
      setActiveFileName(ex.files?.[0]?.name || '')
      setCode(ex.files?.length ? '' : ex.starter_code || '')
    })
    listArtifactAnnotations('exercise', ex.id).then(setAnnotations).catch(() => setAnnotations([]))
  }

  const isProjectMode = () => activeEx?.files?.length > 0

  const activeFileContent = () => {
    const f = files.find(f => f.name === activeFileName)
    return f ? f.content : ''
  }

  useEffect(() => {
    publishWorkspaceAgentContext({
      kind: 'practice',
      checkpointId: cid,
      exerciseId: activeEx?.id,
      title: activeEx?.title || `关卡 ${cid} 练习`,
      selection: selectedCode,
      code: activeEx?.files?.length ? activeFileContent() : code,
    })
  }, [activeEx?.files?.length, activeEx?.id, activeEx?.title, activeFileName, cid, code, files, selectedCode])

  const updateActiveFile = (content: string) => {
    setFiles(prev => prev.map(f => f.name === activeFileName ? { ...f, content } : f))
  }

  const handleSave = async () => {
    if (!activeEx) return
    setSaving(true)
    setSaveMsg('')
    try {
      await saveExerciseDraft(activeEx.id, code, files)
      setSaveMsg('✅ 草稿已保存（不产生学习证据）')
    } catch (e: any) {
      setSaveMsg('❌ 保存失败: ' + (e?.response?.data?.detail || e.message))
    }
    setSaving(false)
  }

  const subscribeExerciseTask = (taskId: number) => {
    genTaskSubscriptionRef.current?.close()
    genTaskSubscriptionRef.current = subscribeTaskEvents(taskId, snap => {
      if (snap.progress?.message) setGenProgress(snap.progress.message)
      if (snap.status === 'completed') {
        setGenProgress('✅ 完成')
        setGenTaskId(null)
        genTaskSubscriptionRef.current?.close()
        void loadExercises()
      } else if (snap.status === 'failed') {
        setGenError(snap.error?.guidance || snap.error?.message || '生成失败')
        setGenProgress('❌ 生成失败')
        setGenTaskId(null)
        genTaskSubscriptionRef.current?.close()
      }
    }, message => {
      setGenError(`习题状态同步失败：${message}`)
      setGenTaskId(null)
      genTaskSubscriptionRef.current?.close()
    })
  }

  const handleGenerateEx = async () => {
    setGenError('')
    setGenProgress('排队中...')
    try {
      const { default: api } = await import('../services/api')
      const res = await api.post(`/checkpoints/${cid}/exercises/generate`)
      setGenTaskId(res.data.task_id)
      subscribeExerciseTask(res.data.task_id)
    } catch (e: any) {
      try {
        const snap = await getExerciseTask(cid)
        if (snap?.task_id && ['queued', 'running'].includes(snap.status)) {
          setGenTaskId(snap.task_id)
          setGenProgress(snap.progress?.message || '生成中...')
          subscribeExerciseTask(snap.task_id)
          return
        }
      } catch { /* surface the original error below */ }
      setGenError(e?.response?.data?.detail || e.message || '生成失败')
      setGenProgress('❌ 生成失败')
    }
  }

  const handleSubmit = async () => {
    if (!activeEx) return
    if (isProjectMode() && files.length === 0) return
    if (!isProjectMode() && !code.trim()) return
    setSubmitting(true)
    setSubmitResult(null)
    try {
      const retrying = activeRemediation?.status === 'explaining'
      const clientSubmissionId = globalThis.crypto?.randomUUID?.() || `exercise-submit-${activeEx.id}-${Date.now()}`
      const result = isProjectMode()
        ? await submitProject(
            activeEx.id, files, retrying ? 'guided' : assistanceLevel,
            retrying ? activeRemediation.id : undefined, retrying ? 'retry' : 'original',
            clientSubmissionId,
          )
        : await submitExercise(
            activeEx.id, code, retrying ? 'guided' : assistanceLevel,
            retrying ? activeRemediation.id : undefined, retrying ? 'retry' : 'original',
            clientSubmissionId,
          )
      setSubmitResult(result)
      if (result.remediation) {
        setActiveRemediation(result.remediation)
        setRemediationCases(prev => ({ ...prev, [activeEx.id]: result.remediation }))
        setAssistanceLevel('guided')
      }
    } catch (e: any) {
      setSubmitResult({ error: e?.response?.data?.detail || e.message })
    }
    setSubmitting(false)
  }

  const createSelectionAnnotation = async () => {
    if (!activeEx) return
    const selection = (selectedCode || descriptionSelection).trim()
    if (!selection) return
    const body = window.prompt('为选中内容添加批注')
    if (body === null || !body.trim()) return
    const item = await createArtifactAnnotation('exercise', activeEx.id, {
      anchor: { selection: selection.slice(0, 2000), surface: selectedCode ? 'answer' : 'prompt' },
      body: body.trim(), idempotency_key: crypto.randomUUID(),
    })
    setAnnotations(current => [item, ...current])
  }

  const editAnnotation = async (item: ArtifactAnnotation) => {
    const body = window.prompt('修改批注', item.note)
    if (body === null) return
    const next = await updateArtifactAnnotation(item.id, body)
    setAnnotations(current => current.map(value => value.id === next.id ? next : value))
  }

  const removeAnnotation = async (item: ArtifactAnnotation) => {
    if (!window.confirm('删除这条批注？')) return
    await deleteArtifactAnnotation(item.id)
    setAnnotations(current => current.filter(value => value.id !== item.id))
  }

  const retryExercise = () => {
    setSubmitResult(null)
    setStdout('')
    setStderr('')
    setAssistanceLevel('guided')
    editorRef.current?.focus()
  }

  const handleRun = async () => {
    setRunning(true)
    setStdout('')
    setStderr('')
    setSubmitResult(null)
    try {
      if (isProjectMode()) {
        const result = await runProject(activeEx.id, files)
        setStdout(result.stdout || '')
        setStderr(result.stderr || '')
        if (result.env && !result.env.ready) {
          setStderr(prev => (prev ? prev + '\n' : '') + '⚠️ 环境未就绪: ' + (result.env.message || ''))
        }
      } else {
        const result = await runCode(code, activeEx?.id)
        setStdout(result.stdout || '')
        setStderr(result.stderr || '')
      }
    } catch (e: any) {
      setStderr(String(e?.response?.data?.detail || e.message))
    }
    setRunning(false)
  }

  const handleReview = async () => {
    if (!activeEx) return
    setWsLoading(true)
    setAssistanceLevel('guided')
    const reviewCodeText = isProjectMode() ? activeFileContent() : code
    const msg: CodeMsg = { role: 'user', content: `请审阅这段代码 (${activeFileName || activeEx.title})` }
    setWsMessages(prev => [...prev, msg])
    try {
      const result = await reviewCode(activeEx.id, reviewCodeText, selectedCode)
      setWsMessages(prev => [...prev, { role: 'assistant', content: result.answer }])
    } catch (e: any) {
      setWsMessages(prev => [...prev, { role: 'assistant', content: '❌ ' + (e?.response?.data?.detail || '请求失败') }])
    }
    setWsLoading(false)
  }

  const revealHint = () => {
    if (!activeEx?.hints?.length || revealedHints >= activeEx.hints.length) return
    setRevealedHints(current => current + 1)
    setAssistanceLevel(current => current === 'guided' ? 'guided' : 'hint')
    recordLearningEvent({
      client_event_id: `hint-${activeEx.id}-${revealedHints + 1}-${Date.now()}`,
      event_type: 'hint_requested',
      project_id: pid,
      checkpoint_id: cid,
      payload: { exercise_id: activeEx.id, hint_index: revealedHints },
    }).catch(() => {})
  }

  // Monaco Editor mount & selection handler + IDE extras
  const handleEditorMount = (editor: any) => {
    editorRef.current = editor
    editor.onDidChangeCursorSelection(() => {
      const selection = editor.getModel()?.getValueInRange(editor.getSelection())
      setSelectedCode(selection || '')
    })
  }

  const editorAction = (cmd: string) => {
    editorRef.current?.trigger('ide-toolbar', cmd, null)
  }

  const toggleVim = async () => {
    if (!editorRef.current) return
    if (vimDisposeRef.current) {
      vimDisposeRef.current.dispose()
      vimDisposeRef.current = null
      setVimEnabled(false)
      return
    }
    setVimLoading(true)
    try {
      const { initVimMode } = await import('monaco-vim')
      vimDisposeRef.current = initVimMode(editorRef.current, document.getElementById('vim-status'))
      setVimEnabled(true)
    } catch (e: any) {
      alert('Vim 模式加载失败: ' + e.message)
    }
    setVimLoading(false)
  }

  const changeFontSize = (delta: number) => {
    const next = Math.min(24, Math.max(10, fontSize + delta))
    setFontSize(next)
    editorRef.current?.updateOptions({ fontSize: next })
  }

  useEffect(() => () => vimDisposeRef.current?.dispose?.(), [])

  if (loading) return <div className="p-8 text-gray-400">加载中...</div>

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-3 shrink-0 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate(`/projects/${pid}/checkpoints/${cid}`)}
            className="text-sm text-gray-400 hover:text-gray-600">
            ← 返回讲义
          </button>
          <span className="text-gray-300">|</span>
          <h1 className="text-lg font-semibold text-gray-900">练习</h1>
          {/* Tabs */}
          <div className="flex bg-gray-100 rounded-lg p-0.5 ml-2">
            <button
              onClick={() => setTab('concepts')}
              className={`px-3 py-1 rounded-md text-xs transition-colors ${
                tab === 'concepts' ? 'bg-white shadow text-primary-700 font-medium' : 'text-gray-500'
              }`}
            >
              🧠 概念题
            </button>
            <button
              onClick={() => setTab('code')}
              className={`px-3 py-1 rounded-md text-xs transition-colors ${
                tab === 'code' ? 'bg-white shadow text-primary-700 font-medium' : 'text-gray-500'
              }`}
            >
              💻 代码题
            </button>
          </div>
        </div>
        {tab === 'code' && !genTaskId && (
          <button onClick={handleGenerateEx}
            className="bg-primary-600 text-white px-3 py-1 rounded text-sm ml-auto
                       hover:bg-primary-700 transition-colors">
            {exercises.length > 0 ? '🔄 重新生成习题' : '🤖 生成习题'}
          </button>
        )}
        {tab === 'code' && genTaskId && (
          <span className="text-xs text-primary-600 flex items-center gap-2 ml-auto">
            <span className="w-2 h-2 rounded-full bg-primary-400 animate-pulse" />
            {genProgress || '生成中...'}
          </span>
        )}
      </div>

      {tab === 'code' && genError && (
        <div className="border-b border-red-200 bg-red-50 px-6 py-2 text-xs text-red-700">
          {genError}
          <button type="button" onClick={() => setGenError('')} className="ml-3 underline">关闭</button>
        </div>
      )}

      {/* Main area */}
      {tab === 'concepts' ? (
        <ConceptQuestions checkpointId={cid} />
      ) : (
      <div className="flex-1 flex overflow-hidden">
        <SplitPane
          direction="vertical"
          initialRatio={0.7}
          minLeft={200}
          minRight={120}
          left={
            <div className="h-full flex overflow-hidden">
              {/* Left: exercise list */}
              <div className="w-56 border-r border-gray-200 bg-white overflow-y-auto shrink-0 p-3">
                <h2 className="text-xs font-semibold text-gray-500 uppercase mb-2">题目列表</h2>
                {exercises.length === 0 && (
                  <p className="text-xs text-gray-400">此关卡暂无练习题</p>
                )}
                {exercises.map((ex, i) => (
                  <button
                    key={ex.id}
                    onClick={() => selectExercise(ex)}
                    className={`w-full text-left text-xs p-2 rounded-lg mb-1 transition-colors ${
                      activeEx?.id === ex.id
                        ? 'bg-primary-100 text-primary-700'
                        : 'hover:bg-gray-100 text-gray-700'
                    }`}
                  >
                    <span className="font-medium">{i + 1}. {ex.title}</span>
                  </button>
                ))}
              </div>

              {/* Center: Editor + Output (horizontal split) */}
              <div className="flex-1 flex flex-col overflow-hidden">
                {!activeEx ? (
                  <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
                    暂无练习题
                  </div>
                ) : (
                  <>
                    {/* Description — collapsible */}
                    <div className="bg-gray-50 border-b border-gray-200 shrink-0">
                      <button
                        onClick={() => setShowDesc(!showDesc)}
                        className="w-full flex items-center justify-between px-4 py-2 text-xs hover:bg-gray-100 transition-colors"
                      >
                        <span className="font-semibold text-gray-700">{activeEx.title}</span>
                        <span className="text-gray-400">{showDesc ? '▲ 收起' : '▼ 展开描述'}</span>
                      </button>
                      {showDesc && (
                        <div className="px-4 pb-2 max-h-40 overflow-y-auto text-xs space-y-1">
                          <p
                            className="text-gray-600 whitespace-pre-wrap"
                            onMouseUp={() => setDescriptionSelection(window.getSelection()?.toString().trim() || '')}
                          >{activeEx.description}</p>
                          {(descriptionSelection || selectedCode) && (
                            <button onClick={() => void createSelectionAnnotation()} className="rounded border border-violet-200 bg-violet-50 px-2 py-1 text-[10px] text-violet-700 hover:bg-violet-100">📝 批注选中内容</button>
                          )}
                          {revealedHints > 0 && (
                            <div className="space-y-1 border border-amber-200 bg-amber-50 px-2 py-1.5 text-amber-800 rounded-lg">
                              {activeEx.hints.slice(0, revealedHints).map((hint: string, index: number) => (
                                <p key={index}>{index + 1}. {hint}</p>
                              ))}
                            </div>
                          )}
                          {activeEx.hints?.length > revealedHints && (
                            <button onClick={revealHint} className="border border-amber-300 bg-white px-2.5 py-1 text-amber-700 hover:bg-amber-50 rounded">
                              查看下一条提示
                            </button>
                          )}
                          {assistanceLevel !== 'none' && (
                            <p className="text-[10px] text-gray-400">本次提交会标记为辅助完成</p>
                          )}
                          <p className="text-[10px] text-sky-700">个人草稿和“运行”不写掌握证据；只有“提交判题”进入学习证据链。</p>
                        </div>
                      )}
                    </div>

                    {/* Editor + Output (resizable) */}
                    <div className="flex-1 flex overflow-hidden">
                      <SplitPane
                        direction="horizontal"
                        initialRatio={0.65}
                        minLeft={200}
                        minRight={180}
                        left={
                          <div className="h-full flex flex-col">
                            {/* Project-mode: file tabs */}
                            {isProjectMode() && (
                              <div className="flex items-center gap-1 px-2 pt-1.5 pb-1 bg-gray-100 border-b border-gray-200 shrink-0 flex-wrap">
                                {files.map(f => (
                                  <button
                                    key={f.name}
                                    onClick={() => setActiveFileName(f.name)}
                                    className={`text-[11px] font-mono px-2.5 py-1 rounded-t transition-colors ${
                                      activeFileName === f.name
                                        ? 'bg-white text-primary-700 font-semibold border border-b-0 border-gray-200'
                                        : 'text-gray-500 hover:text-gray-700'
                                    }`}
                                  >
                                    {f.name}
                                    {f.read_only && <span className="text-gray-400 ml-1 text-[9px]">🔒</span>}
                                  </button>
                                ))}
                                <div className="ml-auto flex items-center gap-2">
                                  {envReady === false && (
                                    <span className="text-[10px] text-amber-600 bg-amber-50 px-2 py-0.5 rounded">
                                      ⚙️ 首次运行将自动准备环境（安装依赖，约 1-2 分钟）
                                    </span>
                                  )}
                                  <button onClick={handleSave} disabled={saving}
                                    className="text-[11px] bg-primary-600 text-white px-2.5 py-0.5 rounded hover:bg-primary-700 disabled:bg-gray-300">
                                    {saving ? '保存中...' : '💾 保存草稿'}
                                  </button>
                                  {saveMsg && <span className="text-[10px] text-gray-500">{saveMsg}</span>}
                                </div>
                              </div>
                            )}
                            <div className="flex-1">
                              <Editor
                                height="100%"
                                defaultLanguage="python"
                                theme={darkTheme ? 'vs-dark' : 'light'}
                                value={isProjectMode() ? activeFileContent() : code}
                                onChange={val => {
                                  if (isProjectMode()) updateActiveFile(val || '')
                                  else setCode(val || '')
                                }}
                                onMount={handleEditorMount}
                                options={{
                                  minimap: { enabled: false },
                                  fontSize,
                                  lineNumbers: 'on',
                                  scrollBeyondLastLine: false,
                                  renderWhitespace: 'none',
                                  readOnly: isProjectMode()
                                    ? (files.find(f => f.name === activeFileName)?.read_only || false)
                                    : false,
                                }}
                              />
                            </div>
                            {/* IDE toolbar: undo/redo/vim/theme/font */}
                            <div className="border-t border-gray-200 px-3 py-1 flex items-center gap-1 bg-gray-50 shrink-0">
                              <button onClick={() => editorAction('undo')} title="撤销 (Ctrl+Z)"
                                className="text-[11px] bg-white border border-gray-200 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-100">↩️ 撤销</button>
                              <button onClick={() => editorAction('redo')} title="重做 (Ctrl+Shift+Z)"
                                className="text-[11px] bg-white border border-gray-200 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-100">↪️ 重做</button>
                              <span className="w-px h-4 bg-gray-200 mx-1" />
                              <button onClick={toggleVim} disabled={vimLoading}
                                className={`text-[11px] px-2 py-0.5 rounded transition-colors ${
                                  vimEnabled
                                    ? 'bg-violet-600 text-white'
                                    : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-100'
                                } disabled:opacity-50`}
                                title="Vim 键位模式 (Esc 切回 NORMAL)">
                                {vimLoading ? '加载中...' : (vimEnabled ? 'Vim: ON' : 'Vim: OFF')}
                              </button>
                              <span className="w-px h-4 bg-gray-200 mx-1" />
                              <button onClick={() => setDarkTheme(!darkTheme)} title="切换主题"
                                className="text-[11px] bg-white border border-gray-200 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-100">
                                {darkTheme ? '☀️' : '🌙'}
                              </button>
                              <button onClick={() => changeFontSize(-1)} title="缩小字号"
                                className="text-[11px] bg-white border border-gray-200 text-gray-600 px-1.5 py-0.5 rounded hover:bg-gray-100">A-</button>
                              <span className="text-[10px] text-gray-400 w-7 text-center">{fontSize}</span>
                              <button onClick={() => changeFontSize(1)} title="放大字号"
                                className="text-[11px] bg-white border border-gray-200 text-gray-600 px-1.5 py-0.5 rounded hover:bg-gray-100">A+</button>
                            </div>
                            {/* Vim status bar */}
                            {vimEnabled && (
                              <div id="vim-status"
                                   className="border-t border-violet-200 bg-violet-50 text-violet-700 text-[10px] font-mono px-3 py-0.5 shrink-0">
                                -- NORMAL --
                              </div>
                            )}
                            <div className="border-t border-gray-200 px-3 py-1.5 flex gap-2 bg-white shrink-0">
                              <button onClick={handleSave} disabled={saving}
                                className="border border-gray-300 bg-white px-3 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50 rounded">
                                {saving ? '保存中...' : '💾 保存草稿'}
                              </button>
                              <button onClick={handleRun} disabled={running}
                                className="bg-green-600 text-white px-3 py-1 rounded text-xs hover:bg-green-700 disabled:bg-gray-300">
                                {running ? '运行中...' : '▶ 运行'}
                              </button>
                              <button onClick={handleSubmit} disabled={submitting || activeRemediation?.status === 'variant_ready' || (isProjectMode() ? files.length === 0 : !code.trim())}
                                className="bg-gray-900 text-white px-3 py-1 rounded text-xs hover:bg-gray-700 disabled:bg-gray-300">
                                {submitting ? '判题中...' : activeRemediation?.status === 'variant_ready' ? '请先完成变式' : '📋 提交判题'}
                              </button>
                              <button onClick={handleReview} disabled={wsLoading}
                                className="bg-primary-600 text-white px-3 py-1 rounded text-xs hover:bg-primary-700 disabled:bg-gray-300">
                                ✔ 审阅
                              </button>
                              {isProjectMode() && (
                                <span className="text-[10px] text-gray-400 self-center">
                                  📁 练习专用运行环境；草稿不产生证据
                                </span>
                              )}
                              {selectedCode && (
                                <span className="text-[10px] text-gray-400 self-center">
                                  已选中 {selectedCode.length} 字符
                                </span>
                              )}
                            </div>
                          </div>
                        }
                        right={
                          <div className="h-full bg-gray-900 text-gray-100 text-xs font-mono p-3 overflow-y-auto">
                            <div className="text-gray-500 text-[10px] uppercase mb-2">输出面板</div>
                            {submitResult && (
                              <div className={`mb-3 rounded p-2 ${submitResult.error ? 'bg-red-900/40 text-red-300' : 'bg-gray-800'}`}>
                                {submitResult.error ? (
                                  <p>❌ {submitResult.error}</p>
                                ) : (
                                  <>
                                    <p className={`font-bold mb-1 ${submitResult.passed === submitResult.total ? 'text-green-400' : 'text-amber-400'}`}>
                                      {submitResult.passed === submitResult.total
                                        ? `✅ 全部通过 (${submitResult.passed}/${submitResult.total})`
                                        : `❌ ${submitResult.passed}/${submitResult.total} 通过`}
                                    </p>
                                    {submitResult.results?.map((r: any, i: number) => (
                                      <div key={i} className={`mt-1 ${r.passed ? 'text-green-400' : 'text-red-400'}`}>
                                        {r.passed ? '✓' : '✗'} 用例 {i + 1}
                                        {!r.passed && (
                                          <span className="text-gray-400">
                                            {' '}期望 {r.expected} → 实际 {r.actual}
                                            {r.stderr ? `（${r.stderr.slice(0, 60)}）` : ''}
                                          </span>
                                        )}
                                      </div>
                                    ))}
                                  </>
                                )}
                              </div>
                            )}
                            {stdout && <pre className="whitespace-pre-wrap">{stdout}</pre>}
                            {stderr && <pre className="whitespace-pre-wrap text-red-400">{stderr}</pre>}
                            {!stdout && !stderr && !submitResult && (
                              <div className="text-gray-600">点击「▶ 运行」执行代码，或「📋 提交判题」跑测试用例</div>
                            )}
                          </div>
                        }
                      />
                    </div>
                  </>
                )}
              </div>
            </div>
          }
          right={
            <div className="h-full flex flex-col bg-white">
              <div className="flex items-center justify-between px-4 py-1.5 border-b border-gray-100 shrink-0">
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-2 h-2 rounded-full bg-primary-400" />
                  <span className="font-medium text-gray-700">纠错与审阅记录</span>
                  {selectedCode && (
                    <span className="text-gray-400 truncate max-w-[200px]">
                      「{selectedCode.slice(0, 40)}...」
                    </span>
                  )}
                </div>
              </div>
              <div className="flex-1 overflow-y-auto px-4 py-1.5 space-y-1.5 text-xs">
                {activeRemediation && (
                  <div className="mb-3">
                    <RemediationPanel
                      remediation={activeRemediation}
                      onChange={next => {
                        setActiveRemediation(next)
                        if (activeEx) setRemediationCases(prev => ({ ...prev, [activeEx.id]: next }))
                      }}
                      onRetry={retryExercise}
                    />
                  </div>
                )}
                {annotations.length > 0 && (
                  <div className="mb-3 space-y-2 border-b border-gray-100 pb-3">
                    <p className="font-medium text-gray-600">我的批注</p>
                    {annotations.map(item => (
                      <button key={item.id} onClick={() => void editAnnotation(item)} className="block w-full rounded-lg border border-violet-100 bg-violet-50 p-2 text-left hover:bg-violet-100">
                        <span className="block truncate text-[10px] text-violet-500">{item.selection || '未定位内容'}</span>
                        <span className="mt-1 block whitespace-pre-wrap text-gray-700">{item.note}</span>
                        <span onClick={event => { event.stopPropagation(); void removeAnnotation(item) }} className="mt-1 inline-block text-[10px] text-gray-400 hover:text-red-500">删除</span>
                      </button>
                    ))}
                  </div>
                )}
                {wsMessages.length === 0 && (
                  <div className="text-gray-400 text-center py-4">
                    点击编辑器下方「审阅」记录代码反馈；自由追问请使用右侧 Agent 对话
                  </div>
                )}
                {wsMessages.map((m, i) => (
                  <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[85%] rounded-lg px-2.5 py-1.5 whitespace-pre-wrap ${
                      m.role === 'user' ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-800'
                    }`}>
                      {m.content}
                    </div>
                  </div>
                ))}
                {wsLoading && <div className="text-gray-400 animate-pulse">思考中...</div>}
                <div ref={wsEndRef} />
              </div>
            </div>
          }
        />
      </div>
      )}
    </div>
  )
}
