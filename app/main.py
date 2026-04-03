"""Insurance Claim Settlement Agent — FastAPI Application."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.routes import router as api_router
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle hooks."""
    # ── Startup: ensure runtime directories exist ──
    for directory in [settings.data_dir, settings.storage_dir,
                      settings.reports_dir, settings.faiss_index_dir]:
        Path(directory).mkdir(parents=True, exist_ok=True)

    # Ensure claims storage directory exists
    claims_dir = Path(settings.storage_dir) / "claims"
    claims_dir.mkdir(parents=True, exist_ok=True)

    print(f"✓ {settings.app_name} started ({settings.app_env})")
    yield
    # ── Shutdown ──
    print(f"✓ {settings.app_name} shutting down")


app = FastAPI(
    title=settings.app_name,
    description=(
        "Reconcile hospital bills against insurance policy documents. "
        "Claims are approved or rejected by deterministic, auditable rules "
        "with exact policy citations for every rejection."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["System"])
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": "0.1.0",
    }


# ── Register API router ──
app.include_router(api_router, prefix="/api/v1")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
