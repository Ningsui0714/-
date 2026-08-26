import { useState, useEffect, useRef } from 'react'
import {
  listConcepts, listRemediationCases, generateConcepts, getConceptTask, explainConcept, submitConcept, subscribeTaskEvents, type TaskEventSubscription,
} from '../../services/api'
import RemediationPanel from './RemediationPanel'

interface Question {
  id: number
  question: string
  options: string[]
  q_type: string
  difficulty: string
  code: string
  order: number
}

const TYPE_LABEL: Record<string, string> = {
  single: '单选', multi: '多选', judge: '判断', code_output: '代码推演',
  wwpd: '代码推演', wwpp: '代码推演',
}
const DIFF_COLOR: Record<string, string> = {
  easy: 'bg-green-50 text-green-600', medium: 'bg-amber-50 text-amber-600', hard: 'bg-red-50 text-red-600',
}

export default function ConceptQuestions({ checkpointId }: { checkpointId: number }) {
  const [questions, setQuestions] = useState<Question[]>([])
  const [answers, setAnswers] = useState<Record<number, number[]>>({})
  const [submitted, setSubmitted] = useState<Record<number, boolean>>({})
  const [results, setResults] = useState<Record<number, { correct: boolean; answer_indexes: number[] }>>({})
  const [explanations, setExplanations] = useState<Record<number, string>>({})
  const [explaining, setExplaining] = useState<Record<number, boolean>>({})
  const [assisted, setAssisted] = useState<Record<number, boolean>>({})
  const [remediations, setRemediations] = useState<Record<number, any>>({})
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const esRef = useRef<TaskEventSubscription | null>(null)

  useEffect(() => {
    load()
    // Recover running generation task
    getConceptTask(checkpointId).then((snap: any) => {
      if (snap?.task_id && ['queued', 'running'].includes(snap.status)) {
        setGenerating(true)
        subscribeTask(snap.task_id)
      }
    }).catch(() => {})
    return () => { esRef.current?.close() }
  }, [checkpointId])

  const load = async () => {
    setLoading(true)
    try {
      const [data, cases] = await Promise.all([
        listConcepts(checkpointId),
        listRemediationCases(checkpointId).catch(() => []),
      ])
      setQuestions(data || [])
      const latestByQuestion: Record<number, any> = {}
      for (const item of cases || []) {
        if (item.item_type === 'concept' && !latestByQuestion[item.item_id]) {
          latestByQuestion[item.item_id] = item
        }
      }
      setRemediations(latestByQuestion)
    } catch { setQuestions([]) }
    setLoading(false)
  }

  const subscribeTask = (taskId: number) => {
    esRef.current?.close()
    esRef.current = subscribeTaskEvents(taskId, snap => {
      if (snap.progress?.message) setProgress(snap.progress.message)
      if (snap.status === 'completed') {
        setGenerating(false)
        setProgress(`✅ ${snap.progress?.message || '完成！'}`)
        esRef.current?.close()
        load()
      } else if (snap.status === 'failed') {
        setGenerating(false)
        setError(snap.error?.guidance || snap.error?.message || '生成失败')
        setProgress('❌ 生成失败')
        esRef.current?.close()
      }
    }, message => {
      setGenerating(false)
      setError(`题目状态同步失败：${message}`)
      setProgress('❌ 无法连接生成任务，请刷新后重试')
      esRef.current?.close()
    })
  }

  const handleGenerate = () => {
    setGenerating(true)
    setError('')
    setProgress('排队中...')
    generateConcepts(checkpointId)
      .then((res: any) => subscribeTask(res.task_id))
      .catch(async (e: any) => {
        // If the request response was lost after the server committed the
        // task, recover it instead of showing a misleading "Network Error".
        try {
          const snap = await getConceptTask(checkpointId)
          if (snap?.task_id && ['queued', 'running'].includes(snap.status)) {
            setGenerating(true)
            setProgress(snap.progress?.message || '生成中...')
            subscribeTask(snap.task_id)
            return
          }
        } catch { /* surface the original error below */ }
        setGenerating(false)
        setError(e?.response?.data?.detail || e.message || '生成失败')
      })
  }

  const toggleOption = (qid: number, idx: number) => {
    const q = questions.find(x => x.id === qid)
    if (!q) return
    setAnswers(prev => {
      const cur = prev[qid] || []
      if (q.q_type === 'multi') {
        return { ...prev, [qid]: cur.includes(idx) ? cur.filter(i => i !== idx) : [...cur, idx] }
      }
      return { ...prev, [qid]: [idx] }
    })
    setSubmitted(prev => ({ ...prev, [qid]: false }))
  }

  const handleSubmit = async (qid: number) => {
    const ans = answers[qid]
    if (!ans || ans.length === 0) { alert('请先选择答案'); return }
    try {
      const remediation = remediations[qid]
      const retrying = remediation?.status === 'explaining'
      const res = await submitConcept(
        checkpointId,
        qid,
        ans,
        retrying || assisted[qid] ? 'guided' : 'none',
        retrying ? remediation.id : undefined,
        retrying ? 'retry' : 'original',
      )
      setResults(prev => ({ ...prev, [qid]: { correct: res.correct, answer_indexes: res.answer_indexes } }))
      setSubmitted(prev => ({ ...prev, [qid]: true }))
      if (res.remediation) {
        setRemediations(prev => ({ ...prev, [qid]: res.remediation }))
        setAssisted(prev => ({ ...prev, [qid]: true }))
      }
    } catch (e: any) {
      alert('提交失败: ' + (e?.response?.data?.detail || e.message))
    }
  }

  const retryQuestion = (qid: number) => {
    setAnswers(prev => ({ ...prev, [qid]: [] }))
    setSubmitted(prev => ({ ...prev, [qid]: false }))
    setResults(prev => {
      const next = { ...prev }
      delete next[qid]
      return next
    })
  }

  const handleExplain = async (q: Question) => {
    setAssisted(prev => ({ ...prev, [q.id]: true }))
    setExplaining(prev => ({ ...prev, [q.id]: true }))
    try {
      const res = await explainConcept(checkpointId, q.id, answers[q.id] || [])
      setExplanations(prev => ({ ...prev, [q.id]: res.explanation || res.base_explanation || '（无解析）' }))
    } catch (e: any) {
      setExplanations(prev => ({ ...prev, [q.id]: '❌ 解析失败: ' + (e?.response?.data?.detail || e.message) }))
    }
    setExplaining(prev => ({ ...prev, [q.id]: false }))
  }

  if (loading) return <div className="p-8 text-gray-400 text-center text-sm">加载中...</div>

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200 bg-white shrink-0">
        <div>
          <h2 className="font-semibold text-gray-900">🧠 概念考察题</h2>
          <p className="text-xs text-gray-400 mt-0.5">围绕本关目标检查理解、辨析与迁移</p>
        </div>
        {!generating && (
          <button
            onClick={handleGenerate}
            className="bg-primary-600 text-white px-4 py-1.5 rounded-lg text-sm hover:bg-primary-700 transition-colors"
          >
            🎲 生成概念题
          </button>
        )}
        {generating && (
          <span className="text-sm text-primary-600 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-primary-400 animate-pulse" />
            {progress || '生成中...'}
          </span>
        )}
      </div>

      {error && <div className="px-6 py-2 text-sm bg-red-50 text-red-700 border-b border-red-200">{error}</div>}

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl mx-auto space-y-4">
          {questions.length === 0 && !generating && (
            <div className="text-center text-gray-400 py-16">
              <p className="text-4xl mb-3">🧠</p>
              <p className="text-sm">还没有概念题，点击「🎲 生成概念题」</p>
            </div>
          )}

          {questions.map(q => (
            <div key={q.id} className="bg-white border border-gray-200 rounded-xl p-5">
              {/* Header */}
              <div className="flex items-center gap-2 mb-3">
                <span className="text-[10px] bg-primary-50 text-primary-700 px-2 py-0.5 rounded-full">
                  {TYPE_LABEL[q.q_type] || q.q_type}
                </span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full ${DIFF_COLOR[q.difficulty] || 'bg-gray-100 text-gray-500'}`}>
                  {q.difficulty}
                </span>
              </div>

              {/* Question */}
              <div className="text-sm text-gray-800 leading-relaxed mb-4 whitespace-pre-wrap">{q.question}</div>

              {/* Options */}
              <div className="space-y-2">
                {q.options.map((opt, idx) => {
                  const selected = (answers[q.id] || []).includes(idx)
                  const result = results[q.id]
                  const isRight = result?.answer_indexes?.includes(idx)
                  const isWrongPick = submitted[q.id] && selected && !isRight
                  return (
                    <label key={idx}
                      className={`flex items-start gap-2 p-2.5 rounded-lg border cursor-pointer text-sm transition-colors ${
                        submitted[q.id] && isRight
                          ? 'border-green-400 bg-green-50'
                          : isWrongPick
                            ? 'border-red-300 bg-red-50'
                            : selected
                              ? 'border-primary-400 bg-primary-50'
                              : 'border-gray-200 hover:bg-gray-50'
                      }`}>
                      <input
                        type={q.q_type === 'multi' ? 'checkbox' : 'radio'}
                        checked={selected}
                        onChange={() => toggleOption(q.id, idx)}
                        disabled={submitted[q.id]}
                        className="mt-0.5 accent-primary-600"
                      />
                      <span className="text-gray-700">{opt}</span>
                      {submitted[q.id] && isRight && <span className="ml-auto text-green-600">✓</span>}
                      {isWrongPick && <span className="ml-auto text-red-500">✗</span>}
                    </label>
                  )
                })}
              </div>

              {/* Result banner */}
              {submitted[q.id] && results[q.id] && (
                <div className={`mt-3 rounded-lg px-3 py-2 text-sm font-medium ${
                  results[q.id].correct ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                }`}>
                  {results[q.id].correct ? '✅ 回答正确！' : '❌ 回答错误，绿色为正确答案'}
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center gap-2 mt-4">
                <button
                  onClick={() => handleSubmit(q.id)}
                  disabled={submitted[q.id] || remediations[q.id]?.status === 'variant_ready'}
                  className="bg-gray-900 text-white px-4 py-1.5 rounded-lg text-xs hover:bg-gray-700 disabled:opacity-40 transition-colors"
                >
                  {remediations[q.id]?.status === 'variant_ready'
                    ? '请先完成变式'
                    : submitted[q.id]
                      ? (results[q.id]?.correct ? '✓ 已答对' : '已提交') : '提交答案'}
                </button>
                <button
                  onClick={() => handleExplain(q)}
                  disabled={explaining[q.id]}
                  className="bg-primary-50 text-primary-700 px-4 py-1.5 rounded-lg text-xs hover:bg-primary-100 disabled:opacity-50 transition-colors"
                >
                  {explaining[q.id] ? '解析中...' : '🤖 AI 解析'}
                </button>
              </div>

              {/* Explanation */}
              {explanations[q.id] && (
                <div className="mt-3 bg-primary-50/50 border border-primary-100 rounded-lg p-3 text-xs text-gray-700 whitespace-pre-wrap">
                  {explanations[q.id]}
                </div>
              )}

              {remediations[q.id] && (
                <div className="mt-3">
                  <RemediationPanel
                    remediation={remediations[q.id]}
                    onChange={next => setRemediations(prev => ({ ...prev, [q.id]: next }))}
                    onRetry={() => retryQuestion(q.id)}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
