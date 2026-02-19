#!/usr/bin/env python3
"""Exhaust BigQuery budget fast — runs large scans on public datasets.

Usage:
    pip install google-cloud-bigquery
    export GCP_PROJECT_ID=your-project-id
    python3 exhaust_bigquery.py

Runs full-table scans on large public datasets to burn through your
BigQuery bytes-scanned budget quickly. Each query scans ~5-10 GB.
"""

import os
import sys
import time

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
ROUNDS = int(os.environ.get("EXHAUST_ROUNDS", "10"))

# Public datasets with large tables (no cost to access the data,
# but the SCAN is billed to YOUR project)
QUERIES = [
    # ~5 GB per scan (GitHub activity data)
    "SELECT COUNT(*) as cnt, type FROM `githubarchive.day.20250101` GROUP BY type",
    # ~2 GB per scan (Stack Overflow posts)
    "SELECT COUNT(*) as cnt, LENGTH(body) as avg_len FROM `bigquery-public-data.stackoverflow.posts_answers` WHERE LENGTH(body) > 100",
    # ~8 GB per scan (Wikipedia page views)
    "SELECT wiki, SUM(views) as total_views FROM `bigquery-public-data.wikipedia.pageviews_2024` WHERE datehour > '2024-01-01' GROUP BY wiki ORDER BY total_views DESC LIMIT 100",
    # ~3 GB per scan (USA names dataset — cross join for size)
    "SELECT a.name, b.name, a.number + b.number as combined FROM `bigquery-public-data.usa_names.usa_1910_current` a CROSS JOIN (SELECT name, number FROM `bigquery-public-data.usa_names.usa_1910_current` LIMIT 1000) b LIMIT 100",
]


def main():
    if not PROJECT_ID:
        print("ERROR: Set GCP_PROJECT_ID environment variable")
        sys.exit(1)

    try:
        from google.cloud import bigquery
    except ImportError:
        print("Install: pip install google-cloud-bigquery")
        sys.exit(1)

    client = bigquery.Client(project=PROJECT_ID)

    print(f"=== BigQuery Budget Exhaust ===")
    print(f"Project:  {PROJECT_ID}")
    print(f"Rounds:   {ROUNDS}")
    print(f"===============================\n")

    total_bytes = 0

    for i in range(1, ROUNDS + 1):
        query = QUERIES[(i - 1) % len(QUERIES)]
        short_query = query[:80] + "..."
        try:
            job = client.query(query)
            result = job.result()
            bytes_billed = job.total_bytes_billed or 0
            total_bytes += bytes_billed
            gb = bytes_billed / (1024 ** 3)
            total_gb = total_bytes / (1024 ** 3)
            print(f"[{i}/{ROUNDS}] {gb:.2f} GB billed | cumulative: {total_gb:.2f} GB | {short_query}")
        except Exception as e:
            print(f"[{i}/{ROUNDS}] ERROR: {e}")
            if "403" in str(e) or "disabled" in str(e).lower() or "Access Denied" in str(e):
                print("\n>>> BigQuery API appears DISABLED — Budget Guard likely triggered! <<<")
                break
            time.sleep(1)

    print(f"\n=== Done ===")
    print(f"Total bytes billed: {total_bytes:,} ({total_bytes / (1024**3):.2f} GB)")
    print(f"Check budget status: curl -X POST $URL/check")


if __name__ == "__main__":
    main()
