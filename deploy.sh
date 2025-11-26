#!/bin/sh

echo_green() {
  local message="$1"
  echo "\e[1;92m${message}\e[0m"
}

echo_blue() {
  local message="$1"
  echo "\e[1;94m${message}\e[0m"
}

echo_red() {
  local message="$1"
  echo "\e[1;91m${message}\e[0m"
}

test_gcloud_installation() {
    if ! command -v gcloud >/dev/null 2>&1; then
        echo_red "❌ gcloud isn't installed, please install it before continuing."
        exit 1
    else
        echo_green "✅ gcloud is installed."
    fi
}

ask_budget() {
    interval="$1"
    while true; do
        printf "(integer) Budget for %s day(s): " "$interval" > /dev/tty
        IFS= read -r budget_int < /dev/tty

        case "$budget_int" in
            '' ) echo "Please enter an integer value." 1>&2 ;;
            -* )
                rest="${budget_int#-}"
                case "$rest" in
                    ''|*[!0-9]*) echo "Please enter an integer value." 1>&2 ;;
                    *) echo "$budget_int"; return ;;
                esac
                ;;
            *[!0-9]* ) echo "Please enter an integer value." 1>&2 ;;
            *) echo "$budget_int"; return ;;
        esac
    done
}

ask_yes_no() {
    question="$1"
    while true; do
        printf "%s [Y/N]: " "$question" > /dev/tty
        IFS= read -r answer < /dev/tty
        case "$answer" in
            [Yy]* ) echo "true"; return ;;
            [Nn]* ) echo "false"; return ;;
            * ) echo "Please answer Y or N." 1>&2 ;;
        esac
    done
}

# --- Main config function ---
config_script() {
    echo_blue "Please, enter the following parameters:"

    printf "GCP Project ID (name): " > /dev/tty
    IFS= read -r GCP_PROJECT_ID < /dev/tty

    budget_1=$(ask_budget 1)
    budget_7=$(ask_budget 7)
    budget_30=$(ask_budget 30)
    debug_mode=$(ask_yes_no "Do you want to run in debug mode?")
    nuke_mode=$(ask_yes_no "Do you want to run in nuke mode? If so, reaching Budget will disable GCP APIs")

    # Fancy Colored Nuke Mode
    if [ "$nuke_mode" = true ]; then
        print_nuke_mode="\e[1;91m$nuke_mode\e[0m" # Scary Red
    else
        print_nuke_mode="\e[1;92m$nuke_mode\e[0m" # Chill Green
    fi

    echo ""
    echo "Here are your project parameters:"
    echo "--------------------------------"
    echo "GCP Project ID: $GCP_PROJECT_ID"
    echo "Budget 1 day  : $budget_1"
    echo "Budget 7 days : $budget_7"
    echo "Budget 30 days: $budget_30"
    echo "Debug mode    : $debug_mode"
    echo "Nuke mode     : $print_nuke_mode"
    echo "--------------------------------"
    echo ""

    confirm=$(ask_yes_no "Do you confirm these parameters?")

    if [ "$confirm" = "true" ]; then
        deploy
    else
        echo "Let's reconfigure the parameters."
        config_script
    fi
}

