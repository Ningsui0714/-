import {
  BookOpen, Braces, CalendarClock, Columns2, FileCode2, FilePenLine, FolderKanban, GitBranch, LayoutDashboard,
  Settings2, UserRound, X,
} from 'lucide-react'
import type { WorkspaceTab, WorkspaceTabKind } from './WorkspaceContext'
import { useWorkspace } from './WorkspaceContext'

const iconByKind: Record<WorkspaceTabKind, typeof LayoutDashboard> = {
  home: LayoutDashboard,
  projects: FolderKanban,
  project: FolderKanban,
  lecture: BookOpen,
  exercise: Braces,
  file: FileCode2,
  memory: GitBranch,
  review: CalendarClock,
  profile: UserRound,
  settings: Settings2,
  wf03: FilePenLine,
}

function Tab({ tab }: { tab: WorkspaceTab }) {
  const {
    activeTabId, splitTabIds, activateTab, closeTab, splitTab, setDraggingTabId,
  } = useWorkspace()
  const Icon = iconByKind[tab.kind]
  const active = activeTabId === tab.id
  const split = splitTabIds.includes(tab.id)

  return (
    <div
      role="tab"
      aria-selected={active}
      tabIndex={0}
      draggable={!tab.pinned}
      onDragStart={event => {
        setDraggingTabId(tab.id)
        event.dataTransfer.effectAllowed = 'copy'
        event.dataTransfer.setData('text/plain', tab.id)
      }}
      onDragEnd={() => setDraggingTabId(null)}
      onClick={() => activateTab(tab.id)}
      onKeyDown={event => {
        if (event.key === 'Enter' || event.key === ' ') activateTab(tab.id)
      }}
      className={`group relative flex h-10 min-w-[142px] max-w-[245px] shrink-0 items-center gap-2 border-r border-slate-700 px-3 text-xs outline-none transition-colors ${
        active ? 'bg-slate-800 text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800/80 hover:text-slate-100'
      } ${tab.pinned ? '' : 'cursor-grab active:cursor-grabbing'}`}
      title={tab.title}
    >
      {active && <span className="absolute inset-x-0 top-0 h-0.5 bg-sky-400" />}
      <Icon size={14} className={tab.kind === 'exercise' ? 'text-violet-400' : 'text-emerald-400'} />
      <span className="min-w-0 flex-1 truncate">{tab.title}</span>
      {tab.dirty && <span className="h-2 w-2 shrink-0 rounded-full bg-amber-300" title="未保存" />}
      {!tab.pinned && (
        <span className="flex shrink-0 items-center gap-0.5 opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus:opacity-100">
          <button
            type="button"
            onKeyDown={event => event.stopPropagation()}
            onClick={event => { event.stopPropagation(); splitTab(tab.id) }}
            title={split ? '已在并排编辑组中打开' : '在右侧并排打开'}
            className={`flex h-6 w-6 items-center justify-center rounded hover:bg-slate-600 ${split ? 'text-sky-300 opacity-100' : 'text-slate-300'}`}
          >
            <Columns2 size={13} />
          </button>
          <button
            type="button"
            onKeyDown={event => event.stopPropagation()}
            onClick={event => { event.stopPropagation(); closeTab(tab.id) }}
            title="关闭标签页"
            className="flex h-6 w-6 items-center justify-center rounded text-slate-300 hover:bg-slate-600 hover:text-white"
          >
            <X size={13} />
          </button>
        </span>
      )}
    </div>
  )
}

export default function WorkspaceTabs() {
  const { tabs } = useWorkspace()
  return (
    <div className="flex h-10 shrink-0 items-stretch border-b border-slate-700 bg-slate-950" role="tablist" aria-label="已打开的学习页面">
      <div className="workspace-tabs-scroll flex min-w-0 flex-1 items-stretch overflow-x-auto overflow-y-hidden">
        {tabs.map(tab => <Tab key={tab.id} tab={tab} />)}
      </div>
      <div className="hidden shrink-0 items-center gap-1 border-l border-slate-700 px-3 text-[10px] text-slate-400 2xl:flex">
        <Columns2 size={12} className="text-emerald-400" />
        拖动标签到右侧可并排
      </div>
    </div>
  )
}
