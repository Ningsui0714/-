import { useCallback } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  MarkerType,
  useNodesState,
  useEdgesState,
  NodeProps,
  Handle,
  Position,
} from 'reactflow'
import 'reactflow/dist/style.css'

interface CheckpointNode {
  id: number
  title: string
  description: string
  order: number
  prerequisites: number[]
  completed: boolean
  chunk_ids: number[]
  archived?: boolean
  progress?: any
  learning_status?: 'not_started' | 'in_progress' | 'verification_due' | 'blocked' | 'completed'
}

interface Props {
  checkpoints: CheckpointNode[]
  onCheckpointClick?: (id: number) => void
}

function CheckpointNodeComponent({ data }: NodeProps) {
  const { label, completed, description, progress, learningStatus } = data as any
  const status = learningStatus || (completed ? 'completed' : 'not_started')
  const statusStyle: Record<string, string> = {
    completed: 'bg-emerald-50 border-emerald-400',
    verification_due: 'bg-amber-50 border-amber-400',
    blocked: 'bg-red-50 border-red-300',
    in_progress: 'bg-indigo-50 border-indigo-400',
    not_started: 'bg-white border-gray-300 hover:border-indigo-400',
  }
  const dotStyle: Record<string, string> = {
    completed: 'bg-emerald-500',
    verification_due: 'bg-amber-500',
    blocked: 'bg-red-500',
    in_progress: 'bg-indigo-500',
    not_started: 'bg-gray-300',
  }
  const statusLabel: Record<string, string> = {
    completed: '已验证', verification_due: '待验证', blocked: '受阻',
    in_progress: '进行中', not_started: '未开始',
  }
  const conceptTotal = progress?.concept_total || 0
  const conceptCorrect = progress?.concept_correct || 0
  const exercisesDone = progress?.exercises_done || 0
  const hasProgress = conceptTotal > 0 || exercisesDone > 0
  return (
    <div
      className={`
        px-4 py-3 rounded-xl shadow-sm border-2 min-w-[180px] cursor-pointer
        transition-all hover:shadow-md
        ${statusStyle[status] || statusStyle.not_started}
      `}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <div className="flex items-center gap-2">
        <span className={`w-3 h-3 rounded-full ${dotStyle[status] || dotStyle.not_started}`} />
        <span className="font-medium text-sm text-gray-900">{label}</span>
      </div>
      <p className={`mt-1 text-[10px] ${status === 'verification_due' ? 'text-amber-700' : 'text-gray-500'}`}>
        {statusLabel[status] || statusLabel.not_started}
      </p>
      {hasProgress && (
        <div className="flex gap-1.5 mt-1.5">
          {exercisesDone > 0 && (
            <span className="text-[10px] bg-green-50 text-green-600 px-1.5 py-0.5 rounded-full">
              💻 {exercisesDone}
            </span>
          )}
          {conceptTotal > 0 && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
              conceptCorrect === conceptTotal ? 'bg-green-50 text-green-600' : 'bg-amber-50 text-amber-600'
            }`}>
              🧠 {conceptCorrect}/{conceptTotal}
            </span>
          )}
        </div>
      )}
      {description && (
        <p className="text-xs text-gray-500 mt-1 line-clamp-2">{description}</p>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-gray-400" />
    </div>
  )
}

const nodeTypes = { checkpoint: CheckpointNodeComponent }

export default function CheckpointGraph({ checkpoints, onCheckpointClick }: Props) {
  // T10: archived checkpoints are hidden from the roadmap (products kept)
  const visible = checkpoints.filter(cp => !cp.archived)
  // Build nodes and edges from checkpoint data
  const initialNodes: Node[] = visible.map(cp => ({
    id: String(cp.id),
    type: 'checkpoint',
    position: { x: 0, y: 0 }, // Will be laid out below
    data: {
      label: cp.title,
      completed: cp.completed,
      description: cp.description,
      checkpointId: cp.id,
      progress: cp.progress,
      learningStatus: cp.learning_status,
    },
    draggable: true,
  }))

  const initialEdges: Edge[] = []
  // NOTE: prerequisites 存的是 order（后端全链路语义），需映射到真实 checkpoint id
  const orderToId: Record<number, number> = {}
  for (const cp of visible) orderToId[cp.order] = cp.id
  for (const cp of visible) {
    for (const prereqOrder of cp.prerequisites) {
      const prereqId = orderToId[prereqOrder]
      if (prereqId === undefined) continue
      initialEdges.push({
        id: `e${prereqId}-${cp.id}`,
        source: String(prereqId),
        target: String(cp.id),
        type: 'smoothstep',
        animated: cp.learning_status === 'in_progress',
        style: { stroke: '#6366f1', strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#6366f1' },
      })
    }
  }

  // Layout: arrange in columns by position
  const layoutNodes = layoutCheckpoints(initialNodes, visible)

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  const onNodeClick = useCallback((_: any, node: Node) => {
    if (onCheckpointClick) {
      onCheckpointClick(node.data.checkpointId)
    }
  }, [onCheckpointClick])

  if (checkpoints.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
        暂无路线图，在上方对话框中开始规划
      </div>
    )
  }

  return (
    <div className="h-[500px] rounded-xl border border-gray-200 bg-gray-50">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        attributionPosition="bottom-left"
      >
        <Background color="#e5e7eb" gap={20} />
        <Controls />
        <MiniMap
          nodeStrokeColor="#6366f1"
          nodeColor="#e0e7ff"
          maskColor="rgba(0,0,0,0.1)"
        />
      </ReactFlow>
    </div>
  )
}

function layoutCheckpoints(
  nodes: Node[],
  checkpoints: CheckpointNode[]
): Node[] {
  const maxPerRow = 4
  const xSpacing = 280
  const ySpacing = 160

  // Build dependency levels using BFS
  const levels: number[] = []
  const orderToLevel: Record<number, number> = {}
  const orderToId: Record<number, number> = {}

  for (const cp of checkpoints) {
    orderToId[cp.order] = cp.id
  }

  const getLevel = (order: number): number => {
    if (order in orderToLevel) return orderToLevel[order]
    const cp = checkpoints.find(c => c.order === order)
    if (!cp || cp.prerequisites.length === 0) {
      orderToLevel[order] = 0
      return 0
    }
    const maxPrereqLevel = Math.max(
      // prerequisites 是 order，直接按 order 递归求层级
      ...cp.prerequisites.map(p => getLevel(p))
    )
    orderToLevel[order] = maxPrereqLevel + 1
    return orderToLevel[order]
  }

  for (const cp of checkpoints) {
    getLevel(cp.order)
  }

  // Group by level
  const levelGroups: Record<number, number[]> = {}
  for (const cp of checkpoints) {
    const lvl = orderToLevel[cp.order] ?? 0
    if (!levelGroups[lvl]) levelGroups[lvl] = []
    levelGroups[lvl].push(cp.order)
  }

  // Position nodes
  return nodes.map(node => {
    const cp = checkpoints.find(c => c.id === Number(node.id))
    if (!cp) return node
    const lvl = orderToLevel[cp.order] ?? 0
    const itemsInLevel = levelGroups[lvl] || []
    const idx = itemsInLevel.indexOf(cp.order)
    const levelWidth = itemsInLevel.length * xSpacing
    const startX = -levelWidth / 2 + xSpacing / 2

    return {
      ...node,
      position: {
        x: startX + idx * xSpacing,
        y: lvl * ySpacing + 40,
      },
    }
  })
}
