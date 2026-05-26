# PostHog: Most Impactful Engineers

An analysis and interactive dashboard that identifies the most impactful engineers at PostHog over the last 90 days, designed for a busy engineering leader to scan in seconds.

**Live dashboard:** https://echauk.github.io/posthog-impact-dashboard/

---

## What this is

A take-home analysis answering: _Who are the most impactful engineers at PostHog?_

Counting commits, lines of code, or reviews doesn't capture impact. This dashboard scores engineers across **six signals** that together describe how someone contributes — what they own, who they help, whether their code sticks, and how clearly they communicate.

The goal is not to rank for performance management. It's to give an engineering leader a fast, defensible read on who is driving the team and why.

---

## The six signals

| # | Signal | Captures |
|---|---|---|
| 1 | **Shipping Consistency** | Whether they show up reliably and ship at a steady pace |
| 2 | **Work Type Mix** *(descriptive)* | Nature of contributions — features, fixes, refactor, churn |
| 3 | **Ownership Profile** | Deep ownership of critical systems and/or cross-team breadth |
| 4 | **Review Impact** | Whether they make the rest of the team better |
| 5 | **Code Reliability** | Whether their code sticks or gets reverted |
| 6 | **Communication Quality** | Whether they communicate their work clearly |

Each signal is computed from several sub-metrics. See [`impact-signals.md`](./impact-signals.md) for the full breakdown.

---

## Scoring methodology

- Each engineer is **percentile-ranked** against their peers (101 active engineers) on each sub-metric
- Sub-metrics are averaged into a 0–100 **signal score**
- The overall impact is the average of the **five scored signals** (Signal 2 — Work Type Mix — is descriptive context, not scored, since it depends on role)
- Signal 5 (Reliability) uses a direct `(1 − revert_rate) × 100` instead of percentile ranking, to avoid penalizing high-volume engineers for rare reverts

**Impact tiers:**

| Tier | Score | |
|---|---|---|
| Exceptional | ≥ 75 | 🟢 |
| High | 65–75 | 🔵 |
| Solid | 50–65 | ⚪ |
| Average | 40–50 | 🟡 |
| Below avg. | < 40 | 🔴 |

---

## How the dashboard is structured

Designed for a busy leader to scan in 5 seconds:

1. **Headline:** title + scope (90 days, top 5 of 101)
2. **Methodology drawer** (collapsed by default) — single click reveals all 6 signal definitions
3. **5 engineer cards**, each showing:
   - Rank, name, overall score, tier badge
   - **One-paragraph narrative** under the name describing where they have impact across all signals
   - **3 strengths** in natural language (no raw counts)
   - Expandable per-signal breakdown with score bars and percentile-backed key facts

What's deliberately **not** included: improvement suggestions, watch-outs/weaknesses for top 5, sorting/filtering, charts, GitHub PR links, avatars. Each addition was considered against "would a busy leader want this in 5 seconds?"

---

## Pipeline

```
GitHub API (gh CLI + GraphQL)
        │
        ▼
engineer-impact-data.json     (raw PR / commit / review data, ~25 MB, not committed)
        │
        ▼  analyze_impact.py
engineer-impact-analysis.json (per-engineer scores + percentiles + signal facts)
        │
        ▼  build_dashboard.py
index.html                    (single static dashboard, embeds the analysis)
```

### Files

| File | Purpose |
|---|---|
| `impact-signals.md` | Definition of the 6 signals and what each measures |
| `dashboard-ui-plan.md` | PRD: layout, interactions, scoring methodology surface, what's intentionally excluded |
| `gather_data_graphql.py` | Pulls 90 days of PR data via GitHub GraphQL (batched, ~700 queries) |
| `gather_commits.py` | Pulls commit history via REST |
| `analyze_impact.py` | Computes per-signal metrics, percentile ranks, overall scores |
| `build_dashboard.py` | Generates the single static `index.html` from the analysis JSON |
| `engineer-impact-analysis.json` | Output of analysis step; consumed by the dashboard |
| `index.html` | The dashboard (single file, self-contained) |

### Regenerating

```bash
# 1. Pull fresh data (requires gh auth and ~40 min for the GraphQL pass)
python3 gather_data_graphql.py
python3 gather_commits.py

# 2. Recompute scores
python3 analyze_impact.py

# 3. Rebuild dashboard
python3 build_dashboard.py
```

Open `index.html` in a browser — no server needed.

---

## Top 5 (last 90 days, as of analysis)

| # | Engineer | Score | Tier |
|---|---|---|---|
| 1 | sampennington | 80.5 | Exceptional |
| 2 | skoob13 | 78.0 | Exceptional |
| 3 | pauldambra | 75.8 | Exceptional |
| 4 | andrewm4894 | 73.2 | High |
| 5 | eli-r-ph | 72.9 | High |

See the [live dashboard](https://echauk.github.io/posthog-impact-dashboard/) for narratives and per-signal evidence.
