import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 90000,
  withCredentials: true,
})

const DESKTOP_AUTH_STORAGE_KEY = 'learnflow.desktop.auth-token'

export function configureDesktopApi(baseURL: string, desktopToken: string) {
  api.defaults.baseURL = baseURL
  api.defaults.headers.common['X-LearnFlow-Desktop-Token'] = desktopToken
  const authToken = sessionStorage.getItem(DESKTOP_AUTH_STORAGE_KEY)
  if (authToken) api.defaults.headers.common.Authorization = `Bearer ${authToken}`
}

api.interceptors.response.use(
  response => {
    const desktopAuthToken = response?.data?.desktop_auth_token
    if (typeof desktopAuthToken === 'string' && desktopAuthToken) {
      sessionStorage.setItem(DESKTOP_AUTH_STORAGE_KEY, desktopAuthToken)
      api.defaults.headers.common.Authorization = `Bearer ${desktopAuthToken}`
    }
    return response
  },
  error => {
    if (error?.response?.status === 401) {
      window.dispatchEvent(new CustomEvent('learnflow:unauthorized'))
    }
    return Promise.reject(error)
  },
)

export interface AuthUser {
  id: number
  username: string
  display_name: string
  learner_id: number
  is_legacy_demo: boolean
  is_dev_login: boolean
  dev_test_login_enabled: boolean
  desktop_auth_token?: string
  profile: {
    education_stage: string
    background: string
    focus_areas: string[]
    weekly_hours: number
    preferred_modes: string[]
    career_goal: string
    career_goal_status: 'exploring' | 'confirmed'
  }
}

export interface RegisterPayload {
  username: string
  password: string
  display_name: string
  education_stage: string
  background: string
  focus_areas: string[]
  weekly_hours: number
  preferred_modes: string[]
  career_goal?: string
  career_goal_status: 'exploring' | 'confirmed'
}

export const getCurrentUser = () => api.get('/auth/me').then(r => r.data as AuthUser)
export const loginUser = (username: string, password: string) =>
  api.post('/auth/login', { username, password }).then(r => r.data as AuthUser)
export const registerUser = (data: RegisterPayload) =>
  api.post('/auth/register', data).then(r => r.data as AuthUser)
export const logoutUser = () => api.post('/auth/logout').then(r => {
  sessionStorage.removeItem(DESKTOP_AUTH_STORAGE_KEY)
  delete api.defaults.headers.common.Authorization
  return r.data
})
export const listDevAccounts = () => api.get('/dev/accounts').then(r => r.data)
export const devLogin = (accountId: number) =>
  api.post(`/dev/accounts/${accountId}/login`).then(r => r.data as AuthUser)

export const getProfile = () => api.get('/profile').then(r => r.data)
export const updateProfile = (data: Record<string, any>) => api.patch('/profile', data).then(r => r.data)
export const getProfileMemories = () => api.get('/profile/memories').then(r => r.data)
export const archiveProfileMemory = (memoryId: string, reason = '') =>
  api.post(`/profile/memories/${encodeURIComponent(memoryId)}/archive`, { reason }).then(r => r.data)
export const restoreProfileMemory = (memoryId: string) =>
  api.post(`/profile/memories/${encodeURIComponent(memoryId)}/restore`).then(r => r.data)
export const getLearningJourney = () => api.get('/profile/journey').then(r => r.data)

// ── 岗位典型工作任务转化（外部星辰工作流适配器） ──
export interface LearningTaskStepHandoff {
  step: number
  step_id: string
  name: string
  action: string
  instruction?: string
  deliverable: string
  check: string
  knowledge_point_ids: string[]
  skill_point_ids: string[]
}

export interface LearningTaskKnowledgePoint {
  knowledge_id: string
  display_code?: string
  name: string
  scope?: string
  description?: string
  concept?: string
  operation?: string
  verification?: string
  learning_resources?: LearningTaskResource[]
  personalized_learning_entry?: Record<string, any>
}

export interface LearningTaskResource {
  resource_id?: string
  platform?: string
  resource_name: string
  resource_type?: string
  resource_url: string
  usage?: string
  link_kind?: string
  link_verified?: boolean
  content_verified?: boolean
  review_status?: string
}

export interface LearningTaskSkillPoint {
  skill_id: string
  display_code?: string
  name: string
  observable_action?: string
  expected_artifact?: string
  description?: string
}

export interface LearningTaskConversionBundle {
  schema_version: 'learning-task-conversion-integration-bundle-v1'
  task_card_id: string
  status: string
  verification_status: string
  task: {
    schema_version: 'learning-task-to-personalized-learning-v1'
    work_task: {
      work_task_id: string
      enterprise_task_name: string
      enterprise_task_description?: string
      teaching_task_name: string
      teaching_task_description?: string
      work_situation?: string | Record<string, any>
      task_scenario?: string | Record<string, any>
      safety_points?: Array<string | Record<string, any>>
      expected_artifacts?: Array<string | Record<string, any>>
      acceptance_tests?: Array<string | Record<string, any>>
      task_steps: LearningTaskStepHandoff[]
      knowledge_points: LearningTaskKnowledgePoint[]
      skill_points: LearningTaskSkillPoint[]
      tools?: string[]
    }
    knowledge_entry_contract?: Record<string, any>
  }
  strong_relationships: Array<Record<string, any>>
  traceability?: Record<string, any>
  upstream_feedback?: Record<string, any>
  downstream_feedback?: Record<string, any>
  artifacts: {
    interactive_html_url: string
    pdf_url: string
    personalized_learning_json_url: string
    feedback_json_url?: string
  }
}

export interface WF03GenerationResult {
  schema_version: 'learnflow-learning-task-generation-v2'
  execute_id: string
  status: 'success' | 'needs_clarification' | 'needs_revision'
  task_card_id: string
  message: string
  bundle: LearningTaskConversionBundle | null
  replayed?: boolean
}

export type WF03FeedbackCode =
  | 'weak_relation'
  | 'incorrect_knowledge_scope'
  | 'incorrect_skill_scope'
  | 'step_mapping_mismatch'
  | 'missing_prerequisite'
  | 'unsupported_task_fact'
  | 'other'

