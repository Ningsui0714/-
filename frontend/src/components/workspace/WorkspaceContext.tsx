import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from 'react'
import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

export type WorkspaceTabKind =
  | 'home'
  | 'projects'
  | 'project'
  | 'lecture'
  | 'exercise'
  | 'file'
  | 'memory'
  | 'review'
  | 'profile'
  | 'settings'
  | 'wf03'

const WORKSPACE_TAB_KINDS: WorkspaceTabKind[] = [
  'home', 'projects', 'project', 'lecture', 'exercise', 'file', 'memory', 'review', 'profile', 'settings', 'wf03',
]

export interface WorkspaceTab {
  id: string
  path: string
  title: string
  kind: WorkspaceTabKind
  projectId?: number
  checkpointId?: number
  workspacePath?: string
  dirty?: boolean
  pinned?: boolean
}

interface WorkspaceTabPatch {
  title?: string
  kind?: WorkspaceTabKind
  projectId?: number
  checkpointId?: number
  workspacePath?: string
  dirty?: boolean
}

interface WorkspaceContextValue {
  tabs: WorkspaceTab[]
  activeTabId: string
  splitTabIds: string[]
  draggingTabId: string | null
  openPath: (path: string, patch?: WorkspaceTabPatch) => void
  activateTab: (tabId: string) => void
  closeTab: (tabId: string) => void
  updateCurrentTab: (patch: WorkspaceTabPatch) => void
  splitTab: (tabId: string) => void
  closeSplit: (tabId: string) => void
  setTabDirty: (tabId: string, dirty: boolean) => void
  setDraggingTabId: (tabId: string | null) => void
}

const HOME_TAB: WorkspaceTab = {
  id: '/agent',
  path: '/agent',
  title: '学习工作台',
  kind: 'home',
  pinned: true,
}

const noOp = () => {}
const WorkspaceContext = createContext<WorkspaceContextValue>({
  tabs: [HOME_TAB],
  activeTabId: HOME_TAB.id,
  splitTabIds: [],
  draggingTabId: null,
  openPath: noOp,
  activateTab: noOp,
  closeTab: noOp,
  updateCurrentTab: noOp,
  splitTab: noOp,
  closeSplit: noOp,
  setTabDirty: noOp,
  setDraggingTabId: noOp,
})

function normalizePath(path: string) {
  const url = new URL(path, window.location.origin)
  url.searchParams.delete('embed')
  const query = url.searchParams.toString()
  return `${url.pathname}${query ? `?${query}` : ''}${url.hash}`
}

function pathMeta(path: string): WorkspaceTab {
  const normalized = normalizePath(path)
  const pathname = new URL(normalized, window.location.origin).pathname
  const workspaceFile = pathname.match(/^\/projects\/(\d+)\/workspace$/)
  if (workspaceFile) {
    const url = new URL(normalized, window.location.origin)
    const workspacePath = url.searchParams.get('path') || ''
    return {
      id: normalized,
      path: normalized,
      title: workspacePath.split('/').pop() || '项目文件',
      kind: 'file',
      projectId: Number(workspaceFile[1]),
      workspacePath,
    }
  }
  const exercise = pathname.match(/^\/projects\/(\d+)\/checkpoints\/(\d+)\/exercises$/)
  if (exercise) {
    return {
      id: normalized,
      path: normalized,
      title: `练习 · 关卡 ${exercise[2]}`,
      kind: 'exercise',
      projectId: Number(exercise[1]),
      checkpointId: Number(exercise[2]),
    }
  }
  const lecture = pathname.match(/^\/projects\/(\d+)\/checkpoints\/(\d+)$/)
  if (lecture) {
    return {
      id: normalized,
      path: normalized,
      title: `讲义 · 关卡 ${lecture[2]}`,
      kind: 'lecture',
      projectId: Number(lecture[1]),
      checkpointId: Number(lecture[2]),
    }
  }
  const project = pathname.match(/^\/projects\/(\d+)$/)
  if (project) {
    return {
      id: normalized,
      path: normalized,
      title: `学习项目 ${project[1]}`,
      kind: 'project',
      projectId: Number(project[1]),
    }
  }
  const wf03Task = pathname.match(/^\/wf03\/tasks\/([A-Za-z0-9_-]+)$/)
  if (wf03Task) {
    return {
      id: normalized,
      path: normalized,
      title: '学习型任务网页',
      kind: 'wf03',
    }
  }
  const learningTaskPlan = pathname.match(/^\/learning-task-plans\/(run_[A-Fa-f0-9]+)$/)
  if (learningTaskPlan) {
    return {
      id: normalized,
      path: normalized,
      title: '学习型任务 Plan',
      kind: 'wf03',
    }
  }
  if (pathname === '/learning-task-conversion/upstream') {
    return {
      id: normalized,
      path: normalized,
      title: '岗位任务接入',
      kind: 'wf03',
    }
  }
  const personalizedLearning = pathname.match(
    /^\/personalized-learning\/tasks\/([A-Za-z0-9_-]+)\/knowledge\/([A-Za-z0-9_-]+)$/,
  )
  if (personalizedLearning) {
    return {
      id: normalized,
      path: normalized,
      title: '个性化学习 · 知识点',
      kind: 'wf03',
    }
  }
  const staticMeta: Record<string, Pick<WorkspaceTab, 'title' | 'kind' | 'pinned'>> = {
    '/agent': { title: '学习工作台', kind: 'home', pinned: true },
    '/projects': { title: '学习项目', kind: 'projects' },
    '/memory': { title: '五核记忆', kind: 'memory' },
    '/review': { title: '全局复习台', kind: 'review' },
    '/profile': { title: '个人画像', kind: 'profile' },
    '/settings': { title: '模型设置', kind: 'settings' },
  }
  const meta = staticMeta[pathname] || { title: 'LearnFlow', kind: 'home' as const }
  return { id: normalized, path: normalized, ...meta }
}

