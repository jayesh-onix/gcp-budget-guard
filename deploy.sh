#!/usr/bin/env bash
###############################################################################
# GCP Budget Guard – Deployment Script (Lab + Production)
#
# Works in both Google Cloud Lab (Qwiklabs) and production environments.
#
# Deploys:
#   1. Required GCP APIs (minimal set – no billing API needed in lab)
#   2. Service account + IAM roles (non-fatal binding)
#   3. Cloud Run Service (keeps the FastAPI endpoint alive)
#   4. Cloud Scheduler (POST /check every N minutes, OIDC auth)
#   5. Pub/Sub topic for budget alerts
#   6. IAM for scheduler → Cloud Run
#   7. Smoke test (authenticated Cloud Run health check)
#
# SAFETY:
#   • Does NOT delete the GCP project.
#   • Does NOT unlink the billing account.
#   • Only disables individual service APIs when their budget is exceeded.
#
# ENVIRONMENT VARIABLES (all overridable):
#   LAB_MODE          – True/False (default: False for production)
#   PRICE_SOURCE      – static/billing (default: billing)
#   DRY_RUN_MODE      – True/False (default: False)
#   DEBUG_MODE        – True/False (default: False)
#   GCP_PROJECT_ID    – auto-detected from gcloud if not set
#   GCP_REGION        – default: us-central1
###############################################################################

set -euo pipefail

# ─── Colours ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()    { echo -e "${RED}[ERR]${NC}  $1"; exit 1; }
header()  { echo -e "\n${CYAN}═══════════════════════════════════════════════${NC}"; echo -e "${CYAN}  $1${NC}"; echo -e "${CYAN}═══════════════════════════════════════════════${NC}"; }

# ─── Parse command-line flags ─────────────────────────────────────────────
AUTO_APPROVE="${AUTO_APPROVE:-False}"
for arg in "$@"; do
    case "$arg" in
        --yes|--auto-approve|-y) AUTO_APPROVE="True" ;;
    esac
done

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

# ─── Modes (production defaults, overridable for lab) ─────────────────────
LAB_MODE="${LAB_MODE:-False}"
PRICE_SOURCE="${PRICE_SOURCE:-billing}"
DRY_RUN_MODE="${DRY_RUN_MODE:-False}"
DEBUG_MODE="${DEBUG_MODE:-False}"

if [ "$LAB_MODE" = "True" ]; then
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║           Running in LAB MODE                       ║${NC}"
    echo -e "${CYAN}║  • Static pricing (no billing API required)         ║${NC}"
    echo -e "${CYAN}║  • Non-fatal IAM binding                            ║${NC}"
    echo -e "${CYAN}║  • OIDC authentication for scheduler                ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""
fi

info "LAB_MODE:             $LAB_MODE"
info "PRICE_SOURCE:         $PRICE_SOURCE"
info "DRY_RUN_MODE:         $DRY_RUN_MODE"
info "DEBUG_MODE:           $DEBUG_MODE"

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

# Modes
# SCHEDULER_INTERVAL_MINUTES (from .env) and SCHEDULER_INTERVAL are both accepted
SCHEDULER_INTERVAL="${SCHEDULER_INTERVAL:-${SCHEDULER_INTERVAL_MINUTES:-10}}"

# Names
SERVICE_NAME="gcp-budget-guard"
SA_NAME="${SERVICE_NAME}-sa"
SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_JOB="${SERVICE_NAME}-scheduler"
PUBSUB_TOPIC="${PUBSUB_TOPIC_NAME:-budget-guard-alerts}"

info "Cloud Run service:    $SERVICE_NAME"
info "Service account:      $SA_EMAIL"
info "Scheduler interval:   every ${SCHEDULER_INTERVAL} minutes"

# Skip interactive prompt in lab mode, CI/CD, or with --yes flag
if [ "$LAB_MODE" != "True" ] && [ "$AUTO_APPROVE" != "True" ]; then
    echo ""
    read -rp "Proceed with deployment? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy] ]] || { info "Deployment cancelled."; exit 0; }
fi

# ─── 1. Enable required GCP APIs ─────────────────────────────────────────
header "1/7  Enabling required APIs"

# Core APIs that work in both lab and production environments
REQUIRED_APIS=(
    "run.googleapis.com"
    "cloudscheduler.googleapis.com"
    "monitoring.googleapis.com"
    "serviceusage.googleapis.com"
    "pubsub.googleapis.com"
)

