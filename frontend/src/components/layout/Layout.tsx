import { useEffect, useMemo, useState } from 'react'
import {
  CalendarClock, GitBranch, LogOut, PanelLeft, PanelRight, PanelsTopLeft, Settings2,
  Sparkles, UserRound, X,
} from 'lucide-react'
import { Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { getDesktopRuntime } from '../../services/desktopRuntime'
import WorkspaceProjectExplorer from '../workspace/WorkspaceProjectExplorer'
import WorkspaceAgentRail from '../workspace/WorkspaceAgentRail'
import WorkspaceTabs from '../workspace/WorkspaceTabs'
import CheckpointPage from '../../pages/CheckpointPage'
import {
  WorkspaceProvider, useWorkspace, workspaceEmbedPath,
} from '../workspace/WorkspaceContext'

function DesktopSplitPane({ tab }: { tab: { id: string; path: string; title: string; kind: string } }) {
  const { activateTab } = useWorkspace()
  if (tab.kind === 'lecture') {
    return (
      <Routes location={tab.path}>
        <Route path="/projects/:projectId/checkpoints/:checkpointId" element={<CheckpointPage />} />
      </Routes>
    )
  }
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 bg-slate-50 px-8 text-center">
      <p className="text-sm font-medium text-slate-700">此页面请在主学习编辑组中打开</p>
      <button
        type="button"
        onClick={() => activateTab(tab.id)}
        className="rounded-lg bg-slate-800 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
      >
        打开 {tab.title}
      </button>
    </div>
  )
}

function WorkspaceStage() {
  const {
    tabs, splitTabIds, draggingTabId, splitTab, closeSplit, setDraggingTabId,
  } = useWorkspace()
  const splitTabs = splitTabIds
    .map(id => tabs.find(tab => tab.id === id))
    .filter(Boolean)
  const desktop = getDesktopRuntime().available
    || '__TAURI_INTERNALS__' in window
    || window.location.protocol === 'tauri:'

  return (
    <main
      className={`relative flex min-h-0 flex-1 items-stretch gap-px overflow-x-auto overflow-y-hidden bg-slate-800 ${draggingTabId ? 'workspace-drag-active' : ''}`}
      onDragOver={event => {
        if (!draggingTabId) return
        event.preventDefault()
        event.dataTransfer.dropEffect = 'copy'
      }}
      onDrop={event => {
        if (!draggingTabId) return
        event.preventDefault()
        const bounds = event.currentTarget.getBoundingClientRect()
        if (event.clientX >= bounds.left + bounds.width * 0.48) splitTab(draggingTabId)
        setDraggingTabId(null)
      }}
    >
      {draggingTabId && (
        <div className="pointer-events-none absolute bottom-5 right-5 top-5 z-30 flex w-[44%] items-center justify-center border-2 border-dashed border-sky-300 bg-sky-700/80 px-8 text-center text-sm font-semibold text-white shadow-2xl">
          松开鼠标，在新的学习编辑组中并排打开
        </div>
      )}

      <section className="h-full min-w-0 flex-1 overflow-hidden bg-slate-50" aria-label="主学习编辑组">
        <Outlet />
      </section>

      {splitTabs.map(tab => tab && (
        <section key={tab.id} className="flex h-full min-w-[460px] flex-1 flex-col overflow-hidden border-l border-slate-700 bg-slate-50" aria-label={`并排页面：${tab.title}`}>
          <header className="flex h-9 shrink-0 items-center gap-2 border-b border-slate-700 bg-slate-900 px-3 text-xs text-slate-200">
            <PanelsTopLeft size={13} className="text-sky-300" />
            <span className="min-w-0 flex-1 truncate">{tab.title}</span>
            <button
              type="button"
              onClick={() => closeSplit(tab.id)}
              title="关闭并排编辑组"
              className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-slate-700 hover:text-white"
            >
              <X size={13} />
            </button>
          </header>
          {desktop
            ? <div className="min-h-0 flex-1 overflow-hidden"><DesktopSplitPane tab={tab} /></div>
            : <iframe title={`并排页面：${tab.title}`} src={workspaceEmbedPath(tab.path)} className="min-h-0 flex-1 border-0 bg-slate-50" />}
        </section>
      ))}
    </main>
  )
}