export interface WF03FeedbackIssue {
  issue_id: string
  feedback_code: WF03FeedbackCode
  severity: 'info' | 'warning' | 'error'
  relation_id?: string
  step_id?: string
  knowledge_id?: string
  skill_id?: string
  message: string
  suggested_correction: string
}

export interface PersonalizedLearningKnowledgeEntry {
  schema_version: 'learning-task-knowledge-to-personalized-learning-v1'
  entry_id: string
  status: 'ready'
  source: {
    source_system: string
    task_card_id: string
    verification_status: string
    full_handoff_json_url: string
  }
  task_context: {
    work_task_id: string
    enterprise_task_name: string
    enterprise_task_description: string
    teaching_task_name: string
    teaching_task_description: string
    work_situation?: string | Record<string, any>
  }
  focus: {
    knowledge_point: LearningTaskKnowledgePoint
    source_steps: LearningTaskStepHandoff[]
    strongly_related_skills: LearningTaskSkillPoint[]
    relationships: Array<Record<string, any>>
  }
  generation_contract: {
    purpose: string
    immutable_fields: string[]
    downstream_may_generate: string[]
    must_preserve_relation_traceability: boolean
  }
  feedback_contract: {
    schema_version: 'personalized-learning-to-task-conversion-feedback-v1'
    method: 'POST'
    url: string
    supported_issue_targets: string[]
  }
  navigation: {
    route_key: 'personalized_learning.generate_from_knowledge'
    entry_path: string
    handoff_json_path: string
    return_path: string
  }
}

export interface PersonalizedLearningLaunchResult {
  status: 'ok'
  entry_id: string
  project_id: string
  knowledge_point_id: string
  redirect_url: string
  content_generation: {
    provider: 'deepseek' | 'spark_openai_compatible' | 'deterministic_template'
    model: string
    configured: boolean
  }
  assessment: {
    type: 'provisional_self_check'
    status: 'queued' | 'generating' | 'ready' | 'failed'
    formal_evidence: false
  }
  created: boolean
}

export interface PersonalizedLearningResultPayload {
  schema_version: 'personalized-learning-result-v1'
  entry_id: string
  project_id: string
  knowledge_point_id: string
  result_type: 'assessment_completed'
  result_id: string
  formal_evidence: false
  summary: {
    assessment_type: 'provisional_self_check'
    score: number
    total: number
    weak_point_count: number
    feedback: string
  }
}

export interface PersonalizedLearningResultReceipt {
  status: 'accepted'
  event_id: number
  result_id: string
  formal_evidence: false
}

export const getLearningTaskConversionCapabilities = () =>
  api.get('/learning-task-conversion/capabilities').then(r => r.data)

export interface LearningTaskConversionWorkflowRun {
  schema_version: 'learning-task-conversion-xfyun-run-v1'
  provider: 'xunfei-xingchen'
  app_id: string
  flow_id: string
  run_id?: string
  content: string
  usage: Record<string, any>
}

export interface LearningTaskPlanUnknown {
  unknown_id: string
  question: string
  required_evidence: 'upstream' | 'database' | 'knowledge_base' | 'official_web' | 'official_or_upstream' | 'user_confirmation'
  blocking: boolean
}

export interface LearningTaskPlanWorkPackage {
  package_id: string
  agent_role: string
  objective: string
  depends_on: string[]
  allowed_tools: string[]
  expected_artifact: string
  completion_condition: string
}

export interface LearningTaskPlanArtifact {
  schema_version: 'learning-work-task-plan-v1'
  run_id: string
  plan_version: number
  goal: string
  task_contract_fingerprint: string
  success_criteria: string[]
  unknowns: LearningTaskPlanUnknown[]
  work_packages: LearningTaskPlanWorkPackage[]
  repair_budget: number
  stop_conditions: string[]
}

export interface LearningTaskPlanCandidate {
  candidate_id: string
  strategy: 'fidelity_first' | 'evidence_first' | 'balanced_parallel'
  title: string
  ordered_package_ids: string[]
  parallel_waves: string[][]
  scores: Record<string, number>
  weighted_score: number
  hard_gate_passed: boolean
  tradeoffs: string[]
}

export interface LearningTaskPlanCritic {
  critic_id: string
  dimension: 'task_identity' | 'dependency' | 'evidence' | 'safety' | 'deliverable' | 'teaching_fit'
  verdict: 'pass' | 'warning' | 'fail'
  score: number
  findings: string[]
  affected_package_ids: string[]
}

export interface LearningTaskPlanRisk {
  risk_id: string
  package_id: string
  category: 'evidence' | 'dependency' | 'safety' | 'artifact' | 'mapping'
  likelihood: 'low' | 'medium' | 'high'
  impact: 'low' | 'medium' | 'high'
  mitigation: string
  evidence_required: boolean
}

export interface LearningTaskPlanRevision {
  revision_id: string
  analysis_version: number
  parent_revision_id: string | null
  cause: string
  failure_code: string | null
  affected_package_ids: string[]
  preserved_package_ids: string[]
  controls_added: string[]
}

export type LearningTaskPlanStageStatus = 'completed' | 'ready' | 'blocked' | 'pending' | 'not_started'

export interface LearningTaskPlanStageSubstep {
  substep_id: string
  label: string
  status: LearningTaskPlanStageStatus
  detail: string
  parent_substep_id: string | null
  depends_on: string[]
  output_ref: string | null
}

export interface LearningTaskPlanStage {
  stage_id: 'task_contract' | 'grounding_clarification' | 'evidence_search_planning' | 'evidence_grounded_task_planning' | 'critic_finalize' | 'execution_handoff'
  sequence: number
  label: string
  status: LearningTaskPlanStageStatus
  summary: string
  input_refs: string[]
  output_refs: string[]
  substeps: LearningTaskPlanStageSubstep[]
}

export interface LearningTaskPlanExecutionItem {
  package_id: string
  objective: string
  status: 'pending' | 'in_progress' | 'completed' | 'blocked'
  expected_artifact: string
  observation_state: 'not_observed' | 'observed' | 'accepted' | 'rejected'
  completion_condition: string
}

export interface LearningTaskPlanHandoffArtifact {
  artifact_id: string
  artifact_type: 'html' | 'pdf' | 'versioned_json' | 'knowledge_learning_entry' | 'feedback_contract'
  label: string
  status: 'planned' | 'ready' | 'generated'
  contract_ref: string
}

