import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  Check,
  CheckCircle2,
  CircleDot,
  FileJson2,
  GitBranch,
  Gauge,
  Layers3,
  Network,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  ShieldAlert,
} from "lucide-react";
import {
  confirmLearningTaskPlan,
  getLearningTaskPlan,
  replanLearningTaskPlan,
  type LearningTaskPlanCandidate,
  type LearningTaskPlanCritic,
  type LearningTaskPlanRun,
  type LearningTaskPlanStage,
  type LearningTaskPlanStageStatus,
} from "../services/api";
import { useWorkspaceTitle } from "../components/workspace/WorkspaceContext";

const phaseLabels: Record<LearningTaskPlanRun["phase"], string> = {
  INTAKE: "等待任务明确",
  CONTRACT_READY: "检索计划待确认",
  PLAN_READY: "等待证据账本",
  EVIDENCE_READY: "证据已就绪",
  STEP_PLAN_READY: "步骤计划已就绪",
  CANDIDATES_READY: "候选已就绪",
  REVIEWED: "评审完成",
  PATCH_REQUIRED: "需要局部修订",
  COMMIT_READY: "等待交付",
  COMMITTED: "已交付",
  FAILED: "运行失败",
};

const criticLabels: Record<string, string> = {
  task_identity: "任务同一性",
  dependency: "依赖可执行性",
  evidence: "证据充分性",
  safety: "安全边界",
  deliverable: "交付可验收性",
  teaching_fit: "教学实施适配",
};

const scoreLabels: Record<string, string> = {
  fidelity: "任务保真",
  executability: "可执行",
  evidence: "证据",
  safety: "安全",
  teaching_fit: "教学适配",
  efficiency: "效率",
};

const decisionLabels: Record<string, string> = {
  SELECT_CANDIDATE: "候选已选定",
  REQUEST_EVIDENCE: "先补充证据",
  LOCAL_REPLAN: "进入局部重规划",
  STOP: "停止并人工复核",
};

const replanLabels = {
  evidence_gap: "证据缺口",
  dependency_blocked: "依赖阻塞",
  safety_conflict: "安全冲突",
  artifact_rejected: "产物未通过",
  mapping_conflict: "知识技能映射冲突",
} as const;

const stageStatusLabels: Record<LearningTaskPlanStageStatus, string> = {
  completed: "已完成",
  ready: "待确认",
  blocked: "有阻塞",
  pending: "待执行",
  not_started: "未开始",
};

const stageStatusTones: Record<LearningTaskPlanStageStatus, string> = {
  completed: "border-emerald-200 bg-emerald-50 text-emerald-700",
  ready: "border-indigo-200 bg-indigo-50 text-indigo-700",
  blocked: "border-amber-200 bg-amber-50 text-amber-700",
  pending: "border-slate-200 bg-slate-100 text-slate-600",
  not_started: "border-slate-200 bg-white text-slate-400",
};

