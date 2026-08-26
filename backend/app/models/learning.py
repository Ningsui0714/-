from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, JSON, Float, ForeignKey, DateTime, Boolean,
    UniqueConstraint,
)

from app.db.database import Base


class Learner(Base):
    __tablename__ = "learners"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=True, unique=True, index=True)
    key = Column(String(100), nullable=False, unique=True, index=True)
    display_name = Column(String(255), default="本地学习者")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserAccount(Base):
    __tablename__ = "user_accounts"

    id = Column(Integer, primary_key=True)
    username = Column(String(32), nullable=False)
    username_normalized = Column(String(32), nullable=False, unique=True, index=True)
    password_hash = Column(Text, nullable=True)
    status = Column(String(20), default="active", nullable=False, index=True)
    is_legacy_demo = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user_accounts.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    is_dev_login = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LearnerProfile(Base):
    __tablename__ = "learner_profiles"

    learner_id = Column(Integer, ForeignKey("learners.id"), primary_key=True)
    education_stage = Column(String(40), default="other")
    background = Column(Text, default="")
    focus_areas = Column(JSON, default=list)
    weekly_hours = Column(Integer, default=5)
    preferred_modes = Column(JSON, default=list)
    career_goal = Column(Text, default="")
    career_goal_status = Column(String(20), default="exploring")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LearningLifeEvent(Base):
    __tablename__ = "learning_life_events"
    __table_args__ = (
        UniqueConstraint("learner_id", "dedupe_key", name="uq_life_event_learner_key"),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    status = Column(String(20), default="active", nullable=False, index=True)
    title = Column(String(255), nullable=False)
    summary = Column(Text, default="")
    payload = Column(JSON, default=dict)
    source_event_id = Column(Integer, ForeignKey("evidence_events.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    confidence = Column(Float, default=1.0)
    dedupe_key = Column(String(160), nullable=False)
    occurred_at = Column(DateTime, default=datetime.utcnow, index=True)
    corrected_at = Column(DateTime, nullable=True)


class LearnerBadge(Base):
    __tablename__ = "learner_badges"
    __table_args__ = (
        UniqueConstraint("learner_id", "award_key", name="uq_badge_learner_award"),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    badge_type = Column(String(50), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    icon_key = Column(String(50), default="award")
    color_token = Column(String(30), default="indigo")
    award_key = Column(String(160), nullable=False)
    life_event_id = Column(Integer, ForeignKey("learning_life_events.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    meta_data = Column(JSON, default=dict)
    awarded_at = Column(DateTime, default=datetime.utcnow, index=True)


class MemoryArchive(Base):
    __tablename__ = "memory_archives"
    __table_args__ = (
        UniqueConstraint(
            "learner_id", "kernel_name", "memory_scope", "memory_key",
            name="uq_memory_archive_path",
        ),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    kernel_name = Column(String(30), nullable=False, index=True)
    memory_scope = Column(String(20), nullable=False)
    memory_key = Column(String(160), nullable=False)
    archived_value = Column(JSON, default=dict)
    reason = Column(Text, default="")
    status = Column(String(20), default="archived", nullable=False, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence_events.id"), nullable=True, index=True)
    archived_at = Column(DateTime, default=datetime.utcnow)
    restored_at = Column(DateTime, nullable=True)


class EvidenceEvent(Base):
    __tablename__ = "evidence_events"
    __table_args__ = (
        UniqueConstraint("learner_id", "learner_seq", name="uq_evidence_learner_seq"),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=True, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    source = Column(String(40), nullable=False, default="system")
    context_id = Column(String(255), default="")
    payload = Column(JSON, default=dict)
    artifact_refs = Column(JSON, default=list)
    confidence = Column(Float, default=1.0)
    provenance = Column(JSON, default=dict)
    client_event_id = Column(String(160), nullable=True, unique=True, index=True)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    learner_seq = Column(Integer, nullable=True, index=True)
    actor_type = Column(String(30), default="system", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class LearningAttempt(Base):
    __tablename__ = "learning_attempts"

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False, index=True)
    item_type = Column(String(30), nullable=False)  # concept | exercise | freeform
    item_id = Column(Integer, nullable=True, index=True)
    status = Column(String(30), default="started", index=True)
    submission = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    assistance_level = Column(String(30), default="none")
    remediation_case_id = Column(
        Integer, ForeignKey("remediation_cases.id"), nullable=True, index=True,
    )
    attempt_role = Column(String(30), default="original", index=True)
    client_submission_id = Column(String(160), nullable=True, unique=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    evaluated_at = Column(DateTime, nullable=True)


class RemediationCase(Base):
    """Explicit wrong-answer remediation state machine.

    A case starts from one evaluated attempt and remains linked to every retry,
    explanation-mode decision, transfer variant, and evidence writeback.
    Strategy selection is deterministic; generated text is a presentation of
    already-verified evidence rather than an LLM-owned decision.
    """

    __tablename__ = "remediation_cases"
    __table_args__ = (
        UniqueConstraint("source_attempt_id", name="uq_remediation_source_attempt"),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False, index=True)
    source_attempt_id = Column(
        Integer, ForeignKey("learning_attempts.id"), nullable=False, index=True,
    )
    item_type = Column(String(30), nullable=False, index=True)
    item_id = Column(Integer, nullable=True, index=True)
    status = Column(String(30), default="explaining", nullable=False, index=True)
    error_fingerprint = Column(String(64), nullable=False, index=True)
    error_class = Column(String(50), nullable=False)
    misconception_tag = Column(String(100), default="")
    evidence = Column(JSON, default=dict)
    evidence_event_ids = Column(JSON, default=list)
    strategy = Column(JSON, default=dict)
    current_delivery_mode = Column(String(40), default="contrast")
    ineffective_modes = Column(JSON, default=list)
    explanation_history = Column(JSON, default=list)
    retry_attempt_id = Column(Integer, ForeignKey("learning_attempts.id"), nullable=True)
    variant_attempt_id = Column(Integer, ForeignKey("learning_attempts.id"), nullable=True)
    variant_payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class ReviewSchedule(Base):
    """Rebuildable spaced-review projection for one learner-owned item.

    This row is operational scheduling state, not a parallel mastery source of
    truth.  LearningAttempt and EvidenceEvent remain authoritative evidence.
    """

    __tablename__ = "review_schedules"
    __table_args__ = (
        UniqueConstraint(
            "learner_id", "item_type", "item_id",
            name="uq_review_schedule_learner_item",
        ),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False, index=True)
    item_type = Column(String(30), nullable=False, index=True)  # concept | exercise
    item_id = Column(Integer, nullable=False, index=True)
    subject_key = Column(String(255), nullable=False, default="", index=True)
    phase = Column(String(30), nullable=False, default="active", index=True)
    due_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    interval_level = Column(Integer, nullable=False, default=0)
    successful_reviews = Column(Integer, nullable=False, default=0)
    lapse_count = Column(Integer, nullable=False, default=0)
    defer_count = Column(Integer, nullable=False, default=0)
    last_grade = Column(String(20), default="")
    last_attempt_id = Column(Integer, ForeignKey("learning_attempts.id"), nullable=True, index=True)
    last_event_id = Column(Integer, ForeignKey("evidence_events.id"), nullable=True, index=True)
    last_question_form = Column(String(40), default="original")
    last_reviewed_at = Column(DateTime, nullable=True, index=True)
    suspended_at = Column(DateTime, nullable=True)
    policy_version = Column(String(40), nullable=False, default="review-policy-v1")
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class KernelState(Base):
    __tablename__ = "kernel_states"
    __table_args__ = (
        UniqueConstraint("learner_id", "kernel_name", name="uq_kernel_learner_name"),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    kernel_name = Column(String(30), nullable=False, index=True)
    short_term = Column(JSON, default=dict)
    long_term = Column(JSON, default=dict)
    action_chain = Column(JSON, default=list)
    evidence_refs = Column(JSON, default=list)
    confidence = Column(Float, default=0.0)
    version = Column(Integer, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KernelMutation(Base):
    __tablename__ = "kernel_mutations"

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("evidence_events.id"), nullable=True, index=True)
    kernel_name = Column(String(30), nullable=False, index=True)
    mutation_type = Column(String(30), default="short_term")
    status = Column(String(30), default="applied")  # applied | proposed | rejected
    patch = Column(JSON, default=dict)
    reason = Column(Text, default="")
    before_version = Column(Integer, default=0)
    after_version = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class MemoryNode(Base):
    __tablename__ = "memory_nodes"

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    node_type = Column(String(20), nullable=False, index=True)  # fact | module | claim
    kernel_name = Column(String(30), nullable=False, index=True)
    subject_key = Column(String(255), nullable=False, default="global", index=True)
    text = Column(Text, nullable=False, default="")
    payload = Column(JSON, default=dict)
    confidence = Column(Float, default=0.0)
    status = Column(String(30), default="active", nullable=False, index=True)
    valid_from = Column(DateTime, nullable=True, index=True)
    valid_to = Column(DateTime, nullable=True, index=True)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MemorySynthesisRun(Base):
    __tablename__ = "memory_synthesis_runs"
    __table_args__ = (
        UniqueConstraint("learner_id", "input_fingerprint", name="uq_memory_run_input"),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    kernel_name = Column(String(30), nullable=False, index=True)
    subject_key = Column(String(255), nullable=False, default="global", index=True)
    status = Column(String(30), default="queued", nullable=False, index=True)
    trigger_reason = Column(String(80), default="threshold")
    candidate_fact_ids = Column(JSON, default=list)
    input_fingerprint = Column(String(64), nullable=False, index=True)
    prompt_version = Column(String(40), default="memory-synthesis-v1")
    model_name = Column(String(100), default="deterministic")
    raw_output = Column(JSON, default=dict)
    validation_errors = Column(JSON, default=list)
    usage = Column(JSON, default=dict)
    attempt_count = Column(Integer, default=0)
    due_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MemoryFact(Base):
    __tablename__ = "memory_facts"
    __table_args__ = (
        UniqueConstraint("source_mutation_id", "fact_ordinal", name="uq_memory_fact_mutation_ordinal"),
    )

    node_id = Column(Integer, ForeignKey("memory_nodes.id"), primary_key=True)
    source_event_id = Column(Integer, ForeignKey("evidence_events.id"), nullable=False, index=True)
    source_mutation_id = Column(Integer, ForeignKey("kernel_mutations.id"), nullable=False, index=True)
    fact_ordinal = Column(Integer, nullable=False)
    predicate = Column(String(255), nullable=False, index=True)
    object_value = Column(JSON, default=dict)
    evidence_grade = Column(String(30), default="observed", nullable=False, index=True)
    consumption_status = Column(String(30), default="eligible", nullable=False, index=True)
    consumed_by_module_id = Column(Integer, ForeignKey("memory_modules.node_id"), nullable=True, index=True)
    reservation_run_id = Column(Integer, ForeignKey("memory_synthesis_runs.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=True, index=True)


class MemoryModule(Base):
    __tablename__ = "memory_modules"

    node_id = Column(Integer, ForeignKey("memory_nodes.id"), primary_key=True)
    synthesis_run_id = Column(Integer, ForeignKey("memory_synthesis_runs.id"), nullable=True, index=True)
    module_type = Column(String(40), default="synthesis")
    summary = Column(Text, nullable=False)
    time_start = Column(DateTime, nullable=False, index=True)
    time_end = Column(DateTime, nullable=False, index=True)
    input_fingerprint = Column(String(64), nullable=False, unique=True, index=True)
    immutable = Column(Boolean, default=True, nullable=False)


class MemoryClaim(Base):
    __tablename__ = "memory_claims"

    node_id = Column(Integer, ForeignKey("memory_nodes.id"), primary_key=True)
    module_node_id = Column(Integer, ForeignKey("memory_modules.node_id"), nullable=False, index=True)
    claim_ordinal = Column(Integer, nullable=False)
    predicate = Column(String(255), nullable=False)
    value = Column(JSON, default=dict)
    verification_status = Column(String(30), default="supported", nullable=False, index=True)


class MemoryEdge(Base):
    __tablename__ = "memory_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_node_id", "target_node_id", "relation_type",
            name="uq_memory_edge_relation",
        ),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    source_node_id = Column(Integer, ForeignKey("memory_nodes.id"), nullable=False, index=True)
    target_node_id = Column(Integer, ForeignKey("memory_nodes.id"), nullable=False, index=True)
    relation_type = Column(String(40), nullable=False, index=True)
    origin = Column(String(30), default="deterministic", nullable=False)
    confidence = Column(Float, default=1.0)
    evidence_event_id = Column(Integer, ForeignKey("evidence_events.id"), nullable=True, index=True)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    session_type = Column(String(30), default="global", index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=True, index=True)
    pending_action_id = Column(Integer, nullable=True)
    title = Column(String(255), default="学习 Tutor")
    status = Column(String(30), default="active", index=True)
    context_summary = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=False, index=True)
    role = Column(String(30), nullable=False)
    content = Column(Text, nullable=False)
    meta_data = Column(JSON, default=dict)
    idempotency_key = Column(String(160), nullable=True, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=False, index=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=True, index=True)
    capability = Column(String(80), nullable=False, index=True)
    status = Column(String(30), default="pending_confirmation", index=True)
    side_effect = Column(String(30), default="none")
    confirmation_policy = Column(String(30), default="none")
    target = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    evidence_target = Column(JSON, default=dict)
    next_affordances = Column(JSON, default=list)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    idempotency_key = Column(String(160), nullable=True, unique=True, index=True)
    error = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LearningProjectProposal(Base):
    __tablename__ = "learning_project_proposals"
    __table_args__ = (
        UniqueConstraint("session_id", "proposal_key", name="uq_project_proposal_session_key"),
    )

    id = Column(Integer, primary_key=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=False, index=True)
    proposal_key = Column(String(100), nullable=False, index=True)
    proposal_type = Column(String(30), default="build", index=True)
    status = Column(String(30), default="draft", index=True)
    action_type = Column(String(30), default="create")  # create | enter_existing
    target_project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    accepted_project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    accepted_action_id = Column(Integer, ForeignKey("agent_actions.id"), nullable=True, index=True)
    artifact = Column(JSON, default=dict)
    revision = Column(Integer, default=1)
    locked_fields = Column(JSON, default=list)
    message_refs = Column(JSON, default=list)
    evidence_refs = Column(JSON, default=list)
    last_change_summary = Column(Text, default="")
    source_status = Column(String(30), default="idle", index=True)
    source_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ProjectProposalRevision(Base):
    __tablename__ = "project_proposal_revisions"
    __table_args__ = (
        UniqueConstraint("proposal_id", "revision", name="uq_project_proposal_revision"),
    )

    id = Column(Integer, primary_key=True)
    proposal_id = Column(
        Integer, ForeignKey("learning_project_proposals.id"), nullable=False, index=True,
    )
    revision = Column(Integer, nullable=False)
    source = Column(String(30), default="tutor")  # tutor | user | resource_search | system
    patch = Column(JSON, default=dict)
    snapshot = Column(JSON, default=dict)
    change_summary = Column(Text, default="")
    message_id = Column(Integer, ForeignKey("agent_messages.id"), nullable=True, index=True)
    evidence_id = Column(Integer, ForeignKey("evidence_events.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"

    id = Column(Integer, primary_key=True)
    version = Column(String(100), nullable=False, unique=True)
    applied_at = Column(DateTime, default=datetime.utcnow)
