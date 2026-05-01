"""
Stress-test eval: fetch PM jobs from all monitored companies and use Claude
to assess filter quality (false positives / false negatives).

Usage:
    ANTHROPIC_API_KEY=sk-... python eval.py

Requires python-jobspy to be installed (pip install -r requirements.txt).
"""

import json
import os
import sys
import urllib.request
from scraper import GREENHOUSE_COMPANIES, get_greenhouse_pm_jobs, get_google_pm_jobs, log


def call_claude(api_key, prompt):
    url = "https://api.anthropic.com/v1/messages"
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["content"][0]["text"]


def eval_company(company_name, jobs, api_key):
    if not jobs:
        return "⚠️  No jobs fetched — check API/network."

    job_lines = "\n".join(f"  - {j['title']} | {j['location']}" for j in jobs)
    prompt = f"""You are evaluating the output of an automated PM job monitor for a job seeker interested in Product Manager roles at top AI/tech companies, based in or open to India.

Company: {company_name}
Jobs returned by the monitor:
{job_lines}

Assess:
1. FALSE POSITIVES — any non-PM roles that slipped through the keyword filter? (e.g. engineering, design, ops)
2. FALSE NEGATIVES — any obvious PM roles you'd expect that seem to be missing? Name specific role types if so.
3. LOCATION relevance — are these roles India-based or open to India / remote? Flag any that seem irrelevant.
4. Overall filter quality: Excellent / Good / Needs work — and one-line reason.

Be concise. Bullet points only."""

    return call_claude(api_key, prompt)


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. Export it and re-run.", file=sys.stderr)
        sys.exit(1)

    all_results = {}

    # Greenhouse companies
    for company in GREENHOUSE_COMPANIES:
        name = company["name"]
        log(f"Fetching {name}...")
        try:
            jobs = get_greenhouse_pm_jobs(company)
            all_results[name] = jobs
        except Exception as e:
            log(f"  ERROR: {e}")
            all_results[name] = []

    # Google (LinkedIn)
    log("Fetching Google (via LinkedIn)...")
    try:
        jobs = get_google_pm_jobs()
        all_results["Google"] = jobs
    except Exception as e:
        log(f"  ERROR: {e}")
        all_results["Google"] = []

    # Summary table
    print("\n" + "=" * 60)
    print("FETCH SUMMARY")
    print("=" * 60)
    for company, jobs in all_results.items():
        print(f"\n{company} — {len(jobs)} PM role(s)")
        for j in jobs:
            print(f"  • {j['title']} | {j['location']}")

    # LLM eval
    print("\n" + "=" * 60)
    print("LLM EVAL (Claude Haiku)")
    print("=" * 60)
    for company, jobs in all_results.items():
        print(f"\n--- {company} ---")
        try:
            print(eval_company(company, jobs, api_key))
        except Exception as e:
            print(f"Eval failed: {e}")


if __name__ == "__main__":
    main()
