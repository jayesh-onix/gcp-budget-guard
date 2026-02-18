# GCP Budget Guard – Production Limitations & Edge Cases

> **Purpose**: Quick-read document listing every limitation and edge case found during code analysis, with solutions.  
> **Status**: Critical issues #1, #3, #4, #5, #7, #8 have been resolved. See ✅ markers below.

---

## 1. Budget Reset is Fixed ✅ RESOLVED

**Original problem:**
- After budget exceeded, admin calls `/reset` → API re-enabled → next check sees same cumulative cost → disables again → infinite loop.

**Solution implemented:**
- `StateManager` persists a **cost baseline** per service.
- When admin calls `POST /reset/{service}`, the system:
  1. Saves the current cumulative cost as a baseline
  2. Resets alert counters (so new alerts can fire)
  3. Re-enables the API
  4. Records the action in audit history
- On each check cycle: `effective_cost = cumulative_cost - baseline`
- Baselines automatically clear on month rollover.
- Files: `state_manager.py`, `budget_monitor.py` (reset_service method), `routes.py`

---

## 2. Disabling APIs Breaks Other Things 🔴

What happens to your org when each API is disabled:

| API Disabled | What Breaks |
|---|---|
| `aiplatform.googleapis.com` (Vertex AI) | All Gemini API calls fail. Training jobs abort. Notebooks become inaccessible. Any Cloud Function / Cloud Run service calling Vertex AI stops working. |
| `bigquery.googleapis.com` (BigQuery) | All SQL queries fail. Scheduled queries stop. Looker/Data Studio dashboards go blank. ETL pipelines (Airflow, Dataform, dbt) break. |
| `firestore.googleapis.com` (Firestore) | All reads/writes fail. Mobile and web apps that use Firestore crash. Real-time listeners disconnect. Cloud Functions triggered by Firestore stop firing. |

**Key point:** The system has **no awareness** of what depends on these APIs. It blindly disables them.

**Also critical:** If we monitor Firestore usage through Cloud Monitoring, and Firestore is the only service that exceeded budget — our system itself doesn't break (we use Cloud Monitoring, not Firestore). But if your **other production apps** use Firestore, they all go down.

**Solution:** Add a per-service "enforcement mode" config:
- `ENFORCE` = disable the API (current behaviour)
- `ALERT_ONLY` = send alert but never disable (safe for critical services)
- `APPROVAL_REQUIRED` = send alert, wait for manual approval before disabling

---

## 3. Persistent State Added ✅ RESOLVED

**Original problem:**
- Alert counters, budget baselines, and action history were all in-memory.
- Cloud Run restarts would lose everything → duplicate alerts, lost baselines.

**Solution implemented:**
- `StateManager` class stores state in a JSON file (`/tmp/budget_guard_state.json` by default).
- Persists: cost baselines, last known costs, alert tracking, action history.
- Thread-safe via `threading.Lock`.
- On Cloud Run: survives within container lifetime. On restart, starts fresh (safe default — conservative behavior).
- `NotificationService` now accepts optional `state_manager` for persistent alert tracking.
- Configurable via `BUDGET_STATE_PATH` env var.
- Files: `state_manager.py`, `notification.py`, `constants.py`

---

## 4. Pricing API Failure Visibility ✅ RESOLVED

**Original problem:**
- If pricing API failed → `price_per_unit = None` → expense reported as $0.
- No indication that the check was incomplete.

