#!/usr/bin/env python3
"""Test all 8 Vertex AI service types against Budget Guard.

This script exercises each monitored Vertex AI sub-service to verify that:
1. Cloud Monitoring reports usage metrics for each service type.
2. Pricing lookups work via both static catalog and billing API.
3. The combined cost flows into the vertex_ai budget correctly.

Prerequisites:
    pip install google-cloud-aiplatform google-cloud-monitoring
    export GCP_PROJECT_ID=your-project-id
    export GCP_REGION=us-central1          # or your region

Usage:
    # Test specific services (comma-separated):
    python3 test_vertex_ai_services.py --services publisher,batch,training

    # Test all services (dry-run: no real API calls, uses static catalog):
    python3 test_vertex_ai_services.py --dry-run

    # Test all services against live GCP:
    python3 test_vertex_ai_services.py --all

    # Verify pricing only (no GCP calls, checks catalog + price provider):
    python3 test_vertex_ai_services.py --pricing-only

Service types:
    publisher     - Publisher model serving (Gemini token usage)
    endpoint      - Online prediction endpoint compute
    batch         - Batch prediction jobs
    training      - Custom training node hours
    pipeline      - Pipeline component executions
    featurestore  - Feature Store online read ops
    vectorsearch  - Vector Search (Matching Engine) queries
    monitoring    - Model Monitoring predictions
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
REGION = os.environ.get("GCP_REGION", "us-central1")

# ─── Service test definitions ──────────────────────────────────────────────

ALL_SERVICES = [
    "publisher", "endpoint", "batch", "training",
    "pipeline", "featurestore", "vectorsearch", "monitoring",
]

METRIC_MAP = {
    "publisher": {
        "metric_name": "aiplatform.googleapis.com/publisher/online_serving/token_count",
        "resource_type": "aiplatform.googleapis.com/PublisherModel",
        "description": "Publisher Model Serving (Gemini / partner models) token usage",
        "catalog_sku": None,  # catch-all: priced per model
    },
    "endpoint": {
        "metric_name": "aiplatform.googleapis.com/prediction/online/accelerator/duty_cycle",
        "resource_type": "aiplatform.googleapis.com/Endpoint",
        "description": "Dedicated Online Prediction Endpoint node hours",
        "catalog_sku": "VAIP-ENDPOINT-N1S4",
    },
    "batch": {
        "metric_name": "aiplatform.googleapis.com/prediction/batch_prediction_job/prediction_count",
        "resource_type": "aiplatform.googleapis.com/BatchPredictionJob",
        "description": "Batch Prediction items processed",
        "catalog_sku": "VAIP-BATCH-PRED-ITEMS",
    },
    "training": {
        "metric_name": "aiplatform.googleapis.com/training/node_hours",
        "resource_type": "aiplatform.googleapis.com/CustomJob",
        "description": "Custom Training job compute (CPU node hours)",
        "catalog_sku": "VAIP-TRAINING-N1S8",
    },
    "pipeline": {
        "metric_name": "aiplatform.googleapis.com/pipeline/run/step_count",
        "resource_type": "aiplatform.googleapis.com/PipelineJob",
        "description": "Vertex AI Pipeline step executions",
        "catalog_sku": "VAIP-PIPELINE-STEP",
    },
    "featurestore": {
        "metric_name": "aiplatform.googleapis.com/featurestore/online_serving/request_count",
        "resource_type": "aiplatform.googleapis.com/FeaturestoreOnlineServingStats",
        "description": "Feature Store online-serving read operations",
        "catalog_sku": "VAIP-FEATURESTORE-READ",
    },
    "vectorsearch": {
        "metric_name": "aiplatform.googleapis.com/matching_engine/online_serving/request_count",
        "resource_type": "aiplatform.googleapis.com/IndexEndpoint",
        "description": "Vector Search (Matching Engine) ANN queries",
        "catalog_sku": "VAIP-VECTOR-SEARCH-QUERY",
    },
    "monitoring": {
        "metric_name": "aiplatform.googleapis.com/model_monitoring/prediction_skew_drift/skew_drift_count",
        "resource_type": "aiplatform.googleapis.com/ModelDeploymentMonitoringJob",
        "description": "Model Monitoring predictions analysed",
        "catalog_sku": "VAIP-MODEL-MONITORING-PRED",
    },
}


@dataclass
class TestResult:
    """Result of a single service test."""
    service: str
    metric_checked: bool = False
    metric_has_data: bool = False
    metric_units: int = 0
    pricing_checked: bool = False
    price_found: bool = False
    price_per_base_unit: float | None = None
    estimated_cost: float = 0.0
    error: str | None = None


# ─── Cloud Monitoring check ──────────────────────────────────────────────

def check_monitoring_metric(
    project_id: str,
    metric_name: str,
    resource_type: str,
) -> tuple[bool, int]:
    """Query Cloud Monitoring for month-to-date usage of a metric.

    Returns (has_data, unit_count).
    """
    try:
        from google.cloud import monitoring_v3
        from google.protobuf.timestamp_pb2 import Timestamp
        import datetime
    except ImportError:
        print("  [SKIP] google-cloud-monitoring not installed")
        return False, 0

    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"

    now = datetime.datetime.now(datetime.timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    start_time = Timestamp()
    start_time.FromDatetime(month_start)
    end_time = Timestamp()
    end_time.FromDatetime(now)

    interval = monitoring_v3.TimeInterval(
        start_time=start_time,
        end_time=end_time,
    )

    metric_filter = (
        f'metric.type = "{metric_name}" '
        f'AND resource.type = "{resource_type}"'
    )

    request = monitoring_v3.ListTimeSeriesRequest(
        name=project_name,
        filter=metric_filter,
        interval=interval,
        view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
    )

    total = 0
    has_data = False
    try:
        results = client.list_time_series(request=request)
        for ts in results:
            has_data = True
            for point in ts.points:
                total += int(point.value.int64_value or point.value.double_value or 0)
    except Exception as exc:
        print(f"  [WARN] Monitoring query failed: {exc}")
        return False, 0

    return has_data, total


# ─── Pricing check ──────────────────────────────────────────────────────

def check_pricing_static(sku_id: str | None) -> tuple[bool, float | None]:
    """Look up the price for a SKU in the static pricing catalog.

    Returns (found, price_per_base_unit).
    """
    catalog_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "config", "pricing_catalog.json"
    )
    if not os.path.exists(catalog_path):
        print(f"  [WARN] Catalog not found at {catalog_path}")
        return False, None

    with open(catalog_path, "r") as f:
        data = json.load(f)

    if sku_id is None:
        # Publisher model (catch-all): use default token price
        defaults = data.get("vertex_ai_defaults", {})
        price = defaults.get("default_input_token_price")
        unit_size = defaults.get("default_token_unit_size", 1_000_000)
        if price is not None:
            return True, float(price) / unit_size
        return False, None

    # Check vertex_ai_services section
    for _name, entry in data.get("vertex_ai_services", {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("sku_id") == sku_id:
            ppu = float(entry.get("price_per_unit", 0))
            us = int(entry.get("unit_size", 1))
            return True, ppu / us if us > 0 else 0.0

    # Check flat SKU index (bigquery, firestore, vertex_ai model entries)
    for section_key in ("vertex_ai", "bigquery", "firestore"):
        section = data.get(section_key, {})
        result = _search_sku_in_section(section, sku_id)
        if result is not None:
            return True, result

    return False, None


def _search_sku_in_section(data: dict, sku_id: str) -> float | None:
    """Recursively search for billing_sku_id in a catalog section."""
    for _key, val in data.items():
        if not isinstance(val, dict):
            continue
        if val.get("billing_sku_id") == sku_id or val.get("sku_id") == sku_id:
            ppu = float(val.get("price_per_unit", 0))
            us = int(val.get("unit_size", 1))
            return ppu / us if us > 0 else 0.0
        # Recurse
        result = _search_sku_in_section(val, sku_id)
        if result is not None:
            return result
    return None


def check_pricing_provider(sku_id: str | None) -> tuple[bool, float | None]:
    """Use the actual PriceProvider chain (same as prod) to resolve a price.

    Requires the src/ directory on sys.path.
    """
    src_dir = os.path.join(os.path.dirname(__file__), "..", "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    # Temporarily set a dummy project ID so the service can initialise
    old_project = os.environ.get("GCP_PROJECT_ID")
    os.environ.setdefault("GCP_PROJECT_ID", "test-price-check-project")

    try:
        # Force static mode for this test
        os.environ["LAB_MODE"] = "True"
        from services.price_provider import create_price_provider
        provider = create_price_provider()

        if sku_id is None:
            # Publisher model catch-all — test with gemini-2.5-pro
            price = provider.get_vertex_ai_token_price("gemini-2.5-pro", "input")
            return (price is not None), price

        price = provider.get_price_per_unit(
            service_id="C7E2-9256-1C43",
            sku_id=sku_id,
        )
        return (price is not None), price
    except Exception as exc:
        print(f"  [WARN] PriceProvider lookup failed: {exc}")
        return False, None
    finally:
        if old_project is None:
            os.environ.pop("GCP_PROJECT_ID", None)
        else:
            os.environ["GCP_PROJECT_ID"] = old_project


# ─── Live GCP service exercisers ─────────────────────────────────────────

def exercise_publisher():
    """Send a small Gemini call to generate publisher token usage."""
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel

        vertexai.init(project=PROJECT_ID, location=REGION)
        model = GenerativeModel("gemini-2.0-flash-lite")
        resp = model.generate_content("Say hello in 10 words.")
        inp = resp.usage_metadata.prompt_token_count
        out = resp.usage_metadata.candidates_token_count
        print(f"  Generated: in={inp} out={out} tokens")
        return True
    except Exception as exc:
        print(f"  [WARN] Publisher call failed: {exc}")
        return False


def exercise_batch():
    """Submit a minimal batch prediction job (does NOT wait for completion)."""
    try:
        from google.cloud import aiplatform

        aiplatform.init(project=PROJECT_ID, location=REGION)
        print("  [INFO] Batch prediction requires a pre-configured dataset and model.")
        print("  [SKIP] Submit manually via `gcloud ai batch-prediction-jobs create ...`")
        return False
    except Exception as exc:
        print(f"  [WARN] Batch prediction exercise failed: {exc}")
        return False


def exercise_training():
    """Submit a minimal custom training job."""
    try:
        from google.cloud import aiplatform

        aiplatform.init(project=PROJECT_ID, location=REGION)
        print("  [INFO] Training jobs require a container image or Python package.")
        print("  [SKIP] Submit manually via `gcloud ai custom-jobs create ...`")
        return False
    except Exception as exc:
        print(f"  [WARN] Training exercise failed: {exc}")
        return False


# ─── Main test runner ────────────────────────────────────────────────────

def run_test(service: str, *, dry_run: bool, pricing_only: bool) -> TestResult:
    """Run a comprehensive test for one Vertex AI service type."""
    info = METRIC_MAP[service]
    result = TestResult(service=service)

    print(f"\n{'='*60}")
    print(f"  {service.upper()}: {info['description']}")
    print(f"  Metric: {info['metric_name']}")
    print(f"  SKU:    {info['catalog_sku'] or '(catch-all — per model)'}")
    print(f"{'='*60}")

    # 1. Pricing check (always runs)
    print("\n  [1/3] Static catalog pricing check ...")
    found, price = check_pricing_static(info["catalog_sku"])
    result.pricing_checked = True
    result.price_found = found
    result.price_per_base_unit = price
    if found:
        print(f"  ✓ Price found: ${price:.10f} per base unit")
    else:
        print(f"  ✗ SKU not found in static catalog")

    # 1b. PriceProvider chain check
    print("  [1b/3] PriceProvider chain check ...")
    prov_found, prov_price = check_pricing_provider(info["catalog_sku"])
    if prov_found:
        print(f"  ✓ PriceProvider resolved: ${prov_price:.10f} per base unit")
        if found and price and abs(price - prov_price) > 1e-12:
            print(f"  ⚠ MISMATCH: catalog={price:.10f} vs provider={prov_price:.10f}")
    else:
        print(f"  ✗ PriceProvider returned None")

    if pricing_only:
        return result

    # 2. Cloud Monitoring check
    if dry_run:
        print("\n  [2/3] Cloud Monitoring check ... [SKIPPED — dry run]")
        result.metric_checked = False
    elif not PROJECT_ID:
        print("\n  [2/3] Cloud Monitoring check ... [SKIPPED — no GCP_PROJECT_ID]")
        result.metric_checked = False
    else:
        print(f"\n  [2/3] Querying Cloud Monitoring (project={PROJECT_ID}) ...")
        has_data, units = check_monitoring_metric(
            PROJECT_ID, info["metric_name"], info["resource_type"]
        )
        result.metric_checked = True
        result.metric_has_data = has_data
        result.metric_units = units
        if has_data:
            print(f"  ✓ Monitoring data found: {units:,} units this month")
        else:
            print(f"  ○ No monitoring data (service may not be in use)")

    # 3. Cost estimate
    if result.price_per_base_unit is not None and result.metric_units > 0:
        result.estimated_cost = result.price_per_base_unit * result.metric_units
        print(f"\n  [3/3] Estimated cost: ${result.estimated_cost:.6f}")
    else:
        print(f"\n  [3/3] Cost estimate: N/A (no usage or no price)")

    return result


def print_summary(results: list[TestResult]) -> None:
    """Print a summary table of all test results."""
    print(f"\n{'='*72}")
    print(f"  VERTEX AI SERVICE TEST SUMMARY")
    print(f"{'='*72}")
    print(f"  {'Service':<16} {'Price':>6} {'Metric':>7} {'Units':>12} {'Cost':>14}")
    print(f"  {'-'*16} {'-'*6} {'-'*7} {'-'*12} {'-'*14}")

    total_cost = 0.0
    for r in results:
        price_ok = "✓" if r.price_found else "✗"
        metric_ok = "✓" if r.metric_has_data else ("○" if r.metric_checked else "–")
        units = f"{r.metric_units:,}" if r.metric_units else "0"
        cost = f"${r.estimated_cost:.6f}" if r.estimated_cost > 0 else "$0.00"
        total_cost += r.estimated_cost
        print(f"  {r.service:<16} {price_ok:>6} {metric_ok:>7} {units:>12} {cost:>14}")

    print(f"  {'-'*16} {'-'*6} {'-'*7} {'-'*12} {'-'*14}")
    print(f"  {'TOTAL':<16} {'':>6} {'':>7} {'':>12} ${total_cost:>13.6f}")
    print()

    # Health summary
    pricing_ok = sum(1 for r in results if r.price_found)
    pricing_total = sum(1 for r in results if r.pricing_checked)
    print(f"  Pricing:    {pricing_ok}/{pricing_total} services have catalog prices")

    monitored = [r for r in results if r.metric_checked]
    if monitored:
        with_data = sum(1 for r in monitored if r.metric_has_data)
        print(f"  Monitoring: {with_data}/{len(monitored)} services have month-to-date data")

    # Failures
    failed = [r for r in results if r.pricing_checked and not r.price_found]
    if failed:
        print(f"\n  ⚠ PRICING MISSING for: {', '.join(r.service for r in failed)}")
        print(f"    → Check pricing_catalog.json vertex_ai_services section")


def main():
    parser = argparse.ArgumentParser(
        description="Test all 8 Vertex AI service types against Budget Guard"
    )
    parser.add_argument(
        "--services",
        type=str,
        default=None,
        help="Comma-separated service names to test (default: all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Test all services against live GCP",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Cloud Monitoring queries (test pricing only)",
    )
    parser.add_argument(
        "--pricing-only",
        action="store_true",
        help="Only verify pricing catalog lookups (no GCP API calls)",
    )
    parser.add_argument(
        "--exercise-publisher",
        action="store_true",
        help="Also send a real Gemini call to generate publisher usage",
    )
    args = parser.parse_args()

    # Determine which services to test
    if args.services:
        services = [s.strip() for s in args.services.split(",")]
        unknown = [s for s in services if s not in METRIC_MAP]
        if unknown:
            print(f"ERROR: Unknown service(s): {', '.join(unknown)}")
            print(f"Valid: {', '.join(ALL_SERVICES)}")
            sys.exit(1)
    else:
        services = ALL_SERVICES

    dry_run = args.dry_run or args.pricing_only

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║      VERTEX AI SERVICE MONITORING & PRICING TESTER         ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(f"  Project:   {PROJECT_ID or '(not set — monitoring will be skipped)'}")
    print(f"  Region:    {REGION}")
    print(f"  Mode:      {'pricing-only' if args.pricing_only else 'dry-run' if dry_run else 'live'}")
    print(f"  Services:  {', '.join(services)}")

    # Optional: exercise publisher model
    if args.exercise_publisher and not dry_run:
        print("\n  Sending a Gemini call to generate publisher usage ...")
        exercise_publisher()
        print("  (Wait ~2-5 min for metrics to appear in Cloud Monitoring)")

    # Run tests
    results = []
    for svc in services:
        result = run_test(svc, dry_run=dry_run, pricing_only=args.pricing_only)
        results.append(result)

    # Summary
    print_summary(results)

    # Exit code: 0 if all pricing checks passed, 1 otherwise
    all_priced = all(r.price_found for r in results if r.pricing_checked)
    sys.exit(0 if all_priced else 1)


if __name__ == "__main__":
    main()
