# Dashboard UI Plan — PostHog: Most Impactful Engineers

## Audience & Goal

**Audience:** A busy engineering leader at PostHog. They understand the basics of what their team does but don't read every PR.

**Goal:** In 5 seconds the leader should be able to identify the top 5 most impactful engineers and have a sense of *why* each is impactful. With one click they should be able to drill into the per-signal evidence behind any score. With one click they should be able to understand how impact was measured.

**Non-goals:**
- Performance management / improvement coaching (no "watch-outs" or "suggestions to make them stronger")
- Comparison tools / sortable tables (focus is on the top 5, not full team browsing)
- PR-level drill-downs (signals are summary-level)

---

## Page Layout (single page, fits laptop screen)

```
┌────────────────────────────────────────────────────────────────────┐
│  PostHog: Most Impactful Engineers                                 │
│  Ranked across 6 signals over the last 90 days.                    │
│  [▾ See methodology]                       Showing top 5 of 101    │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │ #1  sampennington                          80   Exceptional│   │
│  │ ────────────────────────────────────────────────────────── │   │
│  │ Frontend specialist shipping 19 PRs/wk on product          │   │
│  │ analytics. Owns frontend visualization stack.              │   │
│  │                                                            │   │
│  │ Strengths:                                                 │   │
│  │   • PR merge frequency: 19.4 PRs/wk (99th pct)             │   │
│  │   • Commit cadence: 19.0 commits/wk (99th pct)             │   │
│  │   • Review volume: 276 PRs reviewed (99th pct)             │   │
│  │                                                            │   │
│  │ [▾ See signal breakdown]                                   │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                    │
│  ┌── #2  skoob13 ──────────────────────────  78  Exceptional ──┐  │
│  │  ...                                                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  (3 more cards for #3, #4, #5)                                     │
└────────────────────────────────────────────────────────────────────┘
```

---

## Sections in detail

### 1. Header (always visible, sticky)

- **Title:** "PostHog: Most Impactful Engineers"
- **Subtitle:** "Ranked across 6 signals over the last 90 days."
- **Methodology toggle:** Single text link/button: `▾ See methodology`
- **Scope indicator (right-aligned, subtle):** `Showing top 5 of 101 active engineers`

Above-the-fold: the top 1-2 engineer cards should be visible without scrolling.

### 2. Methodology drawer (collapsed by default)

When expanded, shows 6 signal cards in a 3×2 grid (or 2×3 on narrow screens). Each card:

- Signal number + name (e.g., "1. Shipping Consistency")
- One-sentence definition
- "What we measure" — bullet list of metrics
- Source: pulled directly from `impact-signals.md`

Also includes a short scoring methodology paragraph at the top of the drawer:
> *Each engineer is ranked against their peers (101 active engineers in the last 90 days) on each metric, then averaged into a 0–100 score per signal. The overall impact is the average of 5 scored signals (work type is shown as context, not scored).*

### 3. Engineer cards (#1 – #5)

Each card has two states: **collapsed (default)** and **expanded**.

#### Collapsed state (always shown)

Left side:
- Rank badge (e.g., `#1`)
- **Engineer login** (large, bold)
- **One-line summary** (≤120 chars): synthesized from work mix + top directories
  - Format: `"<role descriptor> shipping <PR/wk> PRs/wk on <primary area>. <Signature trait>."`
  - Example: `"Frontend specialist shipping 19 PRs/wk on product analytics. Owns frontend visualization stack."`

Right side:
- **Overall impact score** (very large number, 0–100)
- **Tier badge** (Exceptional / High / Solid / Emerging) — colored chip

Below the divider:
- **Strengths** header
- 3 bullet points, one per top-strength fact (sourced from `top_strengths` in JSON)
  - Format example: `PR merge frequency: 19.4 PRs/wk (99th pct)`
  - Each bullet prefixed with the signal name in muted text: `[Shipping] PR merge frequency: 19.4 PRs/wk (99th pct)`

Bottom of card (always visible):
- **Expand toggle:** `▾ See signal breakdown`

#### Expanded state

When expanded, the card grows downward to reveal:

**A. Per-signal breakdown (5 scored signals + 1 descriptive)**

Each signal is a sub-card with:
- Signal name + score (e.g., `Shipping Consistency — 69 / 100`)
- Colored bar (color follows tier rules below) showing the score
- Bullet list of `key_facts` (already formatted in the JSON, sorted by percentile descending)

For Signal 2 (Work Type Mix — descriptive):
- Just shows the work mix breakdown (e.g., `fix=31% · feat=30% · chore=26%`)
- No score, no color, labeled as `Work Type Mix (descriptive — not scored)`

For Signal 5 (Reliability):
- Shows the score + explanation: `0 reverts in 250 PRs (0.0%) → score = (1 − revert_rate) × 100`

**B. "Where they have impact" narrative**

One short paragraph (2-3 sentences) explaining what makes this engineer matter to the team. Auto-generated from data:
- Primary directories (from `raw_metrics.signal_3.top_dirs`)
- Work type emphasis (from `work_mix`)
- The standout signal (highest score)
- The standout strength (top of `top_strengths`)

