import { useState, useRef, useEffect } from 'react'
import {
  askQuestion, listNotes, createNote, updateNote, deleteNote,
} from '../../services/api'
import { shouldSendMessageOnEnter } from '../../utils/keyboard'

interface Message {
  role: 'user' | 'assistant'
  content: string
  kind?: 'chat' | 'trace'
  trace?: any
}

interface Note {
  id: number
  section_index: number
  selection: string
  note: string
  created_at?: string
  updated_at?: string
}

interface Props {
  checkpointId: number
  selectedText: string
  sectionIndex: number
  onClose: () => void
}

const QUICK_ACTIONS = [
  { key: 'explain', label: '📖 解释' },
  { key: 'example', label: '💡 举例' },
  { key: 'summary', label: '📋 总结' },
  { key: 'translate', label: '🌐 翻译' },
  { key: 'quiz', label: '❓ 出题' },
  { key: 'trace', label: '🔍 溯源' },
]

export default function BottomWorkspace({ checkpointId, selectedText, sectionIndex, onClose }: Props) {
  const [tab, setTab] = useState<'ask' | 'notes'>('ask')
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  // Notes state
  const [notes, setNotes] = useState<Note[]>([])
  const [noteText, setNoteText] = useState('')
  const [noteLoading, setNoteLoading] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, notes])

  useEffect(() => {
    loadNotes()
  }, [checkpointId])

  // Auto-ask when text is newly selected
  useEffect(() => {
    if (selectedText && messages.length === 0) {
      setMessages([{ role: 'user', content: `关于「${selectedText.slice(0, 80)}...」的提问` }])
    }
  }, [selectedText])

  const loadNotes = async () => {
    try {
      const data = await listNotes(checkpointId)
      setNotes(data || [])
    } catch { setNotes([]) }
  }

  const send = async (question?: string, action?: string) => {
    const text = question ?? input
    if ((!text.trim() && !action) || loading) return
    if (!action) setInput('')

    const userMsg: Message = action
      ? { role: 'user', content: `[${QUICK_ACTIONS.find(a => a.key === action)?.label}] 「${selectedText.slice(0, 60)}...」` }
      : { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await askQuestion(checkpointId, {
        selection: selectedText,
        question: text,
        history: messages.map(m => ({ role: m.role, content: m.content })),
        action,
      })
      if (res.kind === 'trace') {
        setMessages(prev => [...prev, { role: 'assistant', content: '', kind: 'trace', trace: res.trace }])
      } else {
        setMessages(prev => [...prev, { role: 'assistant', content: res.answer }])
      }
    } catch (e: any) {
      const errMsg = e?.response?.data?.detail || '请求失败'
      setMessages(prev => [...prev, { role: 'assistant', content: `❌ ${errMsg}` }])
    }
    setLoading(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (shouldSendMessageOnEnter(e)) {
      e.preventDefault()
      send()
    }
  }

  // ── Notes ──
  const saveNote = async () => {
    if (!noteText.trim()) return
    setNoteLoading(true)
    try {
      if (editingId != null) {
        await updateNote(editingId, noteText)
      } else {
        await createNote(checkpointId, {
          section_index: sectionIndex,
          selection: selectedText.slice(0, 200),
          note: noteText,
        })
      }
      setNoteText('')
      setEditingId(null)
      await loadNotes()
    } catch (e: any) {
      alert('保存失败: ' + (e?.response?.data?.detail || e.message))
    }
    setNoteLoading(false)
  }

  const startEdit = (n: Note) => {
    setEditingId(n.id)
    setNoteText(n.note)
  }

  const removeNote = async (id: number) => {
    if (!window.confirm('删除这条笔记？')) return
    try {
      await deleteNote(id)
      await loadNotes()
      if (editingId === id) { setEditingId(null); setNoteText('') }
    } catch {}
  }

  const exportMarkdown = () => {
    const lines = [`# 笔记导出（checkpoint ${checkpointId}）`, '']
    for (const n of notes) {
      lines.push(`## 第 ${n.section_index + 1} 节`)
      if (n.selection) lines.push(`> 选中：「${n.selection}」`)
      lines.push('')
      lines.push(n.note)
      lines.push('', '---', '')
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `notes-checkpoint-${checkpointId}.md`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const sectionTitle = (idx: number) => `第 ${idx + 1} 节`

  return (
    <div className="border-t border-gray-200 bg-white flex flex-col"
         style={{ height: '340px' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-2 text-sm">
          {/* Tabs */}
          <div className="flex bg-gray-100 rounded-lg p-0.5">
            <button
              onClick={() => setTab('ask')}
              className={`px-3 py-1 rounded-md text-xs transition-colors ${
                tab === 'ask' ? 'bg-white shadow text-primary-700 font-medium' : 'text-gray-500'
              }`}
            >
              💬 追问
            </button>
            <button
              onClick={() => setTab('notes')}
              className={`px-3 py-1 rounded-md text-xs transition-colors ${
                tab === 'notes' ? 'bg-white shadow text-primary-700 font-medium' : 'text-gray-500'
              }`}
            >
              📝 笔记
              {notes.length > 0 && (
                <span className="ml-1 text-[10px] bg-primary-100 text-primary-700 rounded-full px-1.5">
                  {notes.length}
                </span>
              )}
            </button>
          </div>
          {selectedText && (
            <span className="text-xs text-gray-400 truncate max-w-[240px]">
              「{selectedText.slice(0, 40)}...」
              {tab === 'notes' && <span className="text-primary-400 ml-1">({sectionTitle(sectionIndex)})</span>}
            </span>
          )}
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-sm px-1">
          ✕
        </button>
      </div>

      {tab === 'ask' && (
        <>
          {/* Quick actions */}
          {selectedText && (
            <div className="px-4 pt-2 shrink-0 flex flex-wrap gap-1.5">
              {QUICK_ACTIONS.map(a => (
                <button
                  key={a.key}
                  onClick={() => send(undefined, a.key)}
                  disabled={loading}
                  className="bg-gray-50 border border-gray-200 text-gray-600 px-2.5 py-1 rounded-lg text-xs
                             hover:bg-primary-50 hover:text-primary-700 hover:border-primary-200
                             disabled:opacity-50 transition-colors"
                >
                  {a.label}
                </button>
              ))}
            </div>
          )}

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-2 space-y-2">
            {messages.length === 0 && (
              <div className="text-center text-gray-400 text-xs py-6">
                选中讲义中的文字，然后提问或点击上方快捷动作
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {m.kind === 'trace' ? (
                  /* Trace result card */
                  <div className="max-w-[92%] rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-xs text-gray-700">
                    <p className="font-semibold text-primary-700 mb-1">🔍 溯源结果</p>
                    {m.trace?.found ? (
                      <>
                        <p className="mb-1"><span className="text-gray-400">来源文件：</span>
                          <code className="bg-white px-1 rounded text-[11px]">{m.trace.file}</code>
                        </p>
                        {m.trace.heading_chain?.length > 0 && (
                          <p className="mb-1 text-gray-500">标题链：{m.trace.heading_chain.join(' → ')}</p>
                        )}
                        <p className="mb-1"><span className="text-gray-400">切片：</span>chunk-{m.trace.chunk_id}</p>
                        <blockquote className="border-l-2 border-primary-300 pl-2 py-1 bg-white/60 rounded text-gray-500">
                          {m.trace.preview}
                        </blockquote>
                      </>
                    ) : (
                      <p className="text-gray-500">{m.trace?.reason || '未找到'}</p>
                    )}
                  </div>
                ) : (
                  <div className={`
                    max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap
                    ${m.role === 'user'
                      ? 'bg-primary-600 text-white'
                      : 'bg-gray-100 text-gray-800'
                    }
                  `}>
                    {m.content}
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-gray-100 rounded-lg px-3 py-2 text-sm text-gray-400">
                  <span className="animate-pulse">思考中...</span>
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>

          {/* Input */}
          <div className="border-t border-gray-100 px-4 py-2 shrink-0">
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入追问... (Enter 发送)"
                className="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm
                           focus:outline-none focus:ring-2 focus:ring-primary-400"
              />
              <button
                onClick={() => send()}
                disabled={loading || !input.trim()}
                className="bg-primary-600 text-white px-3 py-1.5 rounded-lg text-sm
                           hover:bg-primary-700 disabled:bg-gray-300 transition-colors"
              >
                发送
              </button>
            </div>
          </div>
        </>
      )}

      {tab === 'notes' && (
        <div className="flex-1 flex overflow-hidden">
          {/* Note list */}
          <div className="flex-1 overflow-y-auto px-4 py-2 space-y-2">
            {notes.length === 0 && (
              <div className="text-center text-gray-400 text-xs py-6">
                还没有笔记。选中文字 → 在下方写下想法 → 保存
              </div>
            )}
            {notes.map((n) => (
              <div key={n.id} className="border border-gray-100 rounded-lg p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-gray-400 bg-gray-50 px-1.5 py-0.5 rounded">
                    {sectionTitle(n.section_index)}
                  </span>
                  <div className="flex gap-1">
                    <button onClick={() => startEdit(n)}
                            className="text-[10px] text-gray-400 hover:text-primary-600 px-1">编辑</button>
                    <button onClick={() => removeNote(n.id)}
                            className="text-[10px] text-gray-400 hover:text-red-500 px-1">删除</button>
                  </div>
                </div>
                {n.selection && (
                  <p className="text-[11px] text-gray-400 mb-1 italic">「{n.selection.slice(0, 80)}」</p>
                )}
                <p className="text-xs text-gray-700 whitespace-pre-wrap">{n.note}</p>
              </div>
            ))}
            <div ref={endRef} />
          </div>

          {/* Editor */}
          <div className="w-72 border-l border-gray-100 flex flex-col shrink-0">
            <div className="px-3 py-2 text-xs font-medium text-gray-500 flex items-center justify-between">
              <span>{editingId != null ? '✏️ 编辑笔记' : '➕ 新建笔记'}</span>
              <button onClick={exportMarkdown}
                      className="text-[10px] text-primary-600 hover:text-primary-700">
                ⬇ 导出 Markdown
              </button>
            </div>
            {selectedText && (
              <p className="px-3 pb-1 text-[10px] text-gray-400 truncate">
                锚定：{sectionTitle(sectionIndex)} 「{selectedText.slice(0, 40)}...」
              </p>
            )}
            <textarea
              value={noteText}
              onChange={e => setNoteText(e.target.value)}
              placeholder="写下你的想法..."
              className="flex-1 mx-3 mb-2 border border-gray-200 rounded-lg p-2 text-xs
                         focus:outline-none focus:ring-2 focus:ring-primary-300 resize-none"
            />
            <div className="px-3 pb-3 flex gap-2">
              <button
                onClick={saveNote}
                disabled={noteLoading || !noteText.trim()}
                className="flex-1 bg-primary-600 text-white px-3 py-1.5 rounded-lg text-xs
                           hover:bg-primary-700 disabled:bg-gray-300 transition-colors"
              >
                {editingId != null ? '保存修改' : '保存笔记'}
              </button>
              {editingId != null && (
                <button
                  onClick={() => { setEditingId(null); setNoteText('') }}
                  className="bg-gray-100 text-gray-600 px-3 py-1.5 rounded-lg text-xs hover:bg-gray-200"
                >
                  取消
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
