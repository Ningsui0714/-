export type WorkspaceAgentContext =
  | {
      kind: 'learning_design'
      checkpointId: number
      title?: string
      selection?: string
      sectionIndex?: number
    }
  | {
      kind: 'practice'
      checkpointId: number
      exerciseId?: number
      title?: string
      selection?: string
      code?: string
    }
  | {
      kind: 'project_tutor'
      projectId: number
      projectProposal?: any
      projectSources?: Array<{ url?: string }>
      candidateSourcesRefreshing?: boolean
      addingCandidateUrl?: string | null
      onRefreshCandidateSources?: () => void | Promise<void>
      onAddCandidateSource?: (candidate: any) => void | Promise<void>
      onRoadmapUpdate?: (roadmap: any) => void
    }

let currentContext: WorkspaceAgentContext | null = null
const listeners = new Set<(context: WorkspaceAgentContext) => void>()

export function publishWorkspaceAgentContext(context: WorkspaceAgentContext) {
  currentContext = context
  listeners.forEach(listener => listener(context))
}

export function subscribeWorkspaceAgentContext(listener: (context: WorkspaceAgentContext) => void) {
  if (currentContext) listener(currentContext)
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
