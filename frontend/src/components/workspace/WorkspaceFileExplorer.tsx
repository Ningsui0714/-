import { useCallback, useEffect, useState } from 'react'
import {
  ArchiveRestore, Binary, ChevronDown, ChevronRight, ExternalLink, File,
  FileCode2, FilePlus2, Folder, FolderOpen, FolderPlus, Loader2, MoreHorizontal,
  Pencil, RefreshCw, Trash2,
} from 'lucide-react'
import {
  confirmWorkspaceOperation, getWorkspaceFile, getWorkspaceTree,
  linkProjectWorkspace, listWorkspaceOperations, proposeWorkspaceOperation,
  revealWorkspaceItem, saveWorkspaceFile, type WorkspaceNode, type WorkspaceOperation,
  type WorkspaceTree,
} from '../../services/api'
import { chooseWorkspaceDirectory, getDesktopRuntime, initializeDesktopRuntime, type DesktopRuntime } from '../../services/desktopRuntime'


function errorMessage(error: any) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return error instanceof Error ? error.message : '本地文件操作失败'
}

function joinPath(parent: string, name: string) {
  return parent ? `${parent}/${name}` : name
}

function parentPath(path: string) {
  const parts = path.split('/')
  parts.pop()
  return parts.join('/')
}

function safeName(value: string | null) {
  const name = value?.trim() || ''
  return name && name !== '.' && name !== '..' && !/[\\/\0]/.test(name) ? name : null
}

function systemJoin(parent: string, child: string) {
  const separator = parent.includes('\\') ? '\\' : '/'
  return `${parent.replace(/[\\/]$/, '')}${separator}${child}`
}

interface FileNodeRowProps {
  projectId: number
  node: WorkspaceNode
  depth: number
  onOpen: (path: string) => void
  onChanged: () => void
  setNotice: (message: string) => void
}

