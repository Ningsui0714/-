import { useState, useRef, useEffect } from 'react'
import { shouldSendMessageOnEnter } from '../../utils/keyboard'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

interface Props {
  projectId: number
  onRoadmapUpdate?: (roadmap: any) => void
  existingRoadmap?: any
}

export default function ChatInterface({ projectId, onRoadmapUpdate }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  // Load persisted conversation history on mount
  useEffect(() => {
    import('../../services/api').then(m =>
      m.getRoadmapHistory(projectId)
    ).then(data => {
      if (data.history && data.history.length > 0) {
        setMessages(data.history)
      }
      setLoaded(true)
    }).catch(() => setLoaded(true))
  }, [projectId])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    if (!input.trim() || loading) return
    const text = input.trim()
    setInput('')

    const userMsg: Message = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const apiModule = await import('../../services/api')
      const res = await apiModule.sendAgentMessage(projectId, {
        message: text,
        history: [...messages, userMsg],
      })
      const aiMsg: Message = { role: 'assistant', content: res.message }
      setMessages(prev => [...prev, aiMsg])
      if (res.updated_roadmap && onRoadmapUpdate) {
        onRoadmapUpdate(res.updated_roadmap)
      }
    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '❌ 请求失败，请检查后端和 API Key 配置',
      }])
    }
    setLoading(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (shouldSendMessageOnEnter(e)) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="flex flex-col h-full bg-white rounded-xl border border-gray-200">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && (
          <div className="text-center text-gray-400 py-8 text-sm">
            描述你的学习目标、当前水平，AI 将为你规划学习路线
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`
              max-w-[80%] rounded-xl px-4 py-2.5 text-sm whitespace-pre-wrap
              ${m.role === 'user'
                ? 'bg-primary-600 text-white'
                : 'bg-gray-100 text-gray-800'
              }
            `}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-xl px-4 py-2.5 text-sm text-gray-400">
              <span className="animate-pulse">思考中...</span>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-200 p-3">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
            rows={2}
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none
                       focus:outline-none focus:ring-2 focus:ring-primary-400"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="self-end bg-primary-600 text-white px-4 py-2 rounded-lg text-sm
                       hover:bg-primary-700 disabled:bg-gray-300 transition-colors"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  )
}
