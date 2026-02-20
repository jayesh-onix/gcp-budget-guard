# GCP Budget Guard – Project Documentation

## Overview

GCP Budget Guard is a production-ready budget monitoring and enforcement service for Google Cloud Platform. It watches spending across **Vertex AI**, **BigQuery**, and **Firestore** in real time, and automatically **disables only the individual service API** that exceeds its budget — it **never** deletes the GCP project or removes the billing account.

The service runs on **Cloud Run** and is triggered every 10 minutes by **Cloud Scheduler**. It supports two pricing modes: **Cloud Billing Catalog API** for live pricing (production default) and a **static JSON pricing catalog** for lab/sandbox environments where billing API access is restricted. It also uses **Cloud Monitoring** for usage metrics, publishes structured alerts to a **Pub/Sub topic** for downstream integration, and sends multi-recipient **email alerts** via Gmail SMTP with a per-service alert counter (max 2 per service) to prevent spam.

---

## Architecture

```
Cloud Scheduler (*/10 cron)
        │
        ▼ POST /check
┌─────────────────────────────────┐
│       Cloud Run (FastAPI)       │
│                                 │
│  ┌───────────────────────────┐  │
│  │  BudgetMonitorService     │  │
│  │                           │  │
│  │  ┌─ PriceProvider         │  │  ← Pricing abstraction (auto-selects source)
│  │  │   ├─ CloudBilling       │  │     ← Live SKU prices (production)
│  │  │   ├─ StaticCatalog      │  │     ← JSON catalog (lab/fallback)
│  │  │   └─ Fallback           │  │     ← Auto-recovery: billing → static
│  │  ├─ CloudMonitoring       │  │  ← Cloud Monitoring API (usage metrics)
│  │  ├─ WrapperCloudAPIs      │  │  ← Service Usage API (enable/disable APIs)
│  │  └─ NotificationService   │  │  ← Gmail SMTP + Pub/Sub alerts
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

### Request Flow

1. Cloud Scheduler sends `POST /check` every 10 minutes.
2. `BudgetMonitorService.run_check()` iterates over all monitored services.
3. For each metric in a service:
   - Fetch the **unit price** via the PriceProvider (live billing API, static catalog, or automatic fallback).
   - Fetch the **usage count** from Cloud Monitoring for the current calendar month.
   - Compute `expense = price_per_unit × unit_count`.
4. Accumulate per-service expenses and compare against the per-service budget.
5. If usage ≥ 80% (warning): send a warning email.
6. If usage ≥ 100% (critical): **disable only that service's API** and send a critical email.
7. Return a JSON summary to the caller.

---

## Project Structure

```
gcp-budget-guard/
├── docs/                          # Documentation
│   ├── PROJECT_DOCUMENTATION.md   # This file
│   ├── CLOUD_LAB_TESTING_GUIDE.md
│   └── PRODUCTION_DEPLOYMENT_GUIDE.md
├── src/
│   ├── main.py                    # Uvicorn entry point (port 8080)
│   ├── config/
│   │   ├── __init__.py
│   │   ├── budget.py              # ServiceBudget & ProjectBudget data classes
│   │   ├── monitored_services.py  # MonitoredMetric dataclass
│   │   ├── monitored_services_list.py  # Registry of all tracked metrics + SKU IDs
│   │   └── pricing_catalog.json   # Static pricing data (lab/fallback)
│   ├── helpers/
│   │   ├── __init__.py
│   │   ├── constants.py           # Env vars, config loading, fail-fast validation
│   │   ├── logger.py              # Structured JSON logger (GCP Cloud Logging compatible)
│   │   └── utils.py               # Date/time utilities
│   ├── services/
│   │   ├── __init__.py
│   │   ├── budget_monitor.py      # Core orchestrator
│   │   ├── notification.py        # Email + Pub/Sub alerts (max 2 per service)
│   │   ├── price_provider.py      # Pricing abstraction (Cloud Billing / Static / Fallback)
│   │   ├── price_catalog_service.py  # Static JSON pricing catalog loader
│   │   └── state_manager.py       # Persistent state (baselines, alerts, audit history)
│   ├── fastapi_app/
│   │   ├── __init__.py
│   │   ├── app.py                 # FastAPI app factory with lifespan
│   │   └── routes.py              # All HTTP endpoints
│   └── wrappers/
│       ├── __init__.py
│       ├── cloud_apis.py          # Service Usage API (enable/disable individual APIs)
│       ├── cloud_billing.py       # Cloud Billing Catalog API (live SKU prices)
│       └── cloud_monitoring.py    # Cloud Monitoring API (usage time-series)
├── tests/
│   ├── conftest.py                # Test fixtures and env setup
│   ├── test_api_routes.py         # FastAPI endpoint tests (12 tests)
│   ├── test_budget.py             # Budget model tests (11 tests)
│   ├── test_budget_monitor.py     # Orchestrator integration tests (19 tests)
│   ├── test_cloud_apis.py         # Cloud APIs wrapper tests (6 tests)
│   ├── test_cloud_billing.py      # Billing wrapper tests (3 tests)
│   ├── test_cloud_monitoring.py   # Monitoring wrapper tests (2 tests)
│   ├── test_monitored_services.py # Metric registry tests (8 tests)
│   ├── test_notification.py       # Notification + Pub/Sub tests (14 tests)
│   ├── test_price_catalog_service.py  # Static catalog tests (14 tests)
│   ├── test_price_provider.py     # Price provider tests (16 tests)
│   ├── test_state_manager.py      # Persistent state tests (32 tests)
│   └── test_utils.py              # Utility tests (2 tests)
├── pip/
│   └── requirements.txt           # Python dependencies
├── deploy.sh                      # Full GCP deployment script (7 steps)
├── pytest.ini                     # Pytest config (pythonpath=src, testpaths=tests)
├── Dockerfile                     # Production container (Python 3.12-slim)
├── makefile                       # Developer shortcuts
├── .env.example                   # Environment variable template
├── LICENSE.md
├── CONTRIBUTING.md
└── README.md
```

---

## Modules in Detail

### `src/helpers/constants.py`

Loads all configuration from environment variables at import time. If `GCP_PROJECT_ID` is not set, the application fails immediately. Key variables:

| Variable | Default | Description |
|---|---|---|
| `GCP_PROJECT_ID` | *required* | GCP project to monitor |
| `VERTEX_AI_MONTHLY_BUDGET` | `100` | Monthly budget for Vertex AI (USD) |
| `BIGQUERY_MONTHLY_BUDGET` | `100` | Monthly budget for BigQuery (USD) |
| `FIRESTORE_MONTHLY_BUDGET` | `100` | Monthly budget for Firestore (USD) |
| `MONTHLY_BUDGET_AMOUNT` | Sum of above | Overall project budget cap |
| `SMTP_EMAIL` | `""` | Gmail address for sending alerts |
| `SMTP_APP_PASSWORD` | `""` | Gmail App Password |
| `ALERT_RECEIVER_EMAILS` | `""` | Comma-separated recipient emails |
| `WARNING_THRESHOLD_PCT` | `80` | Warning alert at this % of budget |
| `CRITICAL_THRESHOLD_PCT` | `100` | Critical alert / disable at this % |
| `DRY_RUN_MODE` | `False` | If true, logs actions but never disables APIs |
| `DEBUG_MODE` | `False` | Verbose logging |
| `LAB_MODE` | `False` | If true, use static pricing (no billing API required) |
| `PRICE_SOURCE` | `billing` | `billing` = live API with static fallback, `static` = static catalog only |
| `BUDGET_STATE_BUCKET` | `""` | GCS bucket name for persistent state (recommended in production). Auto-created by `deploy.sh`. Leave empty to use local file. |
| `BUDGET_STATE_BLOB` | `budget_guard_state.json` | Blob name inside the GCS bucket |

### `src/helpers/logger.py`

`GCPLogger` outputs structured JSON logs compatible with Cloud Logging severity levels. It uses Python's `logging` module with a custom `JSONFormatter`. In non-debug mode, only INFO and above are emitted.

### `src/config/budget.py`

- **`ServiceBudget`**: Tracks one service's budget vs. expense. Properties: `usage_pct`, `is_exceeded`. Initialised from `constants.py` budget values.
- **`ProjectBudget`**: Aggregates all `ServiceBudget` instances. Methods: `check_overall_limit()`, `get_exceeded_services()`, `as_dict()`.

### `src/config/monitored_services.py`

`MonitoredMetric` is a `@dataclass` representing one billable metric to watch:
- `label` – human-readable name
- `metric_name` – Cloud Monitoring metric path
- `metric_filter` – optional MQL filter string (e.g. model ID, direction)
- `billing_service_id` – Cloud Billing service ID (e.g. `C7E2-9256-1C43`)
- `billing_sku_id` – specific SKU ID for price lookup
- `billing_price_tier` – which pricing tier to use (default 0)
- `price_per_unit`, `unit_count`, `expense` – populated at runtime

### `src/config/monitored_services_list.py`

The registry of all metrics, grouped by service key:

| Service | Metrics | Details |
|---|---|---|
| `vertex_ai` | 12 | Input + output tokens for Gemini 3.0 Pro, 2.5 Pro, 2.5 Flash, 2.5 Flash Lite, 2.0 Flash, 2.0 Flash Lite |
| `bigquery` | 1 | Scanned bytes billed (tier-1, on-demand) |
| `firestore` | 4 | Read, write, delete, TTL-delete operations |

All SKU IDs are from the US-CENTRAL1 region catalogue.

### `src/wrappers/cloud_billing.py`

`CloudBillingWrapper` uses Google's `CloudCatalogClient` to fetch live SKU prices:
- Caches SKUs per `billing_service_id` (only fetches once per service per run).
- `get_sku_price_per_unit()` finds the matching SKU, extracts the tiered rate, and normalises by the conversion factor (e.g. nanos → dollars, per-million → per-unit).

### `src/wrappers/cloud_monitoring.py`

`WrapperCloudMonitoring` uses `MetricServiceClient` to query time-series data:
- Scopes the query window from the 1st of the current calendar month to now (UTC).
- Returns the total integer sum of all data points matching the metric + filter.

### `src/wrappers/cloud_apis.py`

`WrapperCloudAPIs` manages individual API state via the Service Usage REST API:
- `disable_api(api_name)` – disables the API with `disable_dependent_services: False` and up to 3 retries.
- `enable_api(api_name)` – re-enables a previously disabled API.
- `get_api_status(api_name)` – returns `"ENABLED"`, `"DISABLED"`, or `"UNKNOWN"`.
- Respects `DRY_RUN_MODE` globally.

**Critical safety**: This wrapper **only** uses `services.disable()`. It never calls project-delete or billing-account-unlink.

### `src/services/price_provider.py`

Pricing abstraction layer with factory pattern:
- **`PriceProvider`** (ABC): Common interface — `get_price_per_unit()` and `provider_name`.
- **`CloudBillingPriceProvider`**: Wraps `CloudBillingWrapper` for live billing API pricing (production).
- **`StaticPriceProvider`**: Wraps `PriceCatalogService` to load prices from `pricing_catalog.json` (lab/fallback).
- **`FallbackPriceProvider`**: Tries the primary provider; on failure/None, automatically retries with the fallback.
- **`create_price_provider()`**: Factory function — selects the appropriate provider based on `LAB_MODE` and `PRICE_SOURCE` env vars.

### `src/services/price_catalog_service.py`

`PriceCatalogService` loads and queries a static JSON pricing catalog:
- Loads `config/pricing_catalog.json` on init, validates schema, builds a flat `sku_id → pricing entry` index.
- `get_price_per_base_unit()` normalises prices (e.g. $1.25/1M tokens → $1.25e-6/token).
- Supports fallback to a default price for unknown SKUs.
- Also provides `get_free_tier()`, `validate_region()`, and `as_dict()` for status endpoints.

### `src/services/budget_monitor.py`

`BudgetMonitorService` is the main orchestrator:
1. Creates a `ProjectBudget` snapshot.
2. For each service key, iterates its metrics, fetches price (via `PriceProvider`) + usage, computes expense.
3. If ≥ warning threshold → sends warning email.
4. If ≥ critical threshold → disables the API + sends critical email.
5. Returns a JSON summary dict.
6. Also exposes `enable_service()` and `get_service_status()` for manual intervention.
7. `reset_service()` queries the **live** current cumulative cost first (via `_get_current_cumulative_cost()`), falling back to the last cached value, then $0 — ensuring the baseline is as accurate as possible at the moment of reset.

### `src/services/notification.py`

`NotificationService` sends alerts via both HTML emails (Gmail SMTP-SSL) and Pub/Sub:
- Tracks a per-service alert counter (`_alerts_sent`): max **2 alerts per service** per billing cycle.
- 1st alert: **WARNING** when usage reaches 80 % of the service budget.
- 2nd alert: **CRITICAL** when usage reaches 100 % — fires **only after** the service API has been disabled.
- No further alerts are sent for that service until manually reset (`reset_alerts()`).
- Warning emails show current usage % and budget remaining.
- Critical emails include a note that the API has been disabled and instructions to re-enable.
- Sends to all addresses in `ALERT_RECEIVER_EMAILS`.
- Publishes structured JSON alerts to the `PUBSUB_TOPIC_NAME` topic for downstream automation (Cloud Functions, Slack bots, PagerDuty, etc.).
- Pub/Sub messages include all alert metadata: service key, API name, budget, expense, usage %, disabled status, and re-enable instructions.
- Gracefully disables individual channels if not configured (email or Pub/Sub can work independently).

### `src/services/state_manager.py`

`StateManager` provides thread-safe persistent state for the budget guard:
- **Cost baselines** — saved when admin calls `/reset`, subtracted from cumulative monitoring data on each check cycle so that the service is not immediately re-disabled.
- **Last known costs** — cumulative cost recorded during each check, used as the baseline value during reset.
- **Alert tracking** — which alert levels (WARNING / CRITICAL) have been sent per service, persisted across container restarts.
- **Action history** — audit log of resets / disables (last 200 entries).
- **Month rollover** — automatically clears baselines and alert counters when a new billing month starts.
- All operations are thread-safe via `threading.Lock`.
- **Dual-backend storage**: GCS is the primary backend when `BUDGET_STATE_BUCKET` is set — state survives Cloud Run container restarts, scale-to-zero, and redeployments. GCS is never disabled by the budget guard (not a monitored service). Falls back to a local JSON file (default: `/tmp/budget_guard_state.json`) when `BUDGET_STATE_BUCKET` is empty — suitable for local development and testing.
- GCS write failures are non-fatal (logged, in-memory state unchanged).
- Gracefully handles missing/corrupt state (starts fresh).

### `src/fastapi_app/routes.py`

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Health check – returns `{"status": "healthy"}` |
| `/health` | GET | Health check – same as above |
| `/check` | POST | Run a full budget-check cycle |
| `/enable_service/{api_name}` | POST | Re-enable a specific API by its full name |
| `/reset/{service_key}` | POST | Full reset: save cost baseline + reset alerts + re-enable API |
| `/status` | GET | Return all services' budget and API state |
| `/status/{service_key}` | GET | Return one service's state |
| `/favicon.ico` | GET | Returns 204 (prevents browser 404) |

---

## Monitored Metrics Detail

### Vertex AI (Service ID: `C7E2-9256-1C43`)

| Metric | SKU ID | Cloud Monitoring Metric |
|---|---|---|
| Gemini 3.0 Pro – input | `EAC4-305F-1249` | `aiplatform.googleapis.com/publisher/online_serving/token_count` |
| Gemini 3.0 Pro – output | `2737-2D33-D986` | (same, filtered by model + direction) |
| Gemini 2.5 Pro – input | `A121-E2B5-1418` | " |
| Gemini 2.5 Pro – output | `5DA2-3F77-1CA5` | " |
| Gemini 2.5 Flash – input | `FDAB-647C-5A22` | " |
| Gemini 2.5 Flash – output | `AF56-1BF9-492A` | " |
| Gemini 2.5 Flash Lite – input | `F91E-007E-3BA1` | " |
| Gemini 2.5 Flash Lite – output | `2D6E-6AC5-B1FD` | " |
| Gemini 2.0 Flash – input | `1127-99B9-1860` | " |
| Gemini 2.0 Flash – output | `DFB0-8442-43A8` | " |
| Gemini 2.0 Flash Lite – input | `CF72-F84C-8E3B` | " |
| Gemini 2.0 Flash Lite – output | `4D69-506A-5D33` | " |

### BigQuery (Service ID: `24E6-581D-38E5`)

| Metric | SKU ID | Cloud Monitoring Metric |
|---|---|---|
| Scanned Bytes Billed | `3362-E469-6BEF` | `bigquery.googleapis.com/query/statement_scanned_bytes_billed` |

### Firestore (Service ID: `EE2C-7FAC-5E08`)

| Metric | SKU ID | Cloud Monitoring Metric |
|---|---|---|
| Read Operations | `6A94-8525-876F` | `firestore.googleapis.com/document/read_count` |
| Write Operations | `BFCC-1D11-14E1` | `firestore.googleapis.com/document/write_count` |
| Delete Operations | `B813-E6E7-37F4` | `firestore.googleapis.com/document/delete_count` |
| TTL Delete Operations | `6088-280E-4225` | `firestore.googleapis.com/document/ttl_deletion_count` |

---

## Safety Guarantees

1. **Per-service disabling only** – When a service exceeds its budget, only that service's API is disabled via the Service Usage API. Other services continue running.
2. **Never deletes the project** – The codebase contains zero calls to `projects.delete()`.
3. **Never removes billing** – The codebase never calls `updateBillingInfo` to unlink billing.
4. **Dry-run mode** – Set `DRY_RUN_MODE=True` to log what *would* happen without taking any action.
5. **Manual re-enable** – Admins can re-enable any disabled service via `POST /reset/{service_key}` or `POST /enable_service/{api_name}`.
6. **Alert capping** – Each service receives at most **2 notification emails** per billing cycle: one WARNING at 80 % and one CRITICAL at 100 % (only after the API has been disabled). No duplicates are sent on subsequent scheduler runs.

---

## Testing

The test suite contains **138 tests** across 13 test files, all running with mocks (no GCP credentials needed):

```bash
# Run all tests (pytest.ini configures pythonpath automatically)
make test

