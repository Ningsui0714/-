import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../services/api'

interface Settings {
  llm_api_key: string
  llm_base_url: string
  llm_model: string
  embedding_backend: string
  embedding_model: string
  embedding_base_url: string
  vision_api_key: string
  vision_base_url: string
  vision_model: string
  vision_api_enhance: boolean
  has_key: boolean
}

export default function SettingsPage() {
  const navigate = useNavigate()

  const [settings, setSettings] = useState<Settings | null>(null)
  const [editKey, setEditKey] = useState('')
  const [editUrl, setEditUrl] = useState('')
  const [editModel, setEditModel] = useState('')
  const [editEmbBackend, setEditEmbBackend] = useState('local')
  const [editEmbModel, setEditEmbModel] = useState('')
  const [editEmbKey, setEditEmbKey] = useState('')
  const [editEmbUrl, setEditEmbUrl] = useState('')
  const [editVisionKey, setEditVisionKey] = useState('')
  const [editVisionUrl, setEditVisionUrl] = useState('')
  const [editVisionModel, setEditVisionModel] = useState('')
  const [editVisionEnhance, setEditVisionEnhance] = useState(false)
  const [visionTesting, setVisionTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ type: 'ok' | 'error' | ''; msg: string }>({ type: '', msg: '' })
  const [saveMsg, setSaveMsg] = useState('')
  const [projects, setProjects] = useState<any[]>([])
  const [indexingProject, setIndexingProject] = useState<number | null>(null)
  const [indexingAll, setIndexingAll] = useState(false)
  const [showKey, setShowKey] = useState(false)

  useEffect(() => { loadSettings(); loadProjects() }, [])

  const loadSettings = async () => {
    try {
      const res = await api.get('/settings')
      const s: Settings = res.data
      setSettings(s)
      setEditUrl(s.llm_base_url)
      setEditModel(s.llm_model)
      setEditEmbBackend(s.embedding_backend)
      setEditEmbModel(s.embedding_model)
      setEditEmbUrl(s.embedding_base_url || '')
      setEditVisionUrl(s.vision_base_url)
      setEditVisionModel(s.vision_model)
      setEditVisionEnhance(!!s.vision_api_enhance)
    } catch { /* ignore */ }
  }

  const loadProjects = async () => {
    try {
      const res = await api.get('/projects')
      // Get chunk counts for each project
      const withCounts = await Promise.all(res.data.map(async (p: any) => {
        try {
          const c = await api.get(`/projects/${p.id}/chunks`)
          return { ...p, chunks_count: c.data.length }
        } catch { return { ...p, chunks_count: 0 } }
      }))
      setProjects(withCounts)
    } catch { /* ignore */ }
  }

  const handleReindex = async (projectId: number, name: string) => {
    setIndexingProject(projectId)
    setTestResult({ type: '', msg: `正在索引「${name}」的切片...` })
    try {
      const res = await api.post(`/projects/${projectId}/embeddings/index`)
      setTestResult({ type: 'ok', msg: `✅ 「${name}」索引完成: ${res.data.indexed} 个切片` })
    } catch (e: any) {
      setTestResult({ type: 'error', msg: `❌ 索引失败: ${e?.response?.data?.detail || e.message}` })
    }
    setIndexingProject(null)
  }

  const handleReindexAll = async () => {
    setIndexingAll(true)
    for (const p of projects) {
      await handleReindex(p.id, p.name)
    }
    setIndexingAll(false)
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveMsg('')
    try {
      const body: any = {
        llm_base_url: editUrl,
        llm_model: editModel,
        embedding_backend: editEmbBackend,
        embedding_model: editEmbModel,
        embedding_base_url: editEmbUrl,
        vision_base_url: editVisionUrl,
        vision_model: editVisionModel,
        vision_api_enhance: editVisionEnhance,
      }
      if (editKey.trim()) body.llm_api_key = editKey.trim()
      if (editEmbKey.trim()) body.embedding_api_key = editEmbKey.trim()
      if (editVisionKey.trim()) body.vision_api_key = editVisionKey.trim()

      const res = await api.put('/settings', body)
      const keySaved = res.data.updated.includes('LLM_API_KEY')
      setSaveMsg(`✅ 已保存: ${res.data.updated.join(', ')}${keySaved ? '；API Key 已保存，输入框已清空以保护密钥' : ''}`)
      await loadSettings()
      setEditKey('')
      setShowKey(false)
    } catch (e: any) {
      setSaveMsg('❌ 保存失败: ' + (e?.response?.data?.detail || e.message))
    }
    setSaving(false)
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult({ type: '', msg: '' })
    try {
      const res = await api.post('/settings/test', {
        api_key: editKey.trim() || 'use_current',
        base_url: editUrl,
        model: editModel,
      })
      setTestResult({ type: 'ok', msg: `✅ 连接成功！模型: ${res.data.model}` })
    } catch (e: any) {
      const detail = e?.response?.data?.detail || e.message
      setTestResult({ type: 'error', msg: `❌ ${detail}` })
    }
    setTesting(false)
  }

  const handleTestEmbedding = async () => {
    if (editEmbBackend !== 'api') {
      setTestResult({ type: 'ok', msg: 'Local 后端无需测试' })
      return
    }
    setTesting(true)
    setTestResult({ type: '', msg: '' })
    try {
      // Use embedding-specific credentials; fallback to LLM if empty
      const testKey = editEmbKey || editKey || 'use_current'
      const testUrl = editEmbUrl || editUrl
      const res = await api.post('/settings/test-embedding', {
        api_key: testKey,
        base_url: testUrl,
        model: editEmbModel,
      })
      setTestResult({ type: 'ok', msg: `✅ Embedding 可用，维度: ${res.data.dimensions}` })
    } catch (e: any) {
      setTestResult({ type: 'error', msg: `❌ ${e?.response?.data?.detail || e.message}` })
    }
    setTesting(false)
  }

  const handleTestVision = async () => {
    setVisionTesting(true)
    setTestResult({ type: '', msg: '' })
    try {
      const res = await api.post('/settings/test-vision', {
        api_key: editVisionKey || 'use_current',
        base_url: editVisionUrl,
        model: editVisionModel,
      })
      setTestResult({ type: 'ok', msg: `✅ 图片理解可用！模型: ${res.data.model} — ${res.data.message}` })
    } catch (e: any) {
      setTestResult({ type: 'error', msg: `❌ ${e?.response?.data?.detail || e.message}` })
    }
    setVisionTesting(false)
  }

  if (!settings) return <div className="p-8 text-gray-400">加载中...</div>

  return (
    <div className="h-full overflow-y-auto p-8">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <button onClick={() => navigate('/')} className="text-sm text-gray-400 hover:text-gray-600 mb-4">
          ← 返回首页
        </button>
        <h1 className="text-2xl font-bold text-gray-900 mb-1">⚙️ 模型设置</h1>
        <p className="text-sm text-gray-500 mb-8">当前未接入模型时，Tutor 只会显示“未接入模型。”</p>

        {/* Status card */}
        <div className={`rounded-xl border p-5 mb-6 ${settings.has_key
          ? 'bg-green-50 border-green-200'
          : 'bg-yellow-50 border-yellow-200'
        }`}>
          <div className="flex items-center gap-3">
            <span className={`w-3 h-3 rounded-full ${settings.has_key ? 'bg-green-500' : 'bg-yellow-500'}`} />
            <div>
              <p className="font-medium text-sm text-gray-900">
                {settings.has_key ? 'API Key 已配置' : 'API Key 未配置'}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">
                {settings.has_key
                  ? '路线规划、讲义生成、代码审阅等功能可用；保存后输入框清空属于正常的安全处理'
                  : '请配置 API Key 后使用 AI 功能。支持 DeepSeek、OpenAI 等兼容接口'
                }
              </p>
            </div>
          </div>
        </div>

        {/* LLM Settings */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
          <h2 className="font-semibold text-gray-900 mb-4">🤖 AI 模型</h2>

          <div className="space-y-4">
            {/* API Key */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                API Key
                <span className="text-gray-400 font-normal ml-2">必填</span>
              </label>
              <div className="flex gap-2">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={editKey}
                  onChange={e => setEditKey(e.target.value)}
                  placeholder={settings.has_key ? '输入新 Key 替换当前配置' : 'sk-...'}
                  className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm
                             focus:outline-none focus:ring-2 focus:ring-primary-400 font-mono"
                />
                <button onClick={() => setShowKey(!showKey)}
                  className="text-xs text-gray-500 px-2 hover:text-gray-700">
                  {showKey ? '隐藏' : '显示'}
                </button>
              </div>
              {settings.has_key && (
                <p className="text-xs text-gray-400 mt-1">
                  当前 Key: {settings.llm_api_key}（输入新值替换，留空保留现有）
                </p>
              )}
            </div>

            {/* Base URL */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Base URL
                <span className="text-gray-400 font-normal ml-2">推荐使用 DeepSeek</span>
              </label>
              <input
                type="text" value={editUrl}
                onChange={e => setEditUrl(e.target.value)}
                placeholder="https://api.deepseek.com"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-primary-400"
              />
              <div className="flex gap-2 mt-1.5">
                <button onClick={() => setEditUrl('https://api.deepseek.com')}
                  className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                  DeepSeek V4
                </button>
                <button onClick={() => setEditUrl('https://api.openai.com/v1')}
                  className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                  OpenAI
                </button>
                <button onClick={() => setEditUrl('https://api.moonshot.cn/v1')}
                  className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                  Kimi
                </button>
              </div>
            </div>

            {/* Model */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                模型名称
                <span className="text-gray-400 font-normal ml-2">根据 API 提供商填写</span>
              </label>
              <input
                type="text" value={editModel}
                onChange={e => setEditModel(e.target.value)}
                placeholder="deepseek-v4-flash / gpt-4o-mini / moonshot-v1-8k"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-primary-400"
              />
              <div className="flex gap-2 mt-1.5">
                <button onClick={() => setEditModel('deepseek-v4-flash')}
                  className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                  DeepSeek V4 Flash
                </button>
                <button onClick={() => setEditModel('gpt-4o-mini')}
                  className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                  GPT-4o-mini
                </button>
                <button onClick={() => setEditModel('moonshot-v1-8k')}
                  className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                  Kimi K3
                </button>
              </div>
            </div>

            {/* Test + Save */}
            <div className="flex gap-3 pt-2">
              <button onClick={handleTest} disabled={testing || !editUrl}
                className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg text-sm
                           hover:bg-gray-200 disabled:opacity-50 transition-colors">
                {testing ? '测试中...' : '🔌 测试连接'}
              </button>
              <button onClick={handleSave} disabled={saving}
                className="bg-primary-600 text-white px-5 py-2 rounded-lg text-sm
                           hover:bg-primary-700 disabled:bg-gray-300 transition-colors">
                {saving ? '保存中...' : '💾 保存设置'}
              </button>
            </div>
          </div>
        </div>

        {/* Vision Settings (T6: image understanding) */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
          <h2 className="font-semibold text-gray-900 mb-1">🖼 图片理解 (Vision)</h2>
          <p className="text-xs text-gray-500 mb-4">
            仓库图片描述默认走<b>免费管线</b>：md 上下文 + 本地 OCR (Apple Vision) + SVG 结构解析，零成本。
            只有标记为「纯图形/照片」的图片可选地走付费 API 理解（kimi），幂等可随时切换。
          </p>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Vision API Key
                <span className="text-gray-400 font-normal ml-2">可选，留空复用 LLM Key</span>
              </label>
              <input
                type="password"
                value={editVisionKey}
                onChange={e => setEditVisionKey(e.target.value)}
                placeholder={settings.vision_api_key ? `当前: ${settings.vision_api_key}（输入新值替换）` : 'sk-...'}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-primary-400 font-mono"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Base URL</label>
              <input
                type="text" value={editVisionUrl}
                onChange={e => setEditVisionUrl(e.target.value)}
                placeholder="https://api.moonshot.cn/v1"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-primary-400"
              />
              <div className="flex gap-2 mt-1.5">
                <button onClick={() => setEditVisionUrl('https://api.moonshot.cn/v1')}
                  className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                  Moonshot
                </button>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">视觉模型</label>
              <input
                type="text" value={editVisionModel}
                onChange={e => setEditVisionModel(e.target.value)}
                placeholder="kimi-k2.7-code-highspeed"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-primary-400"
              />
              <div className="flex gap-2 mt-1.5">
                <button onClick={() => setEditVisionModel('kimi-k2.7-code-highspeed')}
                  className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                  🚀 最快 (~4s/张)
                </button>
                <button onClick={() => setEditVisionModel('kimi-k3')}
                  className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                  Kimi K3 (~16s/张)
                </button>
                <button onClick={() => setEditVisionModel('kimi-k2.6')}
                  className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                  Kimi K2.6 (~106s/张)
                </button>
              </div>
            </div>

            <div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={editVisionEnhance}
                  onChange={e => setEditVisionEnhance(e.target.checked)}
                  className="w-4 h-4 accent-primary-600"
                />
                <span className="text-sm font-medium text-gray-700">允许付费 API 图片增强</span>
                <span className="text-xs text-gray-400 font-normal">仅处理免费管线无法理解的纯图形/照片（kimi，~4s/张，可随时关闭，已处理结果保留）</span>
              </label>
            </div>

            <div className="flex gap-3 pt-2">
              <button onClick={handleTestVision} disabled={visionTesting || !editVisionModel}
                className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg text-sm
                           hover:bg-gray-200 disabled:opacity-50 transition-colors">
                {visionTesting ? '测试中...' : '🔌 测试图片理解'}
              </button>
            </div>
          </div>
        </div>

        {/* Embedding Settings */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
          <h2 className="font-semibold text-gray-900 mb-4">🧠 向量嵌入</h2>
          <p className="text-xs text-gray-500 mb-4">
            用于讲义生成时的切片检索。Local 模式使用本地 gte-small 模型（免费离线），
            API 模式使用外部嵌入服务（质量更高）。
          </p>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">后端类型</label>
              <div className="flex gap-3">
                <label className={`flex-1 border-2 rounded-xl p-3 cursor-pointer transition-all ${
                  editEmbBackend === 'local'
                    ? 'border-primary-500 bg-primary-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}>
                  <input type="radio" name="emb" value="local" checked={editEmbBackend === 'local'}
                    onChange={() => setEditEmbBackend('local')} className="sr-only" />
                  <p className="font-medium text-sm text-gray-900">Local</p>
                  <p className="text-xs text-gray-500 mt-1">gte-small · 384维<br/>免费离线</p>
                </label>
                <label className={`flex-1 border-2 rounded-xl p-3 cursor-pointer transition-all ${
                  editEmbBackend === 'api'
                    ? 'border-primary-500 bg-primary-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}>
                  <input type="radio" name="emb" value="api" checked={editEmbBackend === 'api'}
                    onChange={() => setEditEmbBackend('api')} className="sr-only" />
                  <p className="font-medium text-sm text-gray-900">API</p>
                  <p className="text-xs text-gray-500 mt-1">外部服务 · 维度可配<br/>质量更高</p>
                </label>
              </div>
            </div>

            {editEmbBackend === 'api' && (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Embedding API Key
                    <span className="text-gray-400 font-normal ml-2">留空则复用 LLM Key</span>
                  </label>
                  <input
                    type="password"
                    value={editEmbKey}
                    onChange={e => setEditEmbKey(e.target.value)}
                    placeholder="留空复用 LLM API Key"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                               focus:outline-none focus:ring-2 focus:ring-primary-400 font-mono"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Embedding Base URL
                    <span className="text-gray-400 font-normal ml-2">留空则复用 LLM URL</span>
                  </label>
                  <input
                    type="text" value={editEmbUrl}
                    onChange={e => setEditEmbUrl(e.target.value)}
                    placeholder="留空复用 LLM Base URL"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                               focus:outline-none focus:ring-2 focus:ring-primary-400"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Embedding 模型名
                  </label>
                  <input
                    type="text" value={editEmbModel}
                    onChange={e => setEditEmbModel(e.target.value)}
                    placeholder="text-embedding-ada-002 / deepseek-embedding"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                               focus:outline-none focus:ring-2 focus:ring-primary-400"
                  />
                  <div className="flex gap-2 mt-1.5">
                    <button onClick={() => setEditEmbModel('text-embedding-ada-002')}
                      className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                      OpenAI ada-002
                    </button>
                    <button onClick={() => setEditEmbModel('deepseek-embedding')}
                      className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-200">
                      DeepSeek Embedding
                    </button>
                  </div>
                </div>
              </div>
            )}

            <div className="flex gap-3">
              <button onClick={handleTestEmbedding} disabled={testing}
                className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg text-sm
                           hover:bg-gray-200 disabled:opacity-50 transition-colors">
                {testing ? '测试中...' : '🧪 测试嵌入'}
              </button>
            </div>
          </div>
        </div>

        {/* Test Result */}
        {testResult.msg && (
          <div className={`rounded-xl border p-4 mb-6 ${
            testResult.type === 'ok' ? 'bg-green-50 border-green-200 text-green-800'
            : testResult.type === 'error' ? 'bg-red-50 border-red-200 text-red-800'
            : 'bg-gray-50 border-gray-200'
          }`}>
            <p className="text-sm">{testResult.msg}</p>
          </div>
        )}

        {/* Re-index */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
          <h2 className="font-semibold text-gray-900 mb-4">🗂️ 向量索引</h2>
          <p className="text-xs text-gray-500 mb-3">
            更换 Embedding 后端或模型后，需要重新索引切片使新向量生效。
          </p>
          {projects.map(p => (
            <div key={p.id} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
              <div>
                <p className="text-sm text-gray-800">{p.name}</p>
                <p className="text-xs text-gray-400">{p.chunks_count || '?'} 个切片</p>
              </div>
              <button
                onClick={() => handleReindex(p.id, p.name)}
                disabled={indexingProject === p.id}
                className="bg-gray-100 text-gray-700 px-3 py-1.5 rounded text-xs
                           hover:bg-gray-200 disabled:opacity-50 transition-colors"
              >
                {indexingProject === p.id ? '索引中...' : '🔄 索引'}
              </button>
            </div>
          ))}
          {projects.length === 0 && (
            <p className="text-xs text-gray-400">暂无项目</p>
          )}
          {projects.length > 1 && (
            <button onClick={handleReindexAll} disabled={indexingProject !== null}
              className="mt-3 w-full text-xs bg-primary-50 text-primary-700 py-2 rounded-lg
                         hover:bg-primary-100 disabled:opacity-50 transition-colors"
            >
              {indexingAll ? '索引中...' : '🔄 全部重新索引'}
            </button>
          )}
        </div>

        {/* Save message */}
        {saveMsg && (
          <div className={`rounded-xl border p-4 mb-6 ${
            saveMsg.startsWith('✅') ? 'bg-green-50 border-green-200 text-green-800'
            : 'bg-red-50 border-red-200 text-red-800'
          }`}>
            <p className="text-sm">{saveMsg}</p>
          </div>
        )}
      </div>
    </div>
  )
}
