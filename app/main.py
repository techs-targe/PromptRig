"""FastAPI application main module.

Based on specification in docs/req.txt section 3.1 (構成要素)
"""

import sys
from pathlib import Path

# Add project root to Python path for module imports
# This ensures modules can be imported correctly on all platforms (Windows/Linux/macOS)
# especially when running with uvicorn directly: uvicorn app.main:app
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import main, config, run, projects, datasets, settings

# Create FastAPI app
app = FastAPI(
    title="Prompt Evaluation System",
    description="LLM prompt evaluation and benchmarking tool - Phase 2 Complete",
    version="2.0.0 (Phase 2 Complete)"
)

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


@app.on_event("startup")
def startup_event():
    """Initialize database on startup.

    Specification: docs/req.txt section 2.3
    """
    from backend.database import init_db
    init_db()
    print("✓ Database initialized")
    print("✓ Application started on http://localhost:9200")
