"""FastAPI application - PR-4A."""

from fastapi import FastAPI

from backend.app.api.routes.docs import router as docs_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.metrics import router as metrics_router
from backend.app.api.routes.qa import router as qa_router
from backend.app.api.routes.runs import router as runs_router

app = FastAPI(title="Travel Planner API", version="0.1.0")

# Register routes
app.include_router(health_router, tags=["health"])
app.include_router(metrics_router, tags=["metrics"])
app.include_router(runs_router, tags=["runs"])
app.include_router(docs_router, tags=["docs"])
app.include_router(qa_router, tags=["qa"])


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "Travel Planner API", "version": "0.1.0"}
