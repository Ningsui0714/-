import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Background, Controls, Edge, Handle, MarkerType, MiniMap, Node, NodeProps,
  Position, ReactFlow,
} from 'reactflow'
import 'reactflow/dist/style.css'
import {
  Ban, Brain, Check, ChevronRight, CircleDot, Clock3, Compass, GitBranch,
  HeartPulse, Loader2, Network, Pencil, RefreshCw, Search, ShieldCheck,
  Sparkles, Wrench, X,
} from 'lucide-react'
import {
  getMemoryConsolidations, getMemoryGraph, getMemoryNode, MemoryGraphNode,
  MemoryKernel, MemoryNodeType, submitMemoryClaimFeedback,
} from '../services/api'

const kernels: Array<{
  id: MemoryKernel
  label: string
  color: string
  light: string
  border: string
  icon: any
}> = [
  { id: 'structure', label: '结构', color: '#0891b2', light: '#ecfeff', border: '#67e8f9', icon: Network },
  { id: 'knowledge', label: '知识', color: '#7c3aed', light: '#f5f3ff', border: '#c4b5fd', icon: Brain },
  { id: 'human', label: '人本', color: '#e11d48', light: '#fff1f2', border: '#fda4af', icon: HeartPulse },
  { id: 'value', label: '价值', color: '#b45309', light: '#fffbeb', border: '#fcd34d', icon: Compass },
  { id: 'practice', label: '实践', color: '#047857', light: '#ecfdf5', border: '#6ee7b7', icon: Wrench },
]

const kernelById = Object.fromEntries(kernels.map(item => [item.id, item])) as Record<MemoryKernel, typeof kernels[number]>
const gradeLabels: Record<string, string> = {
  verified: '已验证', observed: '已观察', self_reported: '用户自述', inferred: '推断',
  exposure_only: '仅接触', corrected: '用户纠正', legacy: '历史导入',
}
const relationLabels: Record<string, string> = {
  NEXT_IN_KERNEL: '同核后继', SAME_EVENT: '同一动作', SAME_SUBJECT: '同一主题',
  SUPPORTS: '支持', CONTRADICTS: '冲突', REFINES: '细化', SUPERSEDES: '取代',
  MOTIVATES: '驱动', ADDRESSES: '回应', BLOCKS: '阻碍', ENABLES: '促进',
  CONSOLIDATED_INTO: '合成为',
}

function LaneNode({ data }: NodeProps) {
  const meta = kernelById[data.kernel as MemoryKernel]
  const Icon = meta.icon
  return (
    <div className="relative h-[116px] border-y" style={{ width: data.width, background: meta.light, borderColor: meta.border }}>
      <div className="sticky left-0 flex h-full w-28 items-center gap-2 border-r bg-white/90 px-4 text-sm font-semibold" style={{ color: meta.color, borderColor: meta.border }}>
        <Icon size={17} /> {meta.label}
      </div>
    </div>
  )
}

function MemoryNodeCard({ data, selected }: NodeProps) {
  const item = data.item as MemoryGraphNode
  const meta = kernelById[item.kernel]
  const typeIcon = item.type === 'module' ? Sparkles : item.type === 'claim' ? ShieldCheck : CircleDot
  const TypeIcon = typeIcon
  const typeLabel = item.type === 'module' ? '模块' : item.type === 'claim' ? '声明' : '事实'
  const width = item.type === 'module' ? 220 : item.type === 'claim' ? 190 : 168
  return (
    <div
      className={`border bg-white shadow-sm transition-shadow ${selected ? 'ring-2 ring-gray-900 ring-offset-2' : ''}`}
      style={{ width, minHeight: item.type === 'module' ? 78 : 58, borderColor: meta.border, borderRadius: 8 }}
    >
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0" style={{ background: meta.color }} />
      <div className="flex items-center justify-between gap-2 border-b px-2.5 py-1.5" style={{ borderColor: meta.border, background: meta.light }}>
        <span className="flex min-w-0 items-center gap-1.5 text-[10px] font-semibold" style={{ color: meta.color }}><TypeIcon size={12} /> {typeLabel}</span>
        <time className="shrink-0 text-[9px] text-gray-500">{formatShortDate(item.occurred_at)}</time>
      </div>
      <p className={`break-words px-2.5 py-2 text-[11px] leading-4 text-gray-800 ${item.type === 'module' ? 'line-clamp-3' : 'line-clamp-2'}`}>{item.text}</p>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0" style={{ background: meta.color }} />
    </div>
  )
}