function WorkspaceFrame() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { openPath } = useWorkspace()
  const [explorerVisible, setExplorerVisible] = useState(() => window.innerWidth >= 1024)
  // Keep the conversation visible on ordinary laptop/desktop workspaces. The
  // rail already becomes an overlay below 2xl, so hiding it at 1280px made the
  // task-to-personalized-learning path look as if the chat had disappeared.
  const [agentRailExpanded, setAgentRailExpanded] = useState(() => window.innerWidth >= 1100)

  useEffect(() => {
    const fitPanelsToViewport = () => {
      if (window.innerWidth < 1024) setExplorerVisible(false)
      if (window.innerWidth < 1100) setAgentRailExpanded(false)
    }
    window.addEventListener('resize', fitPanelsToViewport)
    return () => window.removeEventListener('resize', fitPanelsToViewport)
  }, [])

  useEffect(() => {
    const openAgentConversation = () => {
      setAgentRailExpanded(true)
      window.setTimeout(() => {
        document.querySelector<HTMLElement>('[data-agent-conversation-input]')?.focus()
      }, 80)
    }
    window.addEventListener('learnflow:agent-open', openAgentConversation)
    return () => window.removeEventListener('learnflow:agent-open', openAgentConversation)
  }, [])

  const exit = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-100 text-slate-900">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-3 sm:px-4">
        <button
          type="button"
          onClick={() => setExplorerVisible(value => !value)}
          title={explorerVisible ? '收起项目资源管理器' : '展开项目资源管理器'}
          className={`flex h-9 w-9 items-center justify-center rounded-lg ${explorerVisible ? 'bg-emerald-50 text-emerald-800' : 'text-slate-500 hover:bg-slate-100'}`}
        >
          <PanelLeft size={18} />
        </button>
        <button
          type="button"
          onClick={() => openPath('/agent', { title: '学习工作台', kind: 'home' })}
          className="flex shrink-0 items-center gap-2 rounded-lg px-1.5 py-1 text-left hover:bg-slate-50"
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-700 text-white"><Sparkles size={17} /></span>
          <span className="hidden sm:block">
            <strong className="block text-sm leading-4 text-slate-900">LearnFlow</strong>
            <small className="text-[10px] text-slate-400">学习工作区</small>
          </span>
        </button>

        <div className="min-w-0 flex-1" />
        <div className="hidden items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-medium text-emerald-800 md:flex">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          三类 Agent · 五核证据在线
        </div>
        <button type="button" onClick={() => openPath('/memory', { title: '五核记忆', kind: 'memory' })} title="五核记忆" className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-indigo-700">
          <GitBranch size={17} />
        </button>
        <button type="button" onClick={() => openPath('/review', { title: '全局复习台', kind: 'review' })} title="复习与错题" className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-indigo-700">
          <CalendarClock size={17} />
        </button>
        <button type="button" onClick={() => openPath('/profile', { title: '个人画像', kind: 'profile' })} title="个人画像" className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-indigo-700">
          <UserRound size={17} />
        </button>
        {(user?.is_dev_login || Boolean(getDesktopRuntime().apiBaseUrl)) && (
          <button type="button" onClick={() => openPath('/settings', { title: '模型设置', kind: 'settings' })} title="设置" aria-label="设置" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-indigo-700">
            <Settings2 size={17} />
          </button>
        )}
        <span className="hidden max-w-28 truncate text-xs text-slate-500 lg:block">{user?.display_name}</span>
        <button type="button" onClick={() => setAgentRailExpanded(value => !value)} title={agentRailExpanded ? '收起 Agent 对话' : '展开 Agent 对话'} className={`flex h-9 w-9 items-center justify-center rounded-lg ${agentRailExpanded ? 'bg-emerald-50 text-emerald-800' : 'text-slate-500 hover:bg-slate-100'}`}>
          <PanelRight size={18} />
        </button>
        <button type="button" onClick={exit} title="退出登录" className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 hover:bg-red-50 hover:text-red-600">
          <LogOut size={17} />
        </button>
      </header>

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {explorerVisible && (
          <div className="hidden w-[258px] shrink-0 border-r border-slate-200 lg:block">
            <WorkspaceProjectExplorer />
          </div>
        )}

        <section
          data-agent-rail-expanded={agentRailExpanded}
          className="group/workspace flex min-w-0 flex-1 flex-col overflow-hidden"
        >
          <WorkspaceTabs />
          <WorkspaceStage />
        </section>

        {explorerVisible && (
          <div className="absolute inset-0 z-40 flex bg-slate-950/30 lg:hidden" onClick={() => setExplorerVisible(false)}>
            <div className="h-full w-[min(88vw,320px)] border-r border-slate-200 shadow-2xl" onClick={event => event.stopPropagation()}>
              <WorkspaceProjectExplorer onNavigate={() => setExplorerVisible(false)} />
            </div>
          </div>
        )}
        {agentRailExpanded && (
          <button
            type="button"
            aria-label="关闭 Agent 对话"
            onClick={() => setAgentRailExpanded(false)}
            className="absolute inset-0 z-40 bg-slate-950/30 xl:hidden"
          />
        )}
        <div className={`${
          agentRailExpanded
            ? 'absolute inset-y-0 right-0 z-50 w-[min(92vw,390px)] 2xl:relative 2xl:inset-auto 2xl:z-auto 2xl:w-[390px]'
            : 'hidden xl:block xl:w-[52px]'
        } shrink-0 transition-[width] duration-200`}>
          <WorkspaceAgentRail
            expanded={agentRailExpanded}
            onToggle={() => setAgentRailExpanded(value => !value)}
          />
        </div>
      </div>
    </div>
  )
}

export default function Layout() {
  const { user } = useAuth()
  const location = useLocation()
  const embedded = useMemo(() => new URLSearchParams(location.search).get('embed') === '1', [location.search])

  if (embedded) {
    return <main className="h-screen min-h-0 overflow-hidden bg-slate-50"><Outlet /></main>
  }

  return (
    <WorkspaceProvider learnerKey={String(user?.learner_id || user?.id || 'anonymous')}>
      <WorkspaceFrame />
    </WorkspaceProvider>
  )
}
