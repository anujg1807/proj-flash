import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from jobspy import scrape_jobs

STATE_FILE = Path(__file__).parent / "known_jobs.json"
IST = timezone(timedelta(hours=5, minutes=30))

# --- Anthropic (Greenhouse) ---
ANTHROPIC_URL = "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs"
ANTHROPIC_PM_TITLE_KEYWORDS = [
    "product manager", "product management", "product lead", "research product"
]
ANTHROPIC_PM_DEPARTMENT = "product management"

# --- Google Jobs (via LinkedIn) ---
# Google's own search blocks GitHub Actions (Azure) IPs via bot detection.
# Using LinkedIn with Google's company ID (1441) fetches only Google postings directly.
GOOGLE_LINKEDIN_COMPANY_ID = 1441
GOOGLE_SEARCH_TERM = "product manager"
GOOGLE_LOCATION = "India"
GOOGLE_RESULTS_WANTED = 50
GOOGLE_PM_KEYWORDS = [
    "product manager", "product management", "product lead",
    "group product manager", "senior product manager"
]


# ── Helpers ───────────────────────────────────────────────────────────────────────────────

def now_ist():
    return datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")


def log(msg):
    print(f"[{now_ist()}] {msg}")


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pm-monitor/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def load_known_jobs():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_known_jobs(known):
    STATE_FILE.write_text(json.dumps(known, indent=2, ensure_ascii=False))