**Solution implemented:**
- `_compute_metric_expense()` now returns a **data quality warning** string when pricing fails.
- Warnings are collected in a `data_warnings` list and included in the check response.
- Core safety behavior preserved: expense still defaults to $0.00 (conservative — won't disable on unknown data).
- But failures are now **visible** in API responses and logs, not hidden.
- The existing `FallbackPriceProvider` (CloudBilling → Static) already provides a price fallback chain.
- Files: `budget_monitor.py` (`_compute_metric_expense` return type changed to `str | None`)

---

## 5. Cloud Monitoring API Failure Visibility ✅ RESOLVED

**Original problem:**
- If Cloud Monitoring API failed → `unit_count = 0` → expense reported as $0.
- Same silent failure as Issue #4.

**Solution implemented:**
- Same approach as Issue #4: `_compute_metric_expense()` returns a data quality warning when monitoring query fails.
- Warning included in `data_warnings` list in the check response.
- Files: `budget_monitor.py`

---

## 6. Race Condition: Two Checks Run at Same Time 🟡

**When this happens:**
- Scheduler runs check at 10:00 but it takes 12 minutes
- Scheduler runs another check at 10:10 while first is still running
- Both checks see the same data → both try to disable the same API → duplicate alerts

**Also:** Manual `POST /check` can overlap with scheduled check.

**Solution:** Set Cloud Run `max-instances=1` OR on every check, if the service is already disabled, skip it.

---

## 7. `/reset` Now Does a Full Reset ✅ RESOLVED

**Original problem:**
- `/reset` only re-enabled the API, didn't reset alerts or save a baseline.

**Solution implemented:**
- `BudgetMonitor.reset_service(service_key)` now performs a **complete reset**:
  1. Queries current cumulative cost and saves it as a baseline ✅
  2. Resets alert counters for the service ✅
  3. Re-enables the API ✅
  4. Records the action in audit history ✅
- `/reset/{service_key}` route calls `reset_service()` and returns structured response.
- Files: `budget_monitor.py` (reset_service method), `routes.py`

---

## 8. deploy.sh CI/CD Compatible ✅ RESOLVED

**Original problem:**
- Interactive `read -rp` prompt blocked CI/CD pipelines.

**Solution implemented:**
- Added `--yes` / `--auto-approve` / `-y` command-line flags to both `deploy.sh` and `teardown.sh`.
- When flag is set (or `LAB_MODE=True`), interactive prompts are skipped.
- Cloud Scheduler also improved: `--max-retry-attempts 3` and `--attempt-deadline 180s` to handle Cloud Run cold starts.
- Files: `deploy.sh`, `teardown.sh`

---

## 9. No Authentication on API Endpoints 🟡

**Current state:** Cloud Run is deployed with `--no-allow-unauthenticated`, so Cloud Scheduler needs a token. But there's **no auth check in the FastAPI code itself**.

**Risk:** If someone misconfigures Cloud Run to allow unauthenticated access, **anyone** can:
- Call `POST /check` repeatedly (spam)
- Call `POST /reset/vertex_ai` to re-enable disabled services
- Call `POST /enable_service/...` to bypass budget controls

**Solution:** Add IAM token validation middleware in FastAPI, or at minimum, a shared secret header check.

---

## 10. Hardcoded to One GCP Project 🟡

`PROJECT_ID` is a single value. Enterprise orgs have many projects. You'd need to deploy one instance per project.

**Solution (future):** Support a list of project IDs. Lower priority for now — one project is fine for initial deployment.

---

## 11. Timezone Mismatch 🟡

**System uses:** UTC for month boundaries  
**GCP billing uses:** Pacific Time (PT)

Around midnight PT (8:00 AM UTC), the system might start a "new month" in UTC while billing hasn't rolled over yet in PT, causing a brief window of $0 reported cost.

**Impact:** Small — only affects ~8 hours at month boundary.

**Solution:** Make timezone configurable, or use PT to match GCP billing.

---

## 12. Budget Guard Itself Depends on GCP APIs 🟡

If these APIs are down, Budget Guard itself breaks:

| API | What Happens If Down |
|---|---|
| `monitoring.googleapis.com` | Can't read usage → reports $0 (false safe) |
| `cloudbilling.googleapis.com` | Can't get prices → reports $0 (false safe) |
| `serviceusage.googleapis.com` | Can't disable/enable APIs → enforcement fails silently |

**Solution:** Add a `/health` endpoint that validates all dependencies, not just "is the server running." Report degraded health if any dependency is unreachable.

---

## Summary Table

| # | Issue | Status | Notes |
|---|-------|--------|-------|
| 1 | Budget reset disable loop | ✅ Resolved | Baseline tracking via StateManager |
| 2 | API disable cascade — no impact awareness | 🔴 Open | Needs enforcement mode config |
| 3 | No persistent state | ✅ Resolved | StateManager with JSON file persistence |
| 4 | Pricing failure = silent $0 | ✅ Resolved | Data quality warnings in responses |
| 5 | Monitoring failure = silent $0 | ✅ Resolved | Data quality warnings in responses |
| 6 | Race condition on concurrent checks | 🟡 Open | Use max-instances=1 |
| 7 | `/reset` doesn't fully reset | ✅ Resolved | Full reset: baseline + alerts + enable + audit |
| 8 | deploy.sh interactive prompt | ✅ Resolved | --yes flag + scheduler retry improvements |
| 9 | No app-level authentication | 🟡 Open | Needs auth middleware |
| 10 | Single project only | 🟡 Open | Multi-project refactor |
| 11 | Timezone mismatch (UTC vs PT) | 🟡 Open | Configurable timezone |
| 12 | Own dependency failures undetected | 🟡 Open | Dependency health check |

---

## What to Fix Next (Remaining Priority Order)

> Issues #1, #3, #4, #5, #7, #8 have been resolved. Remaining priorities:

1. **Issue #2**: Add enforcement modes (ENFORCE / ALERT_ONLY / APPROVAL_REQUIRED) — prevent taking down critical production services
2. **Issue #9**: Add app-level authentication middleware
3. **Issue #12**: Add dependency health checks to `/health`
4. **Issue #6**: Handled via `max-instances=1` in deploy.sh, but could add explicit lock
5. **Issue #11**: Make timezone configurable
6. **Issue #10**: Multi-project support for v2
