"""FastAPI application factory with lifespan hook."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from fastapi_app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Log configuration on startup; clean up on shutdown."""
    try:
        from helpers.constants import APP_CONFIG, APP_LOGGER

        APP_LOGGER.info(msg=f"GCP Budget Guard config: {APP_CONFIG}")
    except Exception as exc:
        print(f"Warning: config load during startup: {exc}")
    yield


app = FastAPI(
    title="GCP Budget Guard",
    description="Service-specific GCP budget monitoring & kill-switch",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)


# Health-check that responds instantly (no heavy imports)
@app.get("/")
@app.get("/health")
def health():
    """Lightweight health probe for Cloud Run."""
    return {"status": "healthy", "service": "gcp-budget-guard"}