export interface LearningTaskPlanningAnalysis {
  schema_version: 'learning-work-task-planning-analysis-v3'
  run_id: string
  plan_version: number
  analysis_version: number
  planning_status: 'ready_for_confirmation' | 'planned_not_executed' | 'replanned_not_executed' | 'needs_evidence'
  active_revision_id: string
  hierarchy: Array<{
    node_id: string
    node_type: 'goal' | 'phase' | 'work_package' | 'atomic_step'
    parent_id: string | null
    label: string
    objective: string
    package_id: string | null
    depth: number
  }>
  graph_edges: Array<{ source: string; target: string; edge_type: string }>
  topological_waves: string[][]
  critical_path: string[]
  candidates: LearningTaskPlanCandidate[]
  critics: LearningTaskPlanCritic[]
  risks: LearningTaskPlanRisk[]
  decision: {
    code: 'SELECT_CANDIDATE' | 'REQUEST_EVIDENCE' | 'LOCAL_REPLAN' | 'STOP'
    selected_candidate_id: string | null
    confidence: number
    reasons: string[]
    triggered_rules: string[]
  }
  stages: LearningTaskPlanStage[]
  execution_checklist: LearningTaskPlanExecutionItem[]
  handoff_artifacts: LearningTaskPlanHandoffArtifact[]
  evidence_semantics: 'operational_only'
  revision_history: LearningTaskPlanRevision[]
  repair_budget_remaining: number
  metrics: Record<string, number>
}

export interface LearningTaskPlanRun {
  schema_version: 'learning-work-task-agent-state-v1'
  run_id: string
  phase: 'INTAKE' | 'CONTRACT_READY' | 'PLAN_READY' | 'EVIDENCE_READY' | 'STEP_PLAN_READY' | 'CANDIDATES_READY' | 'REVIEWED' | 'PATCH_REQUIRED' | 'COMMIT_READY' | 'COMMITTED' | 'FAILED'
  status: 'active' | 'needs_input' | 'completed' | 'failed'
  checkpoint_version: number
  task_contract: Record<string, any>
  plan: LearningTaskPlanArtifact
  state: Record<string, any>
  next_actions: string[]
  message: string
  workspace_path: string
  planning_analysis: LearningTaskPlanningAnalysis
}

export const createLearningTaskPlan = (
  query: string,
  sessionId: number,
  clientTurnId: string,
) => api.post('/learning-task-conversion/plans', {
  query,
  session_id: sessionId,
  client_turn_id: clientTurnId,
}).then(r => r.data as LearningTaskPlanRun)

export const getLearningTaskPlan = (runId: string) =>
  api.get(`/learning-task-conversion/plans/${encodeURIComponent(runId)}`)
    .then(r => r.data as LearningTaskPlanRun)

export const confirmLearningTaskPlan = (
  runId: string,
  expectedPlanVersion: number,
  clientEventId?: string,
) => api.post(
  `/learning-task-conversion/plans/${encodeURIComponent(runId)}/confirm`,
  {
    expected_plan_version: expectedPlanVersion,
    client_event_id: clientEventId,
  },
).then(r => r.data as LearningTaskPlanRun)

export const replanLearningTaskPlan = (
  runId: string,
  targetPackageId: string,
  failureCode: 'evidence_gap' | 'dependency_blocked' | 'safety_conflict' | 'artifact_rejected' | 'mapping_conflict',
  observation: string,
  expectedAnalysisVersion: number,
  clientEventId?: string,
) => api.post(
  `/learning-task-conversion/plans/${encodeURIComponent(runId)}/replan`,
  {
    target_package_id: targetPackageId,
    failure_code: failureCode,
    observation,
    expected_analysis_version: expectedAnalysisVersion,
    client_event_id: clientEventId,
  },
).then(r => r.data as LearningTaskPlanRun)

export const runLearningTaskConversionWorkflow = (userInput: string) =>
  api.post('/learning-task-conversion/workflow-runs', { user_input: userInput }, {
    timeout: 240000,
  }).then(r => r.data as LearningTaskConversionWorkflowRun)

export const generateLearningTaskConversion = (
  query: string,
  sessionId?: number,
  clientTurnId?: string,
) =>
  api.post('/learning-task-conversion/generate', {
    query,
    session_id: sessionId,
    client_turn_id: clientTurnId,
  }, { timeout: 300000 })
    .then(r => r.data as WF03GenerationResult)

export const submitCompetencyGraphHandoff = (handoff: Record<string, any>) =>
  api.post('/learning-task-conversion/upstream-handoffs', handoff).then(r => r.data)

export const getLearningTaskConversionBundle = (taskCardId: string) =>
  api.get(`/learning-task-conversion/tasks/${encodeURIComponent(taskCardId)}/bundle`)
    .then(r => r.data as LearningTaskConversionBundle)

export const getPersonalizedLearningHandoff = (taskCardId: string) =>
  api.get(`/learning-task-conversion/tasks/${encodeURIComponent(taskCardId)}/personalized-learning`)
    .then(r => r.data)

const personalizedLearningKnowledgeEntryPath = (
  taskCardId: string,
  knowledgeId: string,
) => (
  `/learning-task-conversion/tasks/${encodeURIComponent(taskCardId)}`
  + `/knowledge/${encodeURIComponent(knowledgeId)}/personalized-learning-entry`
)

export const getPersonalizedLearningKnowledgeEntry = (
  taskCardId: string,
  knowledgeId: string,
) => api.get(personalizedLearningKnowledgeEntryPath(taskCardId, knowledgeId))
  .then(r => r.data as PersonalizedLearningKnowledgeEntry)

export const openPersonalizedLearningKnowledgeEntry = (
  taskCardId: string,
  knowledgeId: string,
) => api.post(personalizedLearningKnowledgeEntryPath(taskCardId, knowledgeId))
  .then(r => r.data as PersonalizedLearningKnowledgeEntry)

export const launchPersonalizedLearningKnowledgeEntry = (
  taskCardId: string,
  knowledgeId: string,
) => api.post(
  `/learning-task-conversion/tasks/${encodeURIComponent(taskCardId)}`
  + `/knowledge/${encodeURIComponent(knowledgeId)}/personalized-learning-launch`,
).then(r => r.data as PersonalizedLearningLaunchResult)