# Only add billing + build APIs in production mode
if [ "$LAB_MODE" != "True" ]; then
    REQUIRED_APIS+=(
        "artifactregistry.googleapis.com"
        "cloudbuild.googleapis.com"
        "cloudbilling.googleapis.com"
    )
fi

for api in "${REQUIRED_APIS[@]}"; do
    STATUS=$(gcloud services list --enabled \
        --filter="config.name=$api" \
        --project "$GCP_PROJECT_ID" \
        --format="value(config.name)" 2>/dev/null || true)
    if [ "$STATUS" = "$api" ]; then
        success "$api already enabled"
    else
        info "Enabling $api …"
        if gcloud services enable "$api" --project "$GCP_PROJECT_ID" --quiet 2>/dev/null; then
            success "$api enabled"
        else
            warn "Could not enable $api (may require elevated permissions) – continuing"
        fi
    fi
done

info "Waiting 15 s for API propagation …"
sleep 15

# ─── 2. Service account & IAM ────────────────────────────────────────────
header "2/7  Service account & IAM"

SA_CREATED=false
if gcloud iam service-accounts describe "$SA_EMAIL" --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
    success "Service account exists: $SA_EMAIL"
else
    info "Creating service account …"
    if gcloud iam service-accounts create "$SA_NAME" \
        --project "$GCP_PROJECT_ID" \
        --display-name "GCP Budget Guard Service Account" 2>/dev/null; then
        success "Service account created"
        SA_CREATED=true
    else
        warn "Could not create service account – it may already exist or permissions are restricted"
        # Try to use the default compute service account instead
        SA_EMAIL="$(gcloud iam service-accounts list --project "$GCP_PROJECT_ID" \
            --filter="email:compute@developer.gserviceaccount.com" \
            --format="value(email)" 2>/dev/null || true)"
        if [ -n "$SA_EMAIL" ]; then
            warn "Using default compute service account: $SA_EMAIL"
        else
            SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
            warn "Proceeding with expected SA email: $SA_EMAIL"
        fi
    fi
fi

# Wait for SA propagation if we just created it
if [ "$SA_CREATED" = true ]; then
    info "Waiting 10s for service account propagation …"
    sleep 10
fi

# IAM roles – core set for all environments
ROLES=(
    "roles/monitoring.viewer"
    "roles/serviceusage.serviceUsageAdmin"
    "roles/run.invoker"
    "roles/pubsub.publisher"
)

# Only add billing viewer role in production mode
if [ "$LAB_MODE" != "True" ]; then
    ROLES+=("roles/cloudbilling.viewer")
fi

# Non-fatal IAM binding – logs warning and continues on failure
bind_role_with_retry() {
    local role=$1
    local max_attempts=2
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        info "Binding $role (attempt $attempt/$max_attempts) …"

        if gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
            --member "serviceAccount:$SA_EMAIL" \
            --role "$role" \
            --condition=None \
            --quiet 2>&1 | grep -q "bindings:" 2>/dev/null; then
            success "$role bound"
            return 0
        fi

        # Check if already bound
        if gcloud projects get-iam-policy "$GCP_PROJECT_ID" \
            --flatten="bindings[].members" \
            --filter="bindings.role=$role AND bindings.members:serviceAccount:$SA_EMAIL" \
            --format="value(bindings.role)" 2>/dev/null | grep -q "$role" 2>/dev/null; then
            success "$role already bound"
            return 0
        fi

        if [ $attempt -lt $max_attempts ]; then
            warn "Retry $attempt failed for $role, waiting 3s …"
            sleep 3
        fi
        attempt=$((attempt + 1))
    done

    warn "Could not bind $role (may require elevated permissions) – continuing deployment"
    return 0  # Non-fatal – never fail deployment for IAM issues
}

for role in "${ROLES[@]}"; do
    bind_role_with_retry "$role"
done

# ─── 3. Cloud Run deployment ─────────────────────────────────────────────
header "3/7  Cloud Run"

