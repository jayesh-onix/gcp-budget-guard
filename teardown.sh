#!/usr/bin/env bash
###############################################################################
# GCP Budget Guard – Teardown Script
#
# Removes all resources created by deploy.sh:
#   1. Cloud Scheduler job
#   2. Cloud Run service
#   3. Pub/Sub topic
#   4. Service account
#   5. GCS state bucket
#
# SAFETY:
#   • Does NOT delete the GCP project.
#   • Does NOT unlink the billing account.
#   • Only removes Budget Guard resources.
###############################################################################

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()    { echo -e "${RED}[ERR]${NC}  $1"; exit 1; }
header()  { echo -e "\n${BLUE}═══════════════════════════════════════════════${NC}"; echo -e "${BLUE}  $1${NC}"; echo -e "${BLUE}═══════════════════════════════════════════════${NC}"; }

# Parse command-line flags
AUTO_APPROVE="${AUTO_APPROVE:-False}"
for arg in "$@"; do
    case "$arg" in
        --yes|--auto-approve|-y) AUTO_APPROVE="True" ;;
    esac
done

command -v gcloud >/dev/null 2>&1 || fail "gcloud CLI not found."

GCP_PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
[ -z "$GCP_PROJECT_ID" ] && fail "GCP_PROJECT_ID not set."

GCP_REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="gcp-budget-guard"
SA_NAME="${SERVICE_NAME}-sa"
SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_JOB="${SERVICE_NAME}-scheduler"
PUBSUB_TOPIC="${PUBSUB_TOPIC_NAME:-budget-guard-alerts}"
BUDGET_STATE_BUCKET="${BUDGET_STATE_BUCKET:-${GCP_PROJECT_ID}-budget-guard-state}"

header "GCP Budget Guard – Teardown"
info "Project:  $GCP_PROJECT_ID"
info "Region:   $GCP_REGION"

if [ "$AUTO_APPROVE" != "True" ]; then
    echo ""
    echo -e "${RED}This will remove all Budget Guard resources from your project.${NC}"
    echo -e "${RED}This will NOT delete the project or billing account.${NC}"
    echo ""
    read -rp "Proceed with teardown? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy] ]] || { info "Teardown cancelled."; exit 0; }
fi

# ─── 1. Delete Cloud Scheduler job ───────────────────────────────────────
header "1/5  Cloud Scheduler"
if gcloud scheduler jobs describe "$SCHEDULER_JOB" \
    --project "$GCP_PROJECT_ID" --location "$GCP_REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs delete "$SCHEDULER_JOB" \
        --project "$GCP_PROJECT_ID" --location "$GCP_REGION" --quiet
    success "Scheduler job deleted: $SCHEDULER_JOB"
else
    warn "Scheduler job not found (already deleted?)"
fi

# ─── 2. Delete Cloud Run service ─────────────────────────────────────────
header "2/5  Cloud Run"
if gcloud run services describe "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" --region "$GCP_REGION" >/dev/null 2>&1; then
    gcloud run services delete "$SERVICE_NAME" \
        --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --quiet
    success "Cloud Run service deleted: $SERVICE_NAME"
else
    warn "Cloud Run service not found (already deleted?)"
fi

# ─── 3. Delete Pub/Sub topic ─────────────────────────────────────────────
header "3/5  Pub/Sub"
if gcloud pubsub topics describe "$PUBSUB_TOPIC" --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
    gcloud pubsub topics delete "$PUBSUB_TOPIC" --project "$GCP_PROJECT_ID" --quiet
    success "Pub/Sub topic deleted: $PUBSUB_TOPIC"
else
    warn "Pub/Sub topic not found (already deleted?)"
fi

# ─── 4. Delete service account ───────────────────────────────────────────
header "4/5  Service Account"
if gcloud iam service-accounts describe "$SA_EMAIL" --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts delete "$SA_EMAIL" \
        --project "$GCP_PROJECT_ID" --quiet
    success "Service account deleted: $SA_EMAIL"
else
    warn "Service account not found (already deleted?)"
fi

# ─── 5. Delete GCS state bucket ──────────────────────────────────────────
header "5/5  GCS State Bucket"
if gcloud storage buckets describe "gs://${BUDGET_STATE_BUCKET}" --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
    gcloud storage rm --recursive "gs://${BUDGET_STATE_BUCKET}" --quiet 2>/dev/null || true
    if gcloud storage buckets delete "gs://${BUDGET_STATE_BUCKET}" --project "$GCP_PROJECT_ID" --quiet 2>/dev/null; then
        success "State bucket deleted: gs://${BUDGET_STATE_BUCKET}"
    else
        warn "Could not delete state bucket gs://${BUDGET_STATE_BUCKET}"
    fi
else
    warn "State bucket not found (already deleted?)"
fi

# ─── Summary ──────────────────────────────────────────────────────────────
header "Teardown Complete"
cat <<EOF

  ✅  All Budget Guard resources have been removed.

  What was deleted:
    • Cloud Scheduler job:  $SCHEDULER_JOB
    • Cloud Run service:    $SERVICE_NAME
    • Pub/Sub topic:        $PUBSUB_TOPIC
    • Service account:      $SA_EMAIL
    • GCS state bucket:     gs://$BUDGET_STATE_BUCKET

  What was NOT touched:
    • GCP project:          $GCP_PROJECT_ID (still exists)
    • Billing account:      (still linked)
    • Your service APIs:    (unchanged)

EOF