export const submitPersonalizedLearningResult = (
  taskCardId: string,
  knowledgeId: string,
  payload: PersonalizedLearningResultPayload,
) => api.post(
  `/learning-task-conversion/tasks/${encodeURIComponent(taskCardId)}`
  + `/knowledge/${encodeURIComponent(knowledgeId)}/personalized-learning-results`,
  payload,
).then(r => r.data as PersonalizedLearningResultReceipt)

export const submitPersonalizedLearningFeedback = (feedback: Record<string, any>) =>
  api.post('/learning-task-conversion/downstream-feedback', feedback).then(r => r.data)

export type MemoryKernel = 'structure' | 'knowledge' | 'human' | 'value' | 'practice'
export type MemoryNodeType = 'fact' | 'module' | 'claim'

export interface MemoryGraphNode {
  id: number
  type: MemoryNodeType
  kernel: MemoryKernel
  subject: string
  text: string
  payload: Record<string, any>
  confidence: number
  status: string
  valid_from?: string
  valid_to?: string
  occurred_at: string
  created_at: string
  fact?: {
    source_event_id: number
    source_mutation_id: number
    predicate: string
    value: any
    evidence_grade: string
    consumption_status: string
    consumed_by_module_id?: number
    project_id?: number
    checkpoint_id?: number
    session_id?: number
  }
  module?: {
    synthesis_run_id?: number
    module_type: string
    summary: string
    time_start: string
    time_end: string
    immutable: boolean
  }
  claim?: {
    module_id: number
    predicate: string
    value: any
    verification_status: string
  }
}

export interface MemoryGraphEdge {
  id: number
  source: number
  target: number
  relation: string
  origin: string
  confidence: number
  payload: Record<string, any>
}

export interface MemoryGraphResponse {
  nodes: MemoryGraphNode[]
  edges: MemoryGraphEdge[]
  page: { limit: number; has_more: boolean; next_after_id?: number }
}

export const getMemoryGraph = (params: Record<string, string | number | undefined> = {}) =>
  api.get('/memory/graph', { params }).then(r => r.data as MemoryGraphResponse)

export const getMemoryNode = (nodeId: number) =>
  api.get(`/memory/nodes/${nodeId}`).then(r => r.data)

export const getMemoryConsolidations = (status?: string) =>
  api.get('/memory/consolidations', { params: { status } }).then(r => r.data)

export const submitMemoryClaimFeedback = (
  claimId: number,
  data: { action: 'confirm' | 'correct' | 'retract'; correction?: string; reason?: string },
) => api.post(`/memory/claims/${claimId}/feedback`, data).then(r => r.data)

// ── Project ──
export const createProject = (data: { name: string; description?: string; user_level?: string }) =>
  api.post('/projects', data).then(r => r.data)

export const listProjects = () =>
  api.get('/projects').then(r => r.data)

export const getProject = (id: number) =>
  api.get(`/projects/${id}`).then(r => r.data)

// ── Desktop project workspace ──
export type WorkspaceNodeKind =
  | 'managed_lecture'
  | 'managed_exercise'
  | 'workspace_text'
  | 'workspace_binary'
  | 'protected'

export interface WorkspaceNode {
  name: string
  path: string
  kind: WorkspaceNodeKind
  is_directory: boolean
  size?: number
  modified_at?: string
  protected_reason?: string
  children: WorkspaceNode[]
}

export interface WorkspaceTree {
  workspace_id: number
  project_id: number
  root_name: string
  nodes: WorkspaceNode[]
}

export interface WorkspaceFile {
  path: string
  kind: WorkspaceNodeKind
  content?: string
  sha256?: string
  size: number
  modified_at: string
  read_only: boolean
  mime_type?: string
  previewable: boolean
}

export interface WorkspaceOperation {
  id: number
  project_id: number
  actor: 'user' | 'agent'
  operation: 'create' | 'write' | 'mkdir' | 'rename' | 'move' | 'delete' | 'restore'
  status: string
  target_path: string
  destination_path?: string
  base_hash?: string
  result: Record<string, any>
  expires_at?: string
  created_at: string
  confirmed_at?: string
  applied_at?: string
}

const workspaceFileUrl = (projectId: number, path: string) =>
  `/projects/${projectId}/workspace/files/${path.split('/').map(encodeURIComponent).join('/')}`

export const linkProjectWorkspace = (
  projectId: number,
  data: { root_path: string; platform: string; create: boolean; client_request_id: string },
) => api.post(`/projects/${projectId}/workspace/link`, data).then(r => r.data)

export const getWorkspaceTree = (projectId: number) =>
  api.get(`/projects/${projectId}/workspace/tree`).then(r => r.data as WorkspaceTree)

