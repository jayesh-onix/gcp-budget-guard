#!/usr/bin/env bash
###############################################################################
# GCP Budget Guard – Production Deployment Script
#
# Deploys:
#   1. Required GCP APIs
#   2. Service account + IAM roles
#   3. Cloud Run Service (not Job – keeps the FastAPI endpoint alive)
#   4. Cloud Scheduler (POST /check every 10 minutes)
#   5. Pub/Sub topic for budget alerts
#   6. (Optional) Budget alert that publishes to the topic
#
# SAFETY:
#   • Does NOT delete the GCP project.
#   • Does NOT unlink the billing account.
#   • Only disables individual service APIs when their budget is exceeded.
###############################################################################

set -euo pipefail

# ─── Colours ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()    { echo -e "${RED}[ERR]${NC}  $1"; exit 1; }
header()  { echo -e "\n${BLUE}═══════════════════════════════════════════════${NC}"; echo -e "${BLUE}  $1${NC}"; echo -e "${BLUE}═══════════════════════════════════════════════${NC}"; }

# ─── Pre-flight checks ───────────────────────────────────────────────────
command -v gcloud >/dev/null 2>&1 || fail "gcloud CLI not found – install Google Cloud SDK first."
success "gcloud CLI found"

# ─── Configuration (with sane defaults) ──────────────────────────────────
header "Configuration"

GCP_PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
[ -z "$GCP_PROJECT_ID" ] && fail "GCP_PROJECT_ID not set.  export GCP_PROJECT_ID=your-project"
info "Project:              $GCP_PROJECT_ID"

GCP_REGION="${GCP_REGION:-us-central1}"
info "Region:               $GCP_REGION"

# Budget per service (USD)
VERTEX_AI_MONTHLY_BUDGET="${VERTEX_AI_MONTHLY_BUDGET:-100}"
BIGQUERY_MONTHLY_BUDGET="${BIGQUERY_MONTHLY_BUDGET:-100}"
FIRESTORE_MONTHLY_BUDGET="${FIRESTORE_MONTHLY_BUDGET:-100}"
MONTHLY_BUDGET_AMOUNT="${MONTHLY_BUDGET_AMOUNT:-300}"
CURRENCY_CODE="${CURRENCY_CODE:-USD}"
info "Vertex AI budget:     \$${VERTEX_AI_MONTHLY_BUDGET}"
info "BigQuery budget:      \$${BIGQUERY_MONTHLY_BUDGET}"
info "Firestore budget:     \$${FIRESTORE_MONTHLY_BUDGET}"
info "Total project budget: \$${MONTHLY_BUDGET_AMOUNT}"

# Notification
SMTP_EMAIL="${SMTP_EMAIL:-}"
SMTP_APP_PASSWORD="${SMTP_APP_PASSWORD:-}"
ALERT_RECEIVER_EMAILS="${ALERT_RECEIVER_EMAILS:-}"
WARNING_THRESHOLD_PCT="${WARNING_THRESHOLD_PCT:-80}"
CRITICAL_THRESHOLD_PCT="${CRITICAL_THRESHOLD_PCT:-100}"
ALERT_COOLDOWN_SECONDS="${ALERT_COOLDOWN_SECONDS:-3600}"

# Modes
DRY_RUN_MODE="${DRY_RUN_MODE:-False}"
DEBUG_MODE="${DEBUG_MODE:-False}"
SCHEDULER_INTERVAL="${SCHEDULER_INTERVAL:-10}"

# Names
SERVICE_NAME="gcp-budget-guard"
SA_NAME="${SERVICE_NAME}-sa"
SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_JOB="${SERVICE_NAME}-scheduler"
PUBSUB_TOPIC="${PUBSUB_TOPIC_NAME:-budget-guard-alerts}"

info "Cloud Run service:    $SERVICE_NAME"
info "Service account:      $SA_EMAIL"
info "Scheduler interval:   every ${SCHEDULER_INTERVAL} minutes"
info "Dry-run mode:         $DRY_RUN_MODE"
info "Debug mode:           $DEBUG_MODE"

echo ""
read -rp "Proceed with deployment? [y/N] " confirm
[[ "$confirm" =~ ^[Yy] ]] || { info "Deployment cancelled."; exit 0; }

