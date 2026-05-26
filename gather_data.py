#!/usr/bin/env python3
"""
Gather PostHog engineering impact data from GitHub API.
Collects last 90 days of PRs, commits, reviews, and files for impact analysis.
"""

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

REPO = "PostHog/posthog"
DAYS = 90
SINCE = (datetime.now(timezone.utc) - timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
OUTPUT_FILE = "engineer-impact-data.json"
MAX_WORKERS = 6

print(f"Collecting data since {SINCE}")


def get_token():
    # gh auth token was added in gh v2.37+; fall back to reading config directly
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()

    # Older gh: read oauth_token from ~/.config/gh/hosts.yml
    import re
    from pathlib import Path
    config_path = Path.home() / ".config" / "gh" / "hosts.yml"
    if config_path.exists():
        text = config_path.read_text()
        match = re.search(r"oauth_token:\s*(\S+)", text)
        if match:
            return match.group(1)

    print("Error: could not retrieve GitHub token. Run: gh auth login")
    sys.exit(1)


TOKEN = get_token()
SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
})


def api_get(path, params=None):
    url = f"https://api.github.com{path}"
    for _ in range(5):
        resp = SESSION.get(url, params=params)
        if resp.status_code == 403:
            reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            sleep = max(reset - time.time() + 2, 2)
            print(f"  Rate limited — sleeping {sleep:.0f}s")
            time.sleep(sleep)
            continue
        if resp.status_code in (404, 410, 422):
            return []
        resp.raise_for_status()
        return resp.json()
    return []


def paginate(path, params=None, stop_fn=None):
    params = dict(params or {})
    params["per_page"] = 100
    params["page"] = 1
    items = []
    while True:
        batch = api_get(path, params)
        if not batch:
            break
        done = False
        for item in batch:
            if stop_fn and stop_fn(item):
                done = True
                break
            items.append(item)
        if done or len(batch) < 100:
            break
        params["page"] += 1
    return items


def is_bot(login):
    if not login:
        return True
    l = login.lower()
    return "[bot]" in l or l == "claude" or l.endswith("-bot") or "dependabot" in l


def fetch_merged_prs():
    print(f"Fetching merged PRs since {SINCE}...")
    # Stop paginating when PRs were last updated before our window (+ 7-day buffer)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DAYS + 7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    raw = paginate(
        f"/repos/{REPO}/pulls",
        {"state": "closed", "sort": "updated", "direction": "desc"},
        stop_fn=lambda pr: pr.get("updated_at", "") < cutoff,
    )

    merged = [
        pr for pr in raw
        if pr.get("merged_at")
        and pr["merged_at"] >= SINCE
        and not is_bot((pr.get("user") or {}).get("login"))
    ]
    print(f"  → {len(merged)} merged PRs by humans in window")
    return merged


def top_dir(filename, depth=2):
    """Return the top-N directory components of a file path."""
    parts = filename.replace("\\", "/").split("/")
    return "/".join(parts[:depth]) if len(parts) > depth else parts[0]


def fetch_pr_details(pr_number):
    # Paginate reviews and files — large PRs can exceed 30-item default page
    reviews_raw = paginate(f"/repos/{REPO}/pulls/{pr_number}/reviews")
    files_raw = paginate(f"/repos/{REPO}/pulls/{pr_number}/files")
    comments_raw = paginate(f"/repos/{REPO}/pulls/{pr_number}/comments")

    reviews = [
        {
            "reviewer": (r.get("user") or {}).get("login", ""),
            "state": r.get("state", ""),
            "submitted_at": r.get("submitted_at", ""),
            "body_length": len(r.get("body") or ""),
        }
        for r in reviews_raw
        if not is_bot((r.get("user") or {}).get("login"))
    ]

    # Aggregate files to directory level instead of storing every file path
    dir_counts = {}
    total_additions = 0
    total_deletions = 0
    for f in files_raw:
        d = top_dir(f.get("filename", "unknown"))
        dir_counts[d] = dir_counts.get(d, 0) + 1
        total_additions += f.get("additions", 0)
        total_deletions += f.get("deletions", 0)

    review_comments = [
        {
            "reviewer": (c.get("user") or {}).get("login", ""),
            "body_length": len(c.get("body") or ""),
            "created_at": c.get("created_at", ""),
        }
        for c in comments_raw
        if not is_bot((c.get("user") or {}).get("login"))
    ]

    return pr_number, reviews, dir_counts, total_additions, total_deletions, review_comments


