#!/usr/bin/env python3
"""Exhaust Firestore budget fast — rapid document read/write operations.

Usage:
    pip install google-cloud-firestore
    export GCP_PROJECT_ID=your-project-id
    python3 exhaust_firestore.py

Creates a test collection and hammers it with reads/writes to burn through
Firestore operation budgets quickly. Cleans up after itself.
"""

import os
import sys
import time
import uuid

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
COLLECTION = "budget_guard_exhaust_test"

# Number of write + read cycles
WRITE_ROUNDS = int(os.environ.get("EXHAUST_WRITES", "500"))
READ_ROUNDS = int(os.environ.get("EXHAUST_READS", "2000"))


def main():
    if not PROJECT_ID:
        print("ERROR: Set GCP_PROJECT_ID environment variable")
        sys.exit(1)

    try:
        from google.cloud import firestore
    except ImportError:
        print("Install: pip install google-cloud-firestore")
        sys.exit(1)

    db = firestore.Client(project=PROJECT_ID)
    collection = db.collection(COLLECTION)

    print(f"=== Firestore Budget Exhaust ===")
    print(f"Project:    {PROJECT_ID}")
    print(f"Collection: {COLLECTION}")
    print(f"Writes:     {WRITE_ROUNDS}")
    print(f"Reads:      {READ_ROUNDS}")
    print(f"================================\n")

    doc_ids = []

    # Phase 1: Writes
    print("--- Phase 1: Writing documents ---")
    for i in range(1, WRITE_ROUNDS + 1):
        try:
            doc_id = f"exhaust_{uuid.uuid4().hex[:8]}"
            collection.document(doc_id).set({
                "index": i,
                "data": f"Budget exhaust test document {i}",
                "padding": "x" * 500,  # bigger payload = more write units
                "timestamp": time.time(),
            })
            doc_ids.append(doc_id)
            if i % 100 == 0:
                print(f"  Written {i}/{WRITE_ROUNDS} documents")
        except Exception as e:
            print(f"  [{i}] WRITE ERROR: {e}")
            if "403" in str(e) or "disabled" in str(e).lower():
                print("\n>>> Firestore API appears DISABLED — Budget Guard likely triggered! <<<")
                break
            time.sleep(0.5)

    # Phase 2: Reads (read each doc multiple times)
    print(f"\n--- Phase 2: Reading documents ({READ_ROUNDS} reads) ---")
    reads_done = 0
    for i in range(READ_ROUNDS):
        if not doc_ids:
            break
        doc_id = doc_ids[i % len(doc_ids)]
        try:
            doc = collection.document(doc_id).get()
            reads_done += 1
            if reads_done % 500 == 0:
                print(f"  Completed {reads_done}/{READ_ROUNDS} reads")
        except Exception as e:
            print(f"  READ ERROR: {e}")
            if "403" in str(e) or "disabled" in str(e).lower():
                print("\n>>> Firestore API appears DISABLED — Budget Guard likely triggered! <<<")
                break
            time.sleep(0.5)

    # Phase 3: Cleanup
    print(f"\n--- Phase 3: Cleanup ({len(doc_ids)} docs) ---")
    for doc_id in doc_ids:
        try:
            collection.document(doc_id).delete()
        except Exception:
            pass  # best-effort cleanup
    print(f"  Cleanup complete")

    print(f"\n=== Done ===")
    print(f"Total writes: {len(doc_ids):,}")
    print(f"Total reads:  {reads_done:,}")
    print(f"Total deletes: {len(doc_ids):,}")
    print(f"Check budget status: curl -X POST $URL/check")


if __name__ == "__main__":
    main()