export const getCheckpointWorkspaceArtifacts = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/workspace/artifacts`).then(r => r.data)

export const getWorkspaceFile = (projectId: number, path: string) =>
  api.get(workspaceFileUrl(projectId, path)).then(r => r.data as WorkspaceFile)

export const saveWorkspaceFile = (
  projectId: number,
  path: string,
  data: { content: string; base_hash?: string; idempotency_key: string },
) => api.put(workspaceFileUrl(projectId, path), data).then(r => r.data as WorkspaceOperation)

export const proposeWorkspaceOperation = (
  projectId: number,
  data: {
    actor: 'user' | 'agent'
    operation: WorkspaceOperation['operation']
    target_path: string
    destination_path?: string
    content?: string
    base_hash?: string
    checkpoint_id?: number
    session_id?: number
    source_operation_id?: number
    idempotency_key: string
  },
) => api.post(`/projects/${projectId}/workspace/operations/propose`, data)
  .then(r => r.data as WorkspaceOperation)

export const confirmWorkspaceOperation = (projectId: number, operationId: number) =>
  api.post(`/projects/${projectId}/workspace/operations/${operationId}/confirm`)
    .then(r => r.data as WorkspaceOperation)

export const listWorkspaceOperations = (
  projectId: number,
  params: { operation?: string; status?: string } = {},
) => api.get(`/projects/${projectId}/workspace/operations`, { params })
  .then(r => r.data.operations as WorkspaceOperation[])

export const revealWorkspaceItem = (projectId: number, path: string) =>
  api.post(`/projects/${projectId}/workspace/reveal`, { path }).then(r => r.data)

export const openWorkspaceItem = (projectId: number, path: string) =>
  api.post(`/projects/${projectId}/workspace/open`, { path }).then(r => r.data)

const workspacePreviewUrl = (projectId: number, path: string) =>
  `/projects/${projectId}/workspace/previews/${path.split('/').map(encodeURIComponent).join('/')}`

export const getWorkspacePreview = (projectId: number, path: string) =>
  api.get(workspacePreviewUrl(projectId, path), { responseType: 'blob' })
    .then(r => URL.createObjectURL(r.data))

// ── Source ──
export const addSource = (projectId: number, data: { type: string; url?: string }) =>
  api.post(`/projects/${projectId}/sources`, data).then(r => r.data)

export const uploadSource = (projectId: number, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post(`/projects/${projectId}/sources/upload`, form).then(r => r.data)
}

export const listSources = (projectId: number) =>
  api.get(`/projects/${projectId}/sources`).then(r => r.data)

export const processSource = (projectId: number, sourceId: number) =>
  api.post(`/projects/${projectId}/sources/${sourceId}/process`).then(r => r.data)

export const processAllSources = (projectId: number) =>
  api.post(`/projects/${projectId}/sources/process-all`).then(r => r.data)

export const startImageCaptioning = (projectId: number, sourceId: number, limit?: number, mode: 'free' | 'api' = 'free') =>
  api.post(`/projects/${projectId}/sources/${sourceId}/images/caption`, { limit, mode }).then(r => r.data)

export const setSourceRole = (projectId: number, sourceId: number, role: 'main' | 'auxiliary') =>
  api.put(`/projects/${projectId}/sources/${sourceId}/role`, { role }).then(r => r.data)

export const reconcileSources = (projectId: number) =>
  api.post(`/projects/${projectId}/reconcile`).then(r => r.data)

export const applyReconcile = (projectId: number, suggestion: any) =>
  api.post(`/projects/${projectId}/reconcile/apply`, suggestion).then(r => r.data)

// ── Chunk ──
export const listChunks = (projectId: number) =>
  api.get(`/projects/${projectId}/chunks`).then(r => r.data)

// ── Roadmap ──
export const getRoadmap = (projectId: number) =>
  api.get(`/projects/${projectId}/roadmap`).then(r => r.data)

// ── Agent ──
export const sendAgentMessage = (projectId: number, data: { message: string; history: any[] }) =>
  api.post(`/projects/${projectId}/roadmap/chat`, data).then(r => r.data)

export const getRoadmapHistory = (projectId: number) =>
  api.get(`/projects/${projectId}/roadmap/history`).then(r => r.data)

// ── Main Tutor ──
export const createTutorSession = (data: { session_type?: 'global' | 'project' | 'checkpoint'; project_id?: number; checkpoint_id?: number; force_new?: boolean }) =>
  api.post('/agent/sessions', data).then(r => r.data)

export const getTutorSession = (sessionId: number) =>
  api.get(`/agent/sessions/${sessionId}`).then(r => r.data)

export const sendTutorTurn = (sessionId: number, data: {
  message: string
  project_id?: number
  checkpoint_id?: number
  selected_action_id?: number
  client_turn_id?: string
  context?: Record<string, any>
}) => api.post(`/agent/sessions/${sessionId}/turns`, data).then(r => r.data)

export const confirmTutorAction = (actionId: number) =>
  api.post(`/agent/actions/${actionId}/confirm`).then(r => r.data)

export const cancelTutorAction = (actionId: number) =>
  api.post(`/agent/actions/${actionId}/cancel`).then(r => r.data)

export const getTutorAction = (actionId: number) =>
  api.get(`/agent/actions/${actionId}`).then(r => r.data)

export interface LocalAgentProfile {
  id: number
  name: string
  adapter: 'codex_cli' | 'deterministic_fake'
  executable_path?: string | null
  enabled: boolean
  priority: number
  task_types: string[]
  capabilities: string[]
  sandbox_policy: string
  network_policy: 'unmanaged' | 'managed_off' | 'managed_on'
  timeout_seconds: number
  last_probe: Record<string, any>
}

export interface LocalAgentRun {
  id: number
  project_id: number
  checkpoint_id: number
  session_id: number
  action_id: number
  profile_id: number
  task_type: string
  goal: string
  constraints: string[]
  required_capabilities: string[]
  status: 'queued' | 'running' | 'completed' | 'failed' | 'canceled' | 'stale' | 'applied'
  changed_files: Array<{
    operation: 'create' | 'write' | 'delete' | 'move'
    path: string
    destination_path?: string
    diff?: string
    requires_separate_confirmation?: boolean
  }>
  diff_text: string
  result: Record<string, any>
  error: Record<string, any>
}

export const listLocalAgentProfiles = () =>
  api.get('/desktop/agent-profiles').then(r => r.data as LocalAgentProfile[])

export const createLocalAgentProfile = (data: {
  name: string
  adapter?: 'codex_cli'
  executable_path?: string | null
  enabled?: boolean
  priority?: number
  task_types?: string[]
  capabilities?: string[]
  sandbox_policy?: 'workspace_write'
  network_policy?: 'unmanaged'
  timeout_seconds?: number
}) => api.post('/desktop/agent-profiles', data).then(r => r.data as LocalAgentProfile)

export const updateLocalAgentProfile = (profileId: number, data: Record<string, any>) =>
  api.patch(`/desktop/agent-profiles/${profileId}`, data).then(r => r.data as LocalAgentProfile)

export const deleteLocalAgentProfile = (profileId: number) =>
  api.delete(`/desktop/agent-profiles/${profileId}`).then(r => r.data)

export const getLocalAgentRun = (runId: number) =>
  api.get(`/local-agent/runs/${runId}`).then(r => r.data as LocalAgentRun)

export const getLocalAgentRunEvents = (runId: number, after = 0) =>
  api.get(`/local-agent/runs/${runId}/events`, { params: { after } }).then(r => r.data)

export const cancelLocalAgentRun = (runId: number) =>
  api.post(`/local-agent/runs/${runId}/cancel`).then(r => r.data as LocalAgentRun)

export const applyLocalAgentRun = (
  runId: number,
  data: { confirm_apply: boolean; confirmed_deletions: string[]; confirmed_moves: string[]; idempotency_key: string },
) => api.post(`/local-agent/runs/${runId}/apply`, data).then(r => r.data as LocalAgentRun)

export interface ProjectProposalMilestone {
  id: string
  title: string
  purpose?: string
  estimated_effort?: string
}

export interface ProjectProposalSource {
  title: string
  url: string
  type: 'github' | 'url'
  description?: string
  stars?: number
  forks?: number
  language?: string
  license?: string
  pushed_at?: string
  rank_score?: number
  quality?: 'excellent' | 'strong' | 'relevant'
  match_reasons?: string[]
  reason?: string
}

export interface ProjectProposal {
  id: number
  proposal_key: string
  proposal_type: 'build' | 'mastery' | 'exam' | 'research'
  status: string
  action_type: 'create' | 'enter_existing'
  target_project_id?: number
  accepted_project_id?: number
  artifact: {
    title: string
    learning_goal: string
    practice_goal: string
    learner_start: string[]
    estimated_effort: string
    milestones: ProjectProposalMilestone[]
    acceptance_criteria: string[]
    risks: string[]
    assumptions?: string[]
    details?: Record<string, any>
    candidate_sources?: ProjectProposalSource[]
    source_search_generation?: number
    source_search_requested_at?: string
    source_search_refreshed_at?: string
    source_search_discovered_count?: number
    source_search_partial_failures?: number
    source_search_result_changed?: boolean
    source_search_last_error?: string
  }
  revision: number
  locked_fields: string[]
  last_change_summary: string
  source_status: 'idle' | 'queued' | 'searching' | 'completed' | 'failed'
  source_task_id?: number
  updated_at?: string
}

export const getProjectProposal = (proposalId: number) =>
  api.get(`/agent/project-proposals/${proposalId}`).then(r => r.data as ProjectProposal)

export const getAcceptedProjectProposal = (projectId: number) =>
  api.get(`/agent/projects/${projectId}/accepted-proposal`).then(r => r.data as ProjectProposal | null)

export const updateProjectProposal = (proposalId: number, data: {
  patch?: Record<string, any>
  lock_fields?: string[]
  unlock_fields?: string[]
  client_event_id?: string
}) => api.patch(`/agent/project-proposals/${proposalId}`, data).then(r => r.data as ProjectProposal)

export const acceptProjectProposal = (proposalId: number, clientEventId: string) =>
  api.post(`/agent/project-proposals/${proposalId}/accept`, { client_event_id: clientEventId }).then(r => r.data)

export const dismissProjectProposal = (proposalId: number) =>
  api.post(`/agent/project-proposals/${proposalId}/dismiss`).then(r => r.data as ProjectProposal)

export const reopenProjectProposal = (proposalId: number) =>
  api.post(`/agent/project-proposals/${proposalId}/reopen`).then(r => r.data as ProjectProposal)

export const refreshProjectProposalSources = (proposalId: number) =>
  api.post(`/agent/project-proposals/${proposalId}/refresh-sources`).then(r => r.data as ProjectProposal)

export const recordLearningEvent = (data: {
  client_event_id: string
  event_type: string
  project_id?: number
  checkpoint_id?: number
  session_id?: number
  payload?: Record<string, any>
}) => api.post('/learning-events', data).then(r => r.data)

// ── Lecture (Phase 2) ──
export const getLecture = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/lecture`).then(r => r.data)

