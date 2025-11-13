"""FastAPI application - PR-3."""

from fastapi import FastAPI

from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.metrics import router as metrics_router

app = FastAPI(title="Travel Planner API", version="0.1.0")

# Register routes
app.include_router(health_router, tags=["health"])
app.include_router(metrics_router, tags=["metrics"])


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "Travel Planner API", "version": "0.1.0"}
