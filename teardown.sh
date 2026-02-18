#!/usr/bin/env bash
###############################################################################
# GCP Budget Guard – Teardown Script
#
# Removes all resources created by deploy.sh:
#   1. Cloud Scheduler job
#   2. Cloud Run service
#   3. Pub/Sub topic
#   4. Service account
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

command -v gcloud >/dev/null 2>&1 || fail "gcloud CLI not found."

GCP_PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
[ -z "$GCP_PROJECT_ID" ] && fail "GCP_PROJECT_ID not set."

GCP_REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="gcp-budget-guard"
SA_NAME="${SERVICE_NAME}-sa"
SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_JOB="${SERVICE_NAME}-scheduler"
PUBSUB_TOPIC="${PUBSUB_TOPIC_NAME:-budget-guard-alerts}"

header "GCP Budget Guard – Teardown"
info "Project:  $GCP_PROJECT_ID"
info "Region:   $GCP_REGION"

echo ""
echo -e "${RED}This will remove all Budget Guard resources from your project.${NC}"
echo -e "${RED}This will NOT delete the project or billing account.${NC}"
echo ""
read -rp "Proceed with teardown? [y/N] " confirm
[[ "$confirm" =~ ^[Yy] ]] || { info "Teardown cancelled."; exit 0; }

# ─── 1. Delete Cloud Scheduler job ───────────────────────────────────────
header "1/4  Cloud Scheduler"
if gcloud scheduler jobs describe "$SCHEDULER_JOB" \
    --project "$GCP_PROJECT_ID" --location "$GCP_REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs delete "$SCHEDULER_JOB" \
        --project "$GCP_PROJECT_ID" --location "$GCP_REGION" --quiet
    success "Scheduler job deleted: $SCHEDULER_JOB"
else
    warn "Scheduler job not found (already deleted?)"
fi

# ─── 2. Delete Cloud Run service ─────────────────────────────────────────
header "2/4  Cloud Run"
if gcloud run services describe "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" --region "$GCP_REGION" >/dev/null 2>&1; then
    gcloud run services delete "$SERVICE_NAME" \
        --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --quiet
    success "Cloud Run service deleted: $SERVICE_NAME"
else
    warn "Cloud Run service not found (already deleted?)"
fi

# ─── 3. Delete Pub/Sub topic ─────────────────────────────────────────────
header "3/4  Pub/Sub"
if gcloud pubsub topics describe "$PUBSUB_TOPIC" --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
    gcloud pubsub topics delete "$PUBSUB_TOPIC" --project "$GCP_PROJECT_ID" --quiet
    success "Pub/Sub topic deleted: $PUBSUB_TOPIC"
else
    warn "Pub/Sub topic not found (already deleted?)"
fi

# ─── 4. Delete service account ───────────────────────────────────────────
header "4/4  Service Account"
if gcloud iam service-accounts describe "$SA_EMAIL" --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts delete "$SA_EMAIL" \
        --project "$GCP_PROJECT_ID" --quiet
    success "Service account deleted: $SA_EMAIL"
else
    warn "Service account not found (already deleted?)"
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

  What was NOT touched:
    • GCP project:          $GCP_PROJECT_ID (still exists)
    • Billing account:      (still linked)
    • Your service APIs:    (unchanged)

EOF