// ── Process animations (process-animator) ──
export interface AnimationStep {
  title: string
  text: string
  bars?: { values: number[]; highlight?: number[]; pivot?: number[]; sorted?: number[]; done?: number[] }
  svg?: string
}
export interface ProcessAnimation {
  id?: number
  checkpoint_id?: number
  section_index?: number
  source?: string
  kind?: 'animation' | 'static'
  title?: string
  subtitle?: string
  legend?: [string, string][]
  steps: AnimationStep[]
}
export const generateAnimation = (text: string) =>
  api.post('/animations/generate', { text }).then(r => r.data)
export const getAnimation = (id: number) =>
  api.get(`/animations/${id}`).then(r => r.data)

export const generateConceptGraph = (checkpointId: number) =>
  api.post(`/checkpoints/${checkpointId}/concept-graph/generate`).then(r => r.data)

export const getConceptGraphTask = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/concept-graph/task`).then(r => r.data)

export interface TaskEventSubscription {
  close: () => void
}

function streamingHeaders() {
  const headers = new Headers()
  for (const [name, value] of Object.entries(api.defaults.headers.common)) {
    if (typeof value === 'string') headers.set(name, value)
  }
  return headers
}

function apiUrl(path: string) {
  return api.getUri({ url: path })
}

async function consumeSSE(response: Response, onData: (data: any) => void, signal: AbortSignal) {
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`服务器错误 (${response.status})${detail ? `: ${detail.slice(0, 200)}` : ''}`)
  }
  const reader = response.body?.getReader()
  if (!reader) throw new Error('响应无数据流')

  const decoder = new TextDecoder()
  let buffer = ''
  const deliver = (frame: string) => {
    const payload = frame.split('\n')
      .filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart())
      .join('\n')
    if (!payload) return
    try { onData(JSON.parse(payload)) } catch { /* Ignore malformed SSE frames. */ }
  }

  while (!signal.aborted) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    frames.forEach(deliver)
  }
  buffer += decoder.decode()
  if (buffer.trim()) deliver(buffer)
}

/**
 * Subscribe to a task snapshot stream with the current API base URL and auth
 * headers. Native EventSource cannot attach the desktop sidecar token, so it
 * would silently fail in Tauri after a task was successfully created.
 */
export function subscribeTaskEvents(
  taskId: number,
  onSnapshot: (snapshot: any) => void,
  onError: (message: string) => void,
): TaskEventSubscription {
  const controller = new AbortController()
  let polling = false

  const sleep = (ms: number) => new Promise(resolve => window.setTimeout(resolve, ms))

  // The sidecar can briefly restart or the WebView can lose an SSE stream.
  // Keep observing the persisted task instead of turning a still-running job
  // into a false UI failure.  The task API is the same source of truth used by
  // the SSE endpoint, so reconnecting is safe and idempotent.
  const pollUntilTerminal = async () => {
    if (polling || controller.signal.aborted) return
    polling = true
    let failures = 0
    try {
      while (!controller.signal.aborted && failures < 12) {
        try {
          const snapshot = (await api.get(`/tasks/${taskId}`)).data
          failures = 0
          onSnapshot(snapshot)
          if (['completed', 'failed', 'canceled'].includes(snapshot.status)) return
        } catch (error: any) {
          failures += 1
          if (failures >= 12) {
            onError(error instanceof Error ? error.message : '任务状态同步失败')
            return
          }
        }
        await sleep(1000)
      }
    } finally {
      polling = false
    }
  }

  void fetch(apiUrl(`/tasks/${taskId}/events`), {
    headers: streamingHeaders(),
    credentials: 'include',
    signal: controller.signal,
  })
    .then(response => consumeSSE(response, onSnapshot, controller.signal))
    .catch((error: unknown) => {
      if (!controller.signal.aborted) {
        void pollUntilTerminal().catch(() => {
          if (!controller.signal.aborted) onError(error instanceof Error ? error.message : '网络错误')
        })
      }
    })

  return { close: () => controller.abort() }
}

// Legacy direct-lecture stream kept for compatibility with older callers.
export function subscribeLectureSSE(
  checkpointId: number,
  onSection: (data: any) => void,
  onDone: (data: any) => void,
  onError: (msg: string) => void,
  onStatus?: (msg: string) => void,
) {
  let aborted = false
  const controller = new AbortController()
  let firstData = false

  // Timeout: if no data within 90s, report error
  const timeoutId = setTimeout(() => {
    if (!firstData && !aborted) {
      aborted = true
      onError('生成超时（90s）：AI 模型响应较慢，请稍后重试。如果持续出现，检查 API Key 和网络连接。')
    }
  }, 90000)

  const abort = () => {
    aborted = true
    controller.abort()
    clearTimeout(timeoutId)
  }

  const doFetch = async () => {
    try {
      const resp = await fetch(apiUrl(`/checkpoints/${checkpointId}/lecture/generate`), {
        headers: streamingHeaders(),
        credentials: 'include',
        signal: controller.signal,
      })

      if (!resp.ok) {
        clearTimeout(timeoutId)
        const body = await resp.text().catch(() => '')
        onError(`服务器错误 (${resp.status}): ${body.slice(0, 200)}`)
        return
      }

      firstData = true
      clearTimeout(timeoutId)

      const reader = resp.body?.getReader()
      if (!reader) {
        onError('响应无数据流')
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (!aborted) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE events
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const event of events) {
          for (const line of event.split('\n')) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                if (data.type === 'section') {
                  onSection(data)
                } else if (data.type === 'status') {
                  if (onStatus) onStatus(data.message || '')
                } else if (data.type === 'done') {
                  onDone(data)
                  return
                } else if (data.type === 'error') {
                  onError(data.message || '未知错误')
                  return
                }
              } catch { /* skip parse errors */ }
            }
          }
        }
      }
    } catch (e: any) {
      if (!aborted) {
        onError(`连接失败: ${e.message || '网络错误'}`)
      }
    }
  }

  doFetch()

  return { close: abort }
}

export const saveLecture = (
  checkpointId: number, sections: any[], baseVersion: number, idempotencyKey: string,
) => api.put(`/checkpoints/${checkpointId}/lecture`, {
  sections, base_version: baseVersion, idempotency_key: idempotencyKey,
}).then(r => r.data)

// ── Tasks (T1: background jobs) ──
export const createLectureTask = (checkpointId: number, mode: 'fresh' | 'resume' = 'fresh', feedback?: string) =>
  api.post(`/checkpoints/${checkpointId}/lecture/generate`, { mode, feedback: feedback || '' }).then(r => r.data)

export const getActiveLectureTask = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/lecture/task`).then(r => r.data)

