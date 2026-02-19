# GCP Budget Guard

**Service-specific budget monitoring and enforcement for Google Cloud Platform.**

GCP Budget Guard watches spending across **Vertex AI**, **BigQuery**, and **Firestore** in real time and automatically **disables only the individual service API** that exceeds its budget. It **never** deletes your GCP project or removes the billing account.

## Key Features

- **Per-service budgets** — Independent monthly limits for Vertex AI, BigQuery, and Firestore
- **Live pricing** — Uses the Cloud Billing Catalog API (no hardcoded prices)
- **Static pricing fallback** — Local JSON catalog for lab environments or when billing API is unavailable
- **Lab mode** — Deploy in Google Cloud Lab (Qwiklabs) without billing API permissions
- **Service-specific disabling** — Only the offending service is disabled; other services keep running
- **Manual re-enable** — Admins can re-enable any disabled service via a simple API call
- **Email alerts** — Warning at 80% and critical at 100% with per-service counter (max 2)
- **Pub/Sub integration** — Structured JSON alerts published to a topic for downstream automation
- **Multi-recipient emails** — Send alerts to multiple people (comma-separated)
- **Dry-run mode** — Test safely without disabling anything
- **10-minute checks** — Cloud Scheduler triggers budget checks every 10 minutes

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
│  │  ┌─ PriceProvider          │  │  ← Auto-selects: billing API / static catalog / fallback
│  │  ├─ CloudMonitoring       │  │  ← Cloud Monitoring API (usage metrics)
│  │  ├─ WrapperCloudAPIs      │  │  ← Service Usage API (enable/disable APIs)
│  │  └─ NotificationService   │  │  ← Gmail SMTP + Pub/Sub alerts
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

## Quick Start

### 1. Configure

```bash
cp .env.example .env
# Edit .env with your project ID, budgets, and email settings
```

### 2. Run Tests (No GCP Needed)

```bash
pip install -r pip/requirements.txt
make test
```

### 3. Run Locally (Dry-Run)

```bash
export GCP_PROJECT_ID=your-project-id
export DRY_RUN_MODE=True
make run-debug
```

### 4. Deploy to GCP

```bash
source .env
make deploy
```

### 5. Re-enable a Disabled Service

```bash
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  $SERVICE_URL/reset/vertex_ai
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/check` | POST | Run a full budget-check cycle |
| `/status` | GET | All services' budget & API state |
| `/status/{service_key}` | GET | Single service state |
| `/reset/{service_key}` | POST | Re-enable a service by key |
| `/enable_service/{api_name}` | POST | Re-enable by full API name |

Valid service keys: `vertex_ai`, `bigquery`, `firestore`

## Safety Guarantees

- **Never deletes the GCP project** — zero calls to `projects.delete()`
- **Never removes billing** — no billing account unlinking
- **Per-service only** — disables individual APIs, not the whole project
- **Dry-run mode** — test everything without taking action

## Documentation

| Document | Description |
|---|---|
| [docs/PROJECT_DOCUMENTATION.md](docs/PROJECT_DOCUMENTATION.md) | Full technical documentation |
| [docs/CLOUD_LAB_TESTING_GUIDE.md](docs/CLOUD_LAB_TESTING_GUIDE.md) | Step-by-step lab testing |
| [docs/PRODUCTION_DEPLOYMENT_GUIDE.md](docs/PRODUCTION_DEPLOYMENT_GUIDE.md) | Production deployment |
| [docs/PRODUCTION_LIMITATIONS_AND_EDGE_CASES.md](docs/PRODUCTION_LIMITATIONS_AND_EDGE_CASES.md) | Known limitations, edge cases & solutions |

## Configuration

All configuration is via environment variables. See [.env.example](.env.example) for the full list.

| Variable | Default | Description |
|---|---|---|
| `GCP_PROJECT_ID` | *required* | GCP project to monitor |
| `VERTEX_AI_MONTHLY_BUDGET` | `100` | Vertex AI budget (USD) |
| `BIGQUERY_MONTHLY_BUDGET` | `100` | BigQuery budget (USD) |
| `FIRESTORE_MONTHLY_BUDGET` | `100` | Firestore budget (USD) |
| `DRY_RUN_MODE` | `False` | Log actions without disabling |
| `LAB_MODE` | `False` | Use static pricing (no billing API required) |
| `PRICE_SOURCE` | `billing` | `billing` = live API + fallback, `static` = catalog only |
| `ALERT_RECEIVER_EMAILS` | `""` | Comma-separated recipient emails |
| `WARNING_THRESHOLD_PCT` | `80` | Warning alert threshold |
| `CRITICAL_THRESHOLD_PCT` | `100` | Disable API threshold |

## Cost

| Resource | Monthly Cost |
|---|---|
| Cloud Run | ~$0 (scale-to-zero) |
| Cloud Scheduler | ~$0.10 |
| Cloud Monitoring | Free tier |
| Cloud Billing API | Free |
| **Total** | **< $1/month** |

## License

See [LICENSE.md](LICENSE.md).