# Or directly
pytest tests -v
```

Test coverage:
- `test_state_manager.py` – 32 tests (baselines, last known costs, alert tracking, deduplication, persistence, month rollover, file resilience; **GCS backend: load, save, missing blob, save failure resilience, local fallback, round-trip**)
- `test_budget_monitor.py` – 19 tests (orchestrator integration: under-budget, exceeded, warning at 80%, data quality warnings, baseline subtraction, reset with baseline + alerts + audit, partial failures; **live query first, cached fallback, zero-cost fallback**)
- `test_price_provider.py` – 16 tests (static provider, cloud billing provider, fallback chain, factory function, provider selection by env)
- `test_notification.py` – 14 tests (alert counter, max-2-per-service, critical-only-after-disable, reset, independent per-service counters, Pub/Sub integration, Pub/Sub payload validation)
- `test_price_catalog_service.py` – 14 tests (real catalog loading, SKU index, per-service price normalisation, fallback prices, free tiers, region validation, missing/corrupt files)
- `test_api_routes.py` – 12 tests (health, favicon, budget check, enable service, reset with baseline, invalid keys, status endpoints)
- `test_budget.py` – 11 tests (ServiceBudget and ProjectBudget logic, zero-budget safety, exceeded detection)
- `test_monitored_services.py` – 8 tests (metric dataclass defaults, registry completeness, billing ID validation, Vertex AI filter validation)
- `test_cloud_apis.py` – 6 tests (enable/disable/status with mocks, dry-run mode)
- `test_cloud_billing.py` – 3 tests (SKU cache population, missing SKU, tiered rate extraction)
- `test_cloud_monitoring.py` – 2 tests (zero-data handling, multi-point aggregation)
- `test_utils.py` – 2 tests (date utilities)
- `conftest.py` – shared fixtures, environment setup, and Pub/Sub mock

---

## Deployment

See [PRODUCTION_DEPLOYMENT_GUIDE.md](PRODUCTION_DEPLOYMENT_GUIDE.md) for full deployment instructions.

Quick summary:

```bash
# 1. Set environment variables
export GCP_PROJECT_ID=your-project
export VERTEX_AI_MONTHLY_BUDGET=100
export BIGQUERY_MONTHLY_BUDGET=100
export FIRESTORE_MONTHLY_BUDGET=100

