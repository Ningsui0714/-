import { useState } from 'react'
import { ArrowLeft, ArrowRight, Check } from 'lucide-react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

const educationOptions = [
  ['middle_school', '初中'], ['high_school', '高中'], ['undergraduate', '本科'],
  ['graduate', '研究生'], ['working', '在职'], ['other', '其他'],
]
const modeOptions = [
  ['explanation', '小讲解'], ['example', '例子'], ['practice', '动手练习'],
  ['project', '项目推进'], ['reflection', '复盘'],
]

export default function RegisterPage() {
  const { user, register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({
    username: '', password: '', display_name: '', education_stage: 'undergraduate',
    background: '', focus: '', weekly_hours: 5, preferred_modes: ['explanation', 'practice', 'project'],
    career_goal: '', career_goal_status: 'exploring' as 'exploring' | 'confirmed',
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/agent" replace />

  const toggleMode = (mode: string) => setForm(current => ({
    ...current,
    preferred_modes: current.preferred_modes.includes(mode)
      ? current.preferred_modes.filter(item => item !== mode)
      : [...current.preferred_modes, mode],
  }))

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await register({
        username: form.username,
        password: form.password,
        display_name: form.display_name,
        education_stage: form.education_stage,
        background: form.background,
        focus_areas: form.focus.split(/[，,]/).map(item => item.trim()).filter(Boolean),
        weekly_hours: Number(form.weekly_hours),
        preferred_modes: form.preferred_modes,
        career_goal: form.career_goal,
        career_goal_status: form.career_goal_status,
      })
      navigate('/agent', { replace: true })
    } catch (requestError: any) {
      const detail = requestError?.response?.data?.detail
      setError(Array.isArray(detail) ? detail[0]?.msg || '请检查注册信息' : detail || '注册失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="min-h-screen bg-[#f4f6f8] px-4 py-8 sm:py-12">
      <section className="mx-auto w-full max-w-2xl border border-gray-200 bg-white p-6 shadow-sm rounded-lg sm:p-9">
        <Link to="/login" className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900"><ArrowLeft size={15} /> 返回登录</Link>
        <div className="mt-6">
          <p className="text-sm font-semibold text-indigo-600">LearnFlow</p>
          <h1 className="mt-2 text-2xl font-semibold text-gray-950">建立你的学习起点</h1>
          <p className="mt-2 text-sm leading-6 text-gray-500">这些信息帮助 Tutor 调整节奏，不会被当作掌握或实践能力证据。</p>
        </div>

        <form onSubmit={submit} className="mt-8 space-y-7">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="用户名">
              <input value={form.username} onChange={event => setForm({ ...form, username: event.target.value })} autoComplete="username" className="form-input" />
            </Field>
            <Field label="昵称">
              <input value={form.display_name} onChange={event => setForm({ ...form, display_name: event.target.value })} className="form-input" />
            </Field>
            <Field label="密码">
              <input type="password" value={form.password} onChange={event => setForm({ ...form, password: event.target.value })} autoComplete="new-password" placeholder="至少 8 位" className="form-input" />
            </Field>
            <Field label="学习阶段">
              <select value={form.education_stage} onChange={event => setForm({ ...form, education_stage: event.target.value })} className="form-input">
                {educationOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </Field>
          </div>

          <Field label="已有基础">
            <textarea value={form.background} onChange={event => setForm({ ...form, background: event.target.value })} rows={3} placeholder="例如：学过 CS61A，熟悉 Python 基础" className="form-input resize-none" />
          </Field>

          <div className="grid gap-4 sm:grid-cols-[1fr_160px]">
            <Field label="关注方向">
              <input value={form.focus} onChange={event => setForm({ ...form, focus: event.target.value })} placeholder="用逗号分隔，例如 AI，数学" className="form-input" />
            </Field>
            <Field label="每周投入（小时）">
              <input type="number" min={1} max={80} value={form.weekly_hours} onChange={event => setForm({ ...form, weekly_hours: Number(event.target.value) })} className="form-input" />
            </Field>
          </div>

          <fieldset>
            <legend className="text-sm font-medium text-gray-700">偏好的学习方式</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {modeOptions.map(([value, label]) => {
                const selected = form.preferred_modes.includes(value)
                return (
                  <button key={value} type="button" onClick={() => toggleMode(value)} className={`inline-flex items-center gap-1.5 border px-3 py-2 text-sm rounded-lg ${selected ? 'border-indigo-300 bg-indigo-50 text-indigo-700' : 'border-gray-300 bg-white text-gray-600'}`}>
                    {selected && <Check size={14} />} {label}
                  </button>
                )
              })}
            </div>
          </fieldset>

          <div className="grid gap-4 sm:grid-cols-[1fr_180px]">
            <Field label="职业理想（可选）">
              <input value={form.career_goal} onChange={event => setForm({ ...form, career_goal: event.target.value })} placeholder="例如：成为机器学习工程师" className="form-input" />
            </Field>
            <Field label="当前状态">
              <select value={form.career_goal_status} onChange={event => setForm({ ...form, career_goal_status: event.target.value as any })} className="form-input">
                <option value="exploring">探索中</option>
                <option value="confirmed">已确定</option>
              </select>
            </Field>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
          <button disabled={busy || !form.username.trim() || form.password.length < 8 || !form.display_name.trim() || !form.background.trim() || !form.focus.trim() || form.preferred_modes.length === 0} className="flex w-full items-center justify-center gap-2 bg-gray-950 px-4 py-3 text-sm font-semibold text-white hover:bg-gray-800 disabled:bg-gray-300 rounded-lg">
            {busy ? '正在建立学习空间...' : '创建账号'} {!busy && <ArrowRight size={16} />}
          </button>
        </form>
      </section>
    </main>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-sm font-medium text-gray-700">{label}<div className="mt-1.5">{children}</div></label>
}
