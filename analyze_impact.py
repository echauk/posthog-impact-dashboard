#!/usr/bin/env python3
"""
Analyze engineer impact across 6 signals defined in impact-signals.md.

For each active engineer, compute raw metrics per signal, normalize to
percentile rank, and produce a composite impact score (0-100).
Output: engineer-impact-analysis.json + console summary of top engineers.
"""

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_FILE = "engineer-impact-data.json"
OUTPUT_FILE = "engineer-impact-analysis.json"

# Minimum activity to be considered for ranking
MIN_PRS = 10        # authored at least 10 PRs in 90 days
MIN_REVIEWS = 30    # OR reviewed 30+ PRs (catches pure reviewers/architects)

# Known bot/automation accounts that don't match standard bot patterns.
# These are AI reviewers, tool integrations, or org service accounts.
BOT_ACCOUNTS = {
    "greptile-apps", "graphite-app", "github-actions",
    "github-advanced-security", "copilot-pull-request-reviewer",
    "chatgpt-codex-connector", "stamphog", "posthog",
    "renovate", "snyk-bot", "pre-commit-ci", "imgbot",
    "cursor", "devin-ai-integration", "codecov", "vercel",
    "sentry-io", "linear", "sweep-ai", "claude",
}


def is_known_bot(login):
    """Check against extended bot list (in addition to substring patterns)."""
    if not login:
        return True
    l = login.lower()
    if l in BOT_ACCOUNTS:
        return True
    if "[bot]" in l or l.endswith("-bot") or "dependabot" in l:
        return True
    # AI assistant patterns
    if "copilot" in l or "greptile" in l or "graphite" in l:
        return True
    return False

# Critical directory tiers — used as criticality weighting in Signal 3
TIER_HIGH = {
    "posthog/api", "posthog/models", "posthog/clickhouse",
    "posthog/temporal", "posthog/hogql", "posthog/queries",
    "posthog/warehouse", "posthog/cdp", "posthog/session_recordings",
    "frontend/src", "rust", "ee", "products", "plugin-server",
    "livestream", "hogvm",
}
TIER_LOW = {
    "docs", ".github", "scripts", "bin", "cypress", "playwright",
    "common", "share",
}

# PostHog standard PR template section headers
TEMPLATE_SECTIONS = ["problem", "changes", "test", "changelog"]


