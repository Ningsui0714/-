import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.database import init_db
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.phase1 import router as phase1_router
from app.api.phase2 import router as phase2_router
from app.api.phase3 import router as phase3_router
from app.api.tasks import router as tasks_router
from app.api.settings import router as settings_router
from app.api.agent import router as agent_router, events_router
from app.api.auth import router as auth_router, dev_router
from app.api.profile import router as profile_router
from app.api.memory import router as memory_router
from app.api.remediation import router as remediation_router
from app.api.review import router as review_router
from app.api.architecture import router as architecture_router
from app.api.workspace import router as workspace_router
from app.api.local_agent import router as local_agent_router
from app.api.learning_task_conversion import router as learning_task_conversion_router
from app.api.learning_task_plan import router as learning_task_plan_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from app.services.task_manager import mark_stale_tasks_failed
    from app.services.local_agent_broker import mark_interrupted_runs_failed
    from app.services.memory_worker import memory_worker_loop
    await mark_stale_tasks_failed()
    await mark_interrupted_runs_failed()
    stop_memory_worker = asyncio.Event()
    memory_task = asyncio.create_task(memory_worker_loop(stop_memory_worker))
    try:
        yield
    finally:
        stop_memory_worker.set()
        try:
            await asyncio.wait_for(memory_task, timeout=3)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            memory_task.cancel()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(projects_router, prefix="/api")
app.include_router(phase1_router, prefix="/api")
app.include_router(phase2_router, prefix="/api")
app.include_router(phase3_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(events_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(dev_router, prefix="/api")
app.include_router(profile_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(remediation_router, prefix="/api")
app.include_router(review_router, prefix="/api")
app.include_router(architecture_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")
app.include_router(local_agent_router, prefix="/api")
app.include_router(learning_task_conversion_router, prefix="/api")
app.include_router(learning_task_plan_router, prefix="/api")
