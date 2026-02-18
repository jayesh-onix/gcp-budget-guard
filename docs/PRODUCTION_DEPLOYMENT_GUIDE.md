# GCP Budget Guard – Production Deployment Guide

This guide covers deploying GCP Budget Guard to a production Google Cloud environment with proper security, monitoring, and operational procedures.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Pre-Deployment Checklist](#pre-deployment-checklist)
3. [Configuration](#configuration)
4. [Automated Deployment](#automated-deployment)
5. [Manual Deployment (Step by Step)](#manual-deployment-step-by-step)
6. [Post-Deployment Verification](#post-deployment-verification)
7. [Operational Procedures](#operational-procedures)
8. [Monitoring and Alerting](#monitoring-and-alerting)
9. [Security Considerations](#security-considerations)
10. [Updating and Rollback](#updating-and-rollback)
11. [Troubleshooting](#troubleshooting)
12. [Architecture Decisions](#architecture-decisions)

---

## Prerequisites

### Required Tools

| Tool | Minimum Version | Purpose |
|---|---|---|
| `gcloud` CLI | Latest | GCP resource management |
| Python | 3.10+ | Local testing |
| Docker | 20+ | Container builds (optional – Cloud Build handles this) |

### Required GCP APIs

The deploy script enables these automatically, but for reference:

- `artifactregistry.googleapis.com` – Container image storage
- `cloudbuild.googleapis.com` – Build from source
- `run.googleapis.com` – Cloud Run hosting
- `cloudscheduler.googleapis.com` – Periodic triggers
- `monitoring.googleapis.com` – Usage metrics
- `serviceusage.googleapis.com` – Enable/disable APIs
- `cloudbilling.googleapis.com` – Live pricing data
- `pubsub.googleapis.com` – Budget alert topic

### Required IAM Permissions (for the deployer)

The person running `deploy.sh` needs:

- `roles/owner` or `roles/editor` on the project (to create service accounts and IAM bindings)
- Alternatively, these specific roles:
  - `roles/iam.serviceAccountAdmin`
  - `roles/resourcemanager.projectIamAdmin`
  - `roles/run.admin`
  - `roles/cloudscheduler.admin`
  - `roles/pubsub.admin`
  - `roles/serviceusage.serviceUsageAdmin`

---

## Pre-Deployment Checklist

Before deploying to production, confirm:

- [ ] GCP project has billing enabled
- [ ] You have decided on per-service budget amounts
- [ ] Gmail App Password is generated (if using email alerts)
- [ ] Recipient email addresses are collected
- [ ] You have tested locally with `DRY_RUN_MODE=True`
- [ ] All 62 tests pass (`make test`)
- [ ] You understand that this service **disables APIs** (not deletes projects)

---

## Configuration

### Environment Variables

Copy `.env.example` and fill in your values:

```bash
cp .env.example .env
```

#### Required

```bash
GCP_PROJECT_ID=my-production-project
```

#### Budget Configuration

```bash
# Per-service budgets in USD
VERTEX_AI_MONTHLY_BUDGET=500
BIGQUERY_MONTHLY_BUDGET=200
FIRESTORE_MONTHLY_BUDGET=100

# Overall project budget (defaults to sum of per-service budgets)
MONTHLY_BUDGET_AMOUNT=800
CURRENCY_CODE=USD
```

#### Alert Thresholds

```bash
# Send warning email at 80% of budget
WARNING_THRESHOLD_PCT=80

# Disable service at 100% of budget
CRITICAL_THRESHOLD_PCT=100

```

#### Email Notifications

```bash
SMTP_EMAIL=budget-alerts@yourcompany.com
SMTP_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

# Multiple recipients, comma-separated
ALERT_RECEIVER_EMAILS=cto@company.com,platform-team@company.com,oncall@company.com
```

> **Gmail App Password**: Go to https://myaccount.google.com/apppasswords, select "Mail" → "Other", name it "Budget Guard", and copy the generated password.

#### Operational Modes

```bash
# Start with True in production, switch to False when confident
DRY_RUN_MODE=False

# Set True only for troubleshooting
DEBUG_MODE=False
```

#### Recommended Production Strategy

1. **Week 1**: Deploy with `DRY_RUN_MODE=True`. Monitor logs to see what *would* happen.
2. **Week 2**: If logs look correct, set `DRY_RUN_MODE=False` to enable enforcement.
3. **Ongoing**: Review alerts and adjust budgets monthly.

---

## Automated Deployment

The `deploy.sh` script handles the entire deployment in 7 steps:

```bash
# Source your environment variables
source .env

# Run the deployment
make deploy
```

Or directly:

```bash
chmod +x deploy.sh
bash deploy.sh
```

### What the Script Does

| Step | Action | Details |
|---|---|---|
| 1/7 | Enable APIs | 8 required GCP APIs |
| 2/7 | Service Account | Creates `gcp-budget-guard-sa` with 4 IAM roles |
| 3/7 | Cloud Run | Deploys from source, 512MB memory, auto-scaling 0-5 |
| 4/7 | Cloud Scheduler | Creates `*/10 * * * *` cron → `POST /check` |
| 5/7 | Pub/Sub | Creates `budget-guard-alerts` topic |
| 6/7 | IAM Binding | Grants scheduler SA permission to invoke Cloud Run |
| 7/7 | Smoke Test | Verifies the health endpoint responds |

### Service Account Roles

| Role | Why |
|---|---|
| `roles/monitoring.viewer` | Read usage metrics from Cloud Monitoring |
| `roles/serviceusage.serviceUsageAdmin` | Enable and disable individual service APIs |
| `roles/run.invoker` | Allow Cloud Scheduler to call the Cloud Run endpoint |
| `roles/cloudbilling.viewer` | Read SKU pricing from Cloud Billing Catalog API |

### Cloud Run Configuration

| Setting | Value | Reason |
|---|---|---|
| Memory | 512 Mi | Sufficient for API calls and JSON processing |
| vCPU | 1 | Budget checks are I/O bound, not CPU bound |
| Timeout | 300s | Budget checks with billing API can take up to a minute |
| Max instances | 5 | Scheduler sends one request at a time; 5 handles retries |
| Min instances | 0 | Scale to zero when idle to save costs |
| Auth | `--no-allow-unauthenticated` | Only Cloud Scheduler (with OAuth token) can invoke |

---

## Manual Deployment (Step by Step)

If you prefer to deploy manually or need to customise steps:

### Step 1: Enable APIs

```bash
PROJECT_ID=your-project

for api in artifactregistry.googleapis.com cloudbuild.googleapis.com \
  run.googleapis.com cloudscheduler.googleapis.com monitoring.googleapis.com \
  serviceusage.googleapis.com cloudbilling.googleapis.com pubsub.googleapis.com; do
  gcloud services enable $api --project $PROJECT_ID
done

sleep 15  # Wait for API propagation
```

### Step 2: Create Service Account

```bash
SA_NAME=gcp-budget-guard-sa
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create $SA_NAME \
  --project $PROJECT_ID \
  --display-name "GCP Budget Guard Service Account"

for role in roles/monitoring.viewer roles/serviceusage.serviceUsageAdmin \
  roles/run.invoker roles/cloudbilling.viewer; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member "serviceAccount:$SA_EMAIL" \
    --role $role \
    --condition=None --quiet
done
```

### Step 3: Deploy Cloud Run

```bash
gcloud run deploy gcp-budget-guard \
  --project $PROJECT_ID \
  --source . \
  --region us-central1 \
  --service-account $SA_EMAIL \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID,VERTEX_AI_MONTHLY_BUDGET=500,BIGQUERY_MONTHLY_BUDGET=200,FIRESTORE_MONTHLY_BUDGET=100,DRY_RUN_MODE=False" \
  --memory 512Mi --cpu 1 --timeout 300 \
  --max-instances 5 --min-instances 0 \
  --no-allow-unauthenticated
```

### Step 4: Create Cloud Scheduler

```bash
SERVICE_URL=$(gcloud run services describe gcp-budget-guard \
  --project $PROJECT_ID --region us-central1 \
  --format "value(status.url)")

gcloud scheduler jobs create http gcp-budget-guard-scheduler \
  --project $PROJECT_ID \
  --location us-central1 \
  --schedule "*/10 * * * *" \
  --uri "${SERVICE_URL}/check" \
  --http-method POST \
  --oauth-service-account-email $SA_EMAIL \
  --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
  --time-zone "Etc/UTC" \
  --max-retry-attempts 1
```

### Step 5: Create Pub/Sub Topic

```bash
gcloud pubsub topics create budget-guard-alerts --project $PROJECT_ID
```

---

## Post-Deployment Verification

### Immediate Checks

```bash
PROJECT_ID=your-project
REGION=us-central1
SERVICE_URL=$(gcloud run services describe gcp-budget-guard --project $PROJECT_ID --region $REGION --format "value(status.url)")

# 1. Health check
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" $SERVICE_URL/health
# Expected: {"status":"healthy","service":"gcp-budget-guard"}

# 2. Manual budget check
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" $SERVICE_URL/check
# Expected: JSON with budget summary, disabled_apis=[], warnings_sent=[]

# 3. Service status
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" $SERVICE_URL/status
# Expected: JSON with all services showing api_state

# 4. Verify scheduler exists
gcloud scheduler jobs describe gcp-budget-guard-scheduler --location $REGION --project $PROJECT_ID

# 5. Check logs
gcloud run services logs read gcp-budget-guard --region $REGION --project $PROJECT_ID --limit 20
```

### Scheduled Run Verification

Wait 10 minutes, then check that the scheduler triggered successfully:

```bash
# Check scheduler execution history
gcloud scheduler jobs describe gcp-budget-guard-scheduler \
  --location us-central1 --project $PROJECT_ID \
  --format "yaml(lastAttemptTime,status,state)"

# Check Cloud Run logs for the scheduled run
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="gcp-budget-guard" AND textPayload:"Budget check cycle complete"' \
  --project $PROJECT_ID --limit 5 --format "table(timestamp,textPayload)"
```

---

## Operational Procedures

### Re-Enable a Disabled Service

When a service is disabled due to budget exceedance:

```bash
# Using the friendly service key
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  $SERVICE_URL/reset/vertex_ai

# Or using the full API name
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  $SERVICE_URL/enable_service/aiplatform.googleapis.com
```

Valid service keys: `vertex_ai`, `bigquery`, `firestore`

### Adjust Budgets

Update the Cloud Run environment variables:

```bash
gcloud run services update gcp-budget-guard \
  --project $PROJECT_ID \
  --region us-central1 \
  --update-env-vars "VERTEX_AI_MONTHLY_BUDGET=750,BIGQUERY_MONTHLY_BUDGET=300"
```

This triggers a new Cloud Run revision with zero downtime.

### Pause Enforcement (Emergency)

Enable dry-run mode without redeploying:

```bash
gcloud run services update gcp-budget-guard \
  --project $PROJECT_ID \
  --region us-central1 \
  --update-env-vars "DRY_RUN_MODE=True"
```

### Pause Scheduling

```bash
gcloud scheduler jobs pause gcp-budget-guard-scheduler \
  --location us-central1 --project $PROJECT_ID
```

Resume:
```bash
gcloud scheduler jobs resume gcp-budget-guard-scheduler \
  --location us-central1 --project $PROJECT_ID
```

### Force an Immediate Check

```bash
gcloud scheduler jobs run gcp-budget-guard-scheduler \
  --location us-central1 --project $PROJECT_ID
```

---

## Monitoring and Alerting

### Cloud Run Metrics to Watch

| Metric | Alert Condition | Meaning |
|---|---|---|
| `run.googleapis.com/request_latencies` | > 60s p99 | Budget check is slow — billing API may be throttled |
| `run.googleapis.com/request_count` (5xx) | > 0 | Budget check is failing |
| `run.googleapis.com/container/instance_count` | > 3 sustained | Unexpected load |

### Log-Based Alerts

Create alerts for critical log entries:

```bash
# Alert when a service is actually disabled
gcloud logging metrics create budget-guard-service-disabled \
  --project $PROJECT_ID \
  --description "Service disabled by Budget Guard" \
  --log-filter 'resource.type="cloud_run_revision" AND textPayload:"API disabled successfully"'

# Alert when budget check fails
gcloud logging metrics create budget-guard-check-failed \
  --project $PROJECT_ID \
  --description "Budget check cycle failed" \
  --log-filter 'resource.type="cloud_run_revision" AND textPayload:"Budget check failed"'
```

### Email Alert Behaviour

- **Warning** (default 80%): Informs recipients that spending is approaching the limit. No action taken.
- **Critical** (default 100%): Informs recipients that the budget was exceeded and the service API was disabled. Includes instructions to re-enable.
- **Alert cap**: Each service receives at most **2 emails** per billing cycle (1× WARNING at 80 %, 1× CRITICAL at 100 % after API disable). No duplicates on subsequent scheduler runs.
- **Graceful degradation**: If SMTP is not configured, the service runs without email — it still enforces budgets.

---

## Security Considerations

### Authentication

- Cloud Run is deployed with `--no-allow-unauthenticated`.
- Cloud Scheduler uses an OAuth token scoped to the service account.
- Manual API calls require a valid identity token: `gcloud auth print-identity-token`.

### Least Privilege

The service account has only 4 roles:

| Role | Scope | Why |
|---|---|---|
| `monitoring.viewer` | Project | Read-only access to Cloud Monitoring metrics |
| `serviceusage.serviceUsageAdmin` | Project | Enable/disable individual APIs (required for enforcement) |
| `run.invoker` | Service | Allow scheduler to invoke this specific Cloud Run service |
| `cloudbilling.viewer` | Project | Read-only access to billing SKU pricing |

The service account **cannot**:
- Delete the project
- Remove or modify billing accounts
- Create or delete other resources
- Access data in Vertex AI, BigQuery, or Firestore

### Secrets Management

For production, consider storing `SMTP_APP_PASSWORD` in Secret Manager:

```bash
# Create secret
echo -n "your-app-password" | gcloud secrets create budget-guard-smtp-password \
  --data-file=- --project $PROJECT_ID

# Grant access to the service account
gcloud secrets add-iam-policy-binding budget-guard-smtp-password \
  --member "serviceAccount:$SA_EMAIL" \
  --role "roles/secretmanager.secretAccessor" \
  --project $PROJECT_ID

# Mount in Cloud Run
gcloud run services update gcp-budget-guard \
  --project $PROJECT_ID --region us-central1 \
  --update-secrets "SMTP_APP_PASSWORD=budget-guard-smtp-password:latest"
```

---

## Updating and Rollback

### Deploy a New Version

```bash
# From the gcp-budget-guard directory
gcloud run deploy gcp-budget-guard \
  --project $PROJECT_ID \
  --source . \
  --region us-central1
```

Cloud Run performs a rolling update with zero downtime.

### Rollback to Previous Version

```bash
# List revisions
gcloud run revisions list --service gcp-budget-guard \
  --project $PROJECT_ID --region us-central1

# Route traffic to a specific revision
gcloud run services update-traffic gcp-budget-guard \
  --project $PROJECT_ID --region us-central1 \
  --to-revisions gcp-budget-guard-00005-abc=100
```

---

## Troubleshooting

### Budget Check Returns All Zeros

**Cause**: No usage data in Cloud Monitoring for the current calendar month.

**Fix**: This is normal at the start of a month or if services haven't been used yet. The metrics query window starts from the 1st of the current month.

### "Permission denied" on Service Usage API

**Cause**: Missing `roles/serviceusage.serviceUsageAdmin` role.

**Fix**:
```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member "serviceAccount:$SA_EMAIL" \
  --role "roles/serviceusage.serviceUsageAdmin" \
  --condition=None
```

### Cloud Billing API Returns No Prices

**Cause**: SKU IDs may have changed for your region, or the API isn't enabled.

**Fix**:
1. Ensure `cloudbilling.googleapis.com` is enabled.
2. Verify SKU IDs at https://cloud.google.com/billing/v1/how-tos/catalog-api.
3. The service logs the specific error — check Cloud Run logs.

### Scheduler Returns 403

**Cause**: The scheduler's service account can't invoke Cloud Run.

**Fix**:
```bash
gcloud run services add-iam-policy-binding gcp-budget-guard \
  --project $PROJECT_ID --region us-central1 \
  --member "serviceAccount:$SA_EMAIL" \
  --role "roles/run.invoker"
```

### Emails Not Sending

1. Verify `SMTP_EMAIL` and `SMTP_APP_PASSWORD` are set in Cloud Run env vars.
2. Check that you used a Gmail **App Password** (not your regular password).
3. Look for SMTP errors in logs:
   ```bash
   gcloud run services logs read gcp-budget-guard --region us-central1 --project $PROJECT_ID | grep -i smtp
   ```
4. Each service only sends 2 emails total (WARNING + CRITICAL). If both were already sent, no further emails are expected until alert counters are reset.

### High Latency on `/check`

**Cause**: Cloud Billing Catalog API can be slow on first call (fetches full SKU list).

**Mitigation**: SKUs are cached in memory per service. First run may take 30-60 seconds; subsequent runs (within the same container instance) take 2-5 seconds.

---

## Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Cloud Run Service (not Job) | FastAPI on Cloud Run | Keeps the HTTP endpoint alive for manual queries + scheduled checks |
| Cloud Billing Catalog API | Live pricing | Avoids stale hardcoded prices; auto-adapts to price changes |
| Per-service budgets | Independent limits | One expensive service doesn't shut down others |
| Service disable (not project delete) | `services.disable()` | Surgical — only affects the offending service |
| Gmail SMTP | Simple email | No additional infrastructure; works with any Gmail account |
| Cooldown deduplication | In-memory dict | Prevents alert storms; resets on container restart (acceptable) |
| 10-minute interval | Cloud Scheduler cron | Balances responsiveness with API quota usage |
| No persistent state | Stateless | Budget resets monthly by design; no database needed |

---

## Cost of Running Budget Guard

The service itself has minimal cost:

| Resource | Estimated Monthly Cost |
|---|---|
| Cloud Run | ~$0 (scale-to-zero, <5 min active/day) |
| Cloud Scheduler | ~$0.10 (1 job) |
| Cloud Monitoring reads | Free tier covers this |
| Cloud Billing API reads | Free |
| **Total** | **< $1/month** |
