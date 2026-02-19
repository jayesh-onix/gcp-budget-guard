# End-to-End Testing & Verification Guide

> Step-by-step: deploy, exhaust budgets, verify disabling, test reset, teardown.  
> Works in both lab and production environments.

---

## Part 1 — Deploy

### Lab (Qwiklabs / Cloud Skills Boost)

```bash
export GCP_PROJECT_ID="your-lab-project-id"
export GCP_REGION="us-central1"
export LAB_MODE=True
export PRICE_SOURCE=static

# Set LOW budgets so services get disabled quickly during testing
export VERTEX_AI_MONTHLY_BUDGET=1
export BIGQUERY_MONTHLY_BUDGET=1
export FIRESTORE_MONTHLY_BUDGET=1
export MONTHLY_BUDGET_AMOUNT=3

# Optional: email alerts
export SMTP_EMAIL="you@gmail.com"
export SMTP_APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"
export ALERT_RECEIVER_EMAILS="you@gmail.com"

# Fast scheduler (every 2 min) for testing
export SCHEDULER_INTERVAL=2

bash deploy.sh --yes
```

### Production (Real GCP Project)

```bash
export GCP_PROJECT_ID="your-prod-project"
export LAB_MODE=False
export PRICE_SOURCE=billing

# Set realistic budgets
export VERTEX_AI_MONTHLY_BUDGET=50
export BIGQUERY_MONTHLY_BUDGET=30
export FIRESTORE_MONTHLY_BUDGET=20
export MONTHLY_BUDGET_AMOUNT=100

export SMTP_EMAIL="you@gmail.com"
export SMTP_APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"
export ALERT_RECEIVER_EMAILS="admin@company.com"

export SCHEDULER_INTERVAL=10

bash deploy.sh
```

### Save URL and Token (used in all steps below)

```bash
URL=$(gcloud run services describe gcp-budget-guard \
  --region us-central1 --format="value(status.url)")
TOKEN=$(gcloud auth print-identity-token)
echo "URL: $URL"
```

---

## Part 2 — Verify Deployment

```bash
# Health check
curl -s -H "Authorization: Bearer $TOKEN" $URL/health

# Status of all services
curl -s -H "Authorization: Bearer $TOKEN" $URL/status | python3 -m json.tool

# Manual budget check (should show $0 or low spend initially)
curl -s -X POST -H "Authorization: Bearer $TOKEN" $URL/check | python3 -m json.tool
```

---

## Part 3 — Exhaust Service Budgets (Trigger the Kill Switch)

### Install dependencies first

```bash
pip install google-cloud-aiplatform google-cloud-bigquery google-cloud-firestore
```

### Test 1: Exhaust Vertex AI (Gemini)

```bash
export GCP_PROJECT_ID="your-project-id"
python3 scripts/exhaust_vertex_ai.py
```

This sends ~50 Gemini API calls. With $1 budget, it should exceed within 1-2 minutes.

**Wait for the next scheduler cycle** (2 min if SCHEDULER_INTERVAL=2), then:

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -s -X POST -H "Authorization: Bearer $TOKEN" $URL/check | python3 -m json.tool
```

**Expected:** Response shows `vertex_ai` as exceeded, `aiplatform.googleapis.com` in `disabled_apis`.

**Verify API is actually disabled:**

```bash
# This should FAIL (API disabled)
python3 -c "
import vertexai
from vertexai.generative_models import GenerativeModel
vertexai.init(project='$GCP_PROJECT_ID', location='us-central1')
model = GenerativeModel('gemini-2.0-flash-lite')
print(model.generate_content('Hello').text)
"
# Expected error: 403 or "API has been disabled"
```

### Test 2: Exhaust BigQuery

```bash
python3 scripts/exhaust_bigquery.py
```

Wait for scheduler, then check:

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -s -X POST -H "Authorization: Bearer $TOKEN" $URL/check | python3 -m json.tool
```

### Test 3: Exhaust Firestore

```bash
python3 scripts/exhaust_firestore.py
```

Wait for scheduler, then check.

