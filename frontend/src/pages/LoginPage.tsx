import { useEffect, useState } from 'react'
import { ArrowRight, FlaskConical, X } from 'lucide-react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { listDevAccounts } from '../services/api'

interface DevAccount {
  id: number
  username: string
  display_name: string
  created_at?: string
  last_login_at?: string
  project_count: number
  is_legacy_demo: boolean
}

export default function LoginPage() {
  const { user, login, enterDevAccount } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [devOpen, setDevOpen] = useState(false)
  const [accounts, setAccounts] = useState<DevAccount[]>([])
  const [devAvailable, setDevAvailable] = useState(true)
  const [devLoading, setDevLoading] = useState(false)
  const [devLoadError, setDevLoadError] = useState('')

  const loadDevAccounts = async () => {
    setDevLoading(true)
    setDevLoadError('')
    try {
      setAccounts(await listDevAccounts())
    } catch (requestError: any) {
      if (requestError?.response?.status === 404) {
        setDevAvailable(false)
      } else {
        setDevLoadError(requestError?.response?.data?.detail || '开发账号列表加载失败，请点击重试')
      }
    } finally {
      setDevLoading(false)
    }
  }

  useEffect(() => { void loadDevAccounts() }, [])

  if (user) return <Navigate to="/agent" replace />

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(username, password)
      const from = (location.state as any)?.from
      navigate(from && from !== '/login' ? from : '/agent', { replace: true })
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || '登录失败，请检查用户名和密码')
    } finally {
      setBusy(false)
    }
  }

  const enterAccount = async (accountId: number) => {
    setBusy(true)
    setError('')
    try {
      await enterDevAccount(accountId)
      navigate('/agent', { replace: true })
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || '开发测试账号进入失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center bg-[#f4f6f8] px-4 py-12">
      {devAvailable && (
        <button
          type="button"
          onClick={() => { setDevOpen(true); void loadDevAccounts() }}
          className="absolute right-4 top-4 inline-flex items-center gap-2 border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 rounded-lg"
        >
          <FlaskConical size={16} /> 开发测试
        </button>
      )}

      <section className="w-full max-w-md border border-gray-200 bg-white p-7 shadow-sm rounded-lg sm:p-9">
        <div className="mb-8">
          <Link to="/login" className="inline-flex items-center gap-2 text-2xl font-bold text-indigo-600">
            <span aria-hidden className="text-3xl">✦</span> LearnFlow
          </Link>
          <h1 className="mt-7 text-2xl font-semibold text-gray-950">继续你的学习</h1>
          <p className="mt-2 text-sm text-gray-500">对话、项目和学习画像只属于当前账号。</p>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <label className="block text-sm font-medium text-gray-700">
            用户名
            <input
              value={username}
              onChange={event => setUsername(event.target.value)}
              autoComplete="username"
              className="mt-1.5 w-full border border-gray-300 px-3 py-2.5 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 rounded-lg"
            />
          </label>
          <label className="block text-sm font-medium text-gray-700">
            密码
            <input
              type="password"
              value={password}
              onChange={event => setPassword(event.target.value)}
              autoComplete="current-password"
              className="mt-1.5 w-full border border-gray-300 px-3 py-2.5 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 rounded-lg"
            />
          </label>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            disabled={busy || !username.trim() || !password}
            className="flex w-full items-center justify-center gap-2 bg-gray-950 px-4 py-2.5 text-sm font-semibold text-white hover:bg-gray-800 disabled:bg-gray-300 rounded-lg"
          >
            登录 <ArrowRight size={16} />
          </button>
        </form>
        <p className="mt-6 text-center text-sm text-gray-500">
          第一次来？ <Link to="/register" className="font-medium text-indigo-600 hover:text-indigo-700">创建账号</Link>
        </p>
      </section>

      {devOpen && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/20" role="dialog" aria-modal="true">
          <button className="flex-1 cursor-default" aria-label="关闭开发测试" onClick={() => setDevOpen(false)} />
          <aside className="h-full w-full max-w-md overflow-y-auto border-l border-gray-200 bg-white p-5 shadow-xl">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-gray-950">开发测试</h2>
                <p className="mt-1 text-xs text-gray-500">无需输入密码，点击账号卡片直接进入；学习数据不会合并。</p>
              </div>
              <button onClick={() => setDevOpen(false)} title="关闭" className="flex h-9 w-9 items-center justify-center text-gray-500 hover:bg-gray-100 rounded-lg"><X size={18} /></button>
            </div>
            {error && <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
            {devLoadError && (
              <div className="mt-4 flex items-center justify-between gap-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                <span>{devLoadError}</span>
                <button type="button" onClick={() => void loadDevAccounts()} className="shrink-0 font-medium underline">重试</button>
              </div>
            )}
            <div className="mt-6 space-y-2">
              {devLoading && <p className="py-10 text-center text-sm text-gray-400">正在读取开发账号…</p>}
              {!devLoading && accounts.map(account => (
                <button
                  key={account.id}
                  type="button"
                  disabled={busy}
                  onClick={() => enterAccount(account.id)}
                  className="w-full border border-gray-200 p-3 text-left hover:border-indigo-300 hover:bg-indigo-50 disabled:opacity-60 rounded-lg"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-gray-900">{account.display_name}</span>
                    <span className="text-xs text-gray-500">{account.project_count} 个项目</span>
                  </div>
                  <p className="mt-1 text-xs text-gray-500">@{account.username}</p>
                  <p className="mt-2 text-[11px] text-gray-400">
                    最近登录 {account.last_login_at ? new Date(account.last_login_at).toLocaleString() : '尚未登录'}
                  </p>
                </button>
              ))}
              {!devLoading && !devLoadError && accounts.length === 0 && <p className="py-10 text-center text-sm text-gray-400">暂无测试账号</p>}
            </div>
          </aside>
        </div>
      )}
    </main>
  )
}