def parse_dt(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def get_dir_tier(directory):
    """Return weight for a directory based on criticality tier."""
    top = directory.split("/")[0] if "/" in directory else directory
    full = directory
    if any(directory.startswith(d) for d in TIER_HIGH) or any(top == d.split("/")[0] for d in TIER_HIGH):
        return 1.5
    if top in TIER_LOW or any(directory.startswith(d) for d in TIER_LOW):
        return 0.5
    return 1.0


def get_domain(directory):
    """Map a directory to a coherent 'domain' label used for ownership-depth aggregation.

    Domain depth = % of work in the engineer's primary domain. Two dirs that
    belong to the same domain area should aggregate together (e.g. frontend/src
    and frontend/__snapshots__ are both "frontend"). Within posthog/* and
    products/*, sub-areas like posthog/api or products/llm_analytics are
    semantically distinct so we keep them separate.
    """
    if not directory:
        return "unknown"
    if directory.startswith("frontend"):
        return "frontend"
    if directory.startswith("rust") or directory == "rust":
        return "Rust"
    if directory.startswith("services/mcp"):
        return "MCP"
    if directory.startswith("ee/hogai"):
        return "AI / HogAI"
    if directory.startswith("services/llm"):
        return "LLM services"
    if directory.startswith("products/llm_analytics"):
        return "LLM analytics"
    if directory.startswith("products/product_analytics"):
        return "product analytics"
    if directory.startswith("products/session_recordings"):
        return "session recordings"
    if directory.startswith("products/replay"):
        return "session replay"
    if directory.startswith("products/"):
        # individual product line: take name after products/
        return directory.split("/")[1].replace("_", " ") if "/" in directory else "products"
    if directory.startswith("posthog/api"):
        return "PostHog API"
    if directory.startswith("posthog/temporal"):
        return "Temporal workflows"
    if directory.startswith("posthog/hogql"):
        return "HogQL"
    if directory.startswith("posthog/models"):
        return "data models"
    if directory.startswith("posthog/clickhouse"):
        return "ClickHouse layer"
    if directory.startswith("posthog/"):
        return "PostHog core"
    if directory.startswith("ee/"):
        return "enterprise features"
    if directory.startswith("services/"):
        return directory.split("/")[1] if "/" in directory else "services"
    if directory == "plugin-server":
        return "plugin server"
    if directory == "livestream":
        return "livestream"
    if directory == "hogvm":
        return "HogVM"
    return directory.split("/")[0] if "/" in directory else directory


def get_label_category(label):
    l = label.lower()
    if "feat" in l:
        return "feat"
    if "fix" in l or "bug" in l:
        return "fix"
    if "refactor" in l:
        return "refactor"
    if "chore" in l:
        return "chore"
    if "perf" in l:
        return "perf"
    if "docs" in l:
        return "docs"
    if "ci" in l:
        return "ci"
    return None


def get_title_category(title):
    """Parse conventional-commit-style title prefix."""
    m = re.match(r"^(\w+)(\([^)]*\))?!?:\s", title.strip())
    if m:
        prefix = m.group(1).lower()
        if prefix in ("feat", "feature"):
            return "feat"
        if prefix in ("fix", "bug"):
            return "fix"
        if prefix in ("refactor", "perf", "chore", "docs", "ci", "test", "style", "build"):
            return prefix
    return None


# ────────────────────────────────────────────────────────────────────────
# Signal computations
# ────────────────────────────────────────────────────────────────────────
def compute_signal_1_consistency(engineer, prs, commits, days=90):
    """Shipping consistency: cadence, regularity, cycle time, review rounds."""
    eng_prs = [p for p in prs.values() if p["author"] == engineer and p["merged_at"]]
    eng_commits = [c for c in commits if c["author_login"] == engineer]

    weeks = days / 7
    pr_per_week = len(eng_prs) / weeks
    commits_per_week = len(eng_commits) / weeks

    # Consistency = coefficient of variation of weekly commit counts (lower = more consistent)
    if eng_commits:
        week_buckets = defaultdict(int)
        for c in eng_commits:
            d = parse_dt(c["date"])
            if d:
                wk = d.isocalendar()[1]
                week_buckets[wk] += 1
        # Fill missing weeks with 0 to compute std properly across the window
        if len(week_buckets) > 1:
            counts = list(week_buckets.values())
            cv = statistics.stdev(counts) / (statistics.mean(counts) + 0.01)
        else:
            cv = 0
    else:
        cv = 0

    # Cycle time (median, hours)
    cycle_hours = []
    for p in eng_prs:
        c = parse_dt(p["created_at"])
        m = parse_dt(p["merged_at"])
        if c and m:
            cycle_hours.append((m - c).total_seconds() / 3600)
    median_cycle = statistics.median(cycle_hours) if cycle_hours else 0

    # Review round trips = mean reviews per PR (proxy: more reviews = more rounds)
    reviews_per_pr = []
    for p in eng_prs:
        reviews_per_pr.append(len(p.get("reviews", [])))
    mean_review_rounds = statistics.mean(reviews_per_pr) if reviews_per_pr else 0

    return {
        "pr_count": len(eng_prs),
        "commit_count": len(eng_commits),
        "pr_per_week": pr_per_week,
        "commits_per_week": commits_per_week,
        "consistency_cv": cv,  # lower is better
        "median_cycle_hours": median_cycle,  # lower is better
        "mean_review_rounds": mean_review_rounds,  # lower is better (fewer iterations needed)
    }


def compute_signal_2_work_type(engineer, prs):
    """Work type distribution from labels + title prefixes."""
    eng_prs = [p for p in prs.values() if p["author"] == engineer and p["merged_at"]]
    categories = Counter()

    for p in eng_prs:
        cat = None
        # Try labels first
        for lbl in p.get("labels", []):
            c = get_label_category(lbl)
            if c:
                cat = c
                break
        # Fall back to title prefix
        if not cat:
            cat = get_title_category(p.get("title", ""))
        if not cat:
            cat = "other"
        categories[cat] += 1

    total = sum(categories.values())
    if total == 0:
        return {"total": 0, "distribution": {}, "feat_fix_ratio": 0}

    distribution = {k: v / total for k, v in categories.items()}
    feat_fix_ratio = distribution.get("feat", 0) + distribution.get("fix", 0)

    return {
        "total": total,
        "distribution": distribution,
        "category_counts": dict(categories),
        "feat_fix_ratio": feat_fix_ratio,
    }


def compute_signal_3_ownership(engineer, prs):
    """Ownership profile: depth, breadth, criticality."""
    eng_prs = [p for p in prs.values() if p["author"] == engineer and p["merged_at"]]

    dir_counts = Counter()
    domain_counts = Counter()
    critical_files = 0  # files in HIGH-tier directories
    total_files = 0

    for p in eng_prs:
        for d, count in p.get("directories", {}).items():
            dir_counts[d] += count
            domain_counts[get_domain(d)] += count
            if get_dir_tier(d) == 1.5:
                critical_files += count
            total_files += count

    if total_files == 0:
        return {
            "top_dirs": [], "depth_score": 0, "breadth_score": 0,
            "critical_files_pct": 0, "total_files_touched": 0,
            "primary_domain": "", "top_domains": [],
        }

    top_dirs = dir_counts.most_common(5)
    top_domains = domain_counts.most_common(5)
    primary_domain, primary_count = top_domains[0]

    # Domain-based depth — used for human-readable DISPLAY.
    primary_domain_share = primary_count / total_files

    # Concentration in top 2 directories — used for SCORING (preserves stable ranking).
    # Both are reasonable depth measures; the dashboard shows the domain-based one
    # because it answers the more intuitive question ("how concentrated in one area?")
    # but for percentile ranking we keep the original top-2-dirs share to avoid
    # rankings shifting whenever the dir→domain mapping evolves.
    top2_share = sum(c for _, c in dir_counts.most_common(2)) / total_files

    # Breadth: distinct top-level dirs touched (filter trivial)
    top_levels = Counter()
    for d in dir_counts:
        tl = d.split("/")[0] if "/" in d else d
        if tl not in TIER_LOW:
            top_levels[tl] += dir_counts[d]
    breadth = len([tl for tl, c in top_levels.items() if c >= 3])  # at least 3 files in that area

    # Critical-area focus: % of files touched that are in HIGH-tier directories
    critical_files_pct = (critical_files / total_files) * 100  # 0..100

    return {
        "top_dirs": top_dirs,
        "top_domains": top_domains,
        "primary_domain": primary_domain,
        "primary_domain_share": primary_domain_share,  # for display
        "depth_score": top2_share,  # 0..1, used for scoring (stable across mapping changes)
        "breadth_score": breadth,  # integer count
        "critical_files_pct": critical_files_pct,  # 0..100
        "total_files_touched": total_files,
    }


def compute_signal_4_review(engineer, prs):
    """Review impact: volume, complexity reviewed, comment depth, response time."""
    reviews = []
    inline_comments = []
    requested_count = 0

    for pr in prs.values():
        # Was this engineer requested as a reviewer?
        if engineer in pr.get("requested_reviewers", []):
            requested_count += 1
        # Reviews submitted
        for r in pr.get("reviews", []):
            if r.get("reviewer") == engineer:
                reviews.append({
                    "pr_id": pr["number"],
                    "complexity_lines": pr.get("total_additions", 0) + pr.get("total_deletions", 0),
                    "complexity_files": pr.get("changed_files", 0),
                    "state": r.get("state", ""),
                    "body_length": r.get("body_length", 0),
                    "submitted_at": r.get("submitted_at"),
                    "pr_created_at": pr.get("created_at"),
                })
        # Inline review comments
        for c in pr.get("review_comments", []):
            if c.get("reviewer") == engineer:
                inline_comments.append(c.get("body_length", 0))

    if not reviews:
        return {
            "review_volume": 0, "review_pr_count": 0, "avg_complexity_lines": 0,
            "avg_complexity_files": 0, "avg_comment_depth_chars": 0,
            "median_time_to_first_review_hours": 0, "requested_reviewer_count": requested_count,
        }

    review_pr_count = len(set(r["pr_id"] for r in reviews))
    avg_complexity_lines = statistics.mean(r["complexity_lines"] for r in reviews)
    avg_complexity_files = statistics.mean(r["complexity_files"] for r in reviews)

    # Comment depth: combined chars from review bodies + inline comments per review event
    total_chars = sum(r["body_length"] for r in reviews) + sum(inline_comments)
    avg_depth = total_chars / len(reviews) if reviews else 0

    # Median time to first review per PR they reviewed
    first_review_times = defaultdict(list)
    for r in reviews:
        pr_open = parse_dt(r["pr_created_at"])
        rev_at = parse_dt(r["submitted_at"])
        if pr_open and rev_at:
            first_review_times[r["pr_id"]].append((rev_at - pr_open).total_seconds() / 3600)
    earliest_per_pr = [min(times) for times in first_review_times.values() if times]
    median_first_review = statistics.median(earliest_per_pr) if earliest_per_pr else 0

    return {
        "review_volume": len(reviews),  # total review events
        "review_pr_count": review_pr_count,  # distinct PRs
        "avg_complexity_lines": avg_complexity_lines,
        "avg_complexity_files": avg_complexity_files,
        "avg_comment_depth_chars": avg_depth,
        "median_time_to_first_review_hours": median_first_review,  # lower is better
        "requested_reviewer_count": requested_count,
        "inline_comment_count": len(inline_comments),
    }


def compute_signal_5_reliability(engineer, prs):
    """Revert rate: how often the engineer's PRs got reverted."""
    eng_pr_titles = {}
    eng_pr_count = 0
    for p in prs.values():
        if p["author"] == engineer and p["merged_at"]:
            eng_pr_count += 1
            t = p.get("title", "").strip()
            if t:
                eng_pr_titles[t] = p["number"]

    revert_count = 0
    reverted_prs = []
    for p in prs.values():
        title = p.get("title", "").strip()
        if not title:
            continue
        # Many PostHog revert titles: `revert: "<original>"` or `Revert "<original>"`
        # Also: `Revert "<original>" (#NNNNN)` or `revert "..." (#NNNNN)`
        # Try several patterns
        original_title = None
        patterns = [
            r'^revert\s*[:\-]?\s*["“](.+?)["”]',  # revert: "..." or revert "..."
            r'^revert\s+(.+?)\s*\(#\d+\)\s*$',     # revert <title> (#NNN)
        ]
        for pat in patterns:
            m = re.match(pat, title, re.IGNORECASE)
            if m:
                original_title = m.group(1).strip()
                break
        if not original_title:
            continue

        # Strip trailing PR ref " (#NNNN)" if present in the captured title
        original_title_clean = re.sub(r"\s*\(#\d+\)\s*$", "", original_title).strip()
        for cand in (original_title, original_title_clean):
            if cand in eng_pr_titles:
                revert_count += 1
                reverted_prs.append({"reverted_by": p["number"], "original_pr": eng_pr_titles[cand]})
                break

    revert_rate = revert_count / eng_pr_count if eng_pr_count > 0 else 0

    return {
        "revert_count": revert_count,
        "total_prs": eng_pr_count,
        "revert_rate": revert_rate,  # lower is better
        "reverted_prs": reverted_prs[:5],
    }


def compute_signal_6_communication(engineer, prs):
    """PR description quality: section completeness, depth."""
    eng_prs = [p for p in prs.values() if p["author"] == engineer and p["merged_at"]]
    if not eng_prs:
        return {
            "avg_body_length": 0, "avg_section_completeness": 0,
            "testing_section_filled_ratio": 0,
        }

    # Header patterns for the PostHog PR template (case-insensitive).
    # Each pattern captures the section's content greedily until the next ## header.
    SECTION_PATTERNS = {
        "problem": r"##\s+(?:problem|why)[^\n]*\n(.*?)(?=\n##\s|\Z)",
        "changes": r"##\s+(?:changes|what|description)[^\n]*\n(.*?)(?=\n##\s|\Z)",
        "testing": r"##\s+(?:how (?:did|do) you test|testing|qa)[^\n]*\n(.*?)(?=\n##\s|\Z)",
    }

    body_lengths = []
    completeness_scores = []
    testing_filled = 0

    for p in eng_prs:
        body = p.get("body", "") or ""
        body_lengths.append(len(body))

        # Strip HTML comments (template scaffolding like <!-- explanation -->) before checking substance
        body_stripped = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)

        substantive_count = 0
        for sec, pattern in SECTION_PATTERNS.items():
            m = re.search(pattern, body_stripped, re.DOTALL | re.IGNORECASE)
            if m:
                content = m.group(1).strip()
                if len(content) > 40:  # substantive threshold
                    substantive_count += 1
                    if sec == "testing":
                        testing_filled += 1

        score = substantive_count / len(SECTION_PATTERNS)
        completeness_scores.append(score)

    return {
        "avg_body_length": statistics.mean(body_lengths),
        "avg_section_completeness": statistics.mean(completeness_scores),
        "testing_section_filled_ratio": testing_filled / len(eng_prs),
    }