def send_telegram(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def send_error_alert(token, chat_id, company, error):
    if not token or not chat_id:
        log("  Telegram creds not set — skipping error alert.")
        return
    msg = (
        f"⚠️ <b>proj-flash error</b>\n\n"
        f"Failed to fetch <b>{company}</b> jobs:\n"
        f"<code>{error}</code>"
    )
    try:
        send_telegram(token, chat_id, msg)
        log("  Error alert sent to Telegram.")
    except Exception as alert_err:
        log(f"  Could not send error alert: {alert_err}")


def format_posted_date(updated_at):
    if updated_at:
        try:
            dt = datetime.fromisoformat(updated_at)
            if dt.hour == 0 and dt.minute == 0 and dt.second == 0 and dt.tzinfo is None:
                return dt.strftime("%d %b %Y")
            return dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")
        except Exception:
            pass
    return "Date not available"


def format_notification(job, total_count):
    posted = format_posted_date(job.get("updated_at"))
    return (
        f"🚨 New {job['company']} PM Role\n\n"
        f"{job['title']}\n"
        f"📍 {job['location']}\n"
        f"🕐 Posted: {posted}\n\n"
        f"Apply → {job['apply_url']}\n\n"
        f"Total {job['company']} PM roles open: {total_count}"
    )


def format_repost_notification(job, total_count):
    posted = format_posted_date(job.get("updated_at"))
    return (
        f"🔄 Reposted {job['company']} PM Role\n\n"
        f"{job['title']}\n"
        f"📍 {job['location']}\n"
        f"🕐 Reposted: {posted}\n\n"
        f"Apply → {job['apply_url']}\n\n"
        f"Total {job['company']} PM roles open: {total_count}"
    )


# ── Anthropic ─────────────────────────────────────────────────────────────────────────────

def fetch_anthropic_jobs():
    data = fetch_json(ANTHROPIC_URL)
    return data.get("jobs", [])


def is_anthropic_pm(job):
    title = job.get("title", "").lower()
    if any(kw in title for kw in ANTHROPIC_PM_TITLE_KEYWORDS):
        return True
    for dept in job.get("departments", []):
        if ANTHROPIC_PM_DEPARTMENT in dept.get("name", "").lower():
            return True
    return False


def normalize_anthropic(job):
    offices = job.get("offices", [])
    location = ", ".join(o["name"] for o in offices if o.get("name")) or "Remote / Not specified"
    return {
        "id": f"anthropic_{job['id']}",
        "company": "Anthropic",
        "title": job.get("title"),
        "location": location,
        "apply_url": job.get("absolute_url", "https://boards.greenhouse.io/anthropic"),
        "updated_at": job.get("updated_at"),
    }


def get_anthropic_pm_jobs():
    t0 = time.time()
    log(f"  Fetching from Greenhouse API: {ANTHROPIC_URL}")
    all_jobs = fetch_anthropic_jobs()
    log(f"  API response: {len(all_jobs)} total jobs across all departments ({time.time()-t0:.1f}s)")

    pm_jobs = [normalize_anthropic(j) for j in all_jobs if is_anthropic_pm(j)]
    log(f"  After PM filter: {len(pm_jobs)} role(s)")
    for job in pm_jobs:
        log(f"    - {job['title']} | {job['location']} | {job['apply_url']}")
    return pm_jobs


# ── Google ───────────────────────────────────────────────────────────────────────────────

def get_google_pm_jobs():
    t0 = time.time()
    log(f"  Source: LinkedIn company_id={GOOGLE_LINKEDIN_COMPANY_ID} | search_term='{GOOGLE_SEARCH_TERM}' | location='{GOOGLE_LOCATION}'")

    try:
        df = scrape_jobs(
            site_name=["linkedin"],
            search_term=GOOGLE_SEARCH_TERM,
            location=GOOGLE_LOCATION,
            linkedin_company_ids=[GOOGLE_LINKEDIN_COMPANY_ID],
            results_wanted=GOOGLE_RESULTS_WANTED,
            verbose=0,
        )
    except Exception as e:
        raise RuntimeError(f"jobspy LinkedIn scrape failed: {e}") from e

    elapsed = time.time() - t0
    if df is None or df.empty:
        raise RuntimeError(
            f"jobspy returned 0 raw results from LinkedIn after {elapsed:.1f}s — possible rate-limit or API change"
        )

    log(f"  Raw results: {len(df)} Google job(s) fetched in {elapsed:.1f}s")
    for _, row in df.iterrows():
        log(f"    title='{row.get('title')}' | location='{row.get('location')}' | posted={row.get('date_posted')}")

    # Filter to PM titles only
    jobs = []
    for _, row in df.iterrows():
        title = str(row.get("title") or "").strip()
        if not any(kw in title.lower() for kw in GOOGLE_PM_KEYWORDS):
            log(f"    SKIP (not PM title): '{title}'")
            continue

        raw_id = str(row.get("id") or "")
        stable_id = f"google_{raw_id}" if raw_id else None
        if not stable_id:
            log(f"    SKIP (no id): '{title}'")
            continue

        date_posted = row.get("date_posted")
        updated_at = date_posted.isoformat() if (date_posted and hasattr(date_posted, "isoformat")) else None
        location = str(row.get("location") or "India").strip()
        apply_url = str(row.get("job_url") or "https://careers.google.com").strip()

        jobs.append({
            "id": stable_id,
            "company": "Google",
            "title": title,
            "location": location,
            "apply_url": apply_url,
            "updated_at": updated_at,
        })

    log(f"  After PM keyword filter: {len(jobs)} role(s) remaining")
    return jobs


# ── Main ───────────────────────────────────────────────────────────────────────────────

def process_company(jobs, known, token, chat_id):
    now_iso = datetime.now(timezone.utc).isoformat()
    new_jobs = []
    reposted_jobs = []

    for job in jobs:
        job_id = job["id"]
        current_date = job.get("updated_at")

        if job_id not in known:
            known[job_id] = {
                "title": job["title"],
                "location": job["location"],
                "apply_url": job["apply_url"],
                "first_seen": now_iso,
                "date_posted": current_date,
            }
            new_jobs.append(job)
        else:
            stored_date = known[job_id].get("date_posted")
            if current_date and stored_date and current_date > stored_date:
                log(f"  REPOST detected: '{job['title']}' ({stored_date} → {current_date})")
                known[job_id]["date_posted"] = current_date
                reposted_jobs.append(job)
            elif current_date and not stored_date:
                known[job_id]["date_posted"] = current_date

    already_known = len(jobs) - len(new_jobs) - len(reposted_jobs)
    log(f"  {already_known} already known, {len(new_jobs)} new, {len(reposted_jobs)} reposted")

    if new_jobs:
        for job in new_jobs:
            log(f"  NEW: '{job['title']}' | {job['location']} | posted={job.get('updated_at', 'unknown')}")
            log(f"       {job['apply_url']}")
        if token and chat_id:
            for job in new_jobs:
                try:
                    send_telegram(token, chat_id, format_notification(job, len(jobs)))
                    log(f"  Telegram alert sent: '{job['title']}'")
                except Exception as e:
                    log(f"  Telegram alert FAILED for '{job['title']}': {e}")
        else:
            log("  Telegram creds not set — skipping notifications.")
    else:
        log("  No new roles.")

    if reposted_jobs:
        if token and chat_id:
            for job in reposted_jobs:
                try:
                    send_telegram(token, chat_id, format_repost_notification(job, len(jobs)))
                    log(f"  Repost alert sent: '{job['title']}'")
                except Exception as e:
                    log(f"  Repost alert FAILED for '{job['title']}': {e}")
        else:
            log("  Telegram creds not set — skipping repost notifications.")
    else:
        log("  No reposts detected.")

    return new_jobs


def main():
    run_start = time.time()
    log("=" * 60)
    log("proj-flash starting")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    log(f"Telegram configured: {'yes' if token and chat_id else 'NO — alerts disabled'}")

    known = load_known_jobs()
    log(f"State: {len(known)} job(s) already in known_jobs.json")
    log("=" * 60)

    total_new = 0

    # Anthropic
    log("[Anthropic] Checking PM roles...")
    t0 = time.time()
    try:
        anthropic_jobs = get_anthropic_pm_jobs()
        log(f"[Anthropic] {len(anthropic_jobs)} PM role(s) found ({time.time()-t0:.1f}s)")
        new = process_company(anthropic_jobs, known, token, chat_id)
        total_new += len(new)
    except Exception as e:
        log(f"[Anthropic] ERROR: {e}")
        send_error_alert(token, chat_id, "Anthropic", e)
    log("-" * 60)

    # Google
    log("[Google] Checking PM roles in India (via LinkedIn)...")
    t0 = time.time()
    try:
        google_jobs = get_google_pm_jobs()
        log(f"[Google] {len(google_jobs)} PM role(s) found ({time.time()-t0:.1f}s)")
        new = process_company(google_jobs, known, token, chat_id)
        total_new += len(new)
    except Exception as e:
        log(f"[Google] ERROR: {e}")
        send_error_alert(token, chat_id, "Google", e)
    log("-" * 60)

    save_known_jobs(known)
    log(f"State saved: {len(known)} job(s) in known_jobs.json")
    log(f"Run complete — {total_new} new role(s) found — {time.time()-run_start:.1f}s total")
    log("=" * 60)


if __name__ == "__main__":
    main()
