import { useEffect, useState } from 'react'
import {
  changeRemediationExplanation,
  createRemediationVariant,
  submitRemediationVariant,
} from '../../services/api'


const MODE_LABELS: Record<string, string> = {
  contrast: '证据对照',
  execution_trace: '执行追踪',
  step_by_step: '分步拆解',
  worked_example: '示例迁移',
}


interface Props {
  remediation: any
  onChange: (next: any) => void
  onRetry: () => void
}


export default function RemediationPanel({ remediation, onChange, onRetry }: Props) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [variantAnswers, setVariantAnswers] = useState<number[]>([])
  const [variantText, setVariantText] = useState('')
  const [variantResult, setVariantResult] = useState<any>(null)

  useEffect(() => {
    setVariantAnswers([])
    setVariantText('')
    setVariantResult(null)
  }, [remediation?.id])

  if (!remediation) return null
  const explanation = remediation.explanation || {}
  const sections = Array.isArray(explanation.sections) ? explanation.sections : []
  const variant = remediation.variant || {}
  const completed = remediation.status === 'completed'

  const requestMode = async (action: 'switch' | 'steps' | 'example') => {
    setBusy(action)
    setError('')
    try {
      onChange(await changeRemediationExplanation(remediation.id, action))
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message)
    } finally {
      setBusy('')
    }
  }

  const prepareVariant = async () => {
    setBusy('variant')
    setError('')
    try {
      onChange(await createRemediationVariant(remediation.id))
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message)
    } finally {
      setBusy('')
    }
  }

  const toggleVariantOption = (index: number) => {
    if (variant.multiple) {
      setVariantAnswers(current => current.includes(index)
        ? current.filter(item => item !== index)
        : [...current, index])
    } else {
      setVariantAnswers([index])
    }
  }

  const evaluateVariant = async () => {
    setBusy('variant-submit')
    setError('')
    try {
      const response = await submitRemediationVariant(remediation.id, variant.type === 'concept_choice'
        ? { answer_indexes: variantAnswers }
        : { answer_text: variantText })
      setVariantResult(response.result)
      onChange(response.remediation)
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || requestError.message)
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="border border-amber-200 bg-amber-50/70 p-3 text-gray-800 rounded-xl">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-base">🧭</span>
            <h3 className="text-sm font-semibold">显式纠错闭环</h3>
            <span className={`px-2 py-0.5 text-[10px] rounded-full ${
              completed ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-800'
            }`}>
              {completed ? '证据已回写' : remediation.status === 'variant_ready' ? '等待变式验证' : '正在纠错'}
            </span>
          </div>
          <p className="mt-1 text-[11px] text-gray-500">
            {remediation.misconception_tag} · 策略由确定性规则选择，不由模型决定
          </p>
        </div>
        <span className="shrink-0 text-[10px] text-gray-400">#{remediation.id}</span>
      </div>

      <div className="mt-3 border border-amber-100 bg-white p-3 rounded-lg">
        <div className="flex items-center justify-between gap-2">
          <strong className="text-xs">{explanation.delivery_mode_label || MODE_LABELS[remediation.current_delivery_mode]}</strong>
          <span className="text-[10px] text-gray-400">{remediation.strategy?.reason_code}</span>
        </div>
        <div className="mt-2 space-y-2">
          {sections.map((section: any, index: number) => (
            <div key={`${section.title}-${index}`} className="text-xs">
              <div className="font-medium text-gray-700">{section.title}</div>
              <p className="mt-0.5 whitespace-pre-wrap leading-relaxed text-gray-600">{section.content}</p>
            </div>
          ))}
        </div>
      </div>

      {!completed && remediation.status !== 'variant_ready' && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button onClick={() => requestMode('switch')} disabled={!!busy}
            className="border border-amber-300 bg-white px-3 py-1.5 text-xs text-amber-800 hover:bg-amber-100 disabled:opacity-50 rounded-lg">
            {busy === 'switch' ? '切换中...' : '换种讲法'}
          </button>
          <button onClick={() => requestMode('steps')} disabled={!!busy}
            className="border border-gray-200 bg-white px-3 py-1.5 text-xs hover:bg-gray-50 disabled:opacity-50 rounded-lg">
            看步骤
          </button>
          <button onClick={() => requestMode('example')} disabled={!!busy}
            className="border border-gray-200 bg-white px-3 py-1.5 text-xs hover:bg-gray-50 disabled:opacity-50 rounded-lg">
            看示例
          </button>
          <button onClick={onRetry} disabled={!!busy}
            className="bg-gray-900 px-3 py-1.5 text-xs text-white hover:bg-gray-700 disabled:opacity-50 rounded-lg">
            重做原题
          </button>
        </div>
      )}

      {!variant.type && remediation.status === 'variant_ready' && !completed && (
        <button onClick={prepareVariant} disabled={!!busy}
          className="mt-3 bg-indigo-600 px-3 py-1.5 text-xs text-white hover:bg-indigo-700 disabled:opacity-50 rounded-lg">
          {busy === 'variant' ? '准备中...' : '进入变式巩固'}
        </button>
      )}

      {variant.type && !completed && (
        <div className="mt-3 border border-indigo-100 bg-indigo-50 p-3 rounded-lg">
          <strong className="text-xs text-indigo-900">变式巩固</strong>
          <p className="mt-1 text-xs text-indigo-800">{variant.prompt}</p>
          {variant.input && <pre className="mt-2 bg-white p-2 text-xs text-gray-700 rounded">输入：{variant.input}</pre>}
          {variant.type === 'concept_choice' ? (
            <div className="mt-2 space-y-1.5">
              {(variant.options || []).map((option: string, index: number) => (
                <label key={index} className="flex cursor-pointer items-start gap-2 bg-white p-2 text-xs rounded-lg">
                  <input
                    type={variant.multiple ? 'checkbox' : 'radio'}
                    checked={variantAnswers.includes(index)}
                    onChange={() => toggleVariantOption(index)}
                  />
                  <span>{option}</span>
                </label>
              ))}
            </div>
          ) : (
            <input value={variantText} onChange={event => setVariantText(event.target.value)}
              placeholder="输入预测结果"
              className="mt-2 w-full border border-indigo-200 bg-white px-3 py-2 text-xs outline-none focus:border-indigo-500 rounded-lg" />
          )}
          <button onClick={evaluateVariant}
            disabled={!!busy || (variant.type === 'concept_choice' ? variantAnswers.length === 0 : !variantText.trim())}
            className="mt-2 bg-indigo-600 px-3 py-1.5 text-xs text-white hover:bg-indigo-700 disabled:opacity-40 rounded-lg">
            {busy === 'variant-submit' ? '验证中...' : '提交变式'}
          </button>
          {variantResult && (
            <p className={`mt-2 text-xs font-medium ${variantResult.correct ? 'text-green-700' : 'text-red-700'}`}>
              {variantResult.correct ? '✅ 迁移验证通过，证据已写回学习记录。' : '❌ 还未通过，请重新根据修正规则判断。'}
            </p>
          )}
        </div>
      )}

      {completed && (
        <div className="mt-3 bg-green-50 px-3 py-2 text-xs text-green-800 rounded-lg">
          ✅ 原题重做与变式验证均通过；本次纠错的作答、策略和证据编号已写回五核记忆。
        </div>
      )}
      {remediation.ineffective_modes?.length > 0 && (
        <p className="mt-2 text-[10px] text-gray-500">
          本案例已记录无效讲法：{remediation.ineffective_modes.map((mode: string) => MODE_LABELS[mode] || mode).join('、')}
        </p>
      )}
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </section>
  )
}