function validTab(value: unknown): value is WorkspaceTab {
  if (!value || typeof value !== 'object') return false
  const tab = value as WorkspaceTab
  return typeof tab.id === 'string'
    && typeof tab.path === 'string'
    && typeof tab.title === 'string'
    && tab.path.startsWith('/')
    && tab.id === normalizePath(tab.path)
    && WORKSPACE_TAB_KINDS.includes(tab.kind)
}

function limitTabs(items: WorkspaceTab[]) {
  const home = items.find(tab => tab.id === HOME_TAB.id) || HOME_TAB
  return [home, ...items.filter(tab => tab.id !== HOME_TAB.id).slice(-15)]
}

export function WorkspaceProvider({ learnerKey, children }: { learnerKey: string; children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const storageKey = `learnflow.workspace.v1.${learnerKey}`
  const [tabs, setTabs] = useState<WorkspaceTab[]>([HOME_TAB])
  const [activeTabId, setActiveTabId] = useState(HOME_TAB.id)
  const [splitTabIds, setSplitTabIds] = useState<string[]>([])
  const [draggingTabId, setDraggingTabId] = useState<string | null>(null)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || '{}')
      const restored = Array.isArray(saved.tabs) ? saved.tabs.filter(validTab) : []
      const withHome = restored.some((tab: WorkspaceTab) => tab.id === HOME_TAB.id)
        ? restored.map((tab: WorkspaceTab) => tab.id === HOME_TAB.id ? HOME_TAB : tab)
        : [HOME_TAB, ...restored]
      const limited = limitTabs(withHome)
      setTabs(limited)
      setSplitTabIds(
        Array.isArray(saved.splitTabIds)
          ? saved.splitTabIds.filter((id: unknown) => typeof id === 'string' && limited.some((tab: WorkspaceTab) => tab.id === id)).slice(0, 2)
          : [],
      )
    } catch {
      setTabs([HOME_TAB])
      setSplitTabIds([])
    }
    setHydrated(true)
  }, [storageKey])

  useEffect(() => {
    if (!hydrated) return
    localStorage.setItem(storageKey, JSON.stringify({ tabs, splitTabIds }))
  }, [hydrated, splitTabIds, storageKey, tabs])

  useEffect(() => {
    if (!hydrated) return
    const path = normalizePath(`${location.pathname}${location.search}${location.hash}`)
    const next = pathMeta(path)
    setTabs(previous => {
      const existing = previous.find(tab => tab.id === next.id)
      return existing ? previous : limitTabs([...previous, next])
    })
    setActiveTabId(next.id)
  }, [hydrated, location.hash, location.pathname, location.search])

  useEffect(() => {
    const remapWorkspacePath = (event: Event) => {
      const detail = (event as CustomEvent<{
        projectId: number
        previousPath: string
        nextPath: string
      }>).detail
      if (!detail?.projectId || !detail.previousPath || !detail.nextPath) return
      const remapTab = (tab: WorkspaceTab): WorkspaceTab => {
        if (tab.kind !== 'file' || tab.projectId !== detail.projectId || !tab.workspacePath) return tab
        const exact = tab.workspacePath === detail.previousPath
        const descendant = tab.workspacePath.startsWith(`${detail.previousPath}/`)
        if (!exact && !descendant) return tab
        const suffix = exact ? '' : tab.workspacePath.slice(detail.previousPath.length)
        const workspacePath = `${detail.nextPath}${suffix}`
        const route = `/projects/${detail.projectId}/workspace?path=${encodeURIComponent(workspacePath)}`
        const replacement = {
          ...tab,
          id: normalizePath(route),
          path: normalizePath(route),
          title: workspacePath.split('/').pop() || tab.title,
          workspacePath,
        }
        return replacement
      }
      const activeTab = tabs.find(tab => tab.id === activeTabId)
      const activeReplacement = activeTab ? remapTab(activeTab) : null
      setTabs(previous => previous.map(remapTab))
      if (activeReplacement && activeReplacement.id !== activeTab?.id) {
        setActiveTabId(activeReplacement.id)
        navigate(activeReplacement.path, { replace: true })
      }
    }
    window.addEventListener('learnflow:workspace-path-moved', remapWorkspacePath)
    return () => window.removeEventListener('learnflow:workspace-path-moved', remapWorkspacePath)
  }, [activeTabId, navigate, tabs])

  const openPath = useCallback((path: string, patch: WorkspaceTabPatch = {}) => {
    const base = pathMeta(path)
    const next = { ...base, ...patch, id: base.id, path: base.path }
    setTabs(previous => {
      const index = previous.findIndex(tab => tab.id === next.id)
      if (index < 0) return limitTabs([...previous, next])
      const copy = [...previous]
      copy[index] = { ...copy[index], ...next }
      return copy
    })
    setActiveTabId(next.id)
    navigate(next.path)
  }, [navigate])

  const activateTab = useCallback((tabId: string) => {
    const tab = tabs.find(item => item.id === tabId)
    if (!tab) return
    setActiveTabId(tab.id)
    navigate(tab.path)
  }, [navigate, tabs])

  const closeTab = useCallback((tabId: string) => {
    const index = tabs.findIndex(tab => tab.id === tabId)
    const target = tabs[index]
    if (index < 0 || target?.pinned) return
    if (target.dirty && !window.confirm(`“${target.title}”还有未保存的修改，仍要关闭吗？`)) return
    const remaining = tabs.filter(tab => tab.id !== tabId)
    setTabs(remaining)
    setSplitTabIds(previous => previous.filter(id => id !== tabId))
    if (activeTabId === tabId) {
      const next = remaining[index] || remaining[index - 1] || HOME_TAB
      setActiveTabId(next.id)
      navigate(next.path)
    }
  }, [activeTabId, navigate, tabs])

  const updateCurrentTab = useCallback((patch: WorkspaceTabPatch) => {
    const currentId = normalizePath(`${location.pathname}${location.search}${location.hash}`)
    setTabs(previous => previous.map(tab => tab.id === currentId ? { ...tab, ...patch } : tab))
  }, [location.hash, location.pathname, location.search])

  const splitTab = useCallback((tabId: string) => {
    if (!tabs.some(tab => tab.id === tabId)) return
    setSplitTabIds(previous => {
      if (previous.includes(tabId)) return previous
      return [...previous, tabId].slice(-2)
    })
  }, [tabs])

  const closeSplit = useCallback((tabId: string) => {
    setSplitTabIds(previous => previous.filter(id => id !== tabId))
  }, [])

  const setTabDirty = useCallback((tabId: string, dirty: boolean) => {
    setTabs(previous => previous.map(tab => tab.id === tabId ? { ...tab, dirty } : tab))
  }, [])

  const value = useMemo<WorkspaceContextValue>(() => ({
    tabs,
    activeTabId,
    splitTabIds,
    draggingTabId,
    openPath,
    activateTab,
    closeTab,
    updateCurrentTab,
    splitTab,
    closeSplit,
    setTabDirty,
    setDraggingTabId,
  }), [
    tabs, activeTabId, splitTabIds, draggingTabId, openPath, activateTab,
    closeTab, updateCurrentTab, splitTab, closeSplit, setTabDirty,
  ])

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}

export function useWorkspace() {
  return useContext(WorkspaceContext)
}

export function useWorkspaceTitle(title: string, patch: WorkspaceTabPatch = {}) {
  const { updateCurrentTab } = useWorkspace()
  const { kind, projectId, checkpointId, workspacePath } = patch
  useEffect(() => {
    if (!title) return
    updateCurrentTab({ title, kind, projectId, checkpointId, workspacePath })
  }, [checkpointId, kind, projectId, title, updateCurrentTab, workspacePath])
}

export function workspaceEmbedPath(path: string) {
  const url = new URL(path, window.location.origin)
  url.searchParams.set('embed', '1')
  return `${url.pathname}${url.search}${url.hash}`
}
