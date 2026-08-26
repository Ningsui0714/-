import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { getCompetitionDemoManifest, getCompetitionDemoStatus } from '../services/api'


export default function DemoEntryPage() {
  const navigate = useNavigate()
  const { enterCompetitionDemo } = useAuth()
  const [message, setMessage] = useState('正在准备离线比赛演示…')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const enter = async () => {
      try {
        const status = await getCompetitionDemoStatus()
        if (!status.enabled) throw new Error('当前未启用比赛演示模式，请运行 bash start.sh demo')
        setMessage('正在进入隔离的演示账号…')
        await enterCompetitionDemo()
        setMessage('正在定位复习与纠错演示台…')
        const manifest = await getCompetitionDemoManifest()
        if (active) {
          // The seeded demo must start from a deterministic IDE layout too.
          Object.keys(localStorage)
            .filter(key => key.startsWith('learnflow.workspace.v1.'))
            .forEach(key => localStorage.removeItem(key))
          navigate(manifest.entry_path, { replace: true })
        }
      } catch (requestError: any) {
        if (active) setError(requestError?.response?.data?.detail || requestError.message)
      }
    }
    enter()
    return () => { active = false }
  }, [])

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f4f6f8] p-6">
      <section className="w-full max-w-lg border border-gray-200 bg-white p-8 text-center shadow-sm rounded-xl">
        <div className="text-4xl">✦</div>
        <h1 className="mt-4 text-xl font-semibold text-gray-950">LearnFlow 比赛演示</h1>
        {!error ? (
          <p className="mt-3 text-sm text-gray-500">{message}</p>
        ) : (
          <div className="mt-4 bg-red-50 p-4 text-left text-sm text-red-700 rounded-lg">
            <p className="font-medium">演示模式启动失败</p>
            <p className="mt-1">{error}</p>
            <code className="mt-3 block bg-white px-3 py-2 text-xs text-gray-700 rounded">bash start.sh demo</code>
          </div>
        )}
      </section>
    </main>
  )
}