export const listLectureVersions = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/lecture/versions`).then(r => r.data)

export const rollbackLecture = (checkpointId: number, versionId: number) =>
  api.post(`/checkpoints/${checkpointId}/lecture/rollback`, { version_id: versionId }).then(r => r.data)

export const getTaskStatus = (taskId: number) =>
  api.get(`/tasks/${taskId}`).then(r => r.data)

export const cancelTask = (taskId: number) =>
  api.post(`/tasks/${taskId}/cancel`).then(r => r.data)

export const askQuestion = (checkpointId: number, data: { selection: string; question: string; history: any[]; action?: string }) =>
  api.post(`/checkpoints/${checkpointId}/ask`, data).then(r => r.data)

// ── T9: anchored notes ──
export const listNotes = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/notes`).then(r => r.data)

export const createNote = (checkpointId: number, data: { section_index: number; selection: string; note: string }) =>
  api.post(`/checkpoints/${checkpointId}/notes`, data).then(r => r.data)

export const updateNote = (noteId: number, note: string) =>
  api.put(`/notes/${noteId}`, { note }).then(r => r.data)

export const deleteNote = (noteId: number) =>
  api.delete(`/notes/${noteId}`).then(r => r.data)

export interface ArtifactAnnotation {
  id: number
  checkpoint_id: number
  artifact_type: 'lecture' | 'exercise'
  artifact_id: number
  artifact_version: number
  section_index: number
  surface: string
  selection: string
  anchor: Record<string, any>
  note: string
  status: 'anchored' | 'orphaned'
}

export const listArtifactAnnotations = (artifactType: 'lecture' | 'exercise', artifactId: number) =>
  api.get(`/artifacts/${artifactType}/${artifactId}/annotations`)
    .then(r => r.data as ArtifactAnnotation[])

export const createArtifactAnnotation = (
  artifactType: 'lecture' | 'exercise', artifactId: number,
  data: { anchor: Record<string, any>; body: string; idempotency_key: string },
) => api.post(`/artifacts/${artifactType}/${artifactId}/annotations`, data)
  .then(r => r.data as ArtifactAnnotation)

