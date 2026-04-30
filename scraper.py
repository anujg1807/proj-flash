import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs"
STATE_FILE = Path(__file__).parent / "known_jobs.json"
IST = timezone(timedelta(hours=5, minutes=30))

PM_TITLE_KEYWORDS = [
    "product manager",
    "product management",
    "product lead",
    "research product",
]
PM_DEPARTMENT = "product management"


def fetch_jobs():
    req = urllib.request.Request(GREENHOUSE_URL, headers={"User-Agent": "pm-monitor/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return data.get("jobs", [])


def is_pm_role(job):
    title = job.get("title", "").lower()
    if any(kw in title for kw in PM_TITLE_KEYWORDS):
        return True
    for dept in job.get("departments", []):
        if PM_DEPARTMENT in dept.get("name", "").lower():
            return True
    return False


def load_known_jobs():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_known_jobs(known):
    STATE_FILE.write_text(json.dumps(known, indent=2, ensure_ascii=False))


def build_location(job):
    offices = job.get("offices", [])
    if offices:
        return ", ".join(o.get("name", "") for o in offices if o.get("name"))
    return "Remote / Not specified"


def send_telegram(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def format_notification(job, total_pm_count):
    updated_at = job.get("updated_at")
    if updated_at:
        posted_ist = datetime.fromisoformat(updated_at).astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")
    else:
        posted_ist = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    title = job["title"]
    location = build_location(job)
    apply_url = job.get("absolute_url", "https://boards.greenhouse.io/anthropic")
    return (
        f"🚨 New Anthropic PM Role\n\n"
        f"{title}\n"
        f"📍 {location}\n"
        f"🕐 Posted: {posted_ist}\n\n"
        f"Apply → {apply_url}\n\n"
        f"Total PM roles open: {total_pm_count}"
    )


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    print("Fetching jobs from Greenhouse...")
    all_jobs = fetch_jobs()
    pm_jobs = [j for j in all_jobs if is_pm_role(j)]
    print(f"Found {len(pm_jobs)} PM role(s) total.")

    known = load_known_jobs()
    new_jobs = [j for j in pm_jobs if str(j["id"]) not in known]

    now_iso = datetime.now(timezone.utc).isoformat()
    for job in new_jobs:
        known[str(job["id"])] = {
            "title": job.get("title"),
            "location": build_location(job),
            "apply_url": job.get("absolute_url"),
            "first_seen": now_iso,
        }

    if new_jobs:
        print(f"New PM role(s) detected: {[j['title'] for j in new_jobs]}")
        save_known_jobs(known)

        if token and chat_id:
            for job in new_jobs:
                msg = format_notification(job, len(pm_jobs))
                send_telegram(token, chat_id, msg)
                print(f"Notification sent for: {job['title']}")
        else:
            print("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping notification.")
    else:
        print("No new PM roles found.")
        # Still save to keep known_jobs.json in sync if roles were removed
        save_known_jobs(known)


if __name__ == "__main__":
    main()