const nodeTypes = { lane: LaneNode, memory: MemoryNodeCard }

function formatShortDate(value?: string) {
  if (!value) return ''
  return new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function formatDateTime(value?: string) {
  if (!value) return '无'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function buildLayout(items: MemoryGraphNode[], selectedId?: number): { nodes: Node[]; width: number } {
  const sorted = [...items].sort((a, b) => {
    const delta = new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime()
    return delta || a.id - b.id
  })
  const rank = new Map(sorted.map((item, index) => [item.id, index]))
  const laneLastX: Partial<Record<MemoryKernel, number>> = {}
  const memoryNodes = sorted.map(item => {
    const baseX = 145 + (rank.get(item.id) || 0) * 88
    const minGap = item.type === 'module' ? 235 : 180
    const x = Math.max(baseX, (laneLastX[item.kernel] || -1000) + minGap)
    laneLastX[item.kernel] = x
    const lane = kernels.findIndex(kernel => kernel.id === item.kernel)
    return {
      id: String(item.id),
      type: 'memory',
      position: { x, y: lane * 140 + (item.type === 'module' ? 19 : 29) },
      data: { item },
      selected: selectedId === item.id,
      draggable: false,
      zIndex: 2,
    } as Node
  })
  const width = Math.max(1450, ...memoryNodes.map(node => node.position.x + 270))
  const laneNodes = kernels.map((kernel, index) => ({
    id: `lane-${kernel.id}`,
    type: 'lane',
    position: { x: 0, y: index * 140 },
    data: { kernel: kernel.id, width },
    draggable: false,
    selectable: false,
    connectable: false,
    focusable: false,
    zIndex: 0,
    style: { width, height: 116 },
  } as Node))
  return { nodes: [...laneNodes, ...memoryNodes], width }
}

export default function MemoryGraphPage() {
  const [graph, setGraph] = useState<{ nodes: MemoryGraphNode[]; edges: any[] }>({ nodes: [], edges: [] })
  const [selectedKernels, setSelectedKernels] = useState<MemoryKernel[]>(kernels.map(item => item.id))
  const [nodeType, setNodeType] = useState<'core' | MemoryNodeType>('core')
  const [status, setStatus] = useState<'active' | 'all'>('active')
  const [windowSize, setWindowSize] = useState<'30d' | '90d' | 'all'>('90d')
  const [subject, setSubject] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState<number>()
  const [detail, setDetail] = useState<any>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [runs, setRuns] = useState<any[]>([])
  const [feedbackMode, setFeedbackMode] = useState<'correct' | null>(null)
  const [correction, setCorrection] = useState('')
  const [feedbackBusy, setFeedbackBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const start = windowSize === 'all' ? undefined : new Date(Date.now() - (windowSize === '30d' ? 30 : 90) * 86400000).toISOString()
      const types = nodeType === 'core' ? 'fact,module' : nodeType
      const [nextGraph, nextRuns] = await Promise.all([
        getMemoryGraph({
          start,
          kernels: selectedKernels.join(','),
          node_types: types,
          statuses: status === 'active' ? 'active,legacy,transient' : undefined,
          subject: subject.trim() || undefined,
          limit: 300,
        }),
        getMemoryConsolidations(),
      ])
      setGraph(nextGraph)
      setRuns(nextRuns.runs || [])
    } catch (err: any) {
      setError(err?.response?.data?.detail || '记忆图谱读取失败')
    } finally {
      setLoading(false)
    }
  }, [nodeType, selectedKernels, status, subject, windowSize])

  useEffect(() => { load() }, [load])

  const openNode = useCallback(async (nodeId: number) => {
    setSelectedId(nodeId)
    setDetailLoading(true)
    setFeedbackMode(null)
    setCorrection('')
    try { setDetail(await getMemoryNode(nodeId)) } finally { setDetailLoading(false) }
  }, [])

  const neighborhood = useMemo(() => {
    if (!selectedId) return new Set<number>()
    const adjacency = new Map<number, number[]>()
    graph.edges.forEach(edge => {
      adjacency.set(edge.source, [...(adjacency.get(edge.source) || []), edge.target])
      adjacency.set(edge.target, [...(adjacency.get(edge.target) || []), edge.source])
    })
    const seen = new Set<number>([selectedId])
    let frontier = [selectedId]
    for (let depth = 0; depth < 2; depth += 1) {
      const next: number[] = []
      frontier.forEach(id => (adjacency.get(id) || []).forEach(neighbor => {
        if (!seen.has(neighbor)) { seen.add(neighbor); next.push(neighbor) }
      }))
      frontier = next
    }
    return seen
  }, [graph.edges, selectedId])

  const flow = useMemo(() => buildLayout(graph.nodes, selectedId), [graph.nodes, selectedId])
  const flowEdges = useMemo(() => graph.edges.map(edge => {
    const source = graph.nodes.find(node => node.id === edge.source)
    const target = graph.nodes.find(node => node.id === edge.target)
    const selected = selectedId && neighborhood.has(edge.source) && neighborhood.has(edge.target)
    const sameKernel = source?.kernel === target?.kernel
    const color = edge.relation === 'CONTRADICTS' ? '#dc2626' : edge.relation === 'SUPERSEDES' ? '#d97706' : '#64748b'
    return {
      id: String(edge.id), source: String(edge.source), target: String(edge.target),
      type: 'smoothstep',
      animated: selected && ['SUPPORTS', 'CONTRADICTS', 'SUPERSEDES'].includes(edge.relation),
      label: selected ? relationLabels[edge.relation] || edge.relation : undefined,
      labelStyle: { fontSize: 9, fill: color },
      style: { stroke: color, strokeWidth: selected ? 2.2 : 1, opacity: selected ? 0.95 : sameKernel ? 0.35 : 0.1 },
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 12, height: 12 },
      zIndex: selected ? 3 : 1,
    } as Edge
  }), [graph.edges, graph.nodes, neighborhood, selectedId])

  const toggleKernel = (kernel: MemoryKernel) => {
    setSelectedKernels(current => current.includes(kernel)
      ? (current.length === 1 ? current : current.filter(item => item !== kernel))
      : [...current, kernel])
  }

  const feedback = async (action: 'confirm' | 'correct' | 'retract') => {
    if (!selectedId) return
    setFeedbackBusy(true)
    try {
      await submitMemoryClaimFeedback(selectedId, { action, correction })
      setFeedbackMode(null)
      setCorrection('')
      await load()
      await openNode(selectedId)
    } finally {
      setFeedbackBusy(false)
    }
  }

  const completedRuns = runs.filter(run => run.status === 'completed').length
  const queuedRuns = runs.filter(run => ['queued', 'running'].includes(run.status)).length

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <header className="shrink-0 border-b border-gray-200 px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gray-950 text-white"><GitBranch size={18} /></div>
            <div><h1 className="text-base font-semibold text-gray-950">记忆图谱</h1><p className="text-xs text-gray-500">{graph.nodes.length} 个节点 · {completedRuns} 次合成 · {queuedRuns} 个处理中</p></div>
          </div>
          <button onClick={load} disabled={loading} title="刷新记忆图谱" className="flex h-9 w-9 items-center justify-center rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-40">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="flex items-center rounded-lg border border-gray-200 bg-gray-50 p-0.5" aria-label="节点类型">
            {([['core', '事实与模块'], ['fact', '事实'], ['module', '模块'], ['claim', '声明']] as const).map(([value, label]) => <button key={value} onClick={() => setNodeType(value)} className={`h-7 rounded-md px-2.5 text-xs font-medium ${nodeType === value ? 'bg-white text-gray-950 shadow-sm' : 'text-gray-500'}`}>{label}</button>)}
          </div>
          <select value={windowSize} onChange={event => setWindowSize(event.target.value as any)} aria-label="时间范围" className="h-8 rounded-lg border border-gray-200 bg-white px-2 text-xs text-gray-700 outline-none">
            <option value="30d">近 30 天</option><option value="90d">近 90 天</option><option value="all">全部时间</option>
          </select>
          <select value={status} onChange={event => setStatus(event.target.value as any)} aria-label="记忆状态" className="h-8 rounded-lg border border-gray-200 bg-white px-2 text-xs text-gray-700 outline-none">
            <option value="active">当前有效</option><option value="all">包含历史</option>
          </select>
          <label className="relative min-w-44 flex-1 sm:max-w-64"><Search size={14} className="absolute left-2.5 top-2 text-gray-400" /><input value={subject} onChange={event => setSubject(event.target.value)} placeholder="筛选主题" className="h-8 w-full rounded-lg border border-gray-200 pl-8 pr-3 text-xs outline-none focus:border-gray-400" /></label>
          <div className="flex flex-wrap gap-1">
            {kernels.map(kernel => {
              const Icon = kernel.icon
              const active = selectedKernels.includes(kernel.id)
              return <button key={kernel.id} onClick={() => toggleKernel(kernel.id)} aria-pressed={active} className="flex h-8 items-center gap-1.5 rounded-lg border px-2 text-xs font-medium" style={{ color: active ? kernel.color : '#9ca3af', borderColor: active ? kernel.border : '#e5e7eb', background: active ? kernel.light : '#fff' }}><Icon size={13} />{kernel.label}</button>
            })}
          </div>
        </div>
      </header>

      <div className="relative min-h-0 flex-1">
        {loading && graph.nodes.length === 0 && <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/80 text-sm text-gray-500"><Loader2 size={18} className="mr-2 animate-spin" />正在读取记忆</div>}
        {error && <div className="absolute left-1/2 top-5 z-20 -translate-x-1/2 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700">{error}</div>}
        {!loading && !error && graph.nodes.length === 0 && <div className="absolute inset-0 z-10 flex items-center justify-center text-sm text-gray-400">当前筛选条件下暂无记忆节点</div>}
        <ReactFlow
          nodes={flow.nodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => { if (node.type === 'memory') openNode(Number(node.id)) }}
          minZoom={0.15}
          maxZoom={1.8}
          defaultViewport={{ x: 8, y: 16, zoom: 0.74 }}
          attributionPosition="bottom-left"
          nodesDraggable={false}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#d1d5db" gap={24} size={0.7} />
          <Controls showInteractive={false} />
          <MiniMap className="memory-graph-minimap" pannable zoomable nodeColor={node => node.type === 'lane' ? '#f8fafc' : kernelById[(node.data?.item?.kernel || 'structure') as MemoryKernel].color} maskColor="rgba(255,255,255,0.72)" />
        </ReactFlow>
      </div>

      {(selectedId || detailLoading) && (
        <aside className="absolute inset-x-0 bottom-0 z-30 max-h-[72vh] overflow-y-auto border-t border-gray-200 bg-white shadow-2xl sm:inset-y-16 sm:left-auto sm:w-[420px] sm:max-h-none sm:border-l sm:border-t-0">
          <div className="sticky top-0 z-10 flex h-12 items-center justify-between border-b border-gray-200 bg-white px-4">
            <p className="text-sm font-semibold text-gray-900">节点详情</p>
            <button onClick={() => { setSelectedId(undefined); setDetail(null) }} title="关闭详情" className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100"><X size={17} /></button>
          </div>
          {detailLoading && <div className="flex items-center justify-center py-16 text-sm text-gray-500"><Loader2 size={17} className="mr-2 animate-spin" />读取证据路径</div>}
          {!detailLoading && detail && <DetailPanel detail={detail} onOpen={openNode} feedbackMode={feedbackMode} setFeedbackMode={setFeedbackMode} correction={correction} setCorrection={setCorrection} onFeedback={feedback} feedbackBusy={feedbackBusy} />}
        </aside>
      )}
    </div>
  )
}

