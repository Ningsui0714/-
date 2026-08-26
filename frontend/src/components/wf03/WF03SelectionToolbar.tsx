import { MessageSquarePlus } from 'lucide-react'
import type { WF03Selection } from './types'

export default function WF03SelectionToolbar({
  selection,
  onAnnotate,
}: {
  selection: WF03Selection
  onAnnotate: () => void
}) {
  const left = Math.min(
    window.innerWidth - 152,
    Math.max(12, selection.rect.left + selection.rect.width / 2 - 70),
  )
  const top = Math.max(12, selection.rect.top - 48)

  return (
    <div
      className="fixed z-[80] flex items-center rounded-lg border border-slate-200 bg-white p-1 text-slate-700 shadow-xl"
      style={{ left, top }}
      role="toolbar"
      aria-label="选区操作"
    >
      <button
        type="button"
        onMouseDown={event => {
          event.preventDefault()
          event.stopPropagation()
          onAnnotate()
        }}
        className="flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium hover:bg-emerald-50 hover:text-emerald-800"
      >
        <MessageSquarePlus size={14} className="text-emerald-700" />
        添加批注
      </button>
    </div>
  )
}
