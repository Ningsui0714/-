import { useState, useMemo, useRef, useEffect } from 'react'
import ReactFlow, { Background, Controls, Handle, Position, MarkerType } from 'reactflow'
import 'reactflow/dist/style.css'
import { generateConceptGraph, getConceptGraphTask, subscribeTaskEvents, type TaskEventSubscription } from '../../services/api'

interface GraphData {
  nodes: { id: string; label: string; section_index: number }[]
  edges: { source: string; target: string; relation: string }[]
}

interface Props {
  checkpointId: number
  graph: GraphData
  sections: any[]
  onClose: () => void
  onGraphUpdate: (g: GraphData) => void
}

function ConceptNode({ data }: any) {
  const { label, sectionTitle } = data
  return (
    <div className="px-3 py-2 rounded-lg bg-white border-2 border-indigo-300 shadow-sm text-center cursor-pointer hover:border-indigo-500 hover:shadow-md transition-all">
      <Handle type="target" position={Position.Top} className="!bg-indigo-300" />
      <span className="text-xs font-medium text-gray-800">{label}</span>
      {sectionTitle && (
        <p className="text-[9px] text-gray-400 mt-0.5">{sectionTitle}</p>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-indigo-300" />
    </div>
  )
}

const nodeTypes = { concept: ConceptNode }

export default function ConceptGraphModal({ checkpointId, graph, sections, onClose, onGraphUpdate }: Props) {
  const [generating, setGenerating] = useState(false)
  const [progress, setProgress] = useState('')
  const [selected, setSelected] = useState<any>(null)
  const esRef = useRef<TaskEventSubscription | null>(null)

  useEffect(() => () => esRef.current?.close(), [])

  const sectionTitles = useMemo(() => {
    const m: Record<number, string> = {}
    ;(sections || []).forEach((s, i) => { m[i] = `第${i + 1}节 ${s.title?.slice(0, 14)}` })
    return m
  }, [sections])

  // Layout: one column per section, nodes stacked vertically
  const layout = useMemo(() => {
    const bySection: Record<number, number> = {}
    const nodes = (graph?.nodes || []).map(n => {
      const si = n.section_index ?? 0
      const y = (bySection[si] || 0) * 84
      bySection[si] = (bySection[si] || 0) + 1
      return {
        id: n.id,
        type: 'concept',
        position: { x: si * 250 + 40, y },
        data: { label: n.label, sectionTitle: sectionTitles[si] || `第${si + 1}节` },
      }
    })
    const edges = (graph?.edges || []).map((e, i) => ({
      id: `e${i}`,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      label: e.relation,
      style: { stroke: '#818cf8', strokeWidth: 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#818cf8' },
      labelStyle: { fontSize: 9, fill: '#6b7280' },
      labelBgStyle: { fill: '#ffffff', fillOpacity: 0.9 },
    }))
    return { nodes, edges }
  }, [graph, sectionTitles])

  const handleGenerate = () => {
    setGenerating(true)
    setProgress('排队中...')
    generateConceptGraph(checkpointId)
      .then((res: any) => {
        esRef.current?.close()
        esRef.current = subscribeTaskEvents(res.task_id, snap => {
          if (snap.progress?.message) setProgress(snap.progress.message)
          if (snap.status === 'completed') {
            esRef.current?.close()
            setGenerating(false)
            import('../../services/api').then(({ getLecture }) =>
              getLecture(checkpointId).then(d => {
                if (d.concept_graph?.nodes?.length) onGraphUpdate(d.concept_graph)
              }))
          } else if (snap.status === 'failed') {
            esRef.current?.close()
            setGenerating(false)
            setProgress('❌ ' + (snap.error?.guidance || '生成失败'))
          }
        }, message => {
          setGenerating(false)
          setProgress(`❌ 图谱状态同步失败：${message}`)
          esRef.current?.close()
        })
      })
      .catch((e: any) => { setGenerating(false); setProgress('❌ ' + e.message) })
  }

  const hasGraph = (graph?.nodes?.length || 0) > 0

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
         onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-[880px] h-[78vh] flex flex-col"
           onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 shrink-0">
          <div className="flex items-center gap-3">
            <h3 className="font-semibold text-gray-800">🕸 概念图谱</h3>
            {!hasGraph && !generating && (
              <button onClick={handleGenerate}
                className="bg-indigo-600 text-white px-3 py-1 rounded-lg text-xs hover:bg-indigo-700">
                ✨ 生成图谱
              </button>
            )}
            {generating && (
              <span className="text-xs text-indigo-600 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse" />
                {progress}
              </span>
            )}
            {hasGraph && !generating && (
              <button onClick={handleGenerate}
                className="text-indigo-600 text-xs hover:text-indigo-800">
                🔄 重新生成
              </button>
            )}
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-sm px-1">✕</button>
        </div>

        {/* Body */}
        <div className="flex-1 flex overflow-hidden">
          <div className="flex-1">
            {hasGraph ? (
              <ReactFlow
                nodes={layout.nodes}
                edges={layout.edges}
                nodeTypes={nodeTypes}
                fitView
                minZoom={0.3}
                onNodeClick={(_, node) => setSelected({
                  label: node.data.label,
                  section_index: (node.data.sectionTitle || '').replace(/^第\d+ 节/, ''),
                  sectionTitle: node.data.sectionTitle,
                })}
              >
                <Background gap={16} />
                <Controls />
              </ReactFlow>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-gray-400">
                <p className="text-4xl mb-3">🕸</p>
                <p className="text-sm">暂无概念图谱</p>
                <p className="text-xs mt-1">点击右上角「✨ 生成图谱」，AI 将从讲义提取概念与关系</p>
              </div>
            )}
          </div>

          {/* Detail panel */}
          {selected && (
            <div className="w-60 border-l border-gray-100 p-4 shrink-0">
              <p className="text-sm font-medium text-gray-800">{selected.label}</p>
              <p className="text-xs text-gray-400 mt-1">{selected.sectionTitle}</p>
              <p className="text-[11px] text-gray-500 mt-3 leading-relaxed">
                在讲义「{selected.sectionTitle}」中讲解。图谱按小节分列：同一列的概念来自同一个小节。
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