# 2. Deploy
make deploy
```

The deploy script handles everything: enabling APIs, creating the service account with correct IAM roles, deploying Cloud Run, setting up Cloud Scheduler, and creating the Pub/Sub topic.

---

## API Reference

### `POST /check`

Runs a full budget-check cycle. Intended to be called by Cloud Scheduler.

**Response** (200):
```json
{
  "project_id": "my-project",
  "dry_run": false,
  "budget": {
    "vertex_ai": {"monthly_budget": 100.0, "current_expense": 45.23, "usage_pct": 45.2, "is_exceeded": false},
    "bigquery": {"monthly_budget": 100.0, "current_expense": 12.50, "usage_pct": 12.5, "is_exceeded": false},
    "firestore": {"monthly_budget": 100.0, "current_expense": 3.10, "usage_pct": 3.1, "is_exceeded": false}
  },
  "disabled_apis": [],
  "warnings_sent": [],
  "metric_details": [...]
}
```

### `POST /reset/{service_key}`

Full reset for a service after budget enforcement. Performs three operations:
1. Saves the current cumulative cost as a **baseline** (so the next check cycle subtracts it and doesn't immediately re-disable).
2. Resets alert counters for the service (allowing new WARNING + CRITICAL emails).
3. Re-enables the API via the Service Usage API.

Valid keys: `vertex_ai`, `bigquery`, `firestore`.

**Response** (200):
```json
{
  "status": "success",
  "service_key": "firestore",
  "api_name": "firestore.googleapis.com",
  "api_enabled": true,
  "baseline_saved": 45.2300,
  "alerts_reset": true
}
```

### `POST /enable_service/{api_name}`

Re-enable a service using its full API name (e.g. `firestore.googleapis.com`).

### `GET /status`

Returns current budget and API state for all monitored services.

### `GET /status/{service_key}`

Returns state for one service.

### `GET /` and `GET /health`

Health check – returns `{"status": "healthy", "service": "gcp-budget-guard"}`.
