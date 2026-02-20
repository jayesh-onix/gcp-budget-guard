# Pricing & Monitoring Architecture

> How GCP Budget Guard tracks Vertex AI usage across **all models** and resolves per-token pricing.

---

## 1. Catch-All Vertex AI Monitoring

### Problem

The previous architecture defined one `MonitoredMetric` per model per direction (input/output). Only 6 Gemini models were tracked — any usage from Claude, Llama, Mistral, or future models was invisible, silently bypassing budget enforcement.

### Solution

A **single catch-all metric** replaces all per-model entries:

```
metric:  aiplatform.googleapis.com/publisher/online_serving/token_count
filter:  resource.type = "aiplatform.googleapis.com/PublisherModel"
group_by:
  - resource.label.model_user_id
  - metric.label.type
```

Cloud Monitoring returns one time series per unique `(model_user_id, type)` pair. Budget Guard iterates each group and applies model-specific pricing.

**Effect:** Any model used through Vertex AI — including ones released after this code was deployed — is automatically captured.

### Data Flow

```
Cloud Monitoring                    Budget Guard
┌──────────────────┐    grouped    ┌────────────────────────┐
│ token_count       │──────────────│ _compute_catch_all_    │
│  group by model + │   results    │ expense()              │
│  type             │              │   ├─ model: gemini-2.5 │
└──────────────────┘              │   │   price: catalog    │
                                  │   ├─ model: claude-3    │
                                  │   │   price: catalog    │
                                  │   └─ model: unknown-v9  │
                                  │       price: default    │
                                  └────────────────────────┘
```

---

## 2. Pricing Resolution Order

For **each model + token type** group returned by the catch-all query, pricing is resolved in strict priority order:

| Priority | Source | When Used |
|----------|--------|-----------|
| 1 | **Static catalog — exact model match** | Model name found in `pricing_catalog.json` `vertex_ai` section |
| 2 | **Static catalog — normalised match** | After stripping `@version` suffix and `publishers/.../models/` prefix |
| 3 | **Default Vertex AI token price** | From `vertex_ai_defaults` section (conservative estimate) |
| 4 | **Global fallback price** | `default_fallback_price` (last resort, never $0) |

### Model ID Normalisation

Cloud Monitoring model_user_id values can vary:

| Raw Value | Normalised |
|-----------|------------|
| `gemini-2.5-pro` | `gemini-2.5-pro` |
| `claude-3-opus@20240229` | `claude-3-opus` |
| `publishers/anthropic/models/claude-3-opus@20240229` | `claude-3-opus` |

The normaliser strips the `publishers/.../models/` prefix and `@...` version suffix before catalog lookup.

### Environment-Based Provider Selection

| Config | Provider Used | Typical Use |
|--------|--------------|-------------|
| `LAB_MODE=True` | `StaticPriceProvider` | Google Cloud Labs |
| `PRICE_SOURCE=static` | `StaticPriceProvider` | Offline testing |
| `PRICE_SOURCE=billing` (default) | `FallbackPriceProvider(CloudBilling → Static)` | Production |

Application logic is identical in all environments — only the price source differs.

---

## 3. Static Pricing Catalog

Located at `src/config/pricing_catalog.json`.

### Structure

```json
{
  "vertex_ai": {
    "<model_name>": {
      "input":  { "price_per_unit": <$/1M tokens>, "unit_size": 1000000 },
      "output": { "price_per_unit": <$/1M tokens>, "unit_size": 1000000 }
    }
  },
  "vertex_ai_defaults": {
    "default_input_token_price": 0.25,
    "default_output_token_price": 1.0,
    "default_token_unit_size": 1000000
  },
  "bigquery": { ... },
  "firestore": { ... },
  "default_fallback_price": 0.0001
}
```

### Models Covered

| Family | Models |
|--------|--------|
| **Gemini** | 3.0-pro, 2.5-pro, 2.5-flash, 2.5-flash-lite, 2.0-flash, 2.0-flash-lite, 1.5-pro, 1.5-flash |
| **Claude** | sonnet-4, 3.5-sonnet-v2, 3.5-haiku, 3-opus, 3-sonnet, 3-haiku |
| **Llama** | 3.1-405b, 3.1-70b, 3.1-8b |
| **Mistral** | large, nemo, codestral |

Unknown models automatically receive the default price ($0.25/$1.00 per 1M tokens).

### Adding a New Model

Edit `pricing_catalog.json` > `vertex_ai` section:

```json
"new-model-name": {
  "input":  { "price_per_unit": X.XX, "unit_size": 1000000, "unit_description": "per 1M input tokens" },
  "output": { "price_per_unit": X.XX, "unit_size": 1000000, "unit_description": "per 1M output tokens" }
}
```

**No code changes required.** The catch-all metric automatically captures usage and the catalog lookup resolves the new model's price.

---

## 4. Monthly Budget Reset

### Automatic Rollover

On the first scheduler execution of a new calendar month:

1. `StateManager.check_month_rollover()` detects the month boundary
2. Baselines, alert counters, and cached costs are cleared
3. `BudgetMonitorService.run_check()` re-enables all previously disabled service APIs
4. The action is recorded in the audit history

### Re-Enable Logic

```python
# In run_check():
rollover = self.state.check_month_rollover()
if rollover or self._pending_rollover:
    self._re_enable_all_services()  # enables vertex_ai, bigquery, firestore
```

This only resets **internal enforcement tracking**. It does not modify real GCP billing or usage data.

---

## 5. BigQuery & Firestore (Unchanged)

These services use traditional per-metric monitoring with SKU-based pricing:

- **BigQuery**: `bigquery.googleapis.com/query/statement_scanned_bytes_billed`
- **Firestore**: read, write, delete, TTL delete operation counts

No catch-all grouping is needed because these services don't have model-level granularity.

---

## 6. Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Static catalog prices may become stale | Slight over/under-estimation in lab mode | Production uses Cloud Billing API with static as fallback |
| Unknown models get conservative default price | May overestimate cost for cheap models | Update catalog when new models are adopted |
| Catch-all captures ALL publisher model usage | Includes any internal/preview models | Acceptable — budget enforcement should be inclusive |
| Cloud Monitoring has ~3 min data latency | Scheduler runs every 10 min, so this is negligible | |
| State is ephemeral on Cloud Run (tmpfs) | Resets on container restart | Baselines rebuild naturally; conservative behaviour by design |

---

## 7. Design Decisions

1. **Catch-all over individual metrics** — One query vs N queries reduces Cloud Monitoring costs and maintenance. New models never cause blind spots.

2. **Model-name-based pricing over SKU-based for Vertex AI** — SKU IDs are opaque and hard to maintain. Model names match what developers actually use.

3. **Conservative default price ($0.25/1M)** — Ensures unknown models always contribute to cost, preventing budget bypass. Slightly overestimates rather than underestimates.

4. **Monthly re-enable in run_check, not __init__** — Guarantees re-enable happens during a scheduler tick (not silently during container cold-start before any check runs).
