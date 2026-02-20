"""Registry of all metrics monitored per service.

Each service key maps to a list of MonitoredMetric objects that will be
individually priced via the Cloud Billing Catalog API and measured via
Cloud Monitoring.

Vertex AI uses a **catch-all** metric: one aggregated query groups usage
by ``model_user_id`` and ``type`` (input / output) so that ANY model –
including future ones – is automatically captured and priced.
"""

from config.monitored_services import MonitoredMetric

# ─── Vertex AI  (service_id = C7E2-9256-1C43) ────────────────────────────────
#
# Catch-all metric: captures token usage for EVERY model (Gemini, Claude,
# Llama, Mistral, Gemma, …).  Results are grouped by model_user_id + type
# and priced per-model in budget_monitor.py using the pricing catalog.

VERTEX_AI_METRICS: list[MonitoredMetric] = [
    MonitoredMetric(
        label="Vertex AI – All Models Token Usage (catch-all)",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter='resource.type = "aiplatform.googleapis.com/PublisherModel"',
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="",  # resolved per-model at runtime
        is_catch_all=True,
        group_by_fields=[
            "resource.label.model_user_id",
            "metric.label.type",
        ],
    ),
]

# ─── BigQuery  (service_id = 24E6-581D-38E5) ─────────────────────────────────

BIGQUERY_METRICS: list[MonitoredMetric] = [
    MonitoredMetric(
        label="BigQuery – Scanned Bytes Billed",
        metric_name="bigquery.googleapis.com/query/statement_scanned_bytes_billed",
        billing_service_id="24E6-581D-38E5",
        billing_sku_id="3362-E469-6BEF",
        billing_price_tier=1,  # tier-1 for on-demand analysis pricing
    ),
]

# ─── Firestore  (service_id = EE2C-7FAC-5E08) ────────────────────────────────

FIRESTORE_METRICS: list[MonitoredMetric] = [
    MonitoredMetric(
        label="Firestore – Read Operations",
        metric_name="firestore.googleapis.com/document/read_count",
        billing_service_id="EE2C-7FAC-5E08",
        billing_sku_id="6A94-8525-876F",
    ),
    MonitoredMetric(
        label="Firestore – Write Operations",
        metric_name="firestore.googleapis.com/document/write_count",
        billing_service_id="EE2C-7FAC-5E08",
        billing_sku_id="BFCC-1D11-14E1",
    ),
    MonitoredMetric(
        label="Firestore – Delete Operations",
        metric_name="firestore.googleapis.com/document/delete_count",
        billing_service_id="EE2C-7FAC-5E08",
        billing_sku_id="B813-E6E7-37F4",
    ),
    MonitoredMetric(
        label="Firestore – TTL Delete Operations",
        metric_name="firestore.googleapis.com/document/ttl_deletion_count",
        billing_service_id="EE2C-7FAC-5E08",
        billing_sku_id="6088-280E-4225",
    ),
]

# ─── Master registry keyed by service key ─────────────────────────────────────

SERVICE_METRICS: dict[str, list[MonitoredMetric]] = {
    "vertex_ai": VERTEX_AI_METRICS,
    "bigquery": BIGQUERY_METRICS,
    "firestore": FIRESTORE_METRICS,
}