# ────────────────────────────────────────────────────────────────────────
# Normalization + scoring
# ────────────────────────────────────────────────────────────────────────
def percentile_rank(values, higher_better=True):
    """Return dict: engineer -> percentile (0-100) for a metric.

    Sort so 'worst' engineer is at index 0 and 'best' at index n-1.
    Then percentile = (rank / (n-1)) * 100 → worst=0, best=100.
    Tied engineers receive the mid-rank.
    """
    # For higher_better=True: ascending (smallest=worst first)
    # For higher_better=False: descending (largest=worst first)
    sorted_vals = sorted(values, key=lambda x: x[1], reverse=not higher_better)
    n = len(sorted_vals)
    result = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_vals[j + 1][1] == sorted_vals[i][1]:
            j += 1
        mid_rank = (i + j) / 2
        pct = (mid_rank / (n - 1)) * 100 if n > 1 else 50
        for k in range(i, j + 1):
            result[sorted_vals[k][0]] = pct
        i = j + 1
    return result


def normalize_metrics(per_engineer):
    """Apply percentile rank normalization to each metric, return 0-100 scores."""

    # Define which metrics are higher-better vs lower-better
    HIGHER_BETTER = {
        "s1_pr_per_week", "s1_commits_per_week",
        "s3_depth_score", "s3_breadth_score", "s3_critical_files_pct",
        "s3_total_files_touched",
        "s4_review_volume", "s4_review_pr_count", "s4_avg_complexity_lines",
        "s4_avg_complexity_files", "s4_avg_comment_depth_chars",
        "s4_requested_reviewer_count", "s4_inline_comment_count",
        "s6_avg_body_length", "s6_avg_section_completeness",
        "s6_testing_section_filled_ratio",
    }
    LOWER_BETTER = {
        "s1_consistency_cv", "s1_median_cycle_hours", "s1_mean_review_rounds",
        "s4_median_time_to_first_review_hours",
        # s5_revert_rate is NOT percentile-ranked — see compute_signal_scores
    }

    all_engineers = list(per_engineer.keys())
    flat_metrics = set()
    for eng_data in per_engineer.values():
        flat_metrics.update(eng_data.keys())

    normalized = {eng: {} for eng in all_engineers}
    for metric in flat_metrics:
        if metric not in HIGHER_BETTER and metric not in LOWER_BETTER:
            continue
        values = [(eng, per_engineer[eng].get(metric, 0)) for eng in all_engineers]
        higher = metric in HIGHER_BETTER
        ranks = percentile_rank(values, higher_better=higher)
        for eng in all_engineers:
            normalized[eng][metric] = ranks[eng]

    return normalized


