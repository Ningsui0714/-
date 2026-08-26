import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import ProcessAnimationViewer from '../animation/ProcessAnimationViewer'
import { getAnimation, ProcessAnimation } from '../../services/api'

/** Repair block delimiters before remark-math sees them.
 *
 * Generated Markdown occasionally opens a display formula with `$$` and
 * closes it with a bare code fence. Without this guard remark-math consumes
 * the rest of the section as one invalid formula, including later code blocks.
 */
export function repairMarkdownFences(md: string): string {
  const lines = md.split('\n')
  const output: string[] = []
  let mathOpen = false
  let codeMarker = ''
  let codeMarkerLength = 0

  for (const line of lines) {
    const trimmed = line.trim()
    if (codeMarker) {
      output.push(line)
      const closing = new RegExp(`^${codeMarker === '`' ? '`' : '~'}{${codeMarkerLength},}\\s*$`)
      if (closing.test(trimmed)) {
        codeMarker = ''
        codeMarkerLength = 0
      }
      continue
    }

    if (trimmed === '$$') {
      output.push(line)
      mathOpen = !mathOpen
      continue
    }

    const fence = trimmed.match(/^(`{3,}|~{3,})(.*)$/)
    if (fence) {
      if (mathOpen) {
        if (fence[2].trim()) {
          output.push('$$')
          output.push(line)
          codeMarker = fence[1][0]
          codeMarkerLength = fence[1].length
        } else {
          output.push(line.replace(trimmed, () => '$$'))
        }
        mathOpen = false
        continue
      }
      output.push(line)
      codeMarker = fence[1][0]
      codeMarkerLength = fence[1].length
      continue
    }

    output.push(line)
  }

  if (mathOpen) output.push('$$')
  return output.join('\n')
}

function normalizeMarkdown(md: string): string {
  return repairMarkdownFences(md).replace(
    /^\$\$[ \t]*(\\begin\{([^}]+)\})\n([\s\S]*?)\\end\{\2\}[ \t]*\$\$$/gm,
    (_m, openEnv: string, environment: string, body: string) =>
      `$$\n${openEnv}\n${body}\\end{${environment}}\n$$`
  )
}

/**
 * 拆分讲义小节内容：markdown 文本与 process-animator 占位符
 * `:::process-anim {id}` → {type:'anim', id}
 */
const ANIM_MARKER_RE = /^:::\s*process-anim\s+(\d+)\s*$/gm

function splitContent(content: string): Array<{ type: 'md'; text: string } | { type: 'anim'; id: number }> {
  const parts: Array<{ type: 'md'; text: string } | { type: 'anim'; id: number }> = []
  ANIM_MARKER_RE.lastIndex = 0
  let last = 0
  let m: RegExpExecArray | null
  while ((m = ANIM_MARKER_RE.exec(content))) {
    if (m.index > last) parts.push({ type: 'md', text: content.slice(last, m.index) })
    parts.push({ type: 'anim', id: Number(m[1]) })
    last = m.index + m[0].length
  }
  if (last < content.length) parts.push({ type: 'md', text: content.slice(last) })
  return parts
}

interface Section {
  title: string
  content: string
  keywords?: string[]
  questions?: string[]
}

export interface LectureNote {
  id: number
  section_index: number
  selection: string
  note: string
  status?: 'anchored' | 'orphaned'
  created_at?: string
  updated_at?: string
}

interface SelectionToolbarState {
  text: string
  sectionIndex: number
  left: number
  top: number
  mode: 'actions' | 'note'
}

interface Props {
  sections: Section[]
  animations?: Record<number, ProcessAnimation>
  onSelect?: (text: string, sectionIndex: number) => void
  onAskSelection?: (text: string, sectionIndex: number) => void
  notes?: LectureNote[]
  onCreateNote?: (selection: string, sectionIndex: number, note: string) => void | Promise<void>
  onUpdateNote?: (noteId: number, note: string) => void | Promise<void>
  onDeleteNote?: (noteId: number) => void | Promise<void>
  onDeleteImage?: (sectionIndex: number, src: string) => void
}

function anchoredNotesPlugin(notes: LectureNote[]) {
  const grouped = new Map<string, number[]>()
  notes.forEach(note => {
    const selection = note.selection.trim()
    if (!selection) return
    grouped.set(selection, [...(grouped.get(selection) || []), note.id])
  })
  const candidates = [...grouped.entries()]
    .map(([selection, ids]) => ({ selection, ids }))
    .sort((a, b) => b.selection.length - a.selection.length)

  return () => (tree: any) => {
    const used = new Set<number>()
    const blockedTags = new Set(['code', 'pre', 'script', 'style', 'svg', 'math'])

    const visit = (node: any, blocked = false) => {
      if (!node?.children || !Array.isArray(node.children)) return
      const nextBlocked = blocked || blockedTags.has(node.tagName)
      const nextChildren: any[] = []

      node.children.forEach((child: any) => {
        if (child.type !== 'text' || nextBlocked) {
          visit(child, nextBlocked)
          nextChildren.push(child)
          return
        }

        let remaining = String(child.value || '')
        while (remaining) {
          let match: { index: number; selection: string; ids: number[] } | null = null
          candidates.forEach(candidate => {
            if (candidate.ids.every(id => used.has(id))) return
            const index = remaining.indexOf(candidate.selection)
            if (index < 0) return
            if (!match || index < match.index || (index === match.index && candidate.selection.length > match.selection.length)) {
              match = { index, selection: candidate.selection, ids: candidate.ids }
            }
          })

          if (!match) {
            nextChildren.push({ type: 'text', value: remaining })
            break
          }
          const found = match as { index: number; selection: string; ids: number[] }
          if (found.index > 0) nextChildren.push({ type: 'text', value: remaining.slice(0, found.index) })
          nextChildren.push({
            type: 'element',
            tagName: 'mark',
            properties: { dataNoteIds: found.ids.join(',') },
            children: [{ type: 'text', value: found.selection }],
          })
          found.ids.forEach(id => used.add(id))
          remaining = remaining.slice(found.index + found.selection.length)
        }
      })

      node.children = nextChildren
    }

    visit(tree)
  }
}

export default function LectureRenderer({
  sections, animations, onSelect, onAskSelection, notes = [],
  onCreateNote, onUpdateNote, onDeleteNote, onDeleteImage,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const toolbarRef = useRef<HTMLDivElement>(null)
  // 懒加载：讲义里出现但 props 里没有的动画（快照流/续生成场景）按 id 拉取
  const [lazy, setLazy] = useState<Record<number, ProcessAnimation>>({})
  const [selectionToolbar, setSelectionToolbar] = useState<SelectionToolbarState | null>(null)
  const [noteDraft, setNoteDraft] = useState('')
  const [savingNote, setSavingNote] = useState(false)
  const [expandedNoteIds, setExpandedNoteIds] = useState<Set<number>>(() => new Set())
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState('')

  useEffect(() => {
    const need: number[] = []
    for (const s of sections || []) {
      ANIM_MARKER_RE.lastIndex = 0
      let m: RegExpExecArray | null
      while ((m = ANIM_MARKER_RE.exec(s.content || ''))) {
        const id = Number(m[1])
        if (!animations?.[id] && !lazy[id] && !need.includes(id)) need.push(id)
      }
    }
    if (!need.length) return
    let alive = true
    need.forEach(id => {
      getAnimation(id)
        .then((a: ProcessAnimation) => { if (alive) setLazy(prev => ({ ...prev, [id]: a })) })
        .catch(() => {})
    })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sections, animations])

  const notesById = useMemo(() => new Map(notes.map(note => [note.id, note])), [notes])

  // Handle text selection and show the contextual action menu below the range.
  useEffect(() => {
    const handleMouseUp = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('[data-lecture-note-ui], [data-selection-toolbar]')) return
      const sel = window.getSelection()
      const text = sel?.toString().trim()
      const range = sel && sel.rangeCount > 0 ? sel.getRangeAt(0) : null
      if (text && range && containerRef.current?.contains(range.commonAncestorContainer)) {
        // Find the section container via the selection anchor
        let node = sel?.anchorNode as HTMLElement | null
        let sectionIndex = 0
        while (node && node !== document.body) {
          const attr = node.getAttribute?.('data-section-index')
          if (attr !== undefined && attr !== null) {
            sectionIndex = Number(attr)
            break
          }
          node = node.parentElement
        }
        const rect = range.getBoundingClientRect()
        const left = Math.max(112, Math.min(window.innerWidth - 112, rect.left + rect.width / 2))
        const top = Math.max(8, Math.min(window.innerHeight - 170, rect.bottom + 8))
        onSelect?.(text, sectionIndex)
        setNoteDraft('')
        setSelectionToolbar({ text, sectionIndex, left, top, mode: 'actions' })
      }
    }
    const handlePointerDown = (event: MouseEvent) => {
      if (toolbarRef.current?.contains(event.target as Node)) return
      setSelectionToolbar(null)
    }
    const handleScroll = () => setSelectionToolbar(null)
    document.addEventListener('mouseup', handleMouseUp)
    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('scroll', handleScroll, true)
    return () => {
      document.removeEventListener('mouseup', handleMouseUp)
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('scroll', handleScroll, true)
    }
  }, [onSelect])

  const clearBrowserSelection = () => window.getSelection()?.removeAllRanges()

  const askSelection = () => {
    if (!selectionToolbar) return
    onAskSelection?.(selectionToolbar.text, selectionToolbar.sectionIndex)
    clearBrowserSelection()
    setSelectionToolbar(null)
  }

  const saveNewNote = async () => {
    if (!selectionToolbar || !noteDraft.trim() || !onCreateNote || savingNote) return
    setSavingNote(true)
    try {
      await onCreateNote(selectionToolbar.text, selectionToolbar.sectionIndex, noteDraft.trim())
      clearBrowserSelection()
      setSelectionToolbar(null)
      setNoteDraft('')
    } finally {
      setSavingNote(false)
    }
  }

  const toggleNote = (ids: number[]) => {
    setExpandedNoteIds(current => {
      const next = new Set(current)
      const shouldExpand = ids.some(id => !next.has(id))
      ids.forEach(id => shouldExpand ? next.add(id) : next.delete(id))
      return next
    })
    setEditingNoteId(null)
  }

  const startEditing = (note: LectureNote) => {
    setExpandedNoteIds(current => new Set(current).add(note.id))
    setEditingNoteId(note.id)
    setEditDraft(note.note)
  }

  const saveEdit = async (noteId: number) => {
    if (!editDraft.trim() || !onUpdateNote || savingNote) return
    setSavingNote(true)
    try {
      await onUpdateNote(noteId, editDraft.trim())
      setEditingNoteId(null)
      setEditDraft('')
    } finally {
      setSavingNote(false)
    }
  }

  const removeNote = async (noteId: number) => {
    if (!onDeleteNote || !window.confirm('删除这条笔记？')) return
    await onDeleteNote(noteId)
    setExpandedNoteIds(current => {
      const next = new Set(current)
      next.delete(noteId)
      return next
    })
    if (editingNoteId === noteId) setEditingNoteId(null)
  }

  if (!sections || sections.length === 0) {
    return (
      <div className="text-center text-gray-400 py-16">
        <p className="text-4xl mb-2">📖</p>
        <p>暂无讲义内容</p>
      </div>
    )
  }

  // markdown 渲染配置（每个小节闭包 i，用于图片删除/选中定位）
  const renderMarkdown = (content: string, i: number) => {
    const sectionNotes = notes.filter(note => note.section_index === i && note.selection.trim())
    const notePlugin = anchoredNotesPlugin(sectionNotes)
    return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex, notePlugin]}
      components={{
        mark({ node, children }: any) {
          const rawIds = node?.properties?.dataNoteIds ?? node?.properties?.['data-note-ids'] ?? ''
          const ids = String(rawIds).split(',').map(Number).filter(Boolean)
          const anchored = ids.map(id => notesById.get(id)).filter(Boolean) as LectureNote[]
          const expanded = anchored.some(note => expandedNoteIds.has(note.id))
          return (
            <span data-lecture-note-ui className="not-prose inline">
              <button
                type="button"
                onClick={() => toggleNote(ids)}
                title={expanded ? '收起笔记' : '展开笔记'}
                className="rounded-sm bg-amber-50/70 px-0.5 text-inherit decoration-amber-500 decoration-dashed underline decoration-1 underline-offset-4 hover:bg-amber-100"
              >
                {children}
              </button>
              {expanded && anchored.map(note => (
                <span key={note.id} className="my-2 block rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-slate-700 shadow-sm">
                  {editingNoteId === note.id ? (
                    <span className="block">
                      <textarea
                        autoFocus
                        aria-label="修改笔记"
                        rows={3}
                        value={editDraft}
                        onChange={event => setEditDraft(event.target.value)}
                        className="block w-full resize-y rounded-md border border-amber-300 bg-white px-2.5 py-2 text-sm outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-100"
                      />
                      <span className="mt-2 flex justify-end gap-2">
                        <button type="button" onClick={() => setEditingNoteId(null)} className="rounded px-2.5 py-1 text-xs text-slate-500 hover:bg-white">取消</button>
                        <button type="button" onClick={() => saveEdit(note.id)} disabled={savingNote || !editDraft.trim()} className="rounded bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700 disabled:bg-slate-300">保存修改</button>
                      </span>
                    </span>
                  ) : (
                    <span className="flex items-start gap-2">
                      <button type="button" onClick={() => startEditing(note)} className="min-w-0 flex-1 whitespace-pre-wrap text-left leading-6" title="点击修改笔记">
                        <span className="mr-1.5 text-amber-600">笔记</span>{note.note}
                      </button>
                      {onDeleteNote && (
                        <button type="button" onClick={() => removeNote(note.id)} className="shrink-0 rounded px-1.5 py-0.5 text-[10px] text-slate-400 hover:bg-white hover:text-red-600">删除</button>
                      )}
                    </span>
                  )}
                </span>
              ))}
            </span>
          )
        },
        pre({ children }: any) {
          return (
            <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 overflow-x-auto text-sm">
              {children}
            </pre>
          )
        },
        code({ className, children, ...props }: any) {
          const content = String(children ?? '')
          const isBlock = Boolean(className) || content.includes('\n')
          if (!isBlock) {
            return <code className="bg-gray-100 text-red-600 px-1 rounded text-sm" {...props}>{children}</code>
          }
          return <code className={className} {...props}>{children}</code>
        },
        // Images: hover to delete (T6)
        img({ src, alt }: any) {
          return (
            <span className="relative inline-block group my-2">
              <img src={src} alt={alt || ''}
                   className="max-w-full rounded-lg border border-gray-200" />
              {onDeleteImage && (
                <button
                  onClick={() => onDeleteImage(i, src)}
                  title="删除这张图片"
                  className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-red-500 text-white
                             text-xs opacity-0 group-hover:opacity-100 transition-opacity
                             shadow hover:bg-red-600"
                >
                  ✕
                </button>
              )}
            </span>
          )
        },
        // Style blockquotes (used for questions)
        blockquote({ children }: any) {
          return (
            <blockquote className="border-l-4 border-primary-300 bg-primary-50
                                    pl-4 py-2 my-4 rounded-r-lg text-sm text-gray-700">
              {children}
            </blockquote>
          )
        },
      }}
    >
      {normalizeMarkdown(content)}
    </ReactMarkdown>
    )
  }

  return (
    <div ref={containerRef} className="prose prose-sm max-w-none px-1">
      {sections.map((section, i) => {
        const parts = splitContent(section.content || '')
        return (
          <div key={i} data-section-index={i} className="mb-10">
            {/* Section header */}
            <div className="flex items-center gap-3 mb-4 pb-3 border-b border-gray-200">
              <span className="w-7 h-7 rounded-full bg-primary-100 text-primary-700
                               flex items-center justify-center text-xs font-bold shrink-0">
                {i + 1}
              </span>
              <h2 className="text-lg font-bold text-gray-900 m-0">{section.title}</h2>
            </div>

            {/* Keywords */}
            {section.keywords && section.keywords.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-3">
                {section.keywords.map((kw, j) => (
                  <span key={j} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                    {kw}
                  </span>
                ))}
              </div>
            )}

            {/* Content: markdown + process-animator 动画块 */}
            <div className="lecture-content text-gray-800 leading-relaxed">
              {parts.map((part, j) => {
                if (part.type === 'md') {
                  return <div key={j}>{renderMarkdown(part.text, i)}</div>
                }
                const anim = animations?.[part.id] ?? lazy[part.id]
                if (!anim) {
                  return (
                    <div key={j} className="my-4 rounded-lg border border-dashed border-gray-300 text-xs text-gray-400 px-3 py-2">
                      🎞️ 过程动画 #{part.id}（加载中或已失效）
                    </div>
                  )
                }
                return <ProcessAnimationViewer key={j} animation={anim} />
              })}
            </div>

            {/* Questions */}
            {section.questions && section.questions.length > 0 && (
              <div className="mt-4 pt-3 border-t border-dashed border-gray-200">
                <p className="text-xs font-semibold text-gray-500 mb-1.5 uppercase tracking-wider">
                  💡 思考题
                </p>
                <ul className="space-y-1">
                  {section.questions.map((q, j) => (
                    <li key={j} className="text-sm text-gray-600">{q}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )
      })}

      {selectionToolbar && (
        <div
          ref={toolbarRef}
          data-selection-toolbar
          className="not-prose fixed z-[70] w-56 -translate-x-1/2 rounded-xl border border-slate-200 bg-white p-2 shadow-2xl"
          style={{ left: selectionToolbar.left, top: selectionToolbar.top }}
        >
          {selectionToolbar.mode === 'actions' ? (
            <div className="grid grid-cols-2 gap-1.5">
              <button type="button" onClick={askSelection} className="rounded-lg bg-sky-50 px-3 py-2 text-xs font-medium text-sky-800 hover:bg-sky-100">追问</button>
              <button
                type="button"
                onClick={() => setSelectionToolbar(current => current ? { ...current, mode: 'note' } : current)}
                className="rounded-lg bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800 hover:bg-amber-100"
              >
                笔记
              </button>
            </div>
          ) : (
            <div>
              <p className="mb-2 truncate text-[10px] text-slate-400">锚定：{selectionToolbar.text}</p>
              <textarea
                autoFocus
                aria-label="笔记内容"
                rows={3}
                value={noteDraft}
                onChange={event => setNoteDraft(event.target.value)}
                onKeyDown={event => {
                  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) saveNewNote()
                }}
                placeholder="写下笔记…"
                className="block w-full resize-none rounded-lg border border-slate-200 px-2.5 py-2 text-xs outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
              />
              <div className="mt-2 flex justify-end gap-1.5">
                <button type="button" onClick={() => setSelectionToolbar(current => current ? { ...current, mode: 'actions' } : current)} className="rounded px-2.5 py-1 text-xs text-slate-500 hover:bg-slate-100">返回</button>
                <button type="button" onClick={saveNewNote} disabled={savingNote || !noteDraft.trim()} className="rounded bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700 disabled:bg-slate-300">{savingNote ? '保存中…' : '保存'}</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