# Build env-vars string
ENV_VARS="GCP_PROJECT_ID=$GCP_PROJECT_ID"
ENV_VARS+=",CURRENCY_CODE=$CURRENCY_CODE"
ENV_VARS+=",LAB_MODE=$LAB_MODE"
ENV_VARS+=",PRICE_SOURCE=$PRICE_SOURCE"
ENV_VARS+=",VERTEX_AI_MONTHLY_BUDGET=$VERTEX_AI_MONTHLY_BUDGET"
ENV_VARS+=",BIGQUERY_MONTHLY_BUDGET=$BIGQUERY_MONTHLY_BUDGET"
ENV_VARS+=",FIRESTORE_MONTHLY_BUDGET=$FIRESTORE_MONTHLY_BUDGET"
ENV_VARS+=",MONTHLY_BUDGET_AMOUNT=$MONTHLY_BUDGET_AMOUNT"
ENV_VARS+=",WARNING_THRESHOLD_PCT=$WARNING_THRESHOLD_PCT"
ENV_VARS+=",CRITICAL_THRESHOLD_PCT=$CRITICAL_THRESHOLD_PCT"
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

# Use OIDC authentication (works in both lab and production environments)
gcloud scheduler jobs create http "$SCHEDULER_JOB" \
    --project "$GCP_PROJECT_ID" \
    --location "$GCP_REGION" \
    --schedule "*/${SCHEDULER_INTERVAL} * * * *" \
    --uri "${SERVICE_URL}/check" \
    --http-method POST \
    --oidc-service-account-email "$SA_EMAIL" \
    --oidc-token-audience "$SERVICE_URL" \
    --time-zone "Etc/UTC" \
    --max-retry-attempts 3 \
    --attempt-deadline 180s \
    --description "GCP Budget Guard – check every ${SCHEDULER_INTERVAL} min" \
    --quiet
success "Scheduler job created: $SCHEDULER_JOB"

# ─── 5. Pub/Sub topic ────────────────────────────────────────────────────
header "5/7  Pub/Sub topic"

if gcloud pubsub topics describe "$PUBSUB_TOPIC" --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
    success "Topic already exists: $PUBSUB_TOPIC"
else
    if gcloud pubsub topics create "$PUBSUB_TOPIC" --project "$GCP_PROJECT_ID" --quiet 2>/dev/null; then
        success "Topic created: $PUBSUB_TOPIC"
    else
        warn "Could not create Pub/Sub topic – continuing"
    fi
fi

# ─── 6. Grant Cloud Run invoker to scheduler SA ──────────────────────────
header "6/7  IAM for scheduler → Cloud Run"

if gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --member "serviceAccount:$SA_EMAIL" \
    --role "roles/run.invoker" \
    --quiet >/dev/null 2>&1; then
    success "Scheduler SA can invoke Cloud Run"
else
    warn "Could not bind run.invoker on Cloud Run service – scheduler may need manual auth setup"
fi

# ─── 7. Smoke test ───────────────────────────────────────────────────────
header "7/7  Smoke test"

info "Testing health endpoint with authenticated request …"
IDENTITY_TOKEN=$(gcloud auth print-identity-token 2>/dev/null || true)

if [ -n "$IDENTITY_TOKEN" ]; then
    HEALTH=$(curl -s -m 15 \
        -H "Authorization: Bearer ${IDENTITY_TOKEN}" \
        "${SERVICE_URL}/health" 2>/dev/null || echo '{"status":"request_failed"}')
    info "Health response: $HEALTH"

    if echo "$HEALTH" | grep -q '"healthy"'; then
        success "Smoke test passed – service is healthy"
    else
        warn "Smoke test returned unexpected response (service may still be starting)"
    fi
else
    warn "Could not obtain identity token – skipping smoke test"
    info "You can manually test with:"
    info "  curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" ${SERVICE_URL}/health"
fi

# ─── Summary ──────────────────────────────────────────────────────────────
header "Deployment Complete"

MODE_LABEL="PRODUCTION"
[ "$LAB_MODE" = "True" ] && MODE_LABEL="LAB"

cat <<EOF

  ✅  GCP Budget Guard deployed successfully!

  Mode:           ${MODE_LABEL}
  Service URL:    $SERVICE_URL
  Scheduler:      Every ${SCHEDULER_INTERVAL} minutes → POST ${SERVICE_URL}/check
  Pub/Sub topic:  $PUBSUB_TOPIC
  Pricing:        $PRICE_SOURCE
  Dry-run:        $DRY_RUN_MODE

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
