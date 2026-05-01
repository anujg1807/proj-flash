import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

STATE_FILE = Path(__file__).parent / "known_jobs.json"
IST = timezone(timedelta(hours=5, minutes=30))

# --- Anthropic (Greenhouse) ---
ANTHROPIC_URL = "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs"
ANTHROPIC_PM_TITLE_KEYWORDS = [
    "product manager", "product management", "product lead", "research product"
]
ANTHROPIC_PM_DEPARTMENT = "product management"

# --- Google Careers ---
GOOGLE_URL = (
    "https://careers.google.com/api/v3/search/"
    "?company=Google&jlo=en_US&location=India&q=product+manager&sort_by=date"
)
GOOGLE_PM_KEYWORDS = [
    "product manager", "product management", "product lead",
    "group product manager", "senior product manager"
]


# ── Helpers ───────────────────────────────────────────────────────────────────────────────

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
        return
    msg = (
        f"⚠️ <b>proj-flash error</b>\n\n"
        f"Failed to fetch <b>{company}</b> jobs:\n"
        f"<code>{error}</code>"
    )
    try:
        send_telegram(token, chat_id, msg)
    except Exception as alert_err:
        print(f"  Could not send error alert: {alert_err}")


def format_posted_date(updated_at):
    if updated_at:
        try:
            return datetime.fromisoformat(updated_at).astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")
        except Exception:
            pass
    return datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")


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
    all_jobs = fetch_anthropic_jobs()
    return [normalize_anthropic(j) for j in all_jobs if is_anthropic_pm(j)]


# ── Google ───────────────────────────────────────────────────────────────────────────────

def fetch_google_jobs():
    jobs = []
    url = GOOGLE_URL
    while url:
        data = fetch_json(url)
        jobs.extend(data.get("jobs", []))
        next_page = data.get("next_page_token") or data.get("nextPageToken")
        url = (GOOGLE_URL + f"&page_token={next_page}") if next_page else None
    return jobs


def is_google_pm(job):
    title = job.get("title", "").lower()
    return any(kw in title for kw in GOOGLE_PM_KEYWORDS)


def normalize_google(job):
    locs = job.get("locations") or job.get("location", [])
    if isinstance(locs, list):
        location = ", ".join(locs) if locs else "India"
    else:
        location = locs or "India"
    job_id = job.get("job_id") or job.get("id", "unknown")
    apply_url = job.get("apply_url") or job.get("absolute_url") or "https://careers.google.com"
    return {
        "id": f"google_{job_id}",
        "company": "Google",
        "title": job.get("title"),
        "location": location,
        "apply_url": apply_url,
        "updated_at": job.get("date_added") or job.get("updated_at"),
    }


def get_google_pm_jobs():
    all_jobs = fetch_google_jobs()
    return [normalize_google(j) for j in all_jobs if is_google_pm(j)]


# ── Main ───────────────────────────────────────────────────────────────────────────────

def process_company(jobs, known, token, chat_id):
    new_jobs = [j for j in jobs if j["id"] not in known]
    now_iso = datetime.now(timezone.utc).isoformat()

    for job in new_jobs:
        known[job["id"]] = {
            "title": job["title"],
            "location": job["location"],
            "apply_url": job["apply_url"],
            "first_seen": now_iso,
        }

    if new_jobs:
        print(f"  New roles: {[j['title'] for j in new_jobs]}")
        if token and chat_id:
            for job in new_jobs:
                msg = format_notification(job, len(jobs))
                send_telegram(token, chat_id, msg)
                print(f"  Notification sent: {job['title']}")
        else:
            print("  Telegram creds not set — skipping notification.")
    else:
        print("  No new roles.")

    return new_jobs


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    known = load_known_jobs()

    # Anthropic
    print("Checking Anthropic PM roles...")
    try:
        anthropic_jobs = get_anthropic_pm_jobs()
        print(f"  Found {len(anthropic_jobs)} PM role(s) total.")
        process_company(anthropic_jobs, known, token, chat_id)
    except Exception as e:
        print(f"  ERROR fetching Anthropic jobs: {e}")
        send_error_alert(token, chat_id, "Anthropic", e)

    # Google
    print("Checking Google PM roles in India...")
    try:
        google_jobs = get_google_pm_jobs()
        print(f"  Found {len(google_jobs)} PM role(s) total.")
        process_company(google_jobs, known, token, chat_id)
    except Exception as e:
        print(f"  ERROR fetching Google jobs: {e}")
        send_error_alert(token, chat_id, "Google", e)

    save_known_jobs(known)
    print("Done.")


if __name__ == "__main__":
    main()
