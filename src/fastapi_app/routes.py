"""API routes for GCP Budget Guard.

Endpoints
─────────
POST /check                 – Run a full budget-check cycle (called by Cloud Scheduler).
POST /enable_service/{api}  – Re-enable a previously disabled API.
GET  /status                – Return per-service budget + API status snapshot.
GET  /status/{service}      – Return status of a single service.
POST /reset/{service}       – Full reset: re-enable API + save baseline + reset alerts.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from helpers.constants import APP_LOGGER, MONITORED_API_SERVICES

router = APIRouter()

# Lazy singleton for the heavy service
_monitor: Any = None


def _get_monitor():
    global _monitor
    if _monitor is None:
        from services.budget_monitor import BudgetMonitorService

        _monitor = BudgetMonitorService()
    return _monitor


# ── Scheduled budget check ────────────────────────────────────────────────

@router.post("/check")
def run_budget_check() -> JSONResponse:
    """Execute a full budget-check cycle.

    Called every 10 minutes by Cloud Scheduler.
    """
    monitor = _get_monitor()
    try:
        result = monitor.run_check()
        return JSONResponse(content=result, status_code=200)
    except Exception as exc:
        APP_LOGGER.error(msg=f"Budget check failed: {exc}")
        return JSONResponse(
            content={"error": str(exc)}, status_code=500
        )


# ── Re-enable a disabled service ─────────────────────────────────────────

@router.post("/enable_service/{api_name:path}")
def enable_service(api_name: str) -> JSONResponse:
    """Manually re-enable a service API that was previously disabled.

    Example:
        POST /enable_service/firestore.googleapis.com
    """
    monitor = _get_monitor()
    try:
        APP_LOGGER.info(msg=f"Manual enable request: {api_name}")
        success = monitor.enable_service(api_name)
        return JSONResponse(
            content={
                "status": "success" if success else "failed",
                "api_name": api_name,
                "message": f"API '{api_name}' enable {'succeeded' if success else 'failed'}",
            },
            status_code=200 if success else 500,
        )
    except Exception as exc:
        APP_LOGGER.error(msg=f"Error enabling {api_name}: {exc}")
        return JSONResponse(
            content={"status": "error", "api_name": api_name, "message": str(exc)},
            status_code=500,
        )


# ── Friendly reset by service key ────────────────────────────────────────

@router.post("/reset/{service_key}")
def reset_service(service_key: str) -> JSONResponse:
    """Full reset: re-enable API + save cost baseline + reset alert counters.

    This is the proper way to recover a service after budget enforcement.
    Saves the current cumulative cost as a baseline so the next check
    does not immediately re-disable the service.

    Example:
        POST /reset/firestore
    """
    api_name = MONITORED_API_SERVICES.get(service_key)
    if not api_name:
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Unknown service key '{service_key}'. "
                f"Valid keys: {list(MONITORED_API_SERVICES.keys())}",
            },
            status_code=400,
        )

    monitor = _get_monitor()
    try:
        result = monitor.reset_service(service_key)
        status_code = 200 if result.get("api_enabled") else 500
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        APP_LOGGER.error(msg=f"Error resetting {service_key}: {exc}")
        return JSONResponse(
            content={
                "status": "error",
                "service_key": service_key,
                "message": str(exc),
            },
            status_code=500,
        )


# ── Status endpoints ─────────────────────────────────────────────────────

@router.get("/status")
def get_all_status() -> JSONResponse:
    """Return budget config and current API state for every monitored service."""
    monitor = _get_monitor()
    statuses = {}
    for key, api_name in MONITORED_API_SERVICES.items():
        statuses[key] = {
            "api_name": api_name,
            "api_state": monitor.get_service_status(api_name),
        }
    return JSONResponse(content={"services": statuses}, status_code=200)


@router.get("/status/{service_key}")
def get_service_status(service_key: str) -> JSONResponse:
    """Return API state for a single service."""
    api_name = MONITORED_API_SERVICES.get(service_key)
    if not api_name:
        return JSONResponse(
            content={"error": f"Unknown service key '{service_key}'"},
            status_code=400,
        )
    monitor = _get_monitor()
    state = monitor.get_service_status(api_name)
    return JSONResponse(
        content={"service_key": service_key, "api_name": api_name, "api_state": state},
        status_code=200,
    )


@router.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)
