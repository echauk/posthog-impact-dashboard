# Engineering Impact Signals

Six signals for measuring engineering impact, designed to be computed from PostHog's GitHub data via the `gh` CLI / GitHub API.

---

## Signal 1 — Shipping Consistency

**What it captures:** Whether an engineer shows up reliably and ships work at a steady pace.

**Metrics:**
- PR merge frequency (PRs merged per week/month over the analysis window)
- Commit cadence (commits per week, std deviation as a measure of consistency vs. bursty)
- Average PR cycle time (timestamp from PR open → merge, lower = trusted + clean code)
- Average Review round trips (number of times reviewers were re-requested before merge)

**Data sources:** PR merged timestamps, commit timestamps, review request events

---

## Signal 2 — Work Type Mix

**What it captures:** The nature of an engineer's contributions — are they building features, fixing bugs, paying down tech debt, or doing churn?

**Metrics:**
- Distribution of PR labels: `feat`, `fix`, `refactor`, `chore`, `bug`, etc.
- Ratio of feature/fix work vs. chore/refactor work over time

**Data sources:** PR labels (PostHog uses conventional commit-style labels consistently)

**Note:** "Is this refactor necessary?" is not scored directly — this is captured implicitly by Signal 6 (description quality / Problem section completeness).

---

## Signal 3 — Ownership Profile

**What it captures:** Whether an engineer has deep ownership of critical systems and/or is a cross-team force multiplier. Breadth and depth are surfaced separately — both can be valuable depending on role.

**Metrics:**
- **Depth:** Primary domain concentration — top 1-2 directories by PR/commit count, percentage of total work in those areas
- **Breadth:** Cross-domain contributions — number of distinct top-level directories touched outside their primary domain
- **Criticality proxy:** Directory-level weighting based on path heuristics (e.g., `posthog/models/`, `posthog/api/`, `frontend/src/` weighted higher than `docs/`, `scripts/`)

**Data sources:** File paths in PR diffs and commits

**Note:** Breadth and depth are displayed as separate data points, not combined. An engineering leader can interpret these differently depending on role expectations.

---

## Signal 4 — Review Impact

**What it captures:** Whether an engineer makes the rest of the team better — are they a trusted, substantive reviewer?

**Metrics:**
- Review volume (number of PRs reviewed over the analysis window)
- Complexity of PRs reviewed (avg diff size + file count of PRs they reviewed — high complexity = trusted with hard stuff)
- Review comment depth (total character count of review comments as proxy for substance vs. rubber-stamping)
- Time to first review (how quickly they respond when requested — lower = reliable team member)
- Reviewer request frequency (how often other engineers specifically request them — strong trust signal)

**Data sources:** PR review events, review comments, reviewer request events, PR file change stats

---

## Signal 5 — Code Reliability

**What it captures:** Whether an engineer's code sticks, or needs to be cleaned up after.

**Metrics:**
- Revert rate: count of `Revert "..."` PRs/commits attributed back to the original author's work
- (Rapid follow-up fix commits on own PRs were considered but excluded for now — revert detection is cleaner and less ambiguous)

**Data sources:** PR titles and commit messages matching `Revert` pattern, linked back to original PR author

---

## Signal 6 — Communication Quality

**What it captures:** Whether an engineer communicates their work clearly — a proxy for professionalism, team awareness, and how easy they are to work with.

**Metrics:**
- Section completeness: are all standard sections filled? (Problem, Changes, How did you test this?, Publish to changelog?, Agent context if applicable)
- Section depth: character count per section (thin vs. substantive)
- Testing section quality: is "How did you test this?" non-empty and specific?

**Data sources:** PR description bodies (PostHog uses a standard PR template with named sections)

---

## Data Gathering Approach

- **No repo clone needed** — all data pulled via `gh api` calls
- **Time window:** Last 6-12 months to focus on currently active team members
- **Primary endpoints:**
  - `GET /repos/PostHog/posthog/pulls` — PR metadata, labels, descriptions, timestamps
  - `GET /repos/PostHog/posthog/pulls/{n}/reviews` — review data per PR
  - `GET /repos/PostHog/posthog/pulls/{n}/files` — files changed per PR
  - `GET /repos/PostHog/posthog/pulls/{n}/comments` — review comments
  - `GET /repos/PostHog/posthog/commits` — commit history with author + stats
