"""Registry of all metrics monitored per service.

Each service key maps to a list of MonitoredMetric objects that will be
individually priced via the Cloud Billing Catalog API and measured via
Cloud Monitoring.

Vertex AI uses a **catch-all** metric for publisher-model token serving: one
aggregated query groups usage by ``model_user_id`` and ``type`` (input /
output) so that ANY model – including future ones – is automatically captured
and priced.

In addition, seven dedicated Vertex AI sub-service metrics track:
- Online prediction endpoint compute (Dedicated Prediction Endpoints)
- Batch prediction job compute
- Custom training node hours
- Vertex AI Pipelines component execution
- Feature Store online-serving read ops
- Matching Engine (Vector Search) query ops
- Model Monitoring prediction volume
"""

from config.monitored_services import MonitoredMetric

# ─── Vertex AI  (service_id = C7E2-9256-1C43) ────────────────────────────────

VERTEX_AI_METRICS: list[MonitoredMetric] = [
    # ── 1. Publisher model serving (Gemini, Claude, Llama, Mistral, …) ──────
    # Catch-all: groups by model_user_id + token_type and prices per-model.
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
    # ── 2. Online prediction endpoints (Dedicated Endpoint Compute) ──────────
    # Measures prediction requests served by dedicated endpoints.
    # Billed per node-hour of the deployed model server.
    # Metric: prediction/online/prediction_count (requests per second → month)
    # We track accelerator memory as a proxy for instance-hours; price is per
    # node-hour for n1-standard-4 equivalent.
    MonitoredMetric(
        label="Vertex AI – Online Prediction Endpoint Node Hours",
        metric_name="aiplatform.googleapis.com/prediction/online/accelerator/duty_cycle",
        metric_filter='resource.type = "aiplatform.googleapis.com/Endpoint"',
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="VAIP-ENDPOINT-N1S4",  # n1-standard-4 equivalent node-hour
        billing_price_tier=0,
    ),
    # ── 3. Batch prediction jobs ──────────────────────────────────────────────
    # Counts batch prediction output items processed this month.
    # Billed per 1K items processed.
    MonitoredMetric(
        label="Vertex AI – Batch Prediction Items Processed",
        metric_name="aiplatform.googleapis.com/prediction/batch_prediction_job/prediction_count",
        metric_filter='resource.type = "aiplatform.googleapis.com/BatchPredictionJob"',
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="VAIP-BATCH-PRED-ITEMS",  # per 1K items
        billing_price_tier=0,
    ),
    # ── 4. Custom training node hours ────────────────────────────────────────
    # Tracks CPU training node-hours consumed by custom training jobs.
    # Billed per vCPU-hour (n1-standard-8 base rate used).
    MonitoredMetric(
        label="Vertex AI – Custom Training Node Hours",
        metric_name="aiplatform.googleapis.com/training/node_hours",
        metric_filter='resource.type = "aiplatform.googleapis.com/CustomJob"',
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="VAIP-TRAINING-N1S8",  # n1-standard-8 per node-hour
        billing_price_tier=0,
    ),
    # ── 5. Vertex AI Pipelines – component execution ─────────────────────────
    # Counts executed pipeline components (steps) in both Kubeflow and
    # TFX pipelines.  Billed per executed component.
    MonitoredMetric(
        label="Vertex AI – Pipeline Component Executions",
        metric_name="aiplatform.googleapis.com/pipeline/run/step_count",
        metric_filter='resource.type = "aiplatform.googleapis.com/PipelineJob"',
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="VAIP-PIPELINE-STEP",  # per pipeline step executed
        billing_price_tier=0,
    ),
    # ── 6. Feature Store online serving ───────────────────────────────────────
    # Counts feature-value read operations against online Feature Store.
    # Billed per 100K read ops.
    MonitoredMetric(
        label="Vertex AI – Feature Store Online Read Ops",
        metric_name="aiplatform.googleapis.com/featurestore/online_serving/request_count",
        metric_filter='resource.type = "aiplatform.googleapis.com/FeaturestoreOnlineServingStats"',
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="VAIP-FEATURESTORE-READ",  # per 100K reads
        billing_price_tier=0,
    ),
    # ── 7. Matching Engine / Vector Search – query ops ────────────────────────
    # Counts ANN (approximate nearest-neighbour) queries served.
    # Billed per 1K queries.
    MonitoredMetric(
        label="Vertex AI – Vector Search Query Ops",
        metric_name="aiplatform.googleapis.com/matching_engine/online_serving/request_count",
        metric_filter='resource.type = "aiplatform.googleapis.com/IndexEndpoint"',
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="VAIP-VECTOR-SEARCH-QUERY",  # per 1K queries
        billing_price_tier=0,
    ),
    # ── 8. Model Monitoring – prediction volume ───────────────────────────────
    # Counts predictions analysed by Vertex AI Model Monitoring jobs.
    # Billed per 1K predictions monitored.
    MonitoredMetric(
        label="Vertex AI – Model Monitoring Predictions Analysed",
        metric_name="aiplatform.googleapis.com/model_monitoring/prediction_skew_drift/skew_drift_count",
        metric_filter='resource.type = "aiplatform.googleapis.com/ModelDeploymentMonitoringJob"',
        billing_service_id="C7E2-9256-1C43",
        billing_sku_id="VAIP-MODEL-MONITORING-PRED",  # per 1K monitored predictions
        billing_price_tier=0,
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