Example (sampennington):
> *"Owns the frontend visualization stack — 1209 files touched across `frontend/src` and `products/product_analytics`. Shipping velocity in the top 1% (19 PRs/wk) combined with 276 PRs reviewed makes him a force multiplier on frontend work."*

---

## Color & tier rules

| Tier         | Score range | Color  | Hex          |
|--------------|-------------|--------|--------------|
| Exceptional  | 75+         | Green  | `#10b981`    |
| High         | 65–75       | Blue   | `#3b82f6`    |
| Solid        | 50–65       | Gray   | `#6b7280`    |
| Average      | 40–50       | Yellow | `#f59e0b`    |
| Below avg.   | <40         | Red    | `#ef4444`    |

- **Overall impact score** uses tier color as a chip / accent.
- **Per-signal score bars** use the same tier scale.
- **Strength facts** are not individually colored — color is at the signal level.
- For top-5 cards specifically, red should be very rare. If it appears, that's OK — it's honest.

---

## Interactions

| Action | Behavior |
|---|---|
| Click `▾ See methodology` | Expand/collapse the 6-signal methodology drawer |
| Click any methodology signal card | Each signal card is itself a small expand/collapse |
| Click `▾ See signal breakdown` on engineer card | Expand/collapse the per-signal detail section |
| Click outside any card | No effect (no modal behavior) |

All transitions: 200ms ease (not snappy, not slow).

---

## Visual / typography spec

- **Font:** system-ui stack (`-apple-system, BlinkMacSystemFont, "Inter", "Helvetica Neue", sans-serif`)
- **Color palette:** clean off-white background (`#fafafa`), white cards (`#ffffff`), subtle border (`#e5e7eb`), text gray scale (`#111827` primary, `#6b7280` secondary, `#9ca3af` muted)
- **Type scale:**
  - Page title: 28px bold
  - Engineer name: 20px bold
  - Overall impact number: 48px bold (single number, e.g., "80")
  - Section labels (Strengths, etc.): 12px uppercase tracked
  - Body / facts: 14px regular
  - Muted captions (e.g., signal prefix): 12px gray
- **Spacing:** generous (16-24px between cards, 12-16px internal padding)
- **No emojis**, no icon fonts. Use Unicode characters (▾, ●) sparingly.

---

## Data wiring

**Source file:** `engineer-impact-analysis.json`

**For each of the top 5 engineers (use `ranked_engineers` array, first 5):**

| UI element | JSON path |
|---|---|
| Engineer login | object key in `engineers` |
| Overall impact score | `engineers[login].overall_impact` |
| Tier badge text + color | `engineers[login].tier` |
| One-line summary | **Computed in HTML/JS** from `work_mix` + top directory + top strength |
| Strengths bullets | `engineers[login].top_strengths` (array of `{signal, fact}`) |
| Per-signal score + facts | `engineers[login].signals.{signal_name}` |
| Work mix (descriptive) | `engineers[login].work_mix` |
| "Where they have impact" narrative | **Computed in HTML/JS** from top directories + work mix + standout signal |

**For methodology drawer:**

Hard-coded copy in HTML, sourced from `impact-signals.md`. Each card has:
- Title from `impact-signals.md` header
- Definition from "What it captures" line
- "What we measure" bullets from "Metrics" section

---

## Tech stack

- **Single static HTML file:** `dashboard.html`
- **Styling:** Tailwind CSS via CDN (`https://cdn.tailwindcss.com`)
- **JS:** Vanilla JavaScript, no framework, no build step
- **Data:** Embed `engineer-impact-analysis.json` as a `<script>` tag containing the parsed JSON (or `fetch()` it from the same directory — embedding is simpler for shareability)
- **No external dependencies** beyond Tailwind CDN
- **Browser support:** Modern Chrome/Safari/Firefox; no IE

---

## File output

- `dashboard.html` — single-file dashboard, openable directly in a browser
- No backend, no build step, no install

---

## What we are deliberately NOT building

To keep this dashboard noise-free and focused:

- ❌ Suggestions to make engineers stronger (performance-review tone)
- ❌ Watch-outs / weaknesses for top 5 engineers (celebratory framing)
- ❌ Filtering, sorting, or searching (top 5 is the curated view)
- ❌ Charts/graphs (numbers + facts are clearer for this audience)
- ❌ Comparison between engineers side-by-side (cards already enable this naturally)
- ❌ Trends over time (90 days is the window)
- ❌ PR-level lists or links to GitHub (signals are summary-level)
- ❌ Engineer photos / avatars (focuses attention on contribution, not identity)

---

## Build acceptance criteria

When the build is done, the dashboard should:

1. Open in a browser by double-clicking `dashboard.html` (no server needed)
2. Show 5 engineer cards above-the-fold or with minimal scroll on a 1440px laptop
3. Have the methodology drawer **collapsed** on first load
4. Have all 5 engineer cards **collapsed (compact view)** on first load
5. Render the correct top 5 from `ranked_engineers` in the JSON
6. Apply tier colors correctly on all overall scores and signal bars
7. Allow expanding/collapsing the methodology and any engineer card independently
8. Display the one-line summary + 3 strengths + tier without any expanding required
