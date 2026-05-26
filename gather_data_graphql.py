#!/usr/bin/env python3
"""
Gather per-PR details from GitHub GraphQL API.
Reuses PR metadata from existing engineer-impact-data.json file.
Fetches reviews, files (aggregated to directories), and inline review comments
in batched GraphQL queries (10 PRs per request) for efficiency.
"""

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

INPUT_FILE = "engineer-impact-data.json"
OUTPUT_FILE = "engineer-impact-data.json"
BATCH_SIZE = 10  # PRs per GraphQL request


def get_token():
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    config_path = Path.home() / ".config" / "gh" / "hosts.yml"
    if config_path.exists():
        text = config_path.read_text()
        m = re.search(r"oauth_token:\s*(\S+)", text)
        if m:
            return m.group(1)
    print("Error: could not get GitHub token")
    sys.exit(1)


TOKEN = get_token()
SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"bearer {TOKEN}",
    "Content-Type": "application/json",
})


def top_dir(path, depth=2):
    parts = path.replace("\\", "/").split("/")
    return "/".join(parts[:depth]) if len(parts) > depth else parts[0]


def build_pr_query(pr_numbers):
    fragments = []
    for n in pr_numbers:
        fragments.append(f"""
    pr{n}: pullRequest(number: {n}) {{
      number
      additions
      deletions
      changedFiles
      reviews(first: 50) {{
        nodes {{
          author {{ login }}
          state
          submittedAt
          bodyText
        }}
      }}
      files(first: 100) {{
        totalCount
        nodes {{ path additions deletions }}
      }}
      reviewThreads(first: 50) {{
        nodes {{
          comments(first: 5) {{
            nodes {{
              author {{ login }}
              bodyText
              createdAt
            }}
          }}
        }}
      }}
    }}
""")
    return f"""
query {{
  repository(owner: "PostHog", name: "posthog") {{
{''.join(fragments)}
  }}
  rateLimit {{ remaining cost resetAt }}
}}
"""


