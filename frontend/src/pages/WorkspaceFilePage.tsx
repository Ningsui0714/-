import Editor from '@monaco-editor/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import {
  AlertTriangle, Binary, Columns2, ExternalLink, Eye, FileCode2, Loader2,
  RefreshCw, Save, SquareCode, ToggleLeft, ToggleRight,
} from 'lucide-react'
import { useLocation, useParams, useSearchParams } from 'react-router-dom'
import { useWorkspace, useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import {
  getWorkspaceFile, getWorkspacePreview, openWorkspaceItem, revealWorkspaceItem,
  saveWorkspaceFile, type WorkspaceFile,
} from '../services/api'
import { getDesktopRuntime } from '../services/desktopRuntime'
import 'katex/dist/katex.min.css'

const languageByExtension: Record<string, string> = {
  py: 'python', ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript',
  json: 'json', md: 'markdown', markdown: 'markdown', html: 'html', css: 'css', scss: 'scss',
  yml: 'yaml', yaml: 'yaml', toml: 'ini', ini: 'ini', sh: 'shell', bash: 'shell',
  sql: 'sql', rs: 'rust', go: 'go', java: 'java', cpp: 'cpp', c: 'c', h: 'cpp',
  txt: 'plaintext', csv: 'plaintext', xml: 'xml', svg: 'xml',
}

function editorLanguage(path: string) {
  return languageByExtension[path.split('.').pop()?.toLowerCase() || ''] || 'plaintext'
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function errorMessage(error: any) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return error instanceof Error ? error.message : '文件操作失败'
}

function relativeWorkspacePath(markdownPath: string, source: string) {
  if (!source || /^(?:https?:|data:|blob:)/i.test(source)) return null
  const clean = source.split('#')[0].split('?')[0].replace(/\\/g, '/')
  const stack = markdownPath.split('/').slice(0, -1)
  for (const part of clean.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') {
      if (!stack.length) return null
      stack.pop()
    } else {
      stack.push(part)
    }
  }
  return stack.join('/')
}

function WorkspaceMarkdownImage({ projectId, markdownPath, src, alt }: {
  projectId: number; markdownPath: string; src?: string; alt?: string
}) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!src) return
    if (/^https?:/i.test(src)) {
      setUrl(src)
      return
    }
    const target = relativeWorkspacePath(markdownPath, src)
    if (!target) return
    let active = true
    let blobUrl = ''
    getWorkspacePreview(projectId, target).then(next => {
      blobUrl = next
      if (active) setUrl(next)
      else URL.revokeObjectURL(next)
    }).catch(() => setUrl(''))
    return () => {
      active = false
      if (blobUrl) URL.revokeObjectURL(blobUrl)
    }
  }, [markdownPath, projectId, src])
  if (!url) return <span className="text-xs text-amber-500">[图片无法预览：{alt || src}]</span>
  return <img src={url} alt={alt || ''} referrerPolicy="no-referrer" className="my-4 max-h-[32rem] max-w-full rounded border border-slate-700" />
}

function MarkdownPreview({ projectId, path, content }: { projectId: number; path: string; content: string }) {
  return (
    <div className="tutor-markdown h-full overflow-auto bg-slate-950 px-8 py-6 text-sm leading-7 text-slate-200">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          img: ({ src, alt }) => <WorkspaceMarkdownImage projectId={projectId} markdownPath={path} src={src} alt={alt} />,
          a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
        }}
      >{content}</ReactMarkdown>
    </div>
  )
}

function BlobPreview({ projectId, path, mimeType }: { projectId: number; path: string; mimeType?: string }) {
  const [url, setUrl] = useState('')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    let blobUrl = ''
    setFailed(false)
    getWorkspacePreview(projectId, path).then(next => {
      blobUrl = next
      if (active) setUrl(next)
      else URL.revokeObjectURL(next)
    }).catch(() => setFailed(true))
    return () => {
      active = false
      if (blobUrl) URL.revokeObjectURL(blobUrl)
    }
  }, [path, projectId])
  if (failed) return <div className="flex h-full items-center justify-center text-sm text-amber-300">预览失败，可使用“系统打开”查看。</div>
  if (!url) return <div className="flex h-full items-center justify-center"><Loader2 className="animate-spin text-slate-400" size={18} /></div>
  if (mimeType === 'application/pdf') return <iframe src={url} title={path} className="h-full w-full border-0 bg-white" />
  return <div className="flex h-full items-center justify-center overflow-auto p-6"><img src={url} alt={path} className="max-h-full max-w-full object-contain" /></div>
}

