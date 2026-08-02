"""
One-off manual test: alert on every open Atlassian PM role WORLDWIDE.

Deliberately does NOT read or write known_jobs.json — running this must not
mark roles as "seen" and suppress the real monitor's future alerts.

Usage (needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID; ANTHROPIC_API_KEY optional):
    python test_atlassian_alert.py
"""

import os
import sys

from scraper import (
    LINKEDIN_COMPANIES,
    format_notification,
    get_linkedin_pm_jobs,
    load_resumes,
    log,
    score_best_fit,
    send_telegram,
)

MAX_ALERTS = 15  # keep the test from flooding the chat; remainder is summarised


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set.")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    resumes = load_resumes()
    log(f"Fit scoring: {'enabled' if api_key and resumes else 'disabled'}")

    company = dict(next(c for c in LINKEDIN_COMPANIES if c["name"] == "Atlassian"))
    company["location"] = None       # worldwide
    company["search_term"] = "product manager"
    company["results_wanted"] = 100

    log("=" * 60)
    log("TEST: Atlassian PM roles worldwide (state file untouched)")
    log("=" * 60)

    jobs = get_linkedin_pm_jobs(company)
    log(f"Found {len(jobs)} Atlassian PM role(s) worldwide")

    if not jobs:
        send_telegram(token, chat_id,
                      "🧪 proj-flash test\n\nNo open Atlassian PM roles found worldwide.")
        log("Sent 'no results' notice.")
        return

    send_telegram(token, chat_id,
                  f"🧪 proj-flash test — {len(jobs)} open Atlassian PM role(s) "
                  f"worldwide. Sending up to {MAX_ALERTS} below.")

    sent = 0
    for job in jobs[:MAX_ALERTS]:
        if api_key and resumes:
            fit = score_best_fit(api_key, resumes, job["title"], job.get("description", ""))
            if fit:
                job["fit"] = f"{fit[2]} ({fit[1]})"
        try:
            send_telegram(token, chat_id, format_notification(job, len(jobs)))
            sent += 1
            log(f"  sent: {job['title']} | {job['location']}")
        except Exception as e:
            log(f"  FAILED: {job['title']}: {e}")

    skipped = len(jobs) - MAX_ALERTS
    if skipped > 0:
        lines = "\n".join(f"• {j['title']} — {j['location']}" for j in jobs[MAX_ALERTS:])
        send_telegram(token, chat_id,
                      f"🧪 {skipped} further Atlassian PM role(s) not sent "
                      f"individually:\n\n{lines}")
        log(f"Summarised {skipped} additional role(s) in one message.")

    log(f"Done — {sent} individual alert(s) sent, {max(skipped, 0)} summarised.")
    log("known_jobs.json was NOT modified.")


if __name__ == "__main__":
    main()