export const updateArtifactAnnotation = (annotationId: number, body: string) =>
  api.put(`/artifact-annotations/${annotationId}`, { body }).then(r => r.data as ArtifactAnnotation)

export const deleteArtifactAnnotation = (annotationId: number) =>
  api.delete(`/artifact-annotations/${annotationId}`).then(r => r.data)

// ── Phase 3: Exercises & Code ──
export const listExercises = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/exercises`).then(r => r.data)

export const getExercise = (exerciseId: number) =>
  api.get(`/exercises/${exerciseId}`).then(r => r.data)

export const getExerciseDraft = (exerciseId: number) =>
  api.get(`/exercises/${exerciseId}/draft`).then(r => r.data)

export const saveExerciseDraft = (exerciseId: number, code: string, files: any[]) =>
  api.put(`/exercises/${exerciseId}/draft`, { code, files }).then(r => r.data)

export const runCode = (code: string, exerciseId?: number) => {
  const url = exerciseId ? `/exercises/${exerciseId}/run` : '/exercises/run'
  return api.post(url, { code }).then(r => r.data)
}

// ── Project-mode exercises (multi-file, pilot) ──
export const runProject = (exerciseId: number, files: any[]) =>
  api.post(`/exercises/${exerciseId}/run`, { code: '', files }).then(r => r.data)

export const getExerciseEnv = (exerciseId: number) =>
  api.get(`/exercises/${exerciseId}/env`).then(r => r.data)

export const submitProject = (
  exerciseId: number,
  files: any[],
  assistanceLevel: string = 'none',
  remediationCaseId?: number,
  attemptRole: string = 'original',
  clientSubmissionId?: string,
) => api.post(`/exercises/${exerciseId}/submit`, {
  code: '', files, assistance_level: assistanceLevel,
  remediation_case_id: remediationCaseId, attempt_role: attemptRole,
  client_submission_id: clientSubmissionId,
}).then(r => r.data)

export const reviewCode = (exerciseId: number, code: string, selection?: string) =>
  api.post(`/exercises/${exerciseId}/review`, { code, selection }).then(r => r.data)

export const askCodeQuestion = (data: { code: string; selection: string; question: string; context?: string }) =>
  api.post('/code/ask', data).then(r => r.data)

// ── T7: Concept questions ──
export const listConcepts = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/concepts`).then(r => r.data)

export const generateConcepts = (checkpointId: number) =>
  api.post(`/checkpoints/${checkpointId}/concepts/generate`).then(r => r.data)

export const getConceptTask = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/concepts/task`).then(r => r.data)

export const explainConcept = (checkpointId: number, questionId: number, userAnswerIndexes: number[]) =>
  api.post(`/checkpoints/${checkpointId}/concepts/${questionId}/explain`, { user_answer_indexes: userAnswerIndexes }).then(r => r.data)

export const submitConcept = (
  checkpointId: number,
  questionId: number,
  answerIndexes: number[],
  assistanceLevel: string = 'none',
  remediationCaseId?: number,
  attemptRole: string = 'original',
) => api.post(`/checkpoints/${checkpointId}/concepts/${questionId}/submit`, {
  answer_indexes: answerIndexes,
  assistance_level: assistanceLevel,
  remediation_case_id: remediationCaseId,
  attempt_role: attemptRole,
}).then(r => r.data)

// ── T8: exercise submit ──
export const submitExercise = (
  exerciseId: number,
  code: string,
  assistanceLevel: string = 'none',
  remediationCaseId?: number,
  attemptRole: string = 'original',
  clientSubmissionId?: string,
) => api.post(`/exercises/${exerciseId}/submit`, {
  code,
  assistance_level: assistanceLevel,
  remediation_case_id: remediationCaseId,
  attempt_role: attemptRole,
  client_submission_id: clientSubmissionId,
}).then(r => r.data)

// ── Explicit remediation loop ──
export const getRemediationCase = (caseId: number) =>
  api.get(`/remediation/${caseId}`).then(r => r.data)

export const listRemediationCases = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/remediation-cases`).then(r => r.data)

export const changeRemediationExplanation = (
  caseId: number, action: 'switch' | 'steps' | 'example',
) => api.post(`/remediation/${caseId}/explanations`, { action }).then(r => r.data)

export const createRemediationVariant = (caseId: number) =>
  api.post(`/remediation/${caseId}/variant`).then(r => r.data)

export const submitRemediationVariant = (
  caseId: number, data: { answer_indexes?: number[]; answer_text?: string },
) => api.post(`/remediation/${caseId}/variant/submit`, data).then(r => r.data)

// ── Global spaced review workbench ──
export const getReviewSummary = (params: Record<string, string | number | undefined> = {}) =>
  api.get('/review/summary', { params }).then(r => r.data)

export const listReviewItems = (params: Record<string, string | number | undefined> = {}) =>
  api.get('/review/items', { params }).then(r => r.data)

export const getReviewItem = (scheduleId: number) =>
  api.get(`/review/items/${scheduleId}`).then(r => r.data)

export const getReviewHistory = (scheduleId: number) =>
  api.get(`/review/items/${scheduleId}/history`).then(r => r.data)

export const submitReviewItem = (scheduleId: number, data: {
  expected_version: number
  client_submission_id: string
  response_status: 'answered' | 'unknown' | 'skipped'
  answer_indexes?: number[]
  answer_text?: string
  code?: string
  files?: Array<Record<string, any>>
  assistance_level?: 'none' | 'hint' | 'guided'
  presentation_version: string
}) => api.post(`/review/items/${scheduleId}/submit`, data).then(r => r.data)

export const manageReviewItem = (
  scheduleId: number,
  action: 'defer' | 'suspend' | 'resume',
  data: { expected_version: number; client_event_id: string },
) => api.post(`/review/items/${scheduleId}/${action}`, data).then(r => r.data)

export const getCompetitionDemoStatus = () =>
  api.get('/demo/status').then(r => r.data)

export const competitionDemoLogin = () =>
  api.post('/demo/login').then(r => r.data)

export const getCompetitionDemoManifest = () =>
  api.get('/demo/manifest').then(r => r.data)

export const getExerciseTask = (checkpointId: number) =>
  api.get(`/checkpoints/${checkpointId}/exercises/task`).then(r => r.data)

export default api