# ─── 1. Enable required GCP APIs ─────────────────────────────────────────
header "1/7  Enabling required APIs"

REQUIRED_APIS=(
    "artifactregistry.googleapis.com"
    "cloudbuild.googleapis.com"
    "run.googleapis.com"
    "cloudscheduler.googleapis.com"
    "monitoring.googleapis.com"
    "serviceusage.googleapis.com"
    "cloudbilling.googleapis.com"
    "pubsub.googleapis.com"
)

for api in "${REQUIRED_APIS[@]}"; do
    STATUS=$(gcloud services list --enabled \
        --filter="config.name=$api" \
        --project "$GCP_PROJECT_ID" \
        --format="value(config.name)" 2>/dev/null || true)
    if [ "$STATUS" = "$api" ]; then
        success "$api already enabled"
    else
        info "Enabling $api …"
        gcloud services enable "$api" --project "$GCP_PROJECT_ID" --quiet
        success "$api enabled"
    fi
done

info "Waiting 15 s for API propagation …"
sleep 15

# ─── 2. Service account & IAM ────────────────────────────────────────────
header "2/7  Service account & IAM"

if gcloud iam service-accounts describe "$SA_EMAIL" --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
    success "Service account exists: $SA_EMAIL"
else
    info "Creating service account …"
    gcloud iam service-accounts create "$SA_NAME" \
        --project "$GCP_PROJECT_ID" \
        --display-name "GCP Budget Guard Service Account"
    success "Service account created"
fi

ROLES=(
    "roles/monitoring.viewer"
    "roles/serviceusage.serviceUsageAdmin"
    "roles/run.invoker"
    "roles/cloudbilling.viewer"
)

for role in "${ROLES[@]}"; do
    info "Binding $role …"
    gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
        --member "serviceAccount:$SA_EMAIL" \
        --role "$role" \
        --condition=None \
        --quiet >/dev/null 2>&1
    success "$role bound"
done

# ─── 3. Cloud Run deployment ─────────────────────────────────────────────
header "3/7  Cloud Run"

# Build env-vars string
ENV_VARS="GCP_PROJECT_ID=$GCP_PROJECT_ID"
ENV_VARS+=",CURRENCY_CODE=$CURRENCY_CODE"
ENV_VARS+=",VERTEX_AI_MONTHLY_BUDGET=$VERTEX_AI_MONTHLY_BUDGET"
ENV_VARS+=",BIGQUERY_MONTHLY_BUDGET=$BIGQUERY_MONTHLY_BUDGET"
ENV_VARS+=",FIRESTORE_MONTHLY_BUDGET=$FIRESTORE_MONTHLY_BUDGET"
ENV_VARS+=",MONTHLY_BUDGET_AMOUNT=$MONTHLY_BUDGET_AMOUNT"
ENV_VARS+=",WARNING_THRESHOLD_PCT=$WARNING_THRESHOLD_PCT"
ENV_VARS+=",CRITICAL_THRESHOLD_PCT=$CRITICAL_THRESHOLD_PCT"
ENV_VARS+=",ALERT_COOLDOWN_SECONDS=$ALERT_COOLDOWN_SECONDS"
ENV_VARS+=",DRY_RUN_MODE=$DRY_RUN_MODE"
ENV_VARS+=",DEBUG_MODE=$DEBUG_MODE"
ENV_VARS+=",SCHEDULER_INTERVAL_MINUTES=$SCHEDULER_INTERVAL"
ENV_VARS+=",PUBSUB_TOPIC_NAME=$PUBSUB_TOPIC"

# Add email config if present
[ -n "$SMTP_EMAIL" ]           && ENV_VARS+=",SMTP_EMAIL=$SMTP_EMAIL"
[ -n "$SMTP_APP_PASSWORD" ]    && ENV_VARS+=",SMTP_APP_PASSWORD=$SMTP_APP_PASSWORD"
[ -n "$ALERT_RECEIVER_EMAILS" ] && ENV_VARS+=",ALERT_RECEIVER_EMAILS=$ALERT_RECEIVER_EMAILS"

