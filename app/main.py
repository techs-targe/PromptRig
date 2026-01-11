"""FastAPI application main module.

Based on specification in docs/req.txt section 3.1 (構成要素)
"""

import sys
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Add project root to Python path for module imports
# This ensures modules can be imported correctly on all platforms (Windows/Linux/macOS)
# especially when running with uvicorn directly: uvicorn app.main:app
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.routes import main, config, run, projects, datasets, settings, workflows, prompts, tags, agent


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Middleware to disable caching for JavaScript files during development."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        # Disable cache for JS files to ensure latest code is always loaded
        if request.url.path.endswith('.js'):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


from backend.utils import get_app_name

# Create FastAPI app with dynamic app name
app_name = get_app_name()
app = FastAPI(
    title=app_name,
    description="LLM prompt evaluation and benchmarking tool - Phase 2 Complete",
    version="2.0.0 (Phase 2 Complete)"
)

# Add middleware to disable JS caching (ensures latest code is always loaded)
app.add_middleware(NoCacheMiddleware)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(main.router)
app.include_router(config.router)
app.include_router(run.router)

# Phase 2 routers
app.include_router(projects.router, tags=["projects"])
app.include_router(datasets.router, tags=["datasets"])
app.include_router(settings.router, tags=["settings"])

# Workflow router (v2.0)
app.include_router(workflows.router, tags=["workflows"])

# Prompts router (v3.0 - new architecture)
app.include_router(prompts.router, tags=["prompts"])

# Tags router (v3.1 - access control)
app.include_router(tags.router, tags=["tags"])

# Agent router (v3.2 - MCP server and AI agent)
app.include_router(agent.router, tags=["agent"])


@app.on_event("startup")
def startup_event():
    """Initialize database on startup and recover stale jobs.

    Specification: docs/req.txt section 2.3

    Job Recovery:
    - Any jobs left in "running" status from a previous server crash
      are marked as "error" to prevent them from staying stuck forever.
    - This ensures users can see that those jobs were interrupted.
    """
    import json
    from backend.database import init_db, SessionLocal
    from backend.database.models import Job, JobItem, WorkflowJob
    from datetime import datetime

    init_db()
    print("✓ Database initialized")

    # Job Recovery: Mark stale "running" jobs as error
    db = SessionLocal()
    try:
        # Find all jobs stuck in "running" status (from previous server crash)
        stale_jobs = db.query(Job).filter(Job.status == "running").all()

        if stale_jobs:
            print(f"⚠ Found {len(stale_jobs)} stale job(s) in 'running' status")

            for job in stale_jobs:
                # Mark job as error
                job.status = "error"
                job.finished_at = datetime.utcnow().isoformat()

                # Mark all running/pending items as error
                stale_items = db.query(JobItem).filter(
                    JobItem.job_id == job.id,
                    JobItem.status.in_(["running", "pending"])
                ).all()

                for item in stale_items:
                    item.status = "error"
                    item.error_message = "Server restarted - job interrupted"

                print(f"  ✓ Job {job.id}: marked as error ({len(stale_items)} items)")

            db.commit()
            print(f"✓ Job recovery completed: {len(stale_jobs)} job(s) recovered")
        else:
            print("✓ No stale jobs to recover")

        # Workflow Job Recovery: Mark stale "running"/"pending" workflow jobs as error
        stale_workflow_jobs = db.query(WorkflowJob).filter(
            WorkflowJob.status.in_(["running", "pending"])
        ).all()

        if stale_workflow_jobs:
            print(f"⚠ Found {len(stale_workflow_jobs)} stale workflow job(s)")

            for wf_job in stale_workflow_jobs:
                wf_job.status = "error"
                wf_job.finished_at = datetime.utcnow().isoformat()
                wf_job.merged_output = json.dumps(
                    {"_error": "Server restarted - workflow job interrupted"},
                    ensure_ascii=False
                )
                print(f"  ✓ WorkflowJob {wf_job.id}: marked as error")

            db.commit()
            print(f"✓ Workflow job recovery completed: {len(stale_workflow_jobs)} job(s) recovered")
        else:
            print("✓ No stale workflow jobs to recover")

    except Exception as e:
        print(f"⚠ Job recovery failed: {e}")
        db.rollback()
    finally:
        db.close()

    print("✓ Application started on http://localhost:9200")