function StageCard({ stage }: { stage: LearningTaskPlanStage }) {
  const byId = new Map(stage.substeps.map((item) => [item.substep_id, item]));
  const parentIds = new Set(
    stage.substeps
      .map((item) => item.parent_substep_id)
      .filter((value): value is string => Boolean(value)),
  );
  const rootCount = stage.substeps.filter(
    (item) => !item.parent_substep_id,
  ).length;
  const leafCount = stage.substeps.filter(
    (item) => !parentIds.has(item.substep_id),
  ).length;
  const dependencyCount = stage.substeps.reduce(
    (total, item) => total + item.depends_on.length,
    0,
  );
  const depthOf = (substepId: string) => {
    let depth = 0;
    let current = byId.get(substepId);
    const visited = new Set<string>();
    while (current?.parent_substep_id && depth < 4) {
      if (visited.has(current.parent_substep_id)) break;
      visited.add(current.parent_substep_id);
      depth += 1;
      current = byId.get(current.parent_substep_id);
    }
    return depth;
  };
  const stageIcon =
    stage.stage_id === "task_contract" ? (
      <FileJson2 size={16} />
    ) : stage.stage_id === "grounding_clarification" ? (
      <Activity size={16} />
    ) : stage.stage_id === "evidence_search_planning" ? (
      <Layers3 size={16} />
    ) : stage.stage_id === "evidence_grounded_task_planning" ? (
      <BrainCircuit size={16} />
    ) : stage.stage_id === "critic_finalize" ? (
      <ShieldCheck size={16} />
    ) : (
      <Network size={16} />
    );

  return (
    <article className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 bg-gradient-to-r from-slate-950 to-slate-800 p-4 text-white">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/10 font-mono text-sm font-bold">
              {String(stage.sequence).padStart(2, "0")}
            </span>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-indigo-200">
                {stageIcon}
                <h2 className="truncate text-sm font-semibold text-white">
                  {stage.label}
                </h2>
              </div>
              <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-slate-400">
                {stage.summary}
              </p>
            </div>
          </div>
          <span
            className={`shrink-0 rounded-full border px-2 py-1 text-[8px] font-semibold ${stageStatusTones[stage.status]}`}
          >
            {stageStatusLabels[stage.status]}
          </span>
        </div>
      </div>
      <div className="border-b border-slate-100 bg-slate-50/70 px-3 py-2">
        <div className="grid grid-cols-4 gap-1 text-center text-[8px]">
          {[
            ["微步骤", stage.substeps.length],
            ["主分支", rootCount],
            ["叶节点", leafCount],
            ["依赖", dependencyCount],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-md bg-white px-1 py-1.5">
              <p className="font-mono font-bold text-slate-700">{value}</p>
              <p className="mt-0.5 text-slate-400">{label}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3 lg:max-h-[460px]">
        <div className="space-y-1.5">
          {stage.substeps.map((item, itemIndex) => {
            const depth = depthOf(item.substep_id);
            return (
              <div
                key={item.substep_id}
                className={`relative min-w-0 rounded-lg border px-2.5 py-2 ${depth === 0 ? "border-slate-200 bg-slate-50" : "border-slate-100 bg-white"}`}
                style={{ marginLeft: `${Math.min(depth, 3) * 12}px` }}
              >
                {depth > 0 && (
                  <span className="absolute -left-3 top-0 h-1/2 w-3 rounded-bl border-b border-l border-slate-300" />
                )}
                <div className="flex min-w-0 items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <span className="shrink-0 font-mono text-[7px] text-indigo-400">
                      {String(stage.sequence).padStart(2, "0")}.
                      {String(itemIndex + 1).padStart(2, "0")}
                    </span>
                    <p className="min-w-0 truncate text-[10px] font-semibold text-slate-800">
                      {item.label}
                    </p>
                  </div>
                  <span
                    className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${item.status === "completed" ? "bg-emerald-500" : item.status === "ready" ? "bg-indigo-500" : item.status === "blocked" ? "bg-amber-500" : "bg-slate-300"}`}
                    title={stageStatusLabels[item.status]}
                  />
                </div>
                <p className="mt-1 line-clamp-2 text-[9px] leading-3.5 text-slate-500">
                  {item.detail}
                </p>
                {item.output_ref && (
                  <p className="mt-1 truncate font-mono text-[8px] text-indigo-400">
                    {item.output_ref}
                  </p>
                )}
                {item.depends_on.length > 0 && (
                  <div className="mt-1.5 flex min-w-0 items-center gap-1 overflow-hidden text-[7px] text-amber-600">
                    <GitBranch size={8} className="shrink-0" />
                    <span className="shrink-0">汇合依赖</span>
                    <span className="truncate font-mono">
                      {item.depends_on.join(" + ")}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-px bg-slate-100 text-[8px]">
        <div className="min-w-0 bg-slate-50 px-3 py-2">
          <p className="text-slate-400">INPUT</p>
          <p className="mt-1 truncate font-mono text-slate-600">
            {stage.input_refs.join(" · ")}
          </p>
        </div>
        <div className="min-w-0 bg-slate-50 px-3 py-2">
          <p className="text-slate-400">OUTPUT</p>
          <p className="mt-1 truncate font-mono text-slate-600">
            {stage.output_refs.join(" · ")}
          </p>
        </div>
      </div>
    </article>
  );
}

function ScoreBar({ name, value }: { name: string; value: number }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[10px]">
        <span className="text-slate-500">{scoreLabels[name] || name}</span>
        <span className="font-mono font-semibold text-slate-700">{value}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-emerald-500"
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );
}

function CandidateCard({
  item,
  selected,
}: {
  item: LearningTaskPlanCandidate;
  selected: boolean;
}) {
  return (
    <article
      className={`min-w-0 rounded-2xl border p-4 shadow-sm ${selected ? "border-indigo-400 bg-indigo-50/60 ring-2 ring-indigo-100" : "border-slate-200 bg-white"}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-950">
              {item.title}
            </h3>
            {selected && (
              <span className="rounded-full bg-indigo-700 px-2 py-0.5 text-[9px] font-semibold text-white">
                决策选中
              </span>
            )}
          </div>
          <p className="mt-1 text-[10px] text-slate-500">
            {item.parallel_waves.length} 个依赖波次 ·{" "}
            {item.ordered_package_ids.length} 个学习任务步骤
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-2xl font-bold text-slate-950">
            {item.weighted_score}
          </p>
          <p className="text-[9px] text-slate-400">综合分</p>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-x-3 gap-y-2">
        {Object.entries(item.scores).map(([name, value]) => (
          <ScoreBar key={name} name={name} value={value} />
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        {item.ordered_package_ids.map((id, index) => (
          <div key={id} className="flex items-center gap-1.5">
            {index > 0 && <ArrowRight size={10} className="text-slate-300" />}
            <span
              className="max-w-28 truncate rounded-md border border-slate-200 bg-white px-2 py-1 font-mono text-[9px] text-slate-600"
              title={id}
            >
              {id}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-3 space-y-1 border-t border-slate-200/70 pt-3">
        {item.tradeoffs.slice(0, 3).map((text) => (
          <p key={text} className="text-[10px] leading-4 text-slate-500">
            · {text}
          </p>
        ))}
      </div>
    </article>
  );
}

function CriticCell({ item }: { item: LearningTaskPlanCritic }) {
  const tone =
    item.verdict === "pass"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : item.verdict === "fail"
        ? "border-red-200 bg-red-50 text-red-800"
        : "border-amber-200 bg-amber-50 text-amber-800";
  return (
    <div className={`min-w-0 rounded-xl border p-3 ${tone}`}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] font-semibold">
          {criticLabels[item.dimension]}
        </p>
        <span className="font-mono text-sm font-bold">{item.score}</span>
      </div>
      <p className="mt-2 text-[10px] leading-4 opacity-80">
        {item.findings[0]}
      </p>
    </div>
  );
}

export default function LearningTaskPlanPage() {
  const { runId = "" } = useParams();
  const [run, setRun] = useState<LearningTaskPlanRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState("");
  const [targetPackage, setTargetPackage] = useState("");
  const [failureCode, setFailureCode] =
    useState<keyof typeof replanLabels>("evidence_gap");
  const [observation, setObservation] = useState(
    "当前检查结果未通过，需要只重规划受影响学习任务步骤及其后继依赖。",
  );

  useWorkspaceTitle(run?.plan.goal || "学习型任务 Plan", { kind: "wf03" });

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    setError("");
    try {
      const value = await getLearningTaskPlan(runId);
      setRun(value);
      setTargetPackage(
        (current) =>
          current ||
          value.planning_analysis.execution_checklist[0]?.package_id ||
          "",
      );
    } catch (failure: any) {
      setError(failure?.response?.data?.detail || "任务 Plan 加载失败。");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    load();
  }, [load]);

  const confirm = async () => {
    if (!run || run.phase !== "CONTRACT_READY" || acting) return;
    setActing(true);
    setError("");
    try {
      setRun(
        await confirmLearningTaskPlan(
          run.run_id,
          run.plan.plan_version,
          globalThis.crypto?.randomUUID?.() || `plan-confirm-${Date.now()}`,
        ),
      );
    } catch (failure: any) {
      setError(failure?.response?.data?.detail || "证据检索计划确认失败。");
    } finally {
      setActing(false);
    }
  };

  const replan = async () => {
    if (!run || !targetPackage || acting) return;
    setActing(true);
    setError("");
    try {
      setRun(
        await replanLearningTaskPlan(
          run.run_id,
          targetPackage,
          failureCode,
          observation,
          run.planning_analysis.analysis_version,
          globalThis.crypto?.randomUUID?.() || `plan-replan-${Date.now()}`,
        ),
      );
    } catch (failure: any) {
      setError(failure?.response?.data?.detail || "局部重规划失败。");
    } finally {
      setActing(false);
    }
  };

  const phases = useMemo(() => {
    if (!run) return [];
    const analysis = run.planning_analysis;
    return analysis.hierarchy
      .filter((node) => node.node_type === "phase")
      .map((phase) => ({
        ...phase,
        packages: analysis.hierarchy.filter(
          (node) =>
            node.node_type === "work_package" &&
            node.parent_id === phase.node_id,
        ),
      }));
  }, [run]);

  if (loading)
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 text-sm text-slate-500">
        <RefreshCw size={16} className="mr-2 animate-spin" />
        正在恢复多候选 Plan…
      </div>
    );
  if (!run)
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 p-6">
        <div className="max-w-md rounded-xl border border-red-200 bg-white p-6 text-center">
          <AlertTriangle className="mx-auto text-red-500" />
          <p className="mt-3 text-sm">{error || "没有找到任务 Plan。"}</p>
          <button
            onClick={load}
            className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-xs text-white"
          >
            重新加载
          </button>
        </div>
      </div>
    );

  const analysis = run.planning_analysis;
  const selectedCandidate = analysis.candidates.find(
    (item) => item.candidate_id === analysis.decision.selected_candidate_id,
  );
  const contract = run.task_contract || {};
  const searchPlanConfirmed =
    run.phase !== "CONTRACT_READY" && run.phase !== "INTAKE";

  return (
    <div className="h-full overflow-y-auto bg-[#f4f6f8] px-3 py-4 transition-[margin] sm:px-5 lg:px-7 xl:group-data-[agent-rail-expanded=true]/workspace:mr-[390px] 2xl:mr-0">
      <div className="mx-auto min-w-0 max-w-[1380px] pb-12">
        <header className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-xl">
          <div className="grid min-w-0 gap-5 p-5 2xl:grid-cols-[1fr_auto] 2xl:p-6">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-indigo-500/20 px-2.5 py-1 text-[10px] font-semibold text-indigo-200">
                  {phaseLabels[run.phase]}
                </span>
                <span className="rounded-full border border-white/10 px-2.5 py-1 text-[10px] text-slate-300">
                  检索计划 v{run.plan.plan_version} · 分析 v
                  {analysis.analysis_version}
                </span>
                <span className="rounded-full border border-white/10 px-2.5 py-1 text-[10px] text-slate-300">
                  学习任务未执行 · 可审计
                </span>
              </div>
              <h1 className="mt-3 max-w-4xl text-xl font-bold tracking-tight sm:text-2xl lg:text-3xl">
                {run.plan.goal}
              </h1>
              <p className="mt-2 max-w-3xl text-xs leading-5 text-slate-400">
                证据前只生成检索计划；证据账本到位后，才生成学习任务树、候选方案、评审矩阵与最终 Plan。所有产物均可检查，不保存隐藏思维链。
              </p>
            </div>
            <div className="flex flex-wrap items-start gap-2 2xl:justify-end">
              <button
                onClick={load}
                className="flex h-9 items-center gap-1.5 rounded-lg border border-white/15 px-3 text-xs text-slate-200 hover:bg-white/10"
              >
                <RefreshCw size={13} />
                刷新
              </button>
              {run.phase === "CONTRACT_READY" && (
                <button
                  onClick={confirm}
                  disabled={acting}
                  className="flex h-9 items-center gap-1.5 rounded-lg bg-indigo-500 px-3.5 text-xs font-semibold text-white hover:bg-indigo-400 disabled:opacity-50"
                >
                  <ShieldCheck size={14} />
                  确认证据检索计划
                </button>
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-px bg-white/10 sm:grid-cols-3 2xl:grid-cols-6">
            {[
              [
                "层级节点",
                analysis.metrics.hierarchy_nodes,
                "目标→作业阶段→任务步骤→原子操作",
              ],
              ["依赖边", analysis.metrics.dependency_edges, "有向无环约束"],
              ["并行波次", analysis.metrics.parallel_waves, "拓扑调度结果"],
              ["候选方案", analysis.metrics.candidate_count, "多策略搜索"],
              ["独立评审", analysis.metrics.critic_count, "六维门禁"],
              ["修订预算", analysis.repair_budget_remaining, "局部子图重算"],
            ].map(([label, value, note]) => (
              <div
                key={String(label)}
                className="min-w-0 bg-slate-900 px-4 py-3"
              >
                <p className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">
                  {label}
                </p>
                <p className="mt-1 text-lg font-bold">{value}</p>
                <p className="truncate text-[9px] text-slate-500">{note}</p>
              </div>
            ))}
          </div>
        </header>

        {error && (
          <p className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700">
            {error}
          </p>
        )}

        <section className="mt-4 min-w-0">
          <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
            <div>
              <div className="flex items-center gap-2">
                <GitBranch size={17} className="text-indigo-700" />
                <h2 className="text-sm font-semibold text-slate-950">
                  证据先行的学习型任务 Plan
                </h2>
              </div>
              <p className="mt-1 text-[10px] text-slate-500">
                每个阶段继续拆成输入、子问题、并行分支、汇合校验、门禁和版本化产物；第 04 阶段才允许生成真实学习任务步骤。
              </p>
            </div>
            <span className="rounded-full border border-slate-200 bg-white px-3 py-1.5 font-mono text-[9px] text-slate-500">
              {analysis.schema_version} · {analysis.metrics.stage_substep_count} substeps
            </span>
          </div>
          <div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
            {analysis.stages.map((stage) => (
              <StageCard key={stage.stage_id} stage={stage} />
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[10px] leading-4 text-amber-900">
            <span>
              局部失败回路：冻结已通过步骤，只把失败节点及其后继依赖送回第 05 阶段重规划。
            </span>
            <span className="font-semibold">
              规划产物 ≠ 已执行 ≠ 掌握证据
            </span>
          </div>
        </section>

        <section className="mt-4 grid min-w-0 gap-4 2xl:grid-cols-[1.05fr_1.95fr]">
          <article className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <FileJson2 size={16} className="text-indigo-700" />
              <h2 className="text-sm font-semibold">语义锁定与成功契约</h2>
            </div>
            <dl className="mt-4 space-y-3 text-xs">
              <div>
                <dt className="text-[10px] text-slate-400">用户原始任务</dt>
                <dd className="mt-1 leading-5 text-slate-800">
                  {String(
                    contract.raw_input || contract.normalized_input || "",
                  )}
                </dd>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <dt className="text-[10px] text-slate-400">动作 / 对象</dt>
                  <dd className="mt-1 text-slate-700">
                    {[contract.action, contract.object]
                      .filter(Boolean)
                      .join(" · ") || "由任务语义统一约束"}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] text-slate-400">交付结果</dt>
                  <dd className="mt-1 text-slate-700">
                    {String(contract.expected_deliverable || "由完成条件约束")}
                  </dd>
                </div>
              </div>
            </dl>
            <div className="mt-4 space-y-2 border-t border-slate-100 pt-3">
              {run.plan.success_criteria.map((item) => (
                <p
                  key={item}
                  className="flex gap-2 text-[11px] leading-4 text-slate-600"
                >
                  <Check
                    size={12}
                    className="mt-0.5 shrink-0 text-emerald-600"
                  />
                  {item}
                </p>
              ))}
            </div>
            <p className="mt-4 break-all rounded-lg bg-slate-50 p-2 font-mono text-[8px] text-slate-400">
              fingerprint: {run.plan.task_contract_fingerprint}
            </p>
          </article>
          <article className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Layers3 size={16} className="text-indigo-700" />
                <h2 className="text-sm font-semibold">证据驱动的四层学习任务分解</h2>
              </div>
              <span className="text-[10px] text-slate-400">
                Goal → Phase → Work Package → Atomic Step
              </span>
            </div>
            <div className="mt-4 grid min-w-0 gap-2 md:grid-cols-2 xl:grid-cols-3">
              {phases.length === 0 && (
                <div className="col-span-full rounded-xl border border-dashed border-amber-300 bg-amber-50 p-5 text-center">
                  <p className="text-xs font-semibold text-amber-900">
                    学习型任务树尚未生成
                  </p>
                  <p className="mt-2 text-[10px] leading-4 text-amber-700">
                    当前只有证据检索计划。证据账本和真实 task_steps 到位后，才会显示 Goal → 作业阶段 → 任务步骤 → 原子操作。
                  </p>
                </div>
              )}
              {phases.map((phase, index) => (
                <div
                  key={phase.node_id}
                  className="min-w-0 rounded-xl border border-slate-200 bg-slate-50 p-3"
                >
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-900 text-[9px] font-bold text-white">
                      {index + 1}
                    </span>
                    <h3 className="truncate text-[11px] font-semibold text-slate-900">
                      {phase.label}
                    </h3>
                  </div>
                  <div className="mt-3 space-y-2">
                    {phase.packages.map((item) => (
                      <div
                        key={item.node_id}
                        className="rounded-lg border border-slate-200 bg-white px-2.5 py-2"
                      >
                        <p className="truncate text-[10px] font-semibold text-indigo-800">
                          {item.package_id}
                        </p>
                        <p className="mt-1 line-clamp-2 text-[9px] leading-4 text-slate-500">
                          {item.label}
                        </p>
                        <p className="mt-1 text-[8px] text-slate-400">
                          3 个原子步骤
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </article>
        </section>

        <section className="mt-4 min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Network size={16} className="text-indigo-700" />
              <h2 className="text-sm font-semibold">学习任务步骤依赖图与关键路径</h2>
            </div>
            <span className="text-[10px] text-slate-400">
              只有同一波次可以并行，跨波次必须等待前置产物
            </span>
          </div>
          <div className="mt-4 flex min-w-0 flex-col gap-2 2xl:flex-row 2xl:items-stretch">
            {analysis.topological_waves.length === 0 && (
              <div className="w-full rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-center text-[10px] text-slate-500">
                等待证据驱动的学习任务步骤，当前不生成虚假的依赖图或关键路径。
              </div>
            )}
            {analysis.topological_waves.map((wave, waveIndex) => (
              <div
                key={waveIndex}
                className="flex min-w-0 flex-1 items-center gap-2"
              >
                {waveIndex > 0 && (
                  <ArrowRight
                    size={16}
                    className="hidden shrink-0 text-indigo-300 2xl:block"
                  />
                )}
                <div className="min-w-0 flex-1 rounded-xl border border-indigo-100 bg-indigo-50/50 p-3">
                  <p className="text-[9px] font-semibold uppercase tracking-wider text-indigo-500">
                    Wave {waveIndex + 1}
                  </p>
                  <div className="mt-2 space-y-1.5">
                    {wave.map((id) => (
                      <div
                        key={id}
                        className={`truncate rounded-md border bg-white px-2 py-1.5 font-mono text-[9px] ${analysis.critical_path.includes(id) ? "border-orange-300 text-orange-700" : "border-indigo-100 text-slate-600"}`}
                        title={id}
                      >
                        {id}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[9px] text-slate-500">
            <span className="rounded-full bg-orange-100 px-2 py-1 font-semibold text-orange-700">
              关键路径
            </span>
            {analysis.critical_path.map((id, index) => (
              <span key={id} className="flex items-center gap-2">
                <span className="font-mono">{id}</span>
                {index < analysis.critical_path.length - 1 && (
                  <ArrowRight size={9} />
                )}
              </span>
            ))}
          </div>
        </section>

        <section className="mt-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <BrainCircuit size={17} className="text-indigo-700" />
              <h2 className="text-sm font-semibold">
                学习型任务多候选搜索与加权选择
              </h2>
            </div>
            <span className="text-[10px] text-slate-500">
              保真 24% · 执行 20% · 证据 18% · 安全 18% · 教学 12% · 效率 8%
            </span>
          </div>
          <div className="grid min-w-0 gap-3 2xl:grid-cols-3">
            {analysis.candidates.length === 0 && (
              <div className="2xl:col-span-3 rounded-xl border border-dashed border-amber-300 bg-amber-50 p-5 text-center text-[10px] text-amber-800">
                证据账本尚未形成，三类学习型任务候选保持阻塞，不使用 Agent 工作包冒充任务步骤。
              </div>
            )}
            {analysis.candidates.map((item) => (
              <CandidateCard
                key={item.candidate_id}
                item={item}
                selected={
                  item.candidate_id === analysis.decision.selected_candidate_id
                }
              />
            ))}
          </div>
        </section>

        <section className="mt-4 grid min-w-0 gap-4 2xl:grid-cols-[1.45fr_0.75fr]">
          <article className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <ShieldCheck size={16} className="text-indigo-700" />
              <h2 className="text-sm font-semibold">学习任务独立 Critic 委员会</h2>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {analysis.critics.length === 0 && (
                <div className="col-span-full rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-center text-[10px] text-slate-500">
                  学习型任务候选尚未生成，六维 Critic 不提前运行。
                </div>
              )}
              {analysis.critics.map((item) => (
                <CriticCell key={item.critic_id} item={item} />
              ))}
            </div>
          </article>
          <article className="min-w-0 rounded-2xl border border-slate-800 bg-slate-950 p-4 text-white shadow-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Gauge size={16} className="text-emerald-400" />
                <h2 className="text-sm font-semibold">决策控制器</h2>
              </div>
              <span className="text-2xl font-bold text-emerald-400">
                {analysis.decision.confidence}
              </span>
            </div>
            <p className="mt-4 text-base font-semibold">
              {decisionLabels[analysis.decision.code]}
            </p>
            {selectedCandidate && (
              <p className="mt-1 text-xs text-indigo-300">
                {selectedCandidate.title}
              </p>
            )}
            <div className="mt-4 space-y-2">
              {analysis.decision.reasons.map((item) => (
                <p
                  key={item}
                  className="flex gap-2 text-[10px] leading-4 text-slate-400"
                >
                  <CircleDot
                    size={10}
                    className="mt-0.5 shrink-0 text-emerald-400"
                  />
                  {item}
                </p>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {analysis.decision.triggered_rules.map((rule) => (
                <span
                  key={rule}
                  className="rounded-md border border-white/10 px-2 py-1 font-mono text-[8px] text-slate-400"
                >
                  {rule}
                </span>
              ))}
            </div>
          </article>
        </section>

        <section className="mt-4 grid min-w-0 gap-4 2xl:grid-cols-2">
          <article className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <ShieldAlert size={16} className="text-amber-600" />
                <h2 className="text-sm font-semibold">风险与证据热区</h2>
              </div>
              <span className="text-[10px] text-slate-400">
                {analysis.risks.length} 项
              </span>
            </div>
            <div className="mt-3 space-y-2">
              {analysis.risks.map((risk) => (
                <div
                  key={risk.risk_id}
                  className="grid min-w-0 grid-cols-[auto_1fr_auto] items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3"
                >
                  <span
                    className={`mt-0.5 h-2.5 w-2.5 rounded-full ${risk.likelihood === "high" ? "bg-red-500" : risk.likelihood === "medium" ? "bg-amber-500" : "bg-emerald-500"}`}
                  />
                  <div className="min-w-0">
                    <p className="truncate font-mono text-[9px] text-slate-500">
                      {risk.package_id}
                    </p>
                    <p className="mt-1 text-[10px] leading-4 text-slate-700">
                      {risk.mitigation}
                    </p>
                  </div>
                  <span className="rounded bg-white px-2 py-1 text-[8px] text-slate-500">
                    {risk.category}
                  </span>
                </div>
              ))}
            </div>
          </article>
          <article className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <RotateCcw size={16} className="text-indigo-700" />
                <h2 className="text-sm font-semibold">局部子图重规划</h2>
              </div>
              <span className="rounded-full bg-slate-100 px-2 py-1 text-[9px] text-slate-600">
                剩余 {analysis.repair_budget_remaining} 轮
              </span>
            </div>
            <p className="mt-2 text-[10px] leading-4 text-slate-500">
              选择失败的学习任务步骤后，只重算该步骤及其后继依赖；语义指纹与未受影响步骤保持冻结。
            </p>
            {analysis.execution_checklist.length === 0 ? (
              <div className="mt-3 rounded-xl border border-dashed border-amber-300 bg-amber-50 p-4 text-center text-[10px] leading-4 text-amber-800">
                证据驱动的学习任务步骤尚未生成，当前不能对 Agent 检索工作包执行“学习任务局部重规划”。
              </div>
            ) : (
              <>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <select
                    value={targetPackage}
                    onChange={(event) => setTargetPackage(event.target.value)}
                    className="min-w-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[10px] text-slate-700"
                  >
                    {analysis.execution_checklist.map((item) => (
                      <option key={item.package_id} value={item.package_id}>
                        {item.package_id} · {item.objective}
                      </option>
                    ))}
                  </select>
                  <select
                    value={failureCode}
                    onChange={(event) =>
                      setFailureCode(
                        event.target.value as keyof typeof replanLabels,
                      )
                    }
                    className="min-w-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[10px] text-slate-700"
                  >
                    {Object.entries(replanLabels).map(([key, label]) => (
                      <option key={key} value={key}>
                        {label}
                      </option>
                    ))}
                  </select>
                </div>
                <textarea
                  value={observation}
                  onChange={(event) => setObservation(event.target.value)}
                  rows={2}
                  className="mt-2 w-full resize-none rounded-lg border border-slate-200 p-3 text-[10px] leading-4 text-slate-700"
                />
                <button
                  onClick={replan}
                  disabled={
                    acting ||
                    analysis.repair_budget_remaining <= 0 ||
                    observation.trim().length < 4
                  }
                  className="mt-2 flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-slate-900 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-40"
                >
                  {acting ? (
                    <RefreshCw size={13} className="animate-spin" />
                  ) : (
                    <GitBranch size={13} />
                  )}
                  生成局部修订版本
                </button>
              </>
            )}
          </article>
        </section>

        <section className="mt-4 min-w-0 rounded-2xl border border-indigo-200 bg-indigo-50/60 p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <FileJson2 size={16} className="text-indigo-700" />
              <h2 className="text-sm font-semibold">规划输出与后续接口</h2>
            </div>
            <span className="rounded-full border border-indigo-200 bg-white px-2 py-1 text-[9px] text-indigo-700">
              planning-analysis-v3 · evidence first
            </span>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 2xl:grid-cols-4">
            {[
              [
                '选定候选 Plan',
                selectedCandidate?.title || '等待证据门禁通过',
                analysis.decision.selected_candidate_id || 'not_selected',
              ],
              [
                '依赖调度结果',
                `${analysis.topological_waves.length} 个波次 · ${analysis.critical_path.length} 个关键路径节点`,
                'topological_schedule.json',
              ],
              [
                '独立评审报告',
                `${analysis.critics.filter((item) => item.verdict === 'pass').length} 通过 · ${analysis.critics.filter((item) => item.verdict === 'warning').length} 警告`,
                'critic_report.json',
              ],
              [
                '版本化规划包',
                `检索计划 v${run.plan.plan_version} · Analysis v${analysis.analysis_version}`,
                `${analysis.active_revision_id}.json`,
              ],
            ].map(([title, description, artifact]) => (
              <div
                key={title}
                className="min-w-0 rounded-xl border border-indigo-100 bg-white p-3"
              >
                <p className="text-[10px] font-semibold text-slate-900">
                  {title}
                </p>
                <p className="mt-2 text-[10px] leading-4 text-slate-600">
                  {description}
                </p>
                <p className="mt-3 truncate font-mono text-[8px] text-indigo-500">
                  {artifact}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-2">
            <article className="min-w-0 rounded-xl border border-indigo-100 bg-white p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10px] font-semibold text-slate-900">
                  待执行运行清单
                </p>
                <span className="rounded-full bg-slate-100 px-2 py-1 text-[8px] text-slate-500">
                  {analysis.execution_checklist.length} pending
                </span>
              </div>
              <div className="mt-2 max-h-44 space-y-1.5 overflow-y-auto">
                {analysis.execution_checklist.map((item) => (
                  <div
                    key={item.package_id}
                    className="grid min-w-0 grid-cols-[auto_1fr_auto] items-center gap-2 rounded-lg border border-slate-100 bg-slate-50 px-2.5 py-2"
                  >
                    <span className="h-2 w-2 rounded-full bg-slate-300" />
                    <div className="min-w-0">
                      <p className="truncate font-mono text-[9px] text-slate-700">
                        {item.package_id}
                      </p>
                      <p className="truncate text-[8px] text-slate-400">
                        {item.expected_artifact} · {item.observation_state}
                      </p>
                    </div>
                    <span className="text-[8px] text-slate-400">{item.status}</span>
                  </div>
                ))}
              </div>
            </article>
            <article className="min-w-0 rounded-xl border border-indigo-100 bg-white p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10px] font-semibold text-slate-900">
                  WF04 / 下游交接契约
                </p>
                <span className="rounded-full bg-amber-100 px-2 py-1 text-[8px] text-amber-700">
                  planned
                </span>
              </div>
              <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                {analysis.handoff_artifacts.map((item) => (
                  <div
                    key={item.artifact_id}
                    className="min-w-0 rounded-lg border border-slate-100 bg-slate-50 px-2.5 py-2"
                  >
                    <p className="truncate text-[9px] font-semibold text-slate-700">
                      {item.label}
                    </p>
                    <p className="mt-1 truncate font-mono text-[8px] text-indigo-400">
                      {item.contract_ref}
                    </p>
                  </div>
                ))}
              </div>
            </article>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
            <span className="font-semibold text-indigo-800">状态边界</span>
            <ArrowRight size={11} />
            <span>pending</span>
            <ArrowRight size={11} />
            <span>in_progress</span>
            <ArrowRight size={11} />
            <span>completed</span>
            <span className="rounded bg-amber-100 px-2 py-1 text-amber-800">
              当前全部尚未执行
            </span>
          </div>
        </section>

        <section className="mt-4 min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-indigo-700" />
            <h2 className="text-sm font-semibold">Plan 版本账本</h2>
          </div>
          <div className="mt-4 flex min-w-0 flex-col gap-3 2xl:flex-row">
            {analysis.revision_history.map((revision, index) => (
              <div
                key={revision.revision_id}
                className="flex min-w-0 flex-1 items-stretch gap-3"
              >
                {index > 0 && (
                  <ArrowRight
                    size={14}
                    className="hidden shrink-0 self-center text-slate-300 2xl:block"
                  />
                )}
                <div
                  className={`min-w-0 flex-1 rounded-xl border p-3 ${revision.revision_id === analysis.active_revision_id ? "border-indigo-300 bg-indigo-50" : "border-slate-200 bg-slate-50"}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-mono text-[9px] font-semibold text-slate-700">
                      {revision.revision_id}
                    </p>
                    <span className="text-[9px] text-slate-400">
                      分析 v{revision.analysis_version}
                    </span>
                  </div>
                  <p className="mt-2 text-[10px] leading-4 text-slate-600">
                    {revision.cause}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    <span className="rounded bg-white px-2 py-1 text-[8px] text-slate-500">
                      影响 {revision.affected_package_ids.length}
                    </span>
                    <span className="rounded bg-white px-2 py-1 text-[8px] text-slate-500">
                      冻结 {revision.preserved_package_ids.length}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div
            className={`mt-4 flex items-start gap-2 rounded-xl border px-3 py-3 text-[10px] leading-4 ${searchPlanConfirmed ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-indigo-200 bg-indigo-50 text-indigo-900"}`}
          >
            <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
            <span>
              {searchPlanConfirmed
                ? "证据检索计划已确认；仍需先形成证据账本，之后才能生成学习型任务 Plan，并进入远端定稿门禁。"
                : "当前等待确认的是证据检索计划，不是最终学习型任务 Plan；确认后只推进到 PLAN_READY。"}
            </span>
          </div>
        </section>
      </div>
    </div>
  );
}
