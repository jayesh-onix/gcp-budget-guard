# GCP Budget Guard – Cloud Lab Testing Guide

This guide walks you through testing GCP Budget Guard in a Google Cloud Lab or sandbox environment. It uses simple language and step-by-step instructions.

---

## What This Service Does

GCP Budget Guard watches how much money your Google Cloud services are using. If a service (like Vertex AI, BigQuery, or Firestore) spends more than its budget, the tool **turns off only that service** to stop further charges. It does **not** delete your project or remove billing.

You can also turn services back on manually whenever you want.

---

## What You Need

- A Google Cloud project with billing enabled
- The `gcloud` command-line tool installed and logged in
- Python 3.10 or later
- A Gmail account (for email alerts – optional for basic testing)

> **Lab Mode**: GCP Budget Guard supports `LAB_MODE=True` which uses static pricing from a local JSON catalog instead of the Cloud Billing API. This is ideal for lab environments where billing API permissions are restricted.

---

## Step 1: Open Your Cloud Lab

1. Go to your Cloud Lab environment (or Google Cloud Shell).
2. Make sure you're logged in:
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```
3. Verify your project:
   ```bash
   gcloud config get-value project
   ```

---

## Step 2: Get the Code

If you haven't already, copy the `gcp-budget-guard` folder into your Cloud Lab environment.

```bash
cd gcp-budget-guard
```

---

## Step 3: Run the Tests (No GCP Needed)

The tests use fake data (mocks) so you don't need real GCP credentials:

```bash
# Install Python dependencies
pip install -r pip/requirements.txt

# Run all 126 tests
make test
```

You should see:
```
126 passed
```

This confirms the code is working correctly.

---

## Step 4: Run Locally in Dry-Run Mode

Dry-run mode lets you see what the service *would* do without actually disabling anything.

### 4a. Set Environment Variables

```bash
export GCP_PROJECT_ID=$(gcloud config get-value project)
export DRY_RUN_MODE=True
export DEBUG_MODE=True
export LAB_MODE=True
export PRICE_SOURCE=static
export VERTEX_AI_MONTHLY_BUDGET=100
export BIGQUERY_MONTHLY_BUDGET=100
export FIRESTORE_MONTHLY_BUDGET=100
```

> **Note**: `LAB_MODE=True` tells the service to use the static pricing catalog (`config/pricing_catalog.json`) instead of the Cloud Billing API. This avoids permission errors in lab environments where `cloudbilling.googleapis.com` is not available.

### 4b. Start the Service

```bash
make run-debug
```

You'll see output like:
```
INFO:     GCP Budget Guard starting up …
INFO:     DRY RUN MODE enabled
INFO:     Uvicorn running on http://0.0.0.0:8080
```

### 4c. Test the Endpoints

Open a **second terminal** and run:

```bash
# Health check
curl http://localhost:8080/health

# Run a budget check
curl -X POST http://localhost:8080/check

# See the status of all services
curl http://localhost:8080/status

# See the status of just one service
curl http://localhost:8080/status/vertex_ai
```

The `/check` endpoint will show you real usage data from your project. Because dry-run mode is on, it won't disable anything even if a budget is exceeded.

### 4d. Stop the Service

Press `Ctrl+C` in the first terminal.

---

## Step 5: Test with Low Budgets (See Alerts in Action)

To see what happens when a budget is exceeded, set very low budgets:

```bash
export VERTEX_AI_MONTHLY_BUDGET=0.001
export BIGQUERY_MONTHLY_BUDGET=0.001
export FIRESTORE_MONTHLY_BUDGET=0.001
export DRY_RUN_MODE=True   # Keep dry-run ON for safety
export LAB_MODE=True        # Use static pricing for lab
```

Start the service again:
```bash
make run-debug
```

Now trigger a check:
```bash
curl -X POST http://localhost:8080/check
```

Look at the response JSON – you'll see services marked as exceeded:
```json
{
  "budget": {
    "vertex_ai": {
      "usage_pct": 9999.9,
      "is_exceeded": true
    }
  },
  "disabled_apis": []   ← empty because dry-run is on
}
```

The logs will show:
```
[WARNING] BUDGET EXCEEDED for vertex_ai
[WARNING] [DRY RUN] Would disable: aiplatform.googleapis.com
```

---

## Step 6: Test Email Notifications (Optional)

If you want to test email alerts:

### 6a. Create a Gmail App Password

1. Go to https://myaccount.google.com/apppasswords
2. Select "Mail" and "Other (Custom name)"
3. Enter "Budget Guard" and click "Generate"
4. Copy the 16-character password

### 6b. Set Email Variables

```bash
export SMTP_EMAIL=your-email@gmail.com
export SMTP_APP_PASSWORD=your-app-password
export ALERT_RECEIVER_EMAILS=your-email@gmail.com
```

### 6c. Trigger a Check

With low budgets still set:
```bash
curl -X POST http://localhost:8080/check
```

Check your email – you should receive warning or critical emails.

---

## Step 7: Test Service Enable/Disable (Careful!)

**Warning**: This section actually disables real services. Only do this if you understand the consequences and are in a disposable lab environment.

### 7a. Turn Off Dry-Run Mode

```bash
export DRY_RUN_MODE=False
export VERTEX_AI_MONTHLY_BUDGET=0.001  # Very low budget
```

### 7b. Run a Check

```bash
curl -X POST http://localhost:8080/check
```

If Vertex AI usage exceeds $0.001, it will be disabled. The response will show:
```json
{
  "disabled_apis": ["aiplatform.googleapis.com"]
}
```

### 7c. Verify the Service is Disabled

```bash
curl http://localhost:8080/status/vertex_ai
```

You should see:
```json
{
  "api_state": "DISABLED"
}
```

### 7d. Re-Enable the Service

```bash
# Using the friendly name
curl -X POST http://localhost:8080/reset/vertex_ai

