"""Entry point – starts Uvicorn serving the FastAPI application."""

import os

import uvicorn

from fastapi_app.app import app  # noqa: F401  (imported for uvicorn target)

debug_mode = os.environ.get("DEBUG_MODE", "False").lower() in ("true", "1", "yes")

if __name__ == "__main__":
    uvicorn.run(
        app="main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        log_level="debug" if debug_mode else "info",
    )