export default function WorkspaceFilePage() {
  const { projectId } = useParams()
  const [searchParams] = useSearchParams()
  const location = useLocation()
  const pid = Number(projectId)
  const path = searchParams.get('path') || ''
  const desktop = getDesktopRuntime()
  const { setTabDirty } = useWorkspace()
  const [file, setFile] = useState<WorkspaceFile | null>(null)
  const [content, setContent] = useState('')
  const [savedContent, setSavedContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [markdownMode, setMarkdownMode] = useState<'preview' | 'source' | 'split'>('preview')
  const [vimEnabled, setVimEnabled] = useState(() => localStorage.getItem('learnflow.editor.vim') === '1')
  const editorRef = useRef<any>(null)
  const vimDisposeRef = useRef<any>(null)
  const saveKeyRef = useRef<string | null>(null)
  const title = path.split('/').pop() || '项目文件'
  const tabId = useMemo(() => `${location.pathname}${location.search}`, [location.pathname, location.search])
  const dirty = Boolean(file?.kind === 'workspace_text' && content !== savedContent)
  const isMarkdown = /\.md(?:own)?$/i.test(path)

  useWorkspaceTitle(title, { kind: 'file', projectId: pid, workspacePath: path })

  const load = useCallback(async () => {
    if (!desktop.available || !pid || !path) return
    setLoading(true)
    setMessage('')
    try {
      const next = await getWorkspaceFile(pid, path)
      setFile(next)
      setContent(next.content || '')
      setSavedContent(next.content || '')
      saveKeyRef.current = null
    } catch (error) {
      setFile(null)
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [desktop.available, path, pid])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    setTabDirty(tabId, dirty)
    return () => setTabDirty(tabId, false)
  }, [dirty, setTabDirty, tabId])
  useEffect(() => {
    localStorage.setItem('learnflow.editor.vim', vimEnabled ? '1' : '0')
    vimDisposeRef.current?.dispose?.()
    vimDisposeRef.current = null
    if (!vimEnabled || !editorRef.current) return
    let canceled = false
    import('monaco-vim').then(({ initVimMode }) => {
      if (!canceled && editorRef.current) vimDisposeRef.current = initVimMode(editorRef.current, document.getElementById('workspace-vim-status'))
    })
    return () => {
      canceled = true
      vimDisposeRef.current?.dispose?.()
      vimDisposeRef.current = null
    }
  }, [vimEnabled, markdownMode, path])
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (!dirty) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])

  const save = useCallback(async () => {
    if (!file || file.kind !== 'workspace_text' || !dirty || saving) return
    setSaving(true)
    setMessage('')
    if (!saveKeyRef.current) saveKeyRef.current = crypto.randomUUID()
    try {
      const operation = await saveWorkspaceFile(pid, path, {
        content, base_hash: file.sha256, idempotency_key: saveKeyRef.current,
      })
      setFile(previous => previous ? {
        ...previous, sha256: operation.result.sha256,
        size: new TextEncoder().encode(content).length, modified_at: new Date().toISOString(),
      } : previous)
      setSavedContent(content)
      saveKeyRef.current = null
      setMessage('已保存')
      window.dispatchEvent(new CustomEvent('learnflow:workspace-changed', { detail: { projectId: pid } }))
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }, [content, dirty, file, path, pid, saving])

  useEffect(() => {
    const keyboardSave = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void save()
      }
    }
    window.addEventListener('keydown', keyboardSave)
    return () => window.removeEventListener('keydown', keyboardSave)
  }, [save])

  const editor = (height = '100%') => (
    <Editor
      height={height}
      language={editorLanguage(path)}
      value={content}
      onMount={instance => { editorRef.current = instance }}
      onChange={value => {
        setContent(value || '')
        saveKeyRef.current = null
        if (message === '已保存') setMessage('')
      }}
      theme="vs-dark"
      path={`learnflow-workspace://${pid}/${path}`}
      options={{
        automaticLayout: true, minimap: { enabled: true }, fontSize: 13,
        tabSize: 4, insertSpaces: true, wordWrap: isMarkdown ? 'on' : 'off',
        scrollBeyondLastLine: false, renderWhitespace: 'selection',
      }}
    />
  )

  if (!desktop.available) return <div className="flex h-full items-center justify-center bg-slate-950 p-8 text-center text-sm text-slate-300">真实本地文件仅在 LearnFlow 桌面版中启用。</div>

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-950 text-slate-100">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-slate-700 bg-slate-900 px-3">
        <FileCode2 size={15} className="text-emerald-400" />
        <div className="min-w-0 flex-1 truncate text-xs text-slate-300"><span className="text-slate-500">项目文件 / </span>{path}</div>
        {message && <span className={`max-w-64 truncate text-[10px] ${message === '已保存' ? 'text-emerald-400' : 'text-amber-300'}`}>{message}</span>}
        {isMarkdown && file?.kind === 'workspace_text' && (
          <div className="flex rounded border border-slate-700 p-0.5">
            {([
              ['preview', Eye, '预览'], ['source', SquareCode, '源码'], ['split', Columns2, '分屏'],
            ] as const).map(([mode, Icon, label]) => (
              <button key={mode} type="button" onClick={() => setMarkdownMode(mode)} title={label} className={`flex h-6 items-center gap-1 rounded px-2 text-[10px] ${markdownMode === mode ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`}><Icon size={11} />{label}</button>
            ))}
          </div>
        )}
        {file?.kind === 'workspace_text' && (
          <button type="button" onClick={() => setVimEnabled(value => !value)} title="Vim 键位模式" className="flex h-7 items-center gap-1 rounded px-2 text-[10px] text-slate-300 hover:bg-slate-700">
            {vimEnabled ? <ToggleRight size={15} className="text-emerald-400" /> : <ToggleLeft size={15} />} Vim
          </button>
        )}
        <button type="button" onClick={() => void load()} title="从磁盘重新载入" className="flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:bg-slate-700 hover:text-white"><RefreshCw size={13} /></button>
        <button type="button" onClick={() => void revealWorkspaceItem(pid, path)} title="在 Finder / Explorer 中显示" className="flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:bg-slate-700 hover:text-white"><ExternalLink size={13} /></button>
        {file && file.kind !== 'workspace_text' && <button type="button" onClick={() => void openWorkspaceItem(pid, path)} className="h-7 rounded border border-slate-600 px-2 text-[10px] text-slate-300 hover:bg-slate-700">系统打开</button>}
        <button type="button" disabled={!dirty || saving || file?.kind !== 'workspace_text'} onClick={() => void save()} className="flex h-7 items-center gap-1.5 rounded bg-emerald-700 px-2.5 text-[11px] font-semibold text-white enabled:hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-40">
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} 保存
        </button>
      </header>

      <div className="min-h-0 flex-1">
        {loading && <div className="flex h-full items-center justify-center text-xs text-slate-400"><Loader2 size={16} className="mr-2 animate-spin" /> 正在读取本地文件…</div>}
        {!loading && !file && <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center text-sm text-slate-400"><AlertTriangle size={28} className="text-amber-400" /><p>{message || '文件不存在或已移动'}</p><button type="button" onClick={() => void load()} className="rounded bg-slate-800 px-3 py-2 text-xs text-white">重试</button></div>}
        {!loading && file?.kind === 'workspace_text' && !isMarkdown && editor()}
        {!loading && file?.kind === 'workspace_text' && isMarkdown && markdownMode === 'source' && editor()}
        {!loading && file?.kind === 'workspace_text' && isMarkdown && markdownMode === 'preview' && <MarkdownPreview projectId={pid} path={path} content={content} />}
        {!loading && file?.kind === 'workspace_text' && isMarkdown && markdownMode === 'split' && <div className="grid h-full grid-cols-2 divide-x divide-slate-700"><div className="min-w-0">{editor()}</div><MarkdownPreview projectId={pid} path={path} content={content} /></div>}
        {!loading && file?.kind !== 'workspace_text' && file?.previewable && <BlobPreview projectId={pid} path={path} mimeType={file.mime_type} />}
        {!loading && file?.kind !== 'workspace_text' && file && !file.previewable && (
          <div className="flex h-full items-center justify-center p-8"><div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-900 p-6 text-center"><Binary size={38} className="mx-auto mb-4 text-sky-400" /><h2 className="text-base font-semibold">大型或二进制文件</h2><p className="mt-2 text-xs leading-5 text-slate-400">为保护编辑器，该文件只显示元数据，不载入正文。</p><dl className="mt-5 grid grid-cols-[90px_1fr] gap-2 text-left text-xs"><dt className="text-slate-500">路径</dt><dd className="break-all text-slate-300">{file.path}</dd><dt className="text-slate-500">类型</dt><dd>{file.mime_type || '未知'}</dd><dt className="text-slate-500">大小</dt><dd>{formatBytes(file.size)}</dd><dt className="text-slate-500">SHA-256</dt><dd className="break-all font-mono text-[10px] text-slate-400">{file.sha256}</dd></dl></div></div>
        )}
      </div>

      <footer className="flex h-6 shrink-0 items-center gap-4 border-t border-slate-800 bg-emerald-800 px-3 text-[10px] text-emerald-50"><span>可信本地工作区</span><span>{file ? formatBytes(file.size) : '—'}</span>{vimEnabled && <span id="workspace-vim-status" className="font-mono" />}<span className="ml-auto">{dirty ? '● 未保存' : '已与磁盘同步'}</span><span>{navigator.platform}</span></footer>
    </div>
  )
}