def fetch_commits():
    print(f"\nFetching commits since {SINCE}...")
    raw = paginate(f"/repos/{REPO}/commits", {"since": SINCE})
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
    print(f"  → {len(commits)} commits by humans")
    return commits


def save(data):
    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def main():
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": SINCE,
        "repo": REPO,
        "days": DAYS,
    }

    # --- Fetch PR list ---
    prs_raw = fetch_merged_prs()

    prs = {}
    for pr in prs_raw:
        n = pr["number"]
        author = (pr.get("user") or {}).get("login", "")
        prs[n] = {
            "number": n,
            "title": pr.get("title", ""),
            "author": author,
            "labels": [l["name"] for l in (pr.get("labels") or [])],
            "created_at": pr.get("created_at", ""),
            "merged_at": pr.get("merged_at", ""),
            # Cap body at 5KB — enough for template sections, avoids giant file
            "body": (pr.get("body") or "")[:5000],
            "requested_reviewers": [
                r.get("login", "") for r in (pr.get("requested_reviewers") or [])
                if not is_bot(r.get("login", ""))
            ],
            "reviews": [],
            "directories": {},
            "total_additions": 0,
            "total_deletions": 0,
            "review_comments": [],
        }

    # --- Fetch per-PR details in parallel ---
    pr_numbers = list(prs.keys())
    print(f"\nFetching per-PR details (reviews, files, comments) for {len(pr_numbers)} PRs...")
    print(f"  Using {MAX_WORKERS} parallel workers — this may take several minutes...")

    done_count = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_pr_details, n): n for n in pr_numbers}
        for future in as_completed(futures):
            pr_num, reviews, dir_counts, total_additions, total_deletions, review_comments = future.result()
            if pr_num in prs:
                prs[pr_num]["reviews"] = reviews
                prs[pr_num]["directories"] = dir_counts
                prs[pr_num]["total_additions"] = total_additions
                prs[pr_num]["total_deletions"] = total_deletions
                prs[pr_num]["review_comments"] = review_comments
            done_count += 1
            if done_count % 100 == 0:
                elapsed = time.time() - start
                rate = done_count / elapsed
                remaining = (len(pr_numbers) - done_count) / rate
                print(f"  {done_count}/{len(pr_numbers)} PRs — {remaining:.0f}s remaining")
                save({"metadata": metadata, "prs": prs, "commits": []})

    # --- Fetch commits ---
    commits = fetch_commits()

    # --- Final save ---
    output = {"metadata": metadata, "prs": prs, "commits": commits}
    save(output)

    # --- Summary ---
    authors = {prs[n]["author"] for n in prs if prs[n]["author"]}
    reviewers = {
        r["reviewer"]
        for pr in prs.values()
        for r in pr["reviews"]
        if r["reviewer"]
    }
    revert_prs = [n for n in prs if prs[n]["title"].lower().startswith("revert")]

    print(f"\n✓ Done! Saved to {OUTPUT_FILE}")
    print(f"  PRs collected:      {len(prs)}")
    print(f"  Commits collected:  {len(commits)}")
    print(f"  PR authors:         {len(authors)}")
    print(f"  Active reviewers:   {len(reviewers)}")
    print(f"  All engineers:      {len(authors | reviewers)}")
    print(f"  Revert PRs found:   {len(revert_prs)}")


if __name__ == "__main__":
    main()
