import { BookOpen, GitBranch, MessageSquareText } from 'lucide-react'
import { useWorkspace, useWorkspaceTitle } from '../components/workspace/WorkspaceContext'

export default function AgentPage() {
  const { openPath } = useWorkspace()
  useWorkspaceTitle('学习工作台', { kind: 'home' })

  return (
    <div className="h-full overflow-y-auto bg-slate-50 p-6 sm:p-10">
      <div className="mx-auto max-w-4xl">
        <span className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-800">
          <MessageSquareText size={14} />
          主 Agent 对话位于右侧
        </span>
        <h1 className="mt-5 text-3xl font-bold tracking-tight text-slate-950">从目标开始，把学习推进到可验证结果</h1>
        <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-600">
          右侧是主 Agent 的独立全局会话；进入项目、讲义或练习后，它会按当前操作切换到相应 Agent。主编辑区只承载学习内容与工具，不复制对话上下文。
        </p>

        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => openPath('/projects', { title: '学习项目', kind: 'projects' })}
            className="group rounded-xl border border-slate-200 bg-white p-5 text-left shadow-sm hover:border-emerald-300 hover:shadow-md"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-100 text-emerald-800"><BookOpen size={19} /></span>
            <strong className="mt-4 block text-sm text-slate-900">打开学习项目</strong>
            <span className="mt-1 block text-xs leading-5 text-slate-500">管理来源、路线、讲义、练习与纠错闭环。</span>
          </button>
          <button
            type="button"
            onClick={() => openPath('/memory', { title: '五核记忆', kind: 'memory' })}
            className="group rounded-xl border border-slate-200 bg-white p-5 text-left shadow-sm hover:border-indigo-300 hover:shadow-md"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-100 text-indigo-800"><GitBranch size={19} /></span>
            <strong className="mt-4 block text-sm text-slate-900">检查五核证据</strong>
            <span className="mt-1 block text-xs leading-5 text-slate-500">查看事实、事件和短期记忆如何支撑当前判断。</span>
          </button>
        </div>
      </div>
    </div>
  )
}
