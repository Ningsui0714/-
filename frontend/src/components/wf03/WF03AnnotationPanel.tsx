import { AlertCircle, CheckCircle2, MessageSquarePlus, Send, Trash2, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { WF03FeedbackCode } from '../../services/api'
import type { WF03Annotation, WF03Selection } from './types'

const feedbackOptions: Array<{ value: WF03FeedbackCode; label: string }> = [
  { value: 'step_mapping_mismatch', label: '步骤映射不准确' },
  { value: 'incorrect_knowledge_scope', label: '知识范围不准确' },
  { value: 'incorrect_skill_scope', label: '技能范围不准确' },
  { value: 'missing_prerequisite', label: '缺少前置条件' },
  { value: 'unsupported_task_fact', label: '任务事实缺少依据' },
  { value: 'weak_relation', label: '知识技能关系较弱' },
  { value: 'other', label: '其他建议' },
]

function defaultCode(selection: WF03Selection): WF03FeedbackCode {
  if (selection.targetType === 'step') return 'step_mapping_mismatch'
  if (selection.targetType === 'knowledge') return 'incorrect_knowledge_scope'
  if (selection.targetType === 'skill') return 'incorrect_skill_scope'
  return 'other'
}

export default function WF03AnnotationPanel({
  selection,
  annotations,
  submitting,
  submittedCount,
  onCancelSelection,
  onAdd,
  onRemove,
  onSubmit,
  onClose,
}: {
  selection: WF03Selection | null
  annotations: WF03Annotation[]
  submitting: boolean
  submittedCount: number
  onCancelSelection: () => void
  onAdd: (annotation: WF03Annotation) => void
  onRemove: (id: string) => void
  onSubmit: () => void
  onClose?: () => void
}) {
  const [message, setMessage] = useState('')
  const [suggestion, setSuggestion] = useState('')
  const [feedbackCode, setFeedbackCode] = useState<WF03FeedbackCode>('other')

  useEffect(() => {
    if (!selection) return
    setMessage('')
    setSuggestion('')
    setFeedbackCode(defaultCode(selection))
  }, [selection])

  const canAdd = Boolean(selection && message.trim().length >= 4)
  const pendingLabel = useMemo(
    () => annotations.length ? `${annotations.length} 条待提交` : '尚无待提交批注',
    [annotations.length],
  )

  const add = () => {
    if (!selection || !canAdd) return
    onAdd({
      id: globalThis.crypto?.randomUUID?.() || `wf03-note-${Date.now()}`,
      selectedText: selection.text,
      targetType: selection.targetType,
      targetId: selection.targetId,
      feedbackCode,
      severity: feedbackCode === 'unsupported_task_fact' ? 'error' : 'warning',
      message: message.trim(),
      suggestedCorrection: suggestion.trim(),
      createdAt: new Date().toISOString(),
    })
    onCancelSelection()
  }

  return (
    <aside className="flex h-full min-h-0 w-full shrink-0 flex-col border-l border-slate-200 bg-white" aria-label="任务批注与复核">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-slate-200 px-4">
        <MessageSquarePlus size={15} className="text-emerald-700" />
        <div className="min-w-0 flex-1">
          <h2 className="text-xs font-semibold text-slate-900">批注与复核</h2>
          <p className="text-[10px] text-slate-400">{pendingLabel}</p>
        </div>
        {submittedCount > 0 && (
          <span className="flex items-center gap-1 text-[10px] text-emerald-700">
            <CheckCircle2 size={12} /> 已提交 {submittedCount}
          </span>
        )}
        {onClose && (
          <button type="button" onClick={onClose} title="收起批注面板" className="text-slate-400 hover:text-slate-700">
            <X size={14} />
          </button>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {selection && (
          <section className="mb-3 rounded-xl border border-emerald-200 bg-emerald-50/60 p-3 shadow-sm">
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-emerald-800">当前选区</p>
                <blockquote className="mt-1.5 line-clamp-4 border-l-2 border-emerald-500 pl-2 text-xs leading-5 text-slate-700">
                  {selection.text}
                </blockquote>
              </div>
              <button type="button" onClick={onCancelSelection} title="取消批注" className="text-slate-400 hover:text-slate-700">
                <X size={14} />
              </button>
            </div>
            <label className="mt-3 block text-[10px] font-medium text-slate-500">
              问题类型
              <select
                value={feedbackCode}
                onChange={event => setFeedbackCode(event.target.value as WF03FeedbackCode)}
                className="mt-1 h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-700 outline-none focus:border-emerald-500"
              >
                {feedbackOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="mt-2 block text-[10px] font-medium text-slate-500">
              批注内容
              <textarea
                autoFocus
                value={message}
                onChange={event => setMessage(event.target.value)}
                rows={3}
                placeholder="说明这里为什么需要调整（至少 4 个字）"
                className="mt-1 w-full resize-none rounded-md border border-slate-200 bg-white px-2.5 py-2 text-xs leading-5 text-slate-800 outline-none focus:border-emerald-500"
              />
            </label>
            <label className="mt-2 block text-[10px] font-medium text-slate-500">
              建议修改（可选）
              <textarea
                value={suggestion}
                onChange={event => setSuggestion(event.target.value)}
                rows={2}
                placeholder="写下建议的替换或补充内容"
                className="mt-1 w-full resize-none rounded-md border border-slate-200 bg-white px-2.5 py-2 text-xs leading-5 text-slate-800 outline-none focus:border-emerald-500"
              />
            </label>
            <button
              type="button"
              onClick={add}
              disabled={!canAdd}
              className="mt-2 flex h-9 w-full items-center justify-center gap-1.5 rounded-md bg-emerald-700 text-xs font-semibold text-white hover:bg-emerald-800 disabled:bg-slate-300"
            >
              <MessageSquarePlus size={14} /> 保存为待提交批注
            </button>
          </section>
        )}

        {!selection && annotations.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center">
            <MessageSquarePlus size={22} className="mx-auto text-slate-300" />
            <p className="mt-2 text-xs font-medium text-slate-600">拖选中间网页里的文字</p>
            <p className="mt-1 text-[10px] leading-4 text-slate-400">松开左键后点击“添加批注”，意见只进入复核，不会直接改写任务事实。</p>
          </div>
        )}

        <div className="space-y-2">
          {annotations.map((annotation, index) => (
            <article key={annotation.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-start gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-amber-100 text-[10px] font-bold text-amber-800">{index + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="line-clamp-2 text-[10px] leading-4 text-slate-500">“{annotation.selectedText}”</p>
                  <p className="mt-1.5 text-xs leading-5 text-slate-800">{annotation.message}</p>
                  {annotation.suggestedCorrection && <p className="mt-1 text-[10px] leading-4 text-emerald-700">建议：{annotation.suggestedCorrection}</p>}
                </div>
                <button type="button" onClick={() => onRemove(annotation.id)} title="删除批注" className="text-slate-300 hover:text-red-600">
                  <Trash2 size={13} />
                </button>
              </div>
            </article>
          ))}
        </div>
      </div>

      <footer className="shrink-0 border-t border-slate-200 p-3">
        <div className="mb-2 flex items-start gap-1.5 text-[10px] leading-4 text-slate-400">
          <AlertCircle size={12} className="mt-0.5 shrink-0" />
          提交后形成可追溯复核请求，不会静默修改企业任务。
        </div>
        <button
          type="button"
          onClick={onSubmit}
          disabled={!annotations.length || submitting}
          className="flex h-9 w-full items-center justify-center gap-1.5 rounded-md bg-emerald-700 text-xs font-semibold text-white hover:bg-emerald-800 disabled:bg-slate-300"
        >
          <Send size={13} /> {submitting ? '正在提交复核…' : `提交 ${annotations.length || ''} 条复核意见`}
        </button>
      </footer>
    </aside>
  )
}