---

## Part 4 — Test Reset (Re-enable a Disabled Service)

After a service has been disabled:

```bash
TOKEN=$(gcloud auth print-identity-token)

# Reset vertex_ai — saves baseline + resets alerts + re-enables API
curl -s -X POST -H "Authorization: Bearer $TOKEN" $URL/reset/vertex_ai | python3 -m json.tool
```

**Expected response:**
```json
{
  "status": "success",
  "service_key": "vertex_ai",
  "api_enabled": true,
  "baseline_saved": 15.2345,
  "alerts_reset": true
}
```

**Verify the API works again:**

```bash
python3 -c "
import vertexai
from vertexai.generative_models import GenerativeModel
vertexai.init(project='$GCP_PROJECT_ID', location='us-central1')
model = GenerativeModel('gemini-2.0-flash-lite')
print(model.generate_content('Say hello in one word').text)
"
# Expected: Works! Returns response
```

**Verify next check does NOT re-disable** (baseline was saved):

```bash
TOKEN=$(gcloud auth print-identity-token)
curl -s -X POST -H "Authorization: Bearer $TOKEN" $URL/check | python3 -m json.tool
# Expected: vertex_ai shows low effective cost (baseline subtracted), NOT in disabled_apis
```

**Reset other services too:**
```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" $URL/reset/bigquery
curl -s -X POST -H "Authorization: Bearer $TOKEN" $URL/reset/firestore
```

---

## Part 5 — Check Logs

```bash
# Cloud Run live logs
gcloud run services logs read gcp-budget-guard \
  --region=us-central1 --project=$GCP_PROJECT_ID --limit=50

# Filter for specific events
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=gcp-budget-guard AND textPayload:BUDGET" \
  --project=$GCP_PROJECT_ID --limit=20
```

What to look for in logs:
- `BUDGET EXCEEDED for vertex_ai` — trigger worked
- `Successfully disabled API: aiplatform.googleapis.com` — kill switch worked
- `Baseline set for vertex_ai: $X.XX` — reset saved baseline
- `Baseline applied for vertex_ai` — check is subtracting baseline

---

## Part 6 — Teardown (Remove Everything)

If the application misbehaves or you're done testing:

### Lab

```bash
bash teardown.sh --yes
```

### Production

```bash
bash teardown.sh
# Will ask for confirmation before deleting
```

### What teardown removes:
1. Cloud Scheduler job (`gcp-budget-guard-scheduler`)
2. Cloud Run service (`gcp-budget-guard`)
3. Pub/Sub topic (`budget-guard-alerts`)
4. Service account (`gcp-budget-guard-sa`)

### What teardown does NOT touch:
- Your GCP project (NOT deleted)
- Your billing account (NOT unlinked)
- Any disabled APIs stay disabled — re-enable manually if needed:

```bash
gcloud services enable aiplatform.googleapis.com --project=$GCP_PROJECT_ID
gcloud services enable bigquery.googleapis.com --project=$GCP_PROJECT_ID
gcloud services enable firestore.googleapis.com --project=$GCP_PROJECT_ID
```

---

## Quick Reference — All Commands

| Action | Command |
|--------|---------|
| Deploy (lab) | `LAB_MODE=True bash deploy.sh --yes` |
| Deploy (prod) | `bash deploy.sh` |
| Health check | `curl -s -H "Auth..." $URL/health` |
| Run budget check | `curl -s -X POST -H "Auth..." $URL/check` |
| Status | `curl -s -H "Auth..." $URL/status` |
| Reset a service | `curl -s -X POST -H "Auth..." $URL/reset/vertex_ai` |
| Enable API only | `curl -s -X POST -H "Auth..." $URL/enable_service/aiplatform.googleapis.com` |
| View logs | `gcloud run services logs read gcp-budget-guard --region=us-central1` |
| Teardown (lab) | `bash teardown.sh --yes` |
| Teardown (prod) | `bash teardown.sh` |

> Replace `"Auth..."` with `"Authorization: Bearer $(gcloud auth print-identity-token)"`
