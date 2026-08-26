import {
  ArrowRight, BookOpenCheck, Check, CheckCircle2, ClipboardCheck, ExternalLink,
  ListChecks, MessageSquarePlus, PackageCheck, PlayCircle, ShieldAlert, Sparkles,
  Target, Wrench,
} from 'lucide-react'
import type { LearningTaskConversionBundle } from '../../services/api'
import type { WF03Selection } from './types'

function text(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function platformLabel(platform?: string, linkKind?: string) {
  if (platform === 'bilibili') return linkKind === 'curated_video' ? 'B站精选' : 'B站搜索'
  if (platform === 'douyin') return linkKind === 'curated_video' ? '抖音精选' : '抖音搜索'
  return platform || '学习资源'
}

export function externalHref(value: unknown) {
  const raw = text(value).trim()
  if (!raw) return ''
  if (/^https?:\/\//i.test(raw)) return raw
  if (raw.startsWith('//')) return `https:${raw}`
  if (/^(localhost|127\.0\.0\.1)(:\d+)?(?:\/|$)/i.test(raw)) return `http://${raw}`
  if (/^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d+)?(?:\/|$)/.test(raw)) return `https://${raw}`
  return ''
}

function displayItem(value: unknown) {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object') return ''
  const item = value as Record<string, unknown>
  return text(item.name)
    || text(item.title)
    || text(item.description)
    || text(item.requirement)
    || text(item.criterion)
    || text(item.deliverable)
    || text(item.expected_artifact)
    || text(item.check)
    || text(item.action)
    || text(item.value)
}

function uniqueItems(items: string[]) {
  return [...new Set(items.map(item => item.trim()).filter(Boolean))]
}

function annotationTarget(
  targetType: WF03Selection['targetType'],
  targetId: string | undefined,
  selectedText: string,
): WF03Selection {
  return {
    text: selectedText,
    targetType,
    targetId,
    rect: { left: 0, top: 0, width: 0, height: 0 },
  }
}

function ResourceLinks({ resources }: { resources: Array<any> }) {
  if (!resources.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {resources.map((resource, index) => {
        const href = externalHref(resource.resource_url)
        if (!href) return null
        return (
          <a
            key={`${resource.resource_id || resource.resource_url}-${index}`}
            href={href}
            target="_blank"
            rel="noreferrer"
            title={resource.resource_name}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-semibold text-slate-600 transition hover:border-emerald-300 hover:text-emerald-800"
          >
            {resource.platform === 'bilibili' || resource.platform === 'douyin'
              ? <PlayCircle size={11} />
              : <ExternalLink size={11} />}
            {platformLabel(resource.platform, resource.link_kind)}
          </a>
        )
      })}
    </div>
  )
}

export default function WF03TaskDocument({
  bundle,
  onAnnotate,
  onOpenPersonalizedLearning,
  openingKnowledgeId,
}: {
  bundle: LearningTaskConversionBundle
  onAnnotate: (selection: WF03Selection) => void
  onOpenPersonalizedLearning: (knowledgeId: string) => void
  openingKnowledgeId?: string
}) {
  const task = bundle.task.work_task
  const knowledgeById = new Map(task.knowledge_points.map(item => [item.knowledge_id, item]))
  const skillById = new Map(task.skill_points.map(item => [item.skill_id, item]))
  const expectedArtifacts = (task.expected_artifacts || []).map(displayItem).filter(Boolean)
  const workSituation = displayItem(task.work_situation) || task.teaching_task_description
  const taskScenario = displayItem(task.task_scenario)
  const deliverables = uniqueItems([
    ...expectedArtifacts,
    ...task.task_steps.map(step => step.deliverable),
  ])
  const acceptanceTests = uniqueItems([
    ...(task.acceptance_tests || []).map(displayItem),
    ...task.task_steps.map(step => step.check),
  ])
  const safetyPoints = uniqueItems((task.safety_points || []).map(displayItem))
  const finalStep = task.task_steps[task.task_steps.length - 1]

  const relationsForStep = (stepName: string, knowledgeId?: string, skillId?: string) => (
    (bundle.strong_relationships || []).filter(relation => {
      const applies = Array.isArray(relation.applies_to_steps) ? relation.applies_to_steps.map(String) : []
      const stepMatches = !applies.length || applies.includes(stepName)
      const knowledgeMatches = !knowledgeId || String(relation.knowledge_id || '') === knowledgeId
      const skillMatches = !skillId || String(relation.skill_id || '') === skillId
      return stepMatches && knowledgeMatches && skillMatches
    })
  )

  return (
    <article className="mx-auto w-full max-w-[980px] pb-16" data-task-document>
      <header className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="h-1 bg-emerald-700" />
        <div className="px-6 py-6 sm:px-8 sm:py-8">
          <div className="flex flex-wrap items-center gap-2 text-[10px] font-semibold tracking-[0.1em]">
            <span className="rounded-md bg-emerald-50 px-2.5 py-1 text-emerald-800">学习型工作任务</span>
            <span className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-500">
              {bundle.verification_status === 'verified' ? '内容已校验' : '等待事实补证'}
            </span>
            <span className="ml-auto text-slate-400">{task.task_steps.length} 个作业阶段</span>
          </div>
          <h1 className="mt-5 max-w-4xl text-2xl font-bold leading-tight tracking-tight text-slate-950 sm:text-[30px]">
            {task.teaching_task_name || task.enterprise_task_name}
          </h1>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-600">
            {task.teaching_task_description || task.enterprise_task_description || '按真实工作过程完成任务并提交可检查成果。'}
          </p>
          <div className="mt-6 grid overflow-hidden rounded-lg border border-slate-200 bg-slate-50 md:grid-cols-[1.25fr_0.75fr]">
            <div className="border-b border-slate-200 p-4 md:border-b-0 md:border-r sm:p-5">
              <p className="text-[10px] font-semibold tracking-[0.12em] text-emerald-700">企业任务</p>
              <p className="mt-1.5 text-sm font-semibold text-slate-900">{task.enterprise_task_name}</p>
              {task.enterprise_task_description && <p className="mt-1.5 text-xs leading-5 text-slate-500">{task.enterprise_task_description}</p>}
            </div>
            <div className="bg-emerald-50/50 p-4 sm:p-5">
              <p className="text-[10px] font-semibold tracking-[0.12em] text-emerald-700">最终验收</p>
              <p className="mt-1.5 text-xs leading-5 text-slate-700">
                {expectedArtifacts[0] || finalStep?.deliverable || '完成全部步骤并提交可检查成果'}
              </p>
            </div>
          </div>
        </div>
      </header>

      {workSituation && (
        <section className="mt-5 grid overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm lg:grid-cols-[180px_1fr]">
          <div className="flex items-center gap-3 bg-emerald-50 px-5 py-4 text-emerald-900 lg:flex-col lg:items-start lg:justify-center lg:px-6">
            <Target size={20} />
            <div>
              <p className="text-[10px] font-bold tracking-[0.12em]">工作情境</p>
              <p className="mt-1 text-xs text-emerald-700">任务边界与交付目标</p>
            </div>
          </div>
          <p className="px-5 py-4 text-sm leading-7 text-slate-700 sm:px-7">{workSituation}</p>
        </section>
      )}

      <section className="mt-5 grid overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm md:grid-cols-2">
        {(taskScenario && taskScenario !== workSituation) && (
          <div className="border-b border-slate-200 p-5 md:col-span-2 sm:p-6">
            <div className="flex items-center gap-2 text-slate-900"><BookOpenCheck size={16} className="text-emerald-700" /><h2 className="text-xs font-bold">任务场景</h2></div>
            <p className="mt-2 text-xs leading-6 text-slate-600">{taskScenario}</p>
          </div>
        )}
        <div className="border-b border-slate-200 p-5 sm:p-6 md:border-r">
          <div className="flex items-center gap-2 text-slate-900"><PackageCheck size={16} className="text-sky-700" /><h2 className="text-xs font-bold">完整任务交付物</h2></div>
          <ol className="mt-3 space-y-2">
            {deliverables.map((item, index) => (
              <li key={`${item}-${index}`} className="flex gap-2 text-[11px] leading-5 text-slate-600"><span className="font-bold text-sky-700">{String(index + 1).padStart(2, '0')}</span>{item}</li>
            ))}
          </ol>
        </div>
        <div className="border-b border-slate-200 p-5 sm:p-6">
          <div className="flex items-center gap-2 text-slate-900"><ListChecks size={16} className="text-emerald-700" /><h2 className="text-xs font-bold">总体验收标准</h2></div>
          <ol className="mt-3 space-y-2">
            {acceptanceTests.map((item, index) => (
              <li key={`${item}-${index}`} className="flex gap-2 text-[11px] leading-5 text-slate-600"><CheckCircle2 size={12} className="mt-1 shrink-0 text-emerald-700" />{item}</li>
            ))}
          </ol>
        </div>
        {!!task.tools?.length && (
          <div className="border-b border-slate-200 p-5 sm:p-6 md:border-b-0 md:border-r">
            <div className="flex items-center gap-2"><Wrench size={15} className="text-slate-700" /><h2 className="text-xs font-bold text-slate-900">工具与实训环境</h2></div>
            <div className="mt-3 flex flex-wrap gap-2">
              {task.tools.map((tool, index) => <span key={`${tool}-${index}`} className="rounded-md bg-slate-100 px-3 py-1.5 text-[11px] font-medium text-slate-600">{tool}</span>)}
            </div>
          </div>
        )}
        {!!safetyPoints.length && (
          <div className="bg-amber-50/70 p-5 sm:p-6">
            <div className="flex items-center gap-2"><ShieldAlert size={15} className="text-amber-700" /><h2 className="text-xs font-bold text-slate-900">安全要点与作业边界</h2></div>
            <ol className="mt-3 space-y-2 text-[11px] leading-5 text-slate-700">
              {safetyPoints.map((item, index) => (
                <li key={`${item}-${index}`} className="flex gap-2"><CheckCircle2 size={12} className="mt-1 shrink-0 text-amber-700" />{item}</li>
              ))}
            </ol>
          </div>
        )}
      </section>

      <section className="mt-8">
        <div className="flex items-end gap-3 px-1">
          <div>
            <p className="text-[10px] font-bold tracking-[0.14em] text-emerald-700">WORK PROCESS</p>
            <h2 className="mt-1 text-xl font-bold tracking-tight text-slate-950">真实作业流程</h2>
          </div>
          <p className="mb-0.5 ml-auto hidden text-xs text-slate-400 sm:block">每一步都绑定产物、验收点与知识技能</p>
        </div>

        <div className="relative mt-5">
          <div className="absolute bottom-8 left-[22px] top-8 w-px bg-emerald-200 sm:left-[27px]" />
          <div className="space-y-4">
            {task.task_steps.map((step, index) => (
              <section
                key={step.step_id}
                className="group relative grid gap-3 pl-[58px] sm:pl-[72px] 2xl:grid-cols-[minmax(0,1fr)_235px]"
                data-step-id={step.step_id}
              >
                <div className="absolute left-0 top-5 z-10 flex h-11 w-11 items-center justify-center rounded-xl border-4 border-slate-100 bg-emerald-700 text-xs font-black text-white shadow-sm sm:left-1 sm:h-12 sm:w-12">
                  {String(step.step || index + 1).padStart(2, '0')}
                </div>
                <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm transition group-hover:-translate-y-0.5 group-hover:border-emerald-300 group-hover:shadow-md">
                  <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-4 sm:px-6">
                    <div className="min-w-0 flex-1">
                      <p className="text-[10px] font-bold tracking-[0.12em] text-emerald-700">阶段 {index + 1}</p>
                      <h3 className="mt-1 text-base font-bold text-slate-950">{step.name}</h3>
                    </div>
                    <button
                      type="button"
                      onClick={() => onAnnotate(annotationTarget('step', step.step_id, `${step.name}：${step.action}`))}
                      className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 text-[10px] font-semibold text-slate-500 transition hover:border-emerald-300 hover:text-emerald-800"
                    >
                      <MessageSquarePlus size={12} /> 批注
                    </button>
                  </div>
                  <div className="px-5 py-4 sm:px-6">
                    <div>
                      <p className="text-[10px] font-bold tracking-[0.1em] text-slate-400">分步操作指南</p>
                      <p className="mt-1.5 text-sm leading-7 text-slate-700">{step.action}</p>
                      {step.instruction && step.instruction.trim() !== step.action.trim() && (
                        <p className="mt-2 border-l-2 border-emerald-200 pl-3 text-xs leading-6 text-slate-500">{step.instruction}</p>
                      )}
                    </div>
                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      <div className="rounded-lg bg-sky-50 px-3.5 py-3">
                        <p className="text-[10px] font-bold tracking-[0.1em] text-sky-700">阶段产物</p>
                        <p className="mt-1.5 text-xs leading-5 text-slate-700">{step.deliverable}</p>
                      </div>
                      <div className="rounded-lg bg-emerald-50 px-3.5 py-3">
                        <p className="text-[10px] font-bold tracking-[0.1em] text-emerald-700">验收检查</p>
                        <p className="mt-1.5 text-xs leading-5 text-slate-700">{step.check}</p>
                      </div>
                    </div>
                  </div>
                </div>

                <aside className="rounded-xl border border-slate-200 bg-slate-50/80 p-4">
                  <p className="text-[10px] font-bold tracking-[0.12em] text-slate-500">步骤能力映射</p>
                  <div className="mt-3 space-y-2.5">
                    {step.knowledge_point_ids.map((id, mappingIndex) => {
                      const knowledge = knowledgeById.get(id)
                      const relations = relationsForStep(step.name, id)
                      return (
                        <div key={`${id}-${mappingIndex}`} className="rounded-lg border border-emerald-100 bg-white p-3" data-knowledge-id={id}>
                          <div className="flex w-full items-start gap-2 text-left">
                            <Sparkles size={13} className="mt-0.5 shrink-0 text-emerald-700" />
                            <span className="min-w-0 flex-1 text-[11px] font-semibold leading-4 text-slate-800">
                              {knowledge?.name || id}
                            </span>
                          </div>
                          {knowledge && (
                            <p className="mt-2 text-[10px] leading-4 text-slate-500">
                              {text(knowledge.scope) || text(knowledge.description) || text(knowledge.concept) || text(knowledge.operation) || '支撑完成并验收本步任务。'}
                            </p>
                          )}
                          {relations.map(relation => relation.reason ? (
                            <p key={String(relation.relation_id || relation.reason)} className="mt-2 rounded-md bg-emerald-50 px-2.5 py-2 text-[9px] leading-4 text-emerald-900">
                              <span className="font-bold">关联理由：</span>{String(relation.reason)}
                            </p>
                          ) : null)}
                          {!!knowledge?.learning_resources?.length && <div className="mt-2.5"><ResourceLinks resources={knowledge.learning_resources} /></div>}
                          <button
                            type="button"
                            onClick={() => onOpenPersonalizedLearning(id)}
                            disabled={openingKnowledgeId === id}
                            title="携带本知识点、当前任务步骤和强关联技能进入个性化学习"
                            className="mt-3 inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-md bg-emerald-700 px-3 text-[10px] font-bold text-white transition hover:bg-emerald-800 disabled:cursor-wait disabled:bg-emerald-300"
                          >
                            <Sparkles size={11} />
                            {openingKnowledgeId === id ? '正在生成个性化学习…' : '进入本步个性化学习'}
                            <ArrowRight size={11} />
                          </button>
                        </div>
                      )
                    })}
                    {step.skill_point_ids.map((id, mappingIndex) => {
                      const skill = skillById.get(id)
                      const relations = relationsForStep(step.name, undefined, id)
                      return (
                        <div key={`${id}-${mappingIndex}`} className="rounded-lg border border-amber-100 bg-amber-50/70 p-3" data-skill-id={id}>
                          <div className="flex items-start gap-2">
                            <Wrench size={12} className="mt-0.5 shrink-0 text-amber-700" />
                            <span className="text-[11px] font-semibold leading-4 text-amber-950">{skill?.name || id}</span>
                          </div>
                          {skill && <p className="mt-2 text-[10px] leading-4 text-amber-900/75">{text(skill.observable_action) || text(skill.expected_artifact) || text(skill.description) || '通过对应任务产物进行观察与验收。'}</p>}
                          {relations.map(relation => relation.reason ? (
                            <p key={String(relation.relation_id || relation.reason)} className="mt-2 text-[9px] leading-4 text-amber-900/70">{String(relation.reason)}</p>
                          ) : null)}
                        </div>
                      )
                    })}
                  </div>
                </aside>
              </section>
            ))}
          </div>
        </div>
      </section>

      <section className="mt-9 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center gap-3 border-b border-slate-200 px-5 py-4 sm:px-6">
          <ClipboardCheck size={17} className="text-emerald-700" />
          <div>
            <h2 className="text-sm font-bold text-slate-950">知识与技能总览</h2>
            <p className="mt-0.5 text-[10px] text-slate-400">主要学习入口已放到对应任务步骤内，此处用于完整核对</p>
          </div>
        </div>
        <div className="grid lg:grid-cols-2">
          <div className="border-b border-slate-200 p-5 sm:p-6 lg:border-b-0 lg:border-r">
            <p className="text-[10px] font-bold tracking-[0.12em] text-emerald-700">支撑知识</p>
            <div className="mt-3 divide-y divide-slate-100">
              {task.knowledge_points.map((item, index) => (
                <article key={item.knowledge_id} className="py-4 first:pt-1" data-knowledge-id={item.knowledge_id}>
                  <div className="flex items-start gap-3">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-emerald-50 text-[10px] font-black text-emerald-700">K{index + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start gap-2">
                        <h3 className="min-w-0 flex-1 text-xs font-bold text-slate-900">{item.name}</h3>
                        <button type="button" onClick={() => onAnnotate(annotationTarget('knowledge', item.knowledge_id, item.name))} className="text-slate-300 transition hover:text-emerald-700" title="批注知识点">
                          <MessageSquarePlus size={13} />
                        </button>
                      </div>
                      <p className="mt-1 text-[11px] leading-5 text-slate-500">
                        {text(item.scope) || text(item.description) || text(item.concept) || text(item.operation) || '用于支撑对应任务步骤。'}
                      </p>
                      {item.verification && <p className="mt-1.5 flex items-start gap-1 text-[10px] leading-4 text-emerald-700"><Check size={11} className="mt-0.5 shrink-0" />{item.verification}</p>}
                      <div className="mt-2.5 flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() => onOpenPersonalizedLearning(item.knowledge_id)}
                          disabled={openingKnowledgeId === item.knowledge_id}
                          className="inline-flex h-7 items-center gap-1.5 rounded-md bg-emerald-700 px-2.5 text-[10px] font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-wait disabled:bg-emerald-300"
                        >
                          <Sparkles size={11} /> {openingKnowledgeId === item.knowledge_id ? '正在进入…' : '个性化学习'}
                        </button>
                        <ResourceLinks resources={item.learning_resources || []} />
                      </div>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>

          <div className="p-5 sm:p-6">
            <p className="text-[10px] font-bold tracking-[0.12em] text-amber-700">目标技能</p>
            <div className="mt-3 divide-y divide-slate-100">
              {task.skill_points.map((item, index) => (
                <article key={item.skill_id} className="py-4 first:pt-1" data-skill-id={item.skill_id}>
                  <div className="flex items-start gap-3">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-amber-50 text-[10px] font-black text-amber-800">S{index + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start gap-2">
                        <h3 className="min-w-0 flex-1 text-xs font-bold text-slate-900">{item.name}</h3>
                        <button type="button" onClick={() => onAnnotate(annotationTarget('skill', item.skill_id, item.name))} className="text-slate-300 transition hover:text-amber-700" title="批注技能点">
                          <MessageSquarePlus size={13} />
                        </button>
                      </div>
                      <p className="mt-1 text-[11px] leading-5 text-slate-500">
                        {text(item.observable_action) || text(item.expected_artifact) || text(item.description) || '通过对应任务产物进行观察与验收。'}
                      </p>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>
      </section>

    </article>
  )
}