def compute_signal_scores(normalized, raw_per_engineer):
    """Aggregate normalized metrics into per-signal scores (0-100)."""
    SIGNAL_DEFS = {
        "signal_1_consistency": [
            "s1_pr_per_week", "s1_commits_per_week",
            "s1_consistency_cv", "s1_median_cycle_hours", "s1_mean_review_rounds",
        ],
        "signal_3_ownership": [
            "s3_depth_score", "s3_breadth_score",
            "s3_critical_files_pct", "s3_total_files_touched",
        ],
        "signal_4_review": [
            "s4_review_pr_count", "s4_avg_complexity_lines",
            "s4_avg_comment_depth_chars", "s4_median_time_to_first_review_hours",
            "s4_requested_reviewer_count",
        ],
        # Signal 5 (reliability) computed directly, not via percentile rank — see below
        "signal_6_communication": [
            "s6_avg_section_completeness", "s6_testing_section_filled_ratio",
            "s6_avg_body_length",
        ],
    }

    signal_scores = {}
    for eng, metrics in normalized.items():
        signal_scores[eng] = {}
        for sig_name, metric_keys in SIGNAL_DEFS.items():
            vals = [metrics[k] for k in metric_keys if k in metrics]
            signal_scores[eng][sig_name] = statistics.mean(vals) if vals else 0

        # Signal 5: direct score from revert rate.
        # (1 - revert_rate) * 100. Engineers with 0 reverts = 100. Penalty grows with rate.
        # This avoids over-penalizing high-volume engineers with rare reverts.
        revert_rate = raw_per_engineer[eng]["signal_5"]["revert_rate"]
        signal_scores[eng]["signal_5_reliability"] = max(0, (1 - revert_rate) * 100)

        # Overall: average of the 5 scored signals (Signal 2 is descriptive only)
        all_sigs = [
            "signal_1_consistency", "signal_3_ownership",
            "signal_4_review", "signal_5_reliability", "signal_6_communication",
        ]
        scored = [signal_scores[eng][s] for s in all_sigs]
        signal_scores[eng]["overall_impact"] = statistics.mean(scored)
    return signal_scores