function FileNodeRow({ projectId, node, depth, onOpen, onChanged, setNotice }: FileNodeRowProps) {
  const [expanded, setExpanded] = useState(depth < 1)
  const [menuOpen, setMenuOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  const baseHash = async () => {
    if (node.is_directory) return undefined
    const file = await getWorkspaceFile(projectId, node.path)
    return file.sha256
  }

  const apply = async (data: Parameters<typeof proposeWorkspaceOperation>[1]) => {
    setBusy(true)
    setNotice('')
    try {
      const proposal = await proposeWorkspaceOperation(projectId, data)
      const confirmed = await confirmWorkspaceOperation(projectId, proposal.id)
      if (confirmed.result?.previous_path && confirmed.result?.path) {
        window.dispatchEvent(new CustomEvent('learnflow:workspace-path-moved', {
          detail: {
            projectId,
            previousPath: confirmed.result.previous_path,
            nextPath: confirmed.result.path,
          },
        }))
      }
      onChanged()
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setBusy(false)
      setMenuOpen(false)
    }
  }

  const createFile = async () => {
    const name = safeName(window.prompt('新文件名'))
    if (!name) return
    const path = joinPath(node.path, name)
    setBusy(true)
    try {
      await saveWorkspaceFile(projectId, path, {
        content: '', idempotency_key: `create-file:${crypto.randomUUID()}`,
      })
      onChanged()
      onOpen(path)
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const createFolder = async () => {
    const name = safeName(window.prompt('新目录名'))
    if (!name) return
    await apply({
      actor: 'user', operation: 'mkdir', target_path: joinPath(node.path, name),
      idempotency_key: `mkdir:${crypto.randomUUID()}`,
    })
  }

  const rename = async () => {
    const name = safeName(window.prompt('新名称', node.name))
    if (!name || name === node.name) return
    const destination = joinPath(parentPath(node.path), name)
    if (!window.confirm(`将“${node.path}”重命名为“${destination}”？`)) return
    await apply({
      actor: 'user', operation: 'rename', target_path: node.path,
      destination_path: destination, base_hash: await baseHash(),
      idempotency_key: `rename:${crypto.randomUUID()}`,
    })
  }

  const move = async () => {
    const destination = window.prompt('移动到（相对于项目根的完整路径）', node.path)?.trim()
    if (!destination || destination === node.path) return
    if (!window.confirm(`将“${node.path}”移动到“${destination}”？`)) return
    await apply({
      actor: 'user', operation: 'move', target_path: node.path,
      destination_path: destination, base_hash: await baseHash(),
      idempotency_key: `move:${crypto.randomUUID()}`,
    })
  }

  const remove = async () => {
    if (!window.confirm(`删除“${node.path}”？项目不会永久删除它，可从回收站恢复。`)) return
    await apply({
      actor: 'user', operation: 'delete', target_path: node.path,
      base_hash: await baseHash(), idempotency_key: `delete:${crypto.randomUUID()}`,
    })
  }

  const protectedNode = node.kind === 'protected'
  const NodeIcon = protectedNode ? Binary
    : node.is_directory ? (expanded ? FolderOpen : Folder)
      : node.kind === 'workspace_text' ? FileCode2 : File

  return (
    <div>
      <div
        className={`group relative flex h-7 items-center rounded text-[11px] ${protectedNode ? 'text-slate-400' : 'text-slate-600 hover:bg-slate-100'}`}
        style={{ paddingLeft: `${Math.min(depth, 8) * 12 + 2}px` }}
      >
        <button
          type="button"
          disabled={protectedNode}
          onClick={() => node.is_directory ? setExpanded(value => !value) : onOpen(node.path)}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left disabled:cursor-not-allowed"
          title={node.path}
        >
          {node.is_directory
            ? expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />
            : <span className="w-[11px]" />}
          <NodeIcon size={13} className={node.kind === 'workspace_binary' ? 'text-sky-500' : node.is_directory ? 'text-amber-500' : 'text-emerald-600'} />
          <span className="min-w-0 flex-1 truncate">{node.name}</span>
          {busy && <Loader2 size={11} className="animate-spin" />}
        </button>
        {!protectedNode && (
          <button
            type="button"
            onClick={() => setMenuOpen(value => !value)}
            className="mr-1 flex h-6 w-6 items-center justify-center rounded text-slate-400 opacity-0 hover:bg-white hover:text-slate-700 group-hover:opacity-100"
            title="文件操作"
          >
            <MoreHorizontal size={13} />
          </button>
        )}
        {menuOpen && (
          <div className="absolute right-1 top-7 z-30 w-40 rounded-md border border-slate-200 bg-white py-1 text-[11px] shadow-xl">
            {node.is_directory && (
              <>
                <button type="button" onClick={() => void createFile()} className="flex w-full items-center gap-2 px-3 py-1.5 hover:bg-slate-100"><FilePlus2 size={12} /> 新建文件</button>
                <button type="button" onClick={() => void createFolder()} className="flex w-full items-center gap-2 px-3 py-1.5 hover:bg-slate-100"><FolderPlus size={12} /> 新建目录</button>
              </>
            )}
            <button type="button" onClick={() => void revealWorkspaceItem(projectId, node.path).finally(() => setMenuOpen(false))} className="flex w-full items-center gap-2 px-3 py-1.5 hover:bg-slate-100"><ExternalLink size={12} /> 系统中显示</button>
            <button type="button" onClick={() => void rename()} className="flex w-full items-center gap-2 px-3 py-1.5 hover:bg-slate-100"><Pencil size={12} /> 重命名</button>
            <button type="button" onClick={() => void move()} className="flex w-full items-center gap-2 px-3 py-1.5 hover:bg-slate-100"><FolderOpen size={12} /> 移动到…</button>
            <button type="button" onClick={() => void remove()} className="flex w-full items-center gap-2 px-3 py-1.5 text-red-600 hover:bg-red-50"><Trash2 size={12} /> 移到回收站</button>
          </div>
        )}
      </div>
      {node.is_directory && expanded && node.children.map(child => (
        <FileNodeRow
          key={child.path}
          projectId={projectId}
          node={child}
          depth={depth + 1}
          onOpen={onOpen}
          onChanged={onChanged}
          setNotice={setNotice}
        />
      ))}
    </div>
  )
}

export default function WorkspaceFileExplorer({
  projectId, projectName, onOpen,
}: {
  projectId: number
  projectName: string
  onOpen: (path: string) => void
}) {
  const [desktop, setDesktop] = useState<DesktopRuntime>(() => getDesktopRuntime())
  const [tree, setTree] = useState<WorkspaceTree | null>(null)
  const [linked, setLinked] = useState<boolean | null>(null)
  const [trash, setTrash] = useState<WorkspaceOperation[]>([])
  const [trashExpanded, setTrashExpanded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [linking, setLinking] = useState(false)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    const refreshRuntime = () => setDesktop(getDesktopRuntime())
    window.addEventListener('learnflow:desktop-runtime-changed', refreshRuntime)
    return () => window.removeEventListener('learnflow:desktop-runtime-changed', refreshRuntime)
  }, [])

  const load = useCallback(async () => {
    if (!desktop.available || !desktop.ready) return
    setLoading(true)
    try {
      const next = await getWorkspaceTree(projectId)
      setTree(next)
      setLinked(true)
      const deleted = await listWorkspaceOperations(projectId, { operation: 'delete', status: 'applied' })
      setTrash(deleted.filter(item => item.result?.restorable))
      setNotice('')
    } catch (error: any) {
      if (error?.response?.status === 404) {
        setLinked(false)
        setTree(null)
      } else {
        setNotice(errorMessage(error))
      }
    } finally {
      setLoading(false)
    }
  }, [desktop.available, desktop.ready, projectId])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const changed = (event: Event) => {
      const changedProjectId = (event as CustomEvent).detail?.projectId
      if (!changedProjectId || changedProjectId === projectId) void load()
    }
    window.addEventListener('learnflow:workspace-changed', changed)
    return () => window.removeEventListener('learnflow:workspace-changed', changed)
  }, [load, projectId])

  const linkedDirectory = async (create: boolean) => {
    const selected = await chooseWorkspaceDirectory()
    if (!selected) return
    let rootPath = selected
    if (create) {
      const suggested = projectName.replace(/[<>:"/\\|?*]/g, '-').trim() || `learnflow-project-${projectId}`
      const name = safeName(window.prompt('本地项目文件夹名称', suggested))
      if (!name) return
      rootPath = systemJoin(selected, name)
    }
    setLinking(true)
    setNotice('')
    try {
      await linkProjectWorkspace(projectId, {
        root_path: rootPath,
        platform: navigator.platform || 'unknown',
        create,
        client_request_id: crypto.randomUUID(),
      })
      await load()
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setLinking(false)
    }
  }

  const createRootFile = async () => {
    const name = safeName(window.prompt('新文件名'))
    if (!name) return
    try {
      await saveWorkspaceFile(projectId, name, {
        content: '', idempotency_key: `create-file:${crypto.randomUUID()}`,
      })
      await load()
      onOpen(name)
    } catch (error) {
      setNotice(errorMessage(error))
    }
  }

  const createRootFolder = async () => {
    const name = safeName(window.prompt('新目录名'))
    if (!name) return
    try {
      const proposal = await proposeWorkspaceOperation(projectId, {
        actor: 'user', operation: 'mkdir', target_path: name,
        idempotency_key: `mkdir:${crypto.randomUUID()}`,
      })
      await confirmWorkspaceOperation(projectId, proposal.id)
      await load()
    } catch (error) {
      setNotice(errorMessage(error))
    }
  }

  const restore = async (deleted: WorkspaceOperation) => {
    if (!window.confirm(`恢复“${deleted.target_path}”？`)) return
    try {
      const proposal = await proposeWorkspaceOperation(projectId, {
        actor: 'user', operation: 'restore', target_path: deleted.target_path,
        source_operation_id: deleted.id,
        idempotency_key: `restore:${crypto.randomUUID()}`,
      })
      await confirmWorkspaceOperation(projectId, proposal.id)
      await load()
    } catch (error) {
      setNotice(errorMessage(error))
    }
  }

  if (!desktop.available) return null

  return (
    <div className="mt-2 border-t border-slate-200 pt-2">
      <div className="flex h-7 items-center gap-1 px-2 text-[9px] font-bold uppercase tracking-[0.12em] text-slate-400">
        <Folder size={11} /> 项目文件
        <span className="min-w-0 flex-1 truncate font-normal normal-case tracking-normal">{tree?.root_name}</span>
        {linked && (
          <>
            <button type="button" onClick={() => void createRootFile()} title="新建文件" className="flex h-6 w-6 items-center justify-center rounded hover:bg-white hover:text-slate-700"><FilePlus2 size={12} /></button>
            <button type="button" onClick={() => void createRootFolder()} title="新建目录" className="flex h-6 w-6 items-center justify-center rounded hover:bg-white hover:text-slate-700"><FolderPlus size={12} /></button>
            <button type="button" onClick={() => void load()} title="刷新" className="flex h-6 w-6 items-center justify-center rounded hover:bg-white hover:text-slate-700"><RefreshCw size={12} /></button>
          </>
        )}
      </div>

      {desktop.startupError && !desktop.ready && (
        <div className="mx-1 rounded-md border border-red-200 bg-red-50 p-2 text-[10px] leading-4 text-red-700">
          <p>本地服务尚未就绪：{desktop.startupError}</p>
          <button
            type="button"
            onClick={() => void initializeDesktopRuntime()}
            className="mt-1 rounded border border-red-300 bg-white px-2 py-1 text-red-700 hover:bg-red-100"
          >
            重试连接
          </button>
        </div>
      )}
      {notice && <p className="px-2 py-1 text-[10px] leading-4 text-amber-700">{notice}</p>}
      {loading && <p className="flex items-center gap-1.5 px-2 py-2 text-[10px] text-slate-400"><Loader2 size={11} className="animate-spin" /> 正在读取文件…</p>}

      {!loading && linked === false && (
        <div className="mx-1 rounded-md border border-dashed border-slate-300 bg-white p-2 text-[10px] leading-4 text-slate-500">
          <p>为这个学习项目关联一个真实本地目录。</p>
          <div className="mt-2 flex flex-wrap gap-1">
            <button type="button" disabled={linking} onClick={() => void linkedDirectory(true)} className="rounded bg-emerald-700 px-2 py-1 text-white disabled:opacity-50">选择父目录并新建</button>
            <button type="button" disabled={linking} onClick={() => void linkedDirectory(false)} className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50 disabled:opacity-50">关联现有目录</button>
          </div>
        </div>
      )}

      {!loading && tree && (
        <div className="mt-0.5">
          {tree.nodes.length === 0 && <p className="px-2 py-2 text-[10px] text-slate-400">目录为空，可新建文件或文件夹。</p>}
          {tree.nodes.map(node => (
            <FileNodeRow
              key={node.path}
              projectId={projectId}
              node={node}
              depth={0}
              onOpen={onOpen}
              onChanged={() => void load()}
              setNotice={setNotice}
            />
          ))}
          {trash.length > 0 && (
            <div className="mt-1 border-t border-slate-200 pt-1">
              <button type="button" onClick={() => setTrashExpanded(value => !value)} className="flex h-7 w-full items-center gap-1.5 px-2 text-[10px] text-slate-500 hover:bg-slate-100">
                {trashExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                <Trash2 size={11} /> 回收站 <span className="ml-auto">{trash.length}</span>
              </button>
              {trashExpanded && trash.map(item => (
                <div key={item.id} className="group flex h-7 items-center gap-1.5 pl-6 pr-1 text-[10px] text-slate-500">
                  <File size={11} />
                  <span className="min-w-0 flex-1 truncate">{item.target_path}</span>
                  <button type="button" onClick={() => void restore(item)} title="恢复" className="flex h-6 w-6 items-center justify-center rounded opacity-0 hover:bg-white hover:text-emerald-700 group-hover:opacity-100"><ArchiveRestore size={12} /></button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
