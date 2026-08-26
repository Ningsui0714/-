import { useEffect, useState } from 'react'
import {
  Archive, Brain, Check, Compass, Edit3, HeartPulse, Network,
  RotateCcw, Save, Sparkles, Trophy, Wrench, X,
} from 'lucide-react'
import {
  archiveProfileMemory, getLearningJourney, getProfile,
  getProfileMemories, restoreProfileMemory, updateProfile,
} from '../services/api'

const kernelMeta: Record<string, { icon: any; accent: string; description: string }> = {
  structure: { icon: Network, accent: 'border-cyan-400', description: '学习位置、路径依赖、转向记录与返回线索' },
  knowledge: { icon: Brain, accent: 'border-violet-400', description: '具体知识点的理解、误解、疑问与验证状态' },
  human: { icon: HeartPulse, accent: 'border-rose-400', description: '学习节奏、偏好与近期负荷' },
  value: { icon: Compass, accent: 'border-amber-400', description: '关注方向、优先级与长期目标' },
  practice: { icon: Wrench, accent: 'border-emerald-400', description: '实践产物、辅助程度与独立证明' },
}

const modeLabels: Record<string, string> = {
  explanation: '小讲解', example: '例子', practice: '动手练习',
  project: '项目推进', reflection: '复盘',
}

