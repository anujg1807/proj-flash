# Anthropic PM Job Monitor

## Project goal
Monitor Anthropic's Greenhouse job board for new Product Management roles.
Send an instant Telegram notification the moment a new PM role is posted.
Runs on GitHub Actions (hourly cron), entirely free, no dashboard needed.

## Stack
- Data source: Greenhouse public API (no auth) — boards-api.greenhouse.io/v1/boards/anthropic/jobs
- Scheduler: GitHub Actions cron (every 1 hour)
- State: known_jobs.json committed to this repo (tracks seen job IDs + first_seen date)
- Notification: Telegram Bot API

## Files to build
1. scraper.py — fetch Greenhouse API, filter PM roles, detect new ones vs known_jobs.json
2. known_jobs.json — persisted state (job id, title, location, apply_url, first_seen)
3. .github/workflows/monitor.yml — hourly cron, runs scraper, commits state changes, sends Telegram alert

## PM role filter logic
A role matches if title contains any of:
"product manager", "product management", "product lead", "research product"
Team/department: "product management"

## Telegram notification format
🚨 New Anthropic PM Role\n\n{title}\n📍 {location}\n🕐 Posted: {datetime} IST\n\nApply → {url}\n\nTotal PM roles open: {count}

## GitHub Actions secrets needed
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

## Context
Owner is a Senior PM based in Bengaluru, India (IST timezone). 
Actively job hunting. Wants to be among first applicants for any new Anthropic PM role.