# Or using the full API name
curl -X POST http://localhost:8080/enable_service/aiplatform.googleapis.com
```

### 7e. Verify It's Enabled Again

```bash
curl http://localhost:8080/status/vertex_ai
```

```json
{
  "api_state": "ENABLED"
}
```

---

## Step 8: Deploy to Cloud Run (Full Test)

If you want to test the full deployment pipeline:

```bash
# Set your budgets to reasonable values
export VERTEX_AI_MONTHLY_BUDGET=100
export BIGQUERY_MONTHLY_BUDGET=100
export FIRESTORE_MONTHLY_BUDGET=100
export DRY_RUN_MODE=True   # Start with dry-run for safety
export LAB_MODE=True        # Use static pricing (no billing API needed)
export PRICE_SOURCE=static  # Use local pricing catalog

# Deploy
make deploy
```

The deploy script will:
1. Enable required GCP APIs (no billing API needed in lab mode)
2. Create a service account with the right permissions (non-fatal IAM binding)
3. Deploy the service to Cloud Run
4. Set up a Cloud Scheduler job (runs every 10 minutes, OIDC auth)
5. Create a Pub/Sub topic for alerts

After deployment, you can test with:
```bash
# Get the service URL
SERVICE_URL=$(gcloud run services describe gcp-budget-guard --region=us-central1 --format="value(status.url)")

# Test health
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" $SERVICE_URL/health

# Run a budget check
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" $SERVICE_URL/check
```

---

## Troubleshooting

### "GCP_PROJECT_ID environment variable is required"
You forgot to set the project ID:
```bash
export GCP_PROJECT_ID=$(gcloud config get-value project)
```

### "Permission denied" errors
Make sure the service account has the right roles. The deploy script handles this, but for local testing you need:
```bash
gcloud auth application-default login
```

### Tests fail with import errors
Make sure you set the Python path:
```bash
PYTHONPATH=src python -m pytest tests/ -v
```

### No emails received
- Check that `SMTP_EMAIL` and `SMTP_APP_PASSWORD` are set correctly.
- Make sure you generated a Gmail **App Password** (not your regular password).
- Check the service logs for SMTP errors.
- Each service receives at most **2 alert emails**: one WARNING at 80 % and one CRITICAL at 100 % (after disablement). No duplicates.

### Service not disabling APIs
- Check if `DRY_RUN_MODE` is set to `True` (it logs but doesn't act).
- Verify the service account has `roles/serviceusage.serviceUsageAdmin`.

---

## Quick Reference

| Command | What It Does |
|---|---|
| `make test` | Run all tests (no GCP needed) |
| `make run` | Start locally (needs environment variables) |
| `make run-debug` | Start locally with verbose logging |
| `make deploy` | Deploy everything to GCP |
| `curl http://localhost:8080/health` | Check if the service is running |
| `curl -X POST http://localhost:8080/check` | Run a budget check |
| `curl http://localhost:8080/status` | See all service statuses |
| `curl -X POST http://localhost:8080/reset/vertex_ai` | Re-enable Vertex AI |

---

## Clean Up

When you're done testing, clean up to avoid charges:

```bash
# Delete the Cloud Run service
gcloud run services delete gcp-budget-guard --region=us-central1 --quiet

# Delete the scheduler job
gcloud scheduler jobs delete gcp-budget-guard-scheduler --location=us-central1 --quiet

# Delete the Pub/Sub topic
gcloud pubsub topics delete budget-guard-alerts --quiet

# Delete the service account
gcloud iam service-accounts delete gcp-budget-guard-sa@$(gcloud config get-value project).iam.gserviceaccount.com --quiet
```

Or simply delete the Cloud Lab project if it's disposable.