export default function ProfilePage() {
  const [profileData, setProfileData] = useState<any>(null)
  const [dimensions, setDimensions] = useState<any[]>([])
  const [journey, setJourney] = useState<any>({ events: [], badges: [] })
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<any>({})
  const [busyMemory, setBusyMemory] = useState('')

  const load = async () => {
    const [profile, memories, path] = await Promise.all([
      getProfile(), getProfileMemories(), getLearningJourney(),
    ])
    setProfileData(profile)
    setDimensions(memories.dimensions || [])
    setJourney(path)
    setDraft(profile.profile || {})
  }

  useEffect(() => { load().catch(() => {}) }, [])

  const saveProfile = async () => {
    await updateProfile({
      display_name: draft.display_name,
      education_stage: draft.education_stage,
      background: draft.background,
      focus_areas: draft.focus_areas,
      weekly_hours: Number(draft.weekly_hours),
      preferred_modes: draft.preferred_modes,
      career_goal: draft.career_goal,
      career_goal_status: draft.career_goal_status,
    })
    setEditing(false)
    await load()
  }

  const toggleMemory = async (memory: any) => {
    setBusyMemory(memory.memory_id)
    try {
      if (memory.status === 'archived') await restoreProfileMemory(memory.memory_id)
      else await archiveProfileMemory(memory.memory_id, '用户在个人画像中纠正')
      const next = await getProfileMemories()
      setDimensions(next.dimensions || [])
      setJourney(await getLearningJourney())
    } finally {
      setBusyMemory('')
    }
  }

  if (!profileData) return <div className="h-full overflow-y-auto p-6 text-sm text-gray-500">正在读取个人画像...</div>
  const profile = profileData.profile

  return (
    <div className="h-full overflow-y-auto bg-gray-50">
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-indigo-600">@{profile.username}</p>
            <h1 className="mt-1 text-2xl font-semibold text-gray-950">{profile.display_name} 的学习画像</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500">这里展示 Tutor 当前会使用的记忆。自述基础不会被当作掌握证据，你也可以随时归档不准确的记忆。</p>
          </div>
          <button onClick={() => setEditing(value => !value)} className="inline-flex items-center gap-2 border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg">
            {editing ? <X size={16} /> : <Edit3 size={16} />} {editing ? '取消' : '编辑资料'}
          </button>
        </div>

        <section className="mt-6 border-y border-gray-200 bg-white px-4 py-5 sm:px-5">
          {editing ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <ProfileField label="昵称"><input className="form-input" value={draft.display_name || ''} onChange={e => setDraft({ ...draft, display_name: e.target.value })} /></ProfileField>
              <ProfileField label="每周投入"><input className="form-input" type="number" min={1} max={80} value={draft.weekly_hours || 1} onChange={e => setDraft({ ...draft, weekly_hours: Number(e.target.value) })} /></ProfileField>
              <ProfileField label="已有基础"><textarea className="form-input resize-none" rows={3} value={draft.background || ''} onChange={e => setDraft({ ...draft, background: e.target.value })} /></ProfileField>
              <ProfileField label="关注方向"><input className="form-input" value={(draft.focus_areas || []).join('，')} onChange={e => setDraft({ ...draft, focus_areas: e.target.value.split(/[，,]/).map((item: string) => item.trim()).filter(Boolean) })} /></ProfileField>
              <ProfileField label="职业理想"><input className="form-input" value={draft.career_goal || ''} onChange={e => setDraft({ ...draft, career_goal: e.target.value })} /></ProfileField>
              <ProfileField label="职业方向状态"><select className="form-input" value={draft.career_goal_status || 'exploring'} onChange={e => setDraft({ ...draft, career_goal_status: e.target.value })}><option value="exploring">探索中</option><option value="confirmed">已确定</option></select></ProfileField>
              <div className="sm:col-span-2"><button onClick={saveProfile} className="inline-flex items-center gap-2 bg-gray-950 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 rounded-lg"><Save size={15} /> 保存资料</button></div>
            </div>
          ) : (
            <div className="grid gap-5 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="学习项目" value={profileData.stats.projects} />
              <Stat label="获得 Badge" value={profileData.stats.badges} />
              <Info label="已有基础" value={profile.background || '尚未填写'} />
              <Info label="每周投入" value={`${profile.weekly_hours} 小时`} />
              <Info label="关注方向" value={(profile.focus_areas || []).join('、') || '探索中'} />
              <Info label="学习方式" value={(profile.preferred_modes || []).map((item: string) => modeLabels[item] || item).join('、') || '未设置'} />
              <Info label="职业理想" value={profile.career_goal || '探索中'} />
              <Info label="方向状态" value={profile.career_goal_status === 'confirmed' ? '已确定' : '探索中'} />
            </div>
          )}
        </section>

        <section className="mt-8">
          <div className="flex items-end justify-between gap-4">
            <div><h2 className="text-lg font-semibold text-gray-950">五维学习记忆</h2><p className="mt-1 text-sm text-gray-500">短期记忆帮助当前对话，长期记忆保持跨会话连续性。</p></div>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {dimensions.map(dimension => {
              const meta = kernelMeta[dimension.kernel] || kernelMeta.structure
              const Icon = meta.icon
              return (
                <article key={dimension.kernel} className={`border border-gray-200 border-t-4 bg-white p-4 rounded-lg ${meta.accent}`}>
                  <div className="flex items-start gap-3">
                    <Icon size={20} className="mt-0.5 text-gray-700" />
                    <div><h3 className="font-semibold text-gray-900">{dimension.label}</h3><p className="mt-0.5 text-xs leading-5 text-gray-500">{meta.description}</p></div>
                  </div>
                  <div className="mt-4 divide-y divide-gray-100">
                    {(dimension.memories || []).map((memory: any) => (
                      <div key={memory.memory_id} className={`py-3 first:pt-0 last:pb-0 ${memory.status === 'archived' ? 'opacity-45' : ''}`}>
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="text-sm font-medium text-gray-800">{memory.label}</p>
                              <span className="text-[10px] text-gray-400">{memory.scope === 'long_term' ? '长期' : '短期'}</span>
                              {memory.verification_status === 'self_reported' && <span className="border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700 rounded">自述 · 未验证</span>}
                              {memory.verification_status === 'verified' && <span className="border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700 rounded">已验证</span>}
                              {memory.verification_status === 'exposure_only' && <span className="border border-gray-200 bg-gray-50 px-1.5 py-0.5 text-[10px] text-gray-500 rounded">仅接触</span>}
                            </div>
                            <p className="mt-1 break-words text-xs leading-5 text-gray-600">{memory.summary}</p>
                            <p className="mt-1 text-[10px] text-gray-400">记忆置信度 {Math.round(memory.confidence * 100)}% · {memory.evidence_count} 条证据{memory.transient_expires_at ? ` · 有效至 ${new Date(memory.transient_expires_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}</p>
                          </div>
                          <button disabled={busyMemory === memory.memory_id} onClick={() => toggleMemory(memory)} title={memory.status === 'archived' ? '恢复记忆' : '归档错误记忆'} className="flex h-8 w-8 shrink-0 items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-800 disabled:opacity-30 rounded-lg">
                            {memory.status === 'archived' ? <RotateCcw size={15} /> : <Archive size={15} />}
                          </button>
                        </div>
                      </div>
                    ))}
                    {(dimension.memories || []).length === 0 && <p className="py-5 text-center text-xs text-gray-400">还没有形成这一维度的记忆</p>}
                  </div>
                </article>
              )
            })}
          </div>
        </section>

        <section className="mt-8 pb-10">
          <h2 className="text-lg font-semibold text-gray-950">学习路径</h2>
          <p className="mt-1 text-sm text-gray-500">重要阶段会留在时间线上；后续纠正记忆不会抹去当时获得的 Badge。</p>
          <div className="mt-5 border-l-2 border-gray-200 pl-5">
            {(journey.events || []).map((event: any) => (
              <article key={event.id} className="relative mb-5 border border-gray-200 bg-white p-4 rounded-lg last:mb-0">
                <span className={`absolute -left-[30px] top-5 flex h-4 w-4 items-center justify-center rounded-full border-2 border-white ${event.badge ? 'bg-amber-400' : 'bg-gray-400'}`} />
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 gap-3">
                    <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${event.badge ? 'bg-amber-50 text-amber-700' : 'bg-gray-100 text-gray-600'}`}>
                      {event.event_type === 'project_completed' ? <Trophy size={19} /> : <Compass size={19} />}
                    </div>
                    <div><h3 className="text-sm font-semibold text-gray-900">{event.title}</h3><p className="mt-1 text-xs leading-5 text-gray-600">{event.summary}</p></div>
                  </div>
                  <div className="text-right"><p className="text-[11px] text-gray-400">{event.occurred_at ? new Date(event.occurred_at).toLocaleDateString() : ''}</p>{event.status === 'corrected' && <span className="mt-1 inline-flex items-center gap-1 text-[10px] text-gray-500"><Check size={11} /> 已纠正</span>}</div>
                </div>
                {event.badge && <div className="mt-3 inline-flex items-center gap-2 border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs font-medium text-amber-800 rounded-lg"><Sparkles size={14} /> {event.badge.title}</div>}
              </article>
            ))}
            {(journey.events || []).length === 0 && <p className="py-6 text-sm text-gray-400">完成一个学习项目或确定职业方向后，路径会从这里开始。</p>}
          </div>
        </section>
      </div>
    </div>
  )
}

function ProfileField({ label, children }: { label: string; children: React.ReactNode }) { return <label className="text-sm font-medium text-gray-700">{label}<div className="mt-1.5">{children}</div></label> }
function Stat({ label, value }: { label: string; value: any }) { return <div><p className="text-2xl font-semibold text-gray-950">{value}</p><p className="mt-1 text-xs text-gray-500">{label}</p></div> }
function Info({ label, value }: { label: string; value: string }) { return <div className="min-w-0"><p className="text-xs text-gray-400">{label}</p><p className="mt-1 break-words font-medium text-gray-800">{value}</p></div> }