function DetailPanel({ detail, onOpen, feedbackMode, setFeedbackMode, correction, setCorrection, onFeedback, feedbackBusy }: any) {
  const meta = kernelById[detail.kernel as MemoryKernel]
  return (
    <div className="px-4 pb-8 pt-4">
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className="rounded border px-2 py-1 font-semibold" style={{ color: meta.color, borderColor: meta.border, background: meta.light }}>{meta.label}</span>
        <span className="rounded border border-gray-200 bg-gray-50 px-2 py-1 text-gray-600">{detail.type === 'fact' ? '动作事实' : detail.type === 'module' ? '维度模块' : '模块声明'}</span>
        <span className="text-gray-400">#{detail.id}</span>
      </div>
      <h2 className="mt-3 break-words text-sm font-semibold leading-6 text-gray-950">{detail.text}</h2>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-y border-gray-100 py-4 text-xs">
        <InfoTerm label="主题" value={detail.subject} />
        <InfoTerm label="状态" value={detail.status} />
        <InfoTerm label="置信度" value={`${Math.round((detail.confidence || 0) * 100)}%`} />
        <InfoTerm label="发生时间" value={formatDateTime(detail.occurred_at)} />
      </dl>

      {detail.fact && <section className="mt-5"><SectionTitle icon={CircleDot} title="事实证据" /><div className="mt-3 space-y-2 text-xs"><InfoRow label="证据等级" value={gradeLabels[detail.fact.evidence_grade] || detail.fact.evidence_grade} /><InfoRow label="谓词" value={detail.fact.predicate} /><InfoRow label="消费状态" value={detail.fact.consumption_status} /></div></section>}
      {detail.source_event && <section className="mt-5"><SectionTitle icon={Clock3} title="原始动作" /><div className="mt-3 border-l-2 border-gray-300 pl-3 text-xs"><p className="font-medium text-gray-800">#{detail.source_event.learner_seq} · {detail.source_event.event_type}</p><p className="mt-1 text-gray-500">{detail.source_event.actor_type} / {detail.source_event.source}</p><p className="mt-2 break-words leading-5 text-gray-700">{JSON.stringify(detail.source_event.payload, null, 2)}</p><p className="mt-2 text-[10px] text-gray-400">发生 {formatDateTime(detail.source_event.occurred_at)}<br />记录 {formatDateTime(detail.source_event.recorded_at)}</p></div></section>}

      {(detail.claims || []).length > 0 && <section className="mt-5"><SectionTitle icon={ShieldCheck} title="模块声明" /><div className="mt-2 divide-y divide-gray-100 border-y border-gray-100">{detail.claims.map((claim: any) => <button key={claim.id} onClick={() => onOpen(claim.id)} className="flex w-full items-start justify-between gap-3 py-3 text-left hover:bg-gray-50"><span className="text-xs leading-5 text-gray-800">{claim.text}</span><ChevronRight size={15} className="mt-0.5 shrink-0 text-gray-400" /></button>)}</div></section>}

      {(detail.evidence_facts || []).length > 0 && <section className="mt-5"><SectionTitle icon={GitBranch} title="直接证据" /><div className="mt-2 divide-y divide-gray-100 border-y border-gray-100">{detail.evidence_facts.map((fact: any) => <button key={fact.id} onClick={() => onOpen(fact.id)} className="flex w-full items-start justify-between gap-3 py-3 text-left hover:bg-gray-50"><span><span className="text-[10px] font-medium text-gray-500">{gradeLabels[fact.fact?.evidence_grade] || fact.fact?.evidence_grade}</span><span className="mt-0.5 block text-xs leading-5 text-gray-800">{fact.text}</span></span><ChevronRight size={15} className="mt-1 shrink-0 text-gray-400" /></button>)}</div></section>}

      {detail.synthesis_run && <section className="mt-5"><SectionTitle icon={Sparkles} title="合成审计" /><div className="mt-3 space-y-2 text-xs"><InfoRow label="运行状态" value={detail.synthesis_run.status} /><InfoRow label="触发规则" value={detail.synthesis_run.trigger_reason} /><InfoRow label="模型" value={detail.synthesis_run.model_name} /><InfoRow label="Prompt" value={detail.synthesis_run.prompt_version} /><InfoRow label="候选事实" value={(detail.synthesis_run.candidate_fact_ids || []).join(', ')} /><InfoRow label="输入指纹" value={detail.synthesis_run.input_fingerprint?.slice(0, 16)} /></div></section>}

      {(detail.relations || []).length > 0 && <section className="mt-5"><SectionTitle icon={Network} title="关系" /><div className="mt-2 flex flex-wrap gap-2">{detail.relations.map((relation: any) => <button key={relation.edge_id} onClick={() => onOpen(relation.node_id)} className="rounded border border-gray-200 bg-gray-50 px-2 py-1.5 text-[11px] text-gray-700 hover:border-gray-400">{relationLabels[relation.relation] || relation.relation} #{relation.node_id}</button>)}</div></section>}

      {detail.type === 'claim' && <section className="mt-6 border-t border-gray-200 pt-4">
        {feedbackMode === 'correct' ? <div><label className="text-xs font-medium text-gray-700">更正后的声明<textarea value={correction} onChange={event => setCorrection(event.target.value)} rows={4} autoFocus className="mt-2 w-full resize-none rounded-lg border border-gray-300 p-3 text-sm leading-5 outline-none focus:border-gray-500" /></label><div className="mt-3 flex gap-2"><button disabled={!correction.trim() || feedbackBusy} onClick={() => onFeedback('correct')} className="flex h-9 items-center gap-2 rounded-lg bg-gray-950 px-3 text-xs font-medium text-white disabled:opacity-40"><Check size={14} />提交纠正</button><button onClick={() => setFeedbackMode(null)} className="h-9 rounded-lg border border-gray-300 px-3 text-xs text-gray-700">取消</button></div></div> : <div className="flex flex-wrap gap-2"><button disabled={feedbackBusy} onClick={() => onFeedback('confirm')} className="flex h-9 items-center gap-2 rounded-lg border border-emerald-300 bg-emerald-50 px-3 text-xs font-medium text-emerald-800"><Check size={14} />确认</button><button disabled={feedbackBusy} onClick={() => setFeedbackMode('correct')} className="flex h-9 items-center gap-2 rounded-lg border border-gray-300 px-3 text-xs font-medium text-gray-700"><Pencil size={14} />纠正</button><button disabled={feedbackBusy} onClick={() => onFeedback('retract')} className="flex h-9 items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 text-xs font-medium text-red-700"><Ban size={14} />撤回</button></div>}
      </section>}
    </div>
  )
}

function SectionTitle({ icon: Icon, title }: { icon: any; title: string }) { return <h3 className="flex items-center gap-2 text-xs font-semibold text-gray-900"><Icon size={14} />{title}</h3> }
function InfoTerm({ label, value }: { label: string; value: string }) { return <div className="min-w-0"><dt className="text-[10px] text-gray-400">{label}</dt><dd className="mt-1 break-words text-gray-700">{value}</dd></div> }
function InfoRow({ label, value }: { label: string; value: any }) { return <div className="flex items-start justify-between gap-4"><span className="shrink-0 text-gray-400">{label}</span><span className="break-all text-right text-gray-700">{String(value ?? '无')}</span></div> }
