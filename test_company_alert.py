"""
Manual test harness: send Telegram alerts for every open PM role at ONE company,
ignoring known_jobs.json entirely.

Deliberately does NOT read or write known_jobs.json — running this must not mark
roles as "seen" and suppress the real monitor's future alerts.

Usage:
    python test_company_alert.py Airbnb
    COMPANY=Atlassian python test_company_alert.py

Needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID; ANTHROPIC_API_KEY optional (fit scoring).
"""

import os
import sys

from scraper import (
    ASHBY_COMPANIES,
    EIGHTFOLD_COMPANIES,
    GREENHOUSE_COMPANIES,
    LINKEDIN_COMPANIES,
    format_notification,
    get_ashby_pm_jobs,
    get_eightfold_pm_jobs,
    get_greenhouse_pm_jobs,
    get_linkedin_pm_jobs,
    load_resumes,
    log,
    score_best_fit,
    send_telegram,
)

MAX_ALERTS = 15  # keep the test from flooding the chat; remainder is summarised

SOURCES = [
    ("Greenhouse", GREENHOUSE_COMPANIES, get_greenhouse_pm_jobs),
    ("Ashby", ASHBY_COMPANIES, get_ashby_pm_jobs),
    ("Eightfold", EIGHTFOLD_COMPANIES, get_eightfold_pm_jobs),
    ("LinkedIn", LINKEDIN_COMPANIES, get_linkedin_pm_jobs),
]


def resolve(name):
    """Find a company config by name across every ATS list."""
    for ats, configs, fetcher in SOURCES:
        for cfg in configs:
            if cfg["name"].lower() == name.lower():
                return ats, dict(cfg), fetcher
    known = sorted(c["name"] for _, cfgs, _ in SOURCES for c in cfgs)
    raise SystemExit(f"Unknown company {name!r}. Configured: {', '.join(known)}")


def main():
    name = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("COMPANY", "")).strip()
    if not name:
        raise SystemExit("Pass a company name as argv[1] or set COMPANY.")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise SystemExit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set.")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    resumes = load_resumes()

    ats, company, fetcher = resolve(name)
    if ats == "LinkedIn":
        company["location"] = None  # worldwide
        company["results_wanted"] = 100

    log("=" * 60)
    log(f"TEST: {company['name']} PM roles via {ats} (state file untouched)")
    log(f"Fit scoring: {'enabled' if api_key and resumes else 'disabled'}")
    log("=" * 60)

    jobs = fetcher(company)
    log(f"Found {len(jobs)} {company['name']} PM role(s)")

    if not jobs:
        send_telegram(token, chat_id,
                      f"🧪 proj-flash test\n\nNo open {company['name']} PM roles found.")
        log("Sent 'no results' notice.")
        return

    send_telegram(token, chat_id,
                  f"🧪 proj-flash test — {len(jobs)} open {company['name']} PM role(s) "
                  f"via {ats}. Sending up to {MAX_ALERTS} below.")

    scored = 0
    for job in jobs[:MAX_ALERTS]:
        if api_key and resumes:
            fit = score_best_fit(api_key, resumes, job["title"], job.get("description", ""))
            if fit:
                job["fit"] = f"{fit[2]} ({fit[1]})"
                scored += 1
                log(f"  Fit score: {job['fit']}")
        try:
            send_telegram(token, chat_id, format_notification(job, len(jobs)))
            log(f"  sent: {job['title']} | {job['location']}")
        except Exception as e:
            log(f"  FAILED: {job['title']}: {e}")

    skipped = len(jobs) - MAX_ALERTS
    if skipped > 0:
        lines = "\n".join(f"• {j['title']} — {j['location']}" for j in jobs[MAX_ALERTS:])
        send_telegram(token, chat_id,
                      f"🧪 {skipped} further {company['name']} PM role(s) not sent "
                      f"individually:\n\n{lines}")
        log(f"Summarised {skipped} additional role(s) in one message.")

    log(f"Done — {min(len(jobs), MAX_ALERTS)} alert(s) sent, {scored} fit-scored, "
        f"{max(skipped, 0)} summarised.")
    log("known_jobs.json was NOT modified.")


if __name__ == "__main__":
    main()