# --- Deploy ---
deploy() {
    echo_green "🚀 Deploying NoBBomb to $GCP_PROJECT_ID"
    echo "💵 Your budget is set to 1 DAY: $budget_1$ / 7 DAYS:$budget_7$ / 30 DAYS:$budget_30$"

    if [ "$debug_mode" = "true" ]; then
        echo "🤓 Debug mode is ON"
    else
        echo "🍃 Debug mode is OFF"
    fi

    if [ "$nuke_mode" = "true" ]; then
        echo "💣 Nuke mode is ON"
    else
        echo "🌲 Nuke mode is OFF"
    fi
    echo ""

    # Constants
    SCHEDULER_JOB_NAME=nobbomb-kill-switch-scheduler
    SERVICE_ACCOUNT_NAME=nobbomb-kill-switch-sa
    SERVICE_ACCOUNT_MAIL=$SERVICE_ACCOUNT_NAME@$GCP_PROJECT_ID.iam.gserviceaccount.com
    CLOUD_RUN_NAME=nobbomb-kill-switch
    GCP_REGION=us-central1

    # Activate Needed Services
    echo_green "Activating NoBBomb Requiered Services.."
    SERVICES="artifactregistry.googleapis.com cloudbuild.googleapis.com run.googleapis.com cloudscheduler.googleapis.com"

    for SERVICE in $SERVICES; do
        echo "Checking $SERVICE..."

        # Vérifie si le service est déjà activé
        STATUS=$(gcloud services list --enabled \
            --filter="config.name=$SERVICE" \
            --project "$GCP_PROJECT_ID" \
            --format="value(config.name)")

        if [ "$STATUS" != "$SERVICE" ]; then
            echo "$SERVICE is not enabled. Enabling now..."
            FIRST_LAUNCH=1
            gcloud services enable "$SERVICE" --project "$GCP_PROJECT_ID"

            # Attendre qu’il soit bien activé
            while true; do
                STATUS=$(gcloud services list --enabled \
                    --filter="config.name=$SERVICE" \
                    --project "$GCP_PROJECT_ID" \
                    --format="value(config.name)")
                if [ "$STATUS" = "$SERVICE" ]; then
                    echo "$SERVICE is enabled ✅"
                    break
                else
                    echo "Waiting for $SERVICE to be enabled..."
                    sleep 5
                fi
            done
        else
            echo "$SERVICE is already enabled ✅"
        fi
    done

    if [ "$FIRST_LAUNCH" = "1" ]; then
        echo "First launch of GCP services detected. Waiting 2 minutes to ensure everything is fully deployed..."
        sleep 120
    fi
    
    # Service Account (force recreation)
    echo_green "Working on the Service Account.."
    if gcloud iam service-accounts list \
        --project "$GCP_PROJECT_ID" \
        --filter "email=$SERVICE_ACCOUNT_MAIL" \
        --format "value(email)" | grep -q "$SERVICE_ACCOUNT_MAIL"; then
        echo_blue "Service Account already exists: $SERVICE_ACCOUNT_MAIL, using it."
    else
        echo_blue "Service Account does not exist. Creating it..."
        gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
            --project "$GCP_PROJECT_ID" \
            --display-name "NoBBomb Kill Switch Service Account"
    fi

    # Cloud Run As Job
    echo_green "Working on the Cloud run Job.."
    gcloud run jobs deploy $CLOUD_RUN_NAME \
    --project "$GCP_PROJECT_ID" \
    --source . \
    --region $GCP_REGION \
    --set-env-vars GCP_PROJECT_ID="$GCP_PROJECT_ID" \
    --set-env-vars DAILY_EXPENSE_LIMIT="$budget_1" \
    --set-env-vars WEEKLY_EXPENSE_LIMIT="$budget_7" \
    --set-env-vars MONTHLY_EXPENSE_LIMIT="$budget_30" \
    --set-env-vars DEBUG_MODE="$debug_mode" \
    --set-env-vars NUKE_MODE="$nuke_mode" \
    --service-account $SERVICE_ACCOUNT_MAIL

    # IAM Permissions
    echo_green "Working on the IAM Permissions.."
    gcloud run jobs add-iam-policy-binding "$CLOUD_RUN_NAME" \
    --project "$GCP_PROJECT_ID" \
    --member "serviceAccount:$SERVICE_ACCOUNT_NAME@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
    --role "roles/run.invoker" \
    --region "$GCP_REGION"

    # Add monitoring viewer role
    gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member "serviceAccount:$SERVICE_ACCOUNT_NAME@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
    --role "roles/monitoring.viewer" \
    --condition None

    # Add monitoring viewer role
    gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member "serviceAccount:$SERVICE_ACCOUNT_NAME@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
    --role "roles/serviceusage.serviceUsageAdmin" \
    --condition None

    # Scheduler every 30 minutes
    if gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" \
        --project "$GCP_PROJECT_ID" \
        --location "$GCP_REGION" >/dev/null 2>&1; then
        
        echo_blue "Cloud Scheduler already exists: $SCHEDULER_JOB_NAME. Deleting it..."

        gcloud scheduler jobs delete "$SCHEDULER_JOB_NAME" \
        --project "$GCP_PROJECT_ID" \
        --location "$GCP_REGION" \
        --quiet
    else
        echo_blue "Cloud Scheduler does not exist. Creating it..."
    fi

    # Create the Scheduler job
    gcloud scheduler jobs create http "$SCHEDULER_JOB_NAME" \
    --project "$GCP_PROJECT_ID" \
    --location "$GCP_REGION" \
    --schedule "*/30 * * * *" \
    --uri "https://$GCP_REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$GCP_PROJECT_ID/jobs/nobbomb-kill-switch:run" \
    --http-method POST \
    --oauth-service-account-email "$SERVICE_ACCOUNT_NAME@$GCP_PROJECT_ID.iam.gserviceaccount.com" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
    --max-retry-attempts 0

    echo_green "Done."
    }

# --- Base Script (ask parameters) ---
test_gcloud_installation
config_script
