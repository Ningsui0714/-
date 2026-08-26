from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, JSON, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    user_level = Column(String(50), default="beginner")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sources = relationship("Source", back_populates="project", cascade="all, delete-orphan")
    roadmap = relationship("Roadmap", back_populates="project", uselist=False, cascade="all, delete-orphan")
    workspace = relationship(
        "ProjectWorkspace", back_populates="project", uselist=False,
        cascade="all, delete-orphan",
    )


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    type = Column(String(50), nullable=False)  # github, url, file
    url = Column(Text, default="")
    role = Column(String(20), default="main")  # main | auxiliary (T10)
    status = Column(String(50), default="pending")  # pending, processing, processed, failed
    error = Column(Text, default="")
    meta_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="sources")
    chunks = relationship("Chunk", back_populates="source", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    tokens = Column(Integer, default=0)
    meta_data = Column(JSON, default=dict)

    source = relationship("Source", back_populates="chunks")
    checkpoints = relationship("CheckpointChunk", back_populates="chunk", cascade="all, delete-orphan")


class Roadmap(Base):
    __tablename__ = "roadmaps"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True)
    raw_json = Column(JSON, default=dict)
    conversation_history = Column(JSON, default=list)  # Persistent chat history
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="roadmap")
    checkpoints = relationship("Checkpoint", back_populates="roadmap", cascade="all, delete-orphan")


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id = Column(Integer, primary_key=True, index=True)
    roadmap_id = Column(Integer, ForeignKey("roadmaps.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    order = Column(Integer, nullable=False)
    prerequisites = Column(JSON, default=list)  # list of checkpoint ids
    completed = Column(Boolean, default=False)
    learning_status = Column(String(30), default="not_started", index=True)
    legacy_completed = Column(Boolean, default=False)
    learning_contract = Column(JSON, default=dict)
    archived = Column(Boolean, default=False)  # T10: removed-but-kept checkpoints
    brief = Column(JSON, default=dict)  # CheckpointBrief handoff contract (see docs/design)
    progress = Column(JSON, default=dict)  # T10: {lecture_read, exercises_done, concept_total, concept_correct, notes_count}
    created_at = Column(DateTime, default=datetime.utcnow)

    roadmap = relationship("Roadmap", back_populates="checkpoints")
    chunk_assignments = relationship("CheckpointChunk", back_populates="checkpoint", cascade="all, delete-orphan")
    lecture = relationship("Lecture", back_populates="checkpoint", uselist=False, cascade="all, delete-orphan")
    lecture_versions = relationship("LectureVersion", back_populates="checkpoint", cascade="all, delete-orphan")
    notes = relationship("LectureNote", back_populates="checkpoint", cascade="all, delete-orphan")
    concept_questions = relationship("ConceptQuestion", back_populates="checkpoint", cascade="all, delete-orphan")
    exercises = relationship("Exercise", back_populates="checkpoint", cascade="all, delete-orphan")
    animations = relationship("ProcessAnimation", back_populates="checkpoint", cascade="all, delete-orphan")


class CheckpointChunk(Base):
    __tablename__ = "checkpoint_chunks"

    id = Column(Integer, primary_key=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False)
    chunk_id = Column(Integer, ForeignKey("chunks.id"), nullable=False)

    checkpoint = relationship("Checkpoint", back_populates="chunk_assignments")
    chunk = relationship("Chunk", back_populates="checkpoints")


class Lecture(Base):
    __tablename__ = "lectures"

    id = Column(Integer, primary_key=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False, unique=True)
    sections = Column(JSON, default=list)  # list of {title, content, keywords, questions}
    plan = Column(JSON, default=list)      # persisted section plan (T10 resume stability)
    concept_graph = Column(JSON, default=dict)  # {nodes, edges} concept map
    status = Column(String(50), default="draft")  # draft, published
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    checkpoint = relationship("Checkpoint", back_populates="lecture")


class Exercise(Base):
    __tablename__ = "exercises"

    id = Column(Integer, primary_key=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    starter_code = Column(Text, default="")
    solution = Column(Text, default="")
    test_cases = Column(JSON, default=list)
    hints = Column(JSON, default=list)
    order = Column(Integer, default=0)
    # ── Project-mode exercises (pilot: PyTorch 训练循环) ──
    files = Column(JSON, default=list)       # [{name, content, read_only}]
    entrypoint = Column(String(255), default="")   # main file to run
    requirements = Column(JSON, default=list)       # ["torch", "scikit-learn"]
    judge_mode = Column(String(50), default="test_cases")  # test_cases | stdout_check
    judge_config = Column(JSON, default=dict)       # {pattern, min_accuracy} for stdout_check
    assessment_meta = Column(JSON, default=dict)   # targets, rubric, evidence contract
    checkpoint = relationship("Checkpoint", back_populates="exercises")


class LectureVersion(Base):
    """Snapshotted lecture version (T5: versioning + rollback).

    Current content lives in Lecture.sections; every destructive rewrite
    (regenerate, rollback) snapshots the previous state here first.
    """

    __tablename__ = "lecture_versions"

    id = Column(Integer, primary_key=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False, index=True)
    sections = Column(JSON, default=list)
    source_version = Column(Integer, default=1, nullable=False)
    reason = Column(String(100), default="")  # regenerate_before | before_rollback
    idempotency_key = Column(String(160), nullable=True, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    checkpoint = relationship("Checkpoint", back_populates="lecture_versions")


class LectureNote(Base):
    """Legacy anchored note table kept as a read-only migration source."""

    __tablename__ = "lecture_notes"

    id = Column(Integer, primary_key=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False, index=True)
    section_index = Column(Integer, default=0)
    selection = Column(Text, default="")  # anchored selected text
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    checkpoint = relationship("Checkpoint", back_populates="notes")


class ArtifactAnnotation(Base):
    """Learner-owned annotation anchored to a managed lecture or exercise."""

    __tablename__ = "artifact_annotations"
    __table_args__ = (
        UniqueConstraint("learner_id", "idempotency_key", name="uq_annotation_learner_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False, index=True)
    artifact_type = Column(String(20), nullable=False, index=True)  # lecture | exercise
    artifact_id = Column(Integer, nullable=False, index=True)
    artifact_version = Column(Integer, default=1, nullable=False)
    anchor = Column(JSON, default=dict)  # section_index/surface/selection/prefix/suffix
    body = Column(Text, default="")
    status = Column(String(20), default="anchored", nullable=False, index=True)
    idempotency_key = Column(String(160), nullable=True)
    legacy_note_id = Column(Integer, nullable=True, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ExerciseDraft(Base):
    """Personal answer draft. Saving it never creates learning evidence."""

    __tablename__ = "exercise_drafts"
    __table_args__ = (
        UniqueConstraint("learner_id", "exercise_id", name="uq_draft_learner_exercise"),
    )

    id = Column(Integer, primary_key=True, index=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    exercise_id = Column(Integer, ForeignKey("exercises.id"), nullable=False, index=True)
    code = Column(Text, default="")
    files = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ConceptQuestion(Base):
    """A formative check with a response format and an evidence contract."""

    __tablename__ = "concept_questions"

    id = Column(Integer, primary_key=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    options = Column(JSON, default=list)        # list[str]
    answer_indexes = Column(JSON, default=list) # list[int] (multi supports >1)
    q_type = Column(String(20), default="single")  # single | multi | judge | code_output
    difficulty = Column(String(10), default="medium")  # easy | medium | hard
    explanation = Column(Text, default="")
    source_chunk_ids = Column(JSON, default=list)
    code = Column(Text, default="")            # executable reference for code_output
    expected_output = Column(Text, default="") # verified by code execution
    assessment_meta = Column(JSON, default=dict)   # mode, targets, rubric, evidence contract
    order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    checkpoint = relationship("Checkpoint", back_populates="concept_questions")


class ProcessAnimation(Base):
    """process-animator：讲义/手动生成的可交互分步动画（steps 为 JSON）。

    source: lecture（讲义自动生成，section_index 指向讲义小节）| manual（工作台手动）
    """

    __tablename__ = "process_animations"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=True, index=True)
    source = Column(String(20), default="manual")  # manual | lecture
    kind = Column(String(20), default="animation")  # animation | static
    section_index = Column(Integer, default=0)
    title = Column(String(255), default="")
    subtitle = Column(Text, default="")
    legend = Column(JSON, default=list)   # [[color, label], ...]
    steps = Column(JSON, default=list)    # [{title, text, bars?, svg?}, ...]
    created_at = Column(DateTime, default=datetime.utcnow)

    checkpoint = relationship("Checkpoint", back_populates="animations")


class Task(Base):
    """Background job record (T1: task/job layer).

    Execution runs in an in-process asyncio task; DB rows are the source of
    truth for status/progress so SSE subscribers can reconnect at any time.
    """

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=True, index=True)
    agent_action_id = Column(Integer, ForeignKey("agent_actions.id"), nullable=True, index=True)
    type = Column(String(50), nullable=False, index=True)  # lecture_generate | ...
    status = Column(String(50), default="queued", index=True)  # queued running completed failed canceled
    payload = Column(JSON, default=dict)
    progress = Column(JSON, default=dict)  # {current, total, message}
    result = Column(JSON, default=dict)
    error = Column(JSON, default=dict)  # {code, message, guidance, retryable}
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProjectWorkspace(Base):
    """A desktop-only link from a learning project to one local folder."""

    __tablename__ = "project_workspaces"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True, index=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    root_path = Column(Text, nullable=False)
    status = Column(String(30), default="linked", nullable=False, index=True)
    platform = Column(String(30), default="unknown")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="workspace")
    operations = relationship(
        "WorkspaceOperation", back_populates="workspace", cascade="all, delete-orphan",
    )


class WorkspaceOperation(Base):
    """Auditable proposal/application record for every managed file mutation."""

    __tablename__ = "workspace_operations"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("project_workspaces.id"), nullable=False, index=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=True, index=True)
    actor = Column(String(20), default="user", nullable=False, index=True)
    operation = Column(String(30), nullable=False, index=True)
    status = Column(String(30), default="proposed", nullable=False, index=True)
    target_path = Column(Text, nullable=False)
    destination_path = Column(Text, nullable=True)
    base_hash = Column(String(64), nullable=True)
    payload = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    idempotency_key = Column(String(160), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)

    workspace = relationship("ProjectWorkspace", back_populates="operations")


class LocalAgentProfile(Base):
    """Learner-owned, allow-listed local Agent configuration."""

    __tablename__ = "local_agent_profiles"
    __table_args__ = (
        UniqueConstraint("learner_id", "name", name="uq_local_agent_profile_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    adapter = Column(String(40), nullable=False, index=True)  # codex_cli | deterministic_fake
    executable_path = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    priority = Column(Integer, default=100, nullable=False)
    task_types = Column(JSON, default=list)
    capabilities = Column(JSON, default=list)
    sandbox_policy = Column(String(40), default="workspace_write", nullable=False)
    network_policy = Column(String(40), default="unmanaged", nullable=False)
    timeout_seconds = Column(Integer, default=900, nullable=False)
    last_probe = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class LocalAgentRun(Base):
    """Two-confirmation local Agent run; never a learning evidence object."""

    __tablename__ = "local_agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    learner_id = Column(Integer, ForeignKey("learners.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    checkpoint_id = Column(Integer, ForeignKey("checkpoints.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.id"), nullable=False, index=True)
    action_id = Column(Integer, ForeignKey("agent_actions.id"), nullable=False, unique=True, index=True)
    profile_id = Column(Integer, ForeignKey("local_agent_profiles.id"), nullable=False, index=True)
    task_type = Column(String(60), nullable=False, index=True)
    goal = Column(Text, nullable=False)
    constraints = Column(JSON, default=list)
    required_capabilities = Column(JSON, default=list)
    status = Column(String(30), default="queued", nullable=False, index=True)
    isolation_root = Column(Text, nullable=True)
    base_manifest = Column(JSON, default=dict)
    changed_files = Column(JSON, default=list)
    diff_text = Column(Text, default="")
    result = Column(JSON, default=dict)
    error = Column(JSON, default=dict)
    idempotency_key = Column(String(160), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)


class LocalAgentRunEvent(Base):
    __tablename__ = "local_agent_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_local_agent_run_event_sequence"),
    )

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("local_agent_runs.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(60), nullable=False, index=True)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
