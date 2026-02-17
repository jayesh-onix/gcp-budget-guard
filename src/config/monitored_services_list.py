"""Registry of all metrics monitored per service.

Each service key maps to a list of MonitoredMetric objects that will be
individually priced via the Cloud Billing Catalog API and measured via
Cloud Monitoring.  SKU IDs are from the US-CENTRAL1 region catalogue.
"""

from config.monitored_services import MonitoredMetric

# ─── Vertex AI  (service_id = C7E2-9256-1C43) ────────────────────────────────

VERTEX_AI_METRICS: list[MonitoredMetric] = [
    # Gemini 3.0 Pro
    MonitoredMetric(
        label="Gemini 3.0 Pro – input",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-3.0-pro" '
            'AND metric.label.type = "input"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="EAC4-305F-1249",
    ),
    MonitoredMetric(
        label="Gemini 3.0 Pro – output",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-3.0-pro" '
            'AND metric.label.type = "output"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="2737-2D33-D986",
    ),
    # Gemini 2.5 Pro
    MonitoredMetric(
        label="Gemini 2.5 Pro – input",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-2.5-pro" '
            'AND metric.label.type = "input"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="A121-E2B5-1418",
    ),
    MonitoredMetric(
        label="Gemini 2.5 Pro – output",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-2.5-pro" '
            'AND metric.label.type = "output"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="5DA2-3F77-1CA5",
    ),
    # Gemini 2.5 Flash
    MonitoredMetric(
        label="Gemini 2.5 Flash – input",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-2.5-flash" '
            'AND metric.label.type = "input"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="FDAB-647C-5A22",
    ),
    MonitoredMetric(
        label="Gemini 2.5 Flash – output",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-2.5-flash" '
            'AND metric.label.type = "output"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="AF56-1BF9-492A",
    ),
    # Gemini 2.5 Flash Lite
    MonitoredMetric(
        label="Gemini 2.5 Flash Lite – input",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-2.5-flash-lite" '
            'AND metric.label.type = "input"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="F91E-007E-3BA1",
    ),
    MonitoredMetric(
        label="Gemini 2.5 Flash Lite – output",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-2.5-flash-lite" '
            'AND metric.label.type = "output"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="2D6E-6AC5-B1FD",
    ),
    # Gemini 2.0 Flash
    MonitoredMetric(
        label="Gemini 2.0 Flash – input",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-2.0-flash" '
            'AND metric.label.type = "input"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="1127-99B9-1860",
    ),
    MonitoredMetric(
        label="Gemini 2.0 Flash – output",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-2.0-flash" '
            'AND metric.label.type = "output"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="DFB0-8442-43A8",
    ),
    # Gemini 2.0 Flash Lite
    MonitoredMetric(
        label="Gemini 2.0 Flash Lite – input",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-2.0-flash-lite" '
            'AND metric.label.type = "input"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="CF72-F84C-8E3B",
    ),
    MonitoredMetric(
        label="Gemini 2.0 Flash Lite – output",
        metric_name="aiplatform.googleapis.com/publisher/online_serving/token_count",
        metric_filter=(
            'resource.type = "aiplatform.googleapis.com/PublisherModel" '
            'AND resource.label.model_user_id = "gemini-2.0-flash-lite" '
            'AND metric.label.type = "output"'
        ),
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="4D69-506A-5D33",
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
