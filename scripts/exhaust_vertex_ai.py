#!/usr/bin/env python3
"""Exhaust Vertex AI (Gemini) budget fast — sends rapid Gemini API calls.

Usage:
    pip install google-cloud-aiplatform
    export GCP_PROJECT_ID=your-project-id
    python3 exhaust_vertex_ai.py

Generates many Gemini API calls with long prompts to quickly burn through
your Vertex AI token budget. Uses gemini-2.0-flash-lite (cheapest model)
for rapid token consumption. Adjust ROUNDS and PROMPT_SIZE to control spend.
"""

import os
import sys
import time

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
REGION = os.environ.get("GCP_REGION", "us-central1")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")

# How many rounds of calls to make (each generates ~2K-4K tokens)
ROUNDS = int(os.environ.get("EXHAUST_ROUNDS", "50"))

# Long prompt to maximize input token count per call
LONG_PROMPT = (
    "Explain in extreme detail the history of computer science from 1940 to 2025. "
    "Cover every major milestone, every programming language invented, every "
    "operating system created, every major company founded, every significant "
    "algorithm discovered, and every hardware breakthrough. Include dates and names. "
) * 5  # ~500 tokens input per call


def main():
    if not PROJECT_ID:
        print("ERROR: Set GCP_PROJECT_ID environment variable")
        sys.exit(1)

    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel
    except ImportError:
        print("Install: pip install google-cloud-aiplatform")
        sys.exit(1)

    vertexai.init(project=PROJECT_ID, location=REGION)
    model = GenerativeModel(MODEL)

    print(f"=== Vertex AI Budget Exhaust ===")
    print(f"Project:  {PROJECT_ID}")
    print(f"Model:    {MODEL}")
    print(f"Rounds:   {ROUNDS}")
    print(f"================================\n")

    total_input = 0
    total_output = 0

    for i in range(1, ROUNDS + 1):
        try:
            response = model.generate_content(LONG_PROMPT)
            in_tokens = response.usage_metadata.prompt_token_count
            out_tokens = response.usage_metadata.candidates_token_count
            total_input += in_tokens
            total_output += out_tokens
            print(f"[{i}/{ROUNDS}] in={in_tokens} out={out_tokens} | cumulative: in={total_input} out={total_output}")
        except Exception as e:
            print(f"[{i}/{ROUNDS}] ERROR: {e}")
            if "403" in str(e) or "PERMISSION_DENIED" in str(e) or "disabled" in str(e).lower():
                print("\n>>> API appears to be DISABLED — Budget Guard likely triggered! <<<")
                break
            time.sleep(1)

    print(f"\n=== Done ===")
    print(f"Total input tokens:  {total_input:,}")
    print(f"Total output tokens: {total_output:,}")
    print(f"Check budget status: curl -X POST $URL/check")


if __name__ == "__main__":
    main()
