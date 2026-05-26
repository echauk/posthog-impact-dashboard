#!/usr/bin/env python3
"""Fetch commits from PostHog repo for the last 90 days. Adds to engineer-impact-data.json."""

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

REPO = "PostHog/posthog"
DAYS = 90
SINCE = (datetime.now(timezone.utc) - timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
DATA_FILE = "engineer-impact-data.json"


def get_token():
    r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    config = Path.home() / ".config" / "gh" / "hosts.yml"
    if config.exists():
        m = re.search(r"oauth_token:\s*(\S+)", config.read_text())
        if m:
            return m.group(1)
    print("No token"); sys.exit(1)


SESSION = requests.Session()
SESSION.headers.update({"Authorization": f"token {get_token()}", "Accept": "application/vnd.github.v3+json"})


def is_bot(login):
    if not login:
        return True
    l = login.lower()
    return "[bot]" in l or l == "claude" or l.endswith("-bot") or "dependabot" in l


def api_get(path, params=None):
    for _ in range(5):
        r = SESSION.get(f"https://api.github.com{path}", params=params)
        if r.status_code == 403:
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - time.time() + 2, 2)
            print(f"  Rate limited, sleeping {wait:.0f}s")
            time.sleep(wait)
            continue
        if r.status_code in (404, 410):
            return []
        r.raise_for_status()
        return r.json()
    return []


def fetch_commits():
    print(f"Fetching commits since {SINCE}...")
    page = 1
    commits = []
    while True:
        batch = api_get(f"/repos/{REPO}/commits", {"since": SINCE, "per_page": 100, "page": page})
        if not batch:
            break
        commits.extend(batch)
        print(f"  Page {page}: {len(batch)} commits ({len(commits)} total)")
        if len(batch) < 100:
            break
        page += 1
    return commits


def main():
    print(f"Loading {DATA_FILE}...")
    with open(DATA_FILE) as f:
        data = json.load(f)

    raw = fetch_commits()
    commits = [
        {
            "sha": c["sha"],
            "author_login": (c.get("author") or {}).get("login", ""),
            "date": ((c.get("commit") or {}).get("author") or {}).get("date", ""),
            "message": ((c.get("commit") or {}).get("message") or "").split("\n")[0],
        }
        for c in raw
        if not is_bot((c.get("author") or {}).get("login"))
    ]
    print(f"\n→ {len(commits)} commits by humans (filtered from {len(raw)} total)")

    data["commits"] = commits
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

    # Final summary
    authors = {p["author"] for p in data["prs"].values() if p["author"]}
    commit_authors = {c["author_login"] for c in commits if c["author_login"]}
    reviewers = {r["reviewer"] for p in data["prs"].values() for r in p.get("reviews", []) if r.get("reviewer")}

    print(f"\n✓ Final data summary:")
    print(f"  PRs:               {len(data['prs'])}")
    print(f"  Commits:           {len(commits)}")
    print(f"  PR authors:        {len(authors)}")
    print(f"  Commit authors:    {len(commit_authors)}")
    print(f"  Active reviewers:  {len(reviewers)}")
    print(f"  All engineers:     {len(authors | reviewers | commit_authors)}")


if __name__ == "__main__":
    main()