# ────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────
def main():
    print(f"Loading {DATA_FILE}...")
    with open(DATA_FILE) as f:
        data = json.load(f)
    prs = data["prs"]
    commits = data["commits"]
    print(f"  PRs: {len(prs)}, Commits: {len(commits)}")

    # --- Identify active engineers (excluding bots) ---
    pr_authors = Counter(
        p["author"] for p in prs.values()
        if p["author"] and not is_known_bot(p["author"])
    )
    reviewers = Counter()
    for p in prs.values():
        for r in p.get("reviews", []):
            reviewer = r.get("reviewer")
            if reviewer and not is_known_bot(reviewer):
                reviewers[reviewer] += 1

    active = set()
    for eng, c in pr_authors.items():
        if c >= MIN_PRS:
            active.add(eng)
    for eng, c in reviewers.items():
        if c >= MIN_REVIEWS:
            active.add(eng)
    print(f"  Active engineers (≥{MIN_PRS} PRs OR ≥{MIN_REVIEWS} reviews): {len(active)}")

    # --- Compute raw metrics for each signal ---
    per_engineer_raw = {}
    flat_metrics = {}

    for eng in active:
        s1 = compute_signal_1_consistency(eng, prs, commits)
        s2 = compute_signal_2_work_type(eng, prs)
        s3 = compute_signal_3_ownership(eng, prs)
        s4 = compute_signal_4_review(eng, prs)
        s5 = compute_signal_5_reliability(eng, prs)
        s6 = compute_signal_6_communication(eng, prs)

        per_engineer_raw[eng] = {
            "signal_1": s1,
            "signal_2": s2,
            "signal_3": s3,
            "signal_4": s4,
            "signal_5": s5,
            "signal_6": s6,
        }

        # Flatten for normalization
        flat_metrics[eng] = {
            **{f"s1_{k}": v for k, v in s1.items() if isinstance(v, (int, float))},
            **{f"s3_{k}": v for k, v in s3.items() if isinstance(v, (int, float))},
            **{f"s4_{k}": v for k, v in s4.items() if isinstance(v, (int, float))},
            "s5_revert_rate": s5["revert_rate"],
            **{f"s6_{k}": v for k, v in s6.items() if isinstance(v, (int, float))},
        }

    # --- Normalize and score ---
    normalized = normalize_metrics(flat_metrics)
    signal_scores = compute_signal_scores(normalized, per_engineer_raw)

    # --- Per-signal metric label + how to format raw value for display ---
    METRIC_DISPLAY = {
        # Signal 1
        "s1_pr_per_week": ("PR merge frequency", lambda v: f"{v:.1f} PRs/wk"),
        "s1_commits_per_week": ("commit cadence", lambda v: f"{v:.1f} commits/wk"),
        "s1_consistency_cv": ("weekly consistency", lambda v: f"variance={v:.2f} (lower=steadier)"),
        "s1_median_cycle_hours": ("PR cycle time", lambda v: f"median={v:.0f}h open→merge"),
        "s1_mean_review_rounds": ("review rounds per PR", lambda v: f"{v:.1f} reviews/PR"),
        # Signal 3
        "s3_depth_score": ("ownership depth", lambda v: f"{v:.0%} of work in primary domain"),
        "s3_breadth_score": ("ownership breadth", lambda v: f"{int(v)} distinct areas"),
        "s3_critical_files_pct": ("critical-area focus", lambda v: f"{v:.0f}% of files in critical paths (vs docs/scripts/utility)"),
        "s3_total_files_touched": ("files touched", lambda v: f"{int(v)} files across PRs"),
        # Signal 4
        "s4_review_pr_count": ("review volume", lambda v: f"{int(v)} PRs reviewed"),
        "s4_avg_complexity_lines": ("complexity reviewed", lambda v: f"{v:.0f} lines/PR avg"),
        "s4_avg_comment_depth_chars": ("review comment depth", lambda v: f"{v:.0f} chars/review"),
        "s4_median_time_to_first_review_hours": ("first review speed", lambda v: f"median={v:.1f}h"),
        "s4_requested_reviewer_count": ("times requested as reviewer", lambda v: f"{int(v)} explicit requests"),
        # Signal 6
        "s6_avg_section_completeness": ("PR template completeness", lambda v: f"{v:.0%} of sections substantive"),
        "s6_testing_section_filled_ratio": ("testing notes", lambda v: f"{v:.0%} of PRs include test detail"),
        "s6_avg_body_length": ("PR description length", lambda v: f"avg {int(v)} chars"),
    }

    SIGNAL_METRIC_KEYS = {
        "signal_1_consistency": [
            "s1_pr_per_week", "s1_commits_per_week",
            "s1_median_cycle_hours", "s1_mean_review_rounds", "s1_consistency_cv",
        ],
        "signal_3_ownership": [
            "s3_total_files_touched", "s3_depth_score",
            "s3_breadth_score", "s3_critical_files_pct",
        ],
        "signal_4_review": [
            "s4_review_pr_count", "s4_avg_comment_depth_chars",
            "s4_requested_reviewer_count", "s4_median_time_to_first_review_hours",
            "s4_avg_complexity_lines",
        ],
        "signal_6_communication": [
            "s6_avg_section_completeness", "s6_testing_section_filled_ratio",
            "s6_avg_body_length",
        ],
    }

    SIGNAL_LABELS = {
        "signal_1_consistency": "Shipping Consistency",
        "signal_3_ownership": "Ownership Profile",
        "signal_4_review": "Review Impact",
        "signal_5_reliability": "Code Reliability",
        "signal_6_communication": "Communication Quality",
    }

    def tier_for(score):
        if score >= 75: return "Exceptional"
        if score >= 65: return "High"
        if score >= 50: return "Solid"
        return "Emerging"

    def signal_headline(percentile):
        if percentile >= 80: return "Top-tier"
        if percentile >= 60: return "Strong"
        if percentile >= 40: return "Average"
        if percentile >= 20: return "Below average"
        return "Bottom-tier"

    def build_engineer_profile(eng):
        """Generate a busy-leader-friendly profile."""
        per_signal = {}
        all_metric_entries = []  # for picking overall strengths/watch-outs

        primary_domain = per_engineer_raw[eng]["signal_3"].get("primary_domain", "their primary domain")

        for sig_name, metric_keys in SIGNAL_METRIC_KEYS.items():
            entries = []
            for mk in metric_keys:
                if mk not in normalized[eng]:
                    continue
                label, fmt = METRIC_DISPLAY[mk]
                raw = flat_metrics[eng].get(mk, 0)
                pct = round(normalized[eng][mk], 0)
                # Special case: depth — show domain-aggregated % for clarity,
                # even though the percentile rank below is based on top-2-dirs share
                # (we use the stable scoring metric for ranks, the domain metric for display).
                if mk == "s3_depth_score":
                    pds = per_engineer_raw[eng]["signal_3"].get("primary_domain_share", raw)
                    raw_display = f"{pds:.0%} of work in {primary_domain}"
                else:
                    raw_display = fmt(raw)
                fact = f"{label}: {raw_display} ({pct:.0f}th pct)"
                entries.append({
                    "label": label,
                    "raw_value": raw,
                    "raw_display": raw_display,
                    "percentile": pct,
                    "fact": fact,
                    "signal": sig_name,
                })
            entries.sort(key=lambda e: e["percentile"], reverse=True)
            all_metric_entries.extend(entries)

            score = signal_scores[eng][sig_name]
            per_signal[sig_name] = {
                "label": SIGNAL_LABELS[sig_name],
                "score": round(score, 1),
                "headline": signal_headline(score),
                "key_facts": [e["fact"] for e in entries],
                "drivers": {  # explicit best/worst metric
                    "strongest": entries[0] if entries else None,
                    "weakest": entries[-1] if entries else None,
                },
            }

        # Signal 5: direct, not percentile-based
        s5 = per_engineer_raw[eng]["signal_5"]
        s5_score = signal_scores[eng]["signal_5_reliability"]
        s5_fact = (f"{s5['revert_count']} reverts in {s5['total_prs']} PRs "
                   f"({s5['revert_rate']:.1%})")
        per_signal["signal_5_reliability"] = {
            "label": SIGNAL_LABELS["signal_5_reliability"],
            "score": round(s5_score, 1),
            "headline": signal_headline(s5_score),
            "key_facts": [s5_fact],
            "explanation": "score = (1 - revert_rate) × 100 (direct, not percentile-based)",
        }

        # Overall strengths: top 3 percentile-ranked metrics across all signals
        top_strengths = sorted(all_metric_entries, key=lambda e: e["percentile"], reverse=True)[:3]
        watch_outs = [e for e in sorted(all_metric_entries, key=lambda e: e["percentile"])
                      if e["percentile"] < 40][:2]
        if s5["revert_count"] > 0:
            watch_outs.append({
                "label": "reverts",
                "fact": s5_fact,
                "percentile": s5_score,  # use direct score
                "signal": "signal_5_reliability",
            })

        # Work-mix headline (descriptive only)
        s2 = per_engineer_raw[eng]["signal_2"]
        if s2["distribution"]:
            mix = sorted(s2["distribution"].items(), key=lambda x: -x[1])
            mix_str = ", ".join(f"{k}={v:.0%}" for k, v in mix[:3])
        else:
            mix_str = "no labeled PRs"

        return {
            "overall_impact": round(signal_scores[eng]["overall_impact"], 1),
            "tier": tier_for(signal_scores[eng]["overall_impact"]),
            "work_mix": mix_str,
            "top_strengths": [
                {"signal": SIGNAL_LABELS.get(e["signal"], e["signal"]), "fact": e["fact"]}
                for e in top_strengths
            ],
            "watch_outs": [
                {"signal": SIGNAL_LABELS.get(e["signal"], e["signal"]), "fact": e.get("fact")}
                for e in watch_outs
            ],
            "signals": per_signal,
            "raw_metrics": per_engineer_raw[eng],
        }

    # --- Build full output ---
    output = {
        "metadata": data["metadata"],
        "engineers_analyzed": len(active),
        "thresholds": {"min_prs": MIN_PRS, "min_reviews": MIN_REVIEWS},
        "scoring_methodology": {
            "approach": "Per-metric percentile rank across active engineers, averaged into per-signal score (0–100), then averaged into overall impact (0–100).",
            "exception": "Signal 5 (reliability) uses direct (1 − revert_rate) × 100 — most engineers have 0 reverts and percentile ranking over-penalizes high-volume engineers with rare reverts.",
            "tiers": {"Exceptional": "≥75", "High": "65-75", "Solid": "50-65", "Emerging": "<50"},
            "scored_signals": list(SIGNAL_LABELS.values()),
            "descriptive_signal": "Work Type Mix (shown as context, not scored — depends on role)",
        },
        "engineers": {},
    }
    for eng in active:
        output["engineers"][eng] = build_engineer_profile(eng)

    # Sort and save
    ranked = sorted(active, key=lambda e: signal_scores[e]["overall_impact"], reverse=True)
    output["ranked_engineers"] = ranked

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    # --- Print summary ---
    print(f"\n{'='*80}")
    print(f"TOP 10 ENGINEERS BY OVERALL IMPACT SCORE")
    print(f"{'='*80}")
    print(f"{'Rank':<5} {'Engineer':<22} {'Overall':<9} {'S1':<7} {'S3':<7} {'S4':<7} {'S5':<7} {'S6':<7}")
    print(f"{'-'*80}")
    for i, eng in enumerate(ranked[:10], 1):
        s = signal_scores[eng]
        print(f"{i:<5} {eng:<22} {s['overall_impact']:>6.1f}   "
              f"{s['signal_1_consistency']:>5.1f}   "
              f"{s['signal_3_ownership']:>5.1f}   "
              f"{s['signal_4_review']:>5.1f}   "
              f"{s['signal_5_reliability']:>5.1f}   "
              f"{s['signal_6_communication']:>5.1f}")

    print(f"\n{'='*80}")
    print(f"TOP 5 DETAILED BREAKDOWN")
    print(f"{'='*80}")
    for i, eng in enumerate(ranked[:5], 1):
        raw = per_engineer_raw[eng]
        s = signal_scores[eng]
        print(f"\n#{i}  {eng}  (overall impact: {s['overall_impact']:.1f}/100)")
        s1 = raw["signal_1"]
        print(f"   Signal 1 — Shipping ({s['signal_1_consistency']:.0f}/100):")
        print(f"     {s1['pr_count']} PRs, {s1['commit_count']} commits, "
              f"{s1['pr_per_week']:.1f} PRs/wk, "
              f"cycle={s1['median_cycle_hours']:.0f}h")

        s2 = raw["signal_2"]
        top_cats = sorted(s2["distribution"].items(), key=lambda x: -x[1])[:3]
        cat_str = ", ".join(f"{k}={v:.0%}" for k, v in top_cats)
        print(f"   Signal 2 — Work mix (descriptive): {cat_str}")

        s3 = raw["signal_3"]
        print(f"   Signal 3 — Ownership ({s['signal_3_ownership']:.0f}/100):")
        top_dirs_str = ", ".join(f"{d}({c})" for d, c in s3["top_dirs"][:3])
        print(f"     depth={s3['depth_score']:.0%} in {s3.get('primary_domain', '?')}, breadth={s3['breadth_score']} areas, "
              f"crit={s3['critical_files_pct']:.0f}%")
        print(f"     top: {top_dirs_str}")

        s4 = raw["signal_4"]
        print(f"   Signal 4 — Review ({s['signal_4_review']:.0f}/100):")
        print(f"     {s4['review_pr_count']} PRs reviewed, "
              f"avg complexity={s4['avg_complexity_lines']:.0f} lines, "
              f"comment depth={s4['avg_comment_depth_chars']:.0f} chars, "
              f"first review={s4['median_time_to_first_review_hours']:.1f}h")

        s5 = raw["signal_5"]
        print(f"   Signal 5 — Reliability ({s['signal_5_reliability']:.0f}/100):")
        print(f"     {s5['revert_count']} reverts out of {s5['total_prs']} PRs "
              f"({s5['revert_rate']:.1%})")

        s6 = raw["signal_6"]
        print(f"   Signal 6 — Communication ({s['signal_6_communication']:.0f}/100):")
        print(f"     avg body length={s6['avg_body_length']:.0f} chars, "
              f"section completeness={s6['avg_section_completeness']:.0%}, "
              f"testing filled={s6['testing_section_filled_ratio']:.0%}")

    print(f"\n✓ Full analysis saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