def gql_request(query, retries=5):
    for attempt in range(retries):
        resp = SESSION.post("https://api.github.com/graphql", json={"query": query}, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            if "errors" in data:
                # Partial data might still be present; log and return what we got
                err_msgs = [e.get("message", "") for e in data.get("errors", [])]
                # Rate-limit related errors
                if any("rate limit" in m.lower() or "secondary rate" in m.lower() for m in err_msgs):
                    print(f"  Rate limit error: {err_msgs[0][:100]}; sleeping 60s...")
                    time.sleep(60)
                    continue
                # Not-found PRs in batch are OK (we just skip them)
                non_critical = all("Could not resolve" in m or "NOT_FOUND" in m for m in err_msgs)
                if not non_critical:
                    print(f"  GraphQL errors (continuing): {err_msgs[0][:200]}")
            return data
        elif resp.status_code in (502, 503, 504):
            wait = 2 ** attempt
            print(f"  HTTP {resp.status_code}, retry in {wait}s")
            time.sleep(wait)
        else:
            print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
            time.sleep(5)
    return None


def is_bot(login):
    if not login:
        return True
    l = login.lower()
    return "[bot]" in l or l == "claude" or l.endswith("-bot") or "dependabot" in l


def parse_pr_details(pr_data):
    """Extract reviews, directory aggregation, and review comments from GraphQL response."""
    if not pr_data:
        return None

    # Reviews — store body length only
    reviews = []
    for r in (pr_data.get("reviews") or {}).get("nodes", []) or []:
        author = (r.get("author") or {}).get("login", "")
        if is_bot(author):
            continue
        reviews.append({
            "reviewer": author,
            "state": r.get("state", ""),
            "submitted_at": r.get("submittedAt", ""),
            "body_length": len(r.get("bodyText") or ""),
        })

    # Files — aggregate to top-2 directory level
    dir_counts = {}
    total_add = 0
    total_del = 0
    files_node = (pr_data.get("files") or {})
    for f in files_node.get("nodes", []) or []:
        path = f.get("path", "unknown")
        d = top_dir(path)
        dir_counts[d] = dir_counts.get(d, 0) + 1
        total_add += f.get("additions", 0) or 0
        total_del += f.get("deletions", 0) or 0

    # Inline review comments — flattened from reviewThreads
    review_comments = []
    for thread in (pr_data.get("reviewThreads") or {}).get("nodes", []) or []:
        for c in (thread.get("comments") or {}).get("nodes", []) or []:
            author = (c.get("author") or {}).get("login", "")
            if is_bot(author):
                continue
            review_comments.append({
                "reviewer": author,
                "body_length": len(c.get("bodyText") or ""),
                "created_at": c.get("createdAt", ""),
            })

    # PR-level totals, prefer GraphQL's authoritative additions/deletions/changedFiles
    return {
        "reviews": reviews,
        "directories": dir_counts,
        "total_additions": pr_data.get("additions") or total_add,
        "total_deletions": pr_data.get("deletions") or total_del,
        "changed_files": pr_data.get("changedFiles") or len(files_node.get("nodes") or []),
        "review_comments": review_comments,
    }


def save(data, path=OUTPUT_FILE):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    Path(tmp).rename(path)


def main():
    # Load existing PR metadata
    print(f"Loading existing data from {INPUT_FILE}...")
    with open(INPUT_FILE) as f:
        data = json.load(f)

    prs = data["prs"]
    print(f"  Loaded {len(prs)} PRs")

    # Identify PRs missing details (no reviews/directories filled)
    # In the new schema, presence of 'directories' indicates detail fetched
    pr_numbers_to_fetch = []
    for k, pr in prs.items():
        # Reset to new schema fields if not present
        has_details = pr.get("directories") and isinstance(pr["directories"], dict) and len(pr["directories"]) > 0
        has_details = has_details or pr.get("total_additions", 0) > 0
        if not has_details:
            pr_numbers_to_fetch.append(int(k))

        # Ensure new schema fields exist
        pr.setdefault("directories", {})
        pr.setdefault("total_additions", 0)
        pr.setdefault("total_deletions", 0)
        pr.setdefault("changed_files", 0)
        pr.setdefault("reviews", [])
        pr.setdefault("review_comments", [])
        # Drop old "files" key if present
        pr.pop("files", None)

    print(f"  Need to fetch details for {len(pr_numbers_to_fetch)} PRs")

    if not pr_numbers_to_fetch:
        print("Nothing to do!")
        return

    # Fetch in batches
    start = time.time()
    processed = 0
    save_every = 100  # save every N PRs

    for i in range(0, len(pr_numbers_to_fetch), BATCH_SIZE):
        batch = pr_numbers_to_fetch[i:i + BATCH_SIZE]
        query = build_pr_query(batch)
        result = gql_request(query)

        if result is None or "data" not in result:
            print(f"  Failed batch starting at {i}, skipping")
            continue

        repo_data = (result.get("data") or {}).get("repository") or {}
        rate_limit = (result.get("data") or {}).get("rateLimit") or {}

        for n in batch:
            pr_data = repo_data.get(f"pr{n}")
            if pr_data is None:
                continue
            parsed = parse_pr_details(pr_data)
            if parsed:
                k = str(n) if str(n) in prs else n
                if k in prs:
                    prs[k].update(parsed)
                    processed += 1

        # Progress
        if (i // BATCH_SIZE) % 10 == 0 or i + BATCH_SIZE >= len(pr_numbers_to_fetch):
            elapsed = time.time() - start
            rate = processed / elapsed if elapsed > 0 else 0
            remaining = (len(pr_numbers_to_fetch) - processed) / rate if rate > 0 else 0
            print(f"  {processed}/{len(pr_numbers_to_fetch)} PRs — "
                  f"rate={rate:.1f}/s, ETA={remaining:.0f}s, "
                  f"GraphQL quota={rate_limit.get('remaining', '?')}/5000")

        # Incremental save
        if processed > 0 and processed % save_every == 0:
            save(data)

        # Stop if rate limit getting low
        if isinstance(rate_limit.get("remaining"), int) and rate_limit["remaining"] < 50:
            reset_at = rate_limit.get("resetAt", "")
            print(f"  Quota low ({rate_limit['remaining']}), reset at {reset_at}. Stopping.")
            break

    # Final save
    save(data)
    print(f"\n✓ Done! Updated {OUTPUT_FILE} with {processed} PR details.")


if __name__ == "__main__":
    main()