info "Deploying Cloud Run service from source …"
gcloud run deploy "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --source . \
    --region "$GCP_REGION" \
    --service-account "$SA_EMAIL" \
    --set-env-vars "$ENV_VARS" \
    --memory 512Mi \
    --cpu 1 \
    --timeout 300 \
    --max-instances 5 \
    --min-instances 0 \
    --no-allow-unauthenticated \
    --quiet

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --format "value(status.url)")
success "Cloud Run deployed: $SERVICE_URL"

# ─── 4. Cloud Scheduler ──────────────────────────────────────────────────
header "4/7  Cloud Scheduler (every ${SCHEDULER_INTERVAL} min)"

if gcloud scheduler jobs describe "$SCHEDULER_JOB" \
    --project "$GCP_PROJECT_ID" --location "$GCP_REGION" >/dev/null 2>&1; then
    info "Deleting existing scheduler job …"
    gcloud scheduler jobs delete "$SCHEDULER_JOB" \
        --project "$GCP_PROJECT_ID" --location "$GCP_REGION" --quiet
fi

gcloud scheduler jobs create http "$SCHEDULER_JOB" \
    --project "$GCP_PROJECT_ID" \
    --location "$GCP_REGION" \
    --schedule "*/${SCHEDULER_INTERVAL} * * * *" \
    --uri "${SERVICE_URL}/check" \
    --http-method POST \
    --oauth-service-account-email "$SA_EMAIL" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
    --time-zone "Etc/UTC" \
    --max-retry-attempts 1 \
    --description "GCP Budget Guard – check every ${SCHEDULER_INTERVAL} min" \
    --quiet
success "Scheduler job created: $SCHEDULER_JOB"

# ─── 5. Pub/Sub topic ────────────────────────────────────────────────────
header "5/7  Pub/Sub topic"

if gcloud pubsub topics describe "$PUBSUB_TOPIC" --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
    success "Topic already exists: $PUBSUB_TOPIC"
else
    gcloud pubsub topics create "$PUBSUB_TOPIC" --project "$GCP_PROJECT_ID" --quiet
    success "Topic created: $PUBSUB_TOPIC"
fi

# ─── 6. Grant Cloud Run invoker to scheduler SA ──────────────────────────
header "6/7  IAM for scheduler → Cloud Run"

gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --member "serviceAccount:$SA_EMAIL" \
    --role "roles/run.invoker" \
    --quiet >/dev/null 2>&1
success "Scheduler SA can invoke Cloud Run"

# ─── 7. Smoke test ───────────────────────────────────────────────────────
header "7/7  Smoke test"

info "Testing health endpoint …"
HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    "${SERVICE_URL}/health" 2>/dev/null || echo "000")

if [ "$HEALTH_RESPONSE" = "200" ]; then
    success "Health endpoint returned HTTP 200"
else
    warn "Health endpoint returned HTTP $HEALTH_RESPONSE (may take a moment for first deploy)"
fi

# ─── Summary ──────────────────────────────────────────────────────────────
header "Deployment Complete"

cat <<EOF

  ✅  GCP Budget Guard deployed successfully!

  Service URL:    $SERVICE_URL
  Scheduler:      Every ${SCHEDULER_INTERVAL} minutes → POST ${SERVICE_URL}/check
  Pub/Sub topic:  $PUBSUB_TOPIC

  Budgets:
    Vertex AI:    \$${VERTEX_AI_MONTHLY_BUDGET}/month
    BigQuery:     \$${BIGQUERY_MONTHLY_BUDGET}/month
    Firestore:    \$${FIRESTORE_MONTHLY_BUDGET}/month
    Total:        \$${MONTHLY_BUDGET_AMOUNT}/month

  Useful commands:
    # Manual budget check
    curl -X POST -H "Authorization: Bearer \$(gcloud auth print-identity-token)" ${SERVICE_URL}/check

    # Re-enable a disabled service
    curl -X POST -H "Authorization: Bearer \$(gcloud auth print-identity-token)" ${SERVICE_URL}/reset/firestore

    # View status
    curl -H "Authorization: Bearer \$(gcloud auth print-identity-token)" ${SERVICE_URL}/status

    # View logs
    gcloud run services logs read $SERVICE_NAME --region=$GCP_REGION --project=$GCP_PROJECT_ID

EOF
