import { useEffect, useState } from 'react'
import { Bot, Plus, Trash2, X } from 'lucide-react'
import {
  createLocalAgentProfile, deleteLocalAgentProfile, listLocalAgentProfiles,
  updateLocalAgentProfile, type LocalAgentProfile,
} from '../../services/api'

export default function LocalAgentProfilesDialog({ onClose }: { onClose: () => void }) {
  const [profiles, setProfiles] = useState<LocalAgentProfile[]>([])
  const [name, setName] = useState('Codex CLI')
  const [executable, setExecutable] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const messageOf = (value: any, fallback: string) => {
    const detail = value?.response?.data?.detail
    return typeof detail === 'string' ? detail : detail?.message || fallback
  }

  const load = async () => {
    try { setProfiles(await listLocalAgentProfiles()) }
    catch (e: any) { setError(messageOf(e, '无法载入本地 Agent 配置')) }
  }
  useEffect(() => { load() }, [])

  const add = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError('')
    try {
      await createLocalAgentProfile({
        name: name.trim(), adapter: 'codex_cli', executable_path: executable.trim() || null,
        network_policy: 'unmanaged', sandbox_policy: 'workspace_write',
      })
      setName('Codex CLI')
      setExecutable('')
      await load()
    } catch (e: any) {
      setError(messageOf(e, '配置失败'))
    } finally { setBusy(false) }
  }

  return (
    <div className="absolute inset-0 z-30 flex flex-col bg-white" data-testid="local-agent-profiles-dialog">
      <header className="flex h-14 items-center justify-between border-b border-slate-200 px-4">
        <div><p className="text-sm font-semibold text-slate-900">本地代码 Agent</p><p className="text-[10px] text-slate-500">配置是工具，不会新增第四类主 Agent</p></div>
        <button type="button" onClick={onClose} title="关闭" className="p-1 text-slate-500 hover:bg-slate-100 rounded"><X size={16} /></button>
      </header>
      <div className="flex-1 space-y-3 overflow-auto p-4">
        <div className="border border-slate-200 p-3 rounded-lg">
          <p className="text-xs font-semibold text-slate-900">新增 Codex CLI 配置</p>
          <input value={name} onChange={event => setName(event.target.value)} placeholder="配置名称" className="mt-2 w-full border border-slate-300 px-2.5 py-2 text-xs outline-none focus:border-indigo-500 rounded" />
          <input value={executable} onChange={event => setExecutable(event.target.value)} placeholder="可执行文件绝对路径（留空自动查找 codex）" className="mt-2 w-full border border-slate-300 px-2.5 py-2 text-xs outline-none focus:border-indigo-500 rounded" />
          <div className="mt-2 border border-amber-200 bg-amber-50 p-2 text-[10px] leading-4 text-amber-900 rounded">
            沙箱：workspace-write；联网：未受管。Broker 不会把“未受管”显示成“已断网”。登录复用本机 Codex CLI，不读取或保存明文凭据。
          </div>
          <button type="button" onClick={add} disabled={busy || !name.trim()} className="mt-2 flex items-center gap-1 bg-indigo-600 px-2.5 py-1.5 text-xs text-white disabled:bg-slate-300 rounded"><Plus size={12} />新增并探测</button>
        </div>

        {profiles.map(profile => (
          <div key={profile.id} className="border border-slate-200 p-3 rounded-lg">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-900"><Bot size={13} />{profile.name}</p>
                <p className="mt-1 text-[10px] text-slate-500">{profile.adapter} · 优先级 {profile.priority} · 联网 {profile.network_policy}</p>
                <p className={`mt-1 text-[10px] ${profile.last_probe?.available && profile.last_probe?.authenticated ? 'text-emerald-700' : 'text-amber-700'}`}>
                  {profile.last_probe?.available
                    ? (profile.last_probe?.authenticated ? `可用 · ${profile.last_probe?.version || ''}` : '已安装但未登录')
                    : (profile.last_probe?.message || '尚未探测')}
                </p>
              </div>
              <button type="button" onClick={async () => { await deleteLocalAgentProfile(profile.id); await load() }} title="删除配置" className="p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 rounded"><Trash2 size={13} /></button>
            </div>
            <label className="mt-2 flex items-center gap-2 text-[10px] text-slate-600">
              <input type="checkbox" checked={profile.enabled} onChange={async event => { await updateLocalAgentProfile(profile.id, { enabled: event.target.checked }); await load() }} />
              允许 Broker 确定性选择此配置
            </label>
          </div>
        ))}
        {error && <p className="border border-red-200 bg-red-50 p-2 text-[10px] text-red-700 rounded">{error}</p>}
      </div>
    </div>
  )
}
