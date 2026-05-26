#!/usr/bin/env python3
"""Build dashboard.html with top-5 engineer data embedded inline."""

import json
from pathlib import Path

ROOT = Path(__file__).parent
ANALYSIS_FILE = ROOT / "engineer-impact-analysis.json"
OUTPUT = ROOT / "index.html"


def load_slim_data():
    with open(ANALYSIS_FILE) as f:
        data = json.load(f)
    return {
        "metadata": data["metadata"],
        "engineers_analyzed": data["engineers_analyzed"],
        "thresholds": data["thresholds"],
        "scoring_methodology": data["scoring_methodology"],
        "ranked_engineers": data["ranked_engineers"][:5],
        "engineers": {k: data["engineers"][k] for k in data["ranked_engineers"][:5]},
    }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PostHog: Most Impactful Engineers</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    :root {
      --tier-exceptional: #10b981;
      --tier-high: #3b82f6;
      --tier-solid: #6b7280;
      --tier-average: #f59e0b;
      --tier-belowavg: #ef4444;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Inter", "Helvetica Neue", sans-serif;
      background: #fafafa;
      color: #111827;
    }
    .collapsible {
      overflow: hidden;
      transition: max-height 220ms ease, opacity 220ms ease, margin-top 220ms ease;
      max-height: 4000px;
      opacity: 1;
    }
    .collapsible.collapsed {
      max-height: 0;
      opacity: 0;
      margin-top: 0 !important;
    }
    .tier-bar {
      height: 6px;
      border-radius: 3px;
      background: #e5e7eb;
      overflow: hidden;
    }
    .tier-bar-fill {
      height: 100%;
      border-radius: 3px;
      transition: width 400ms ease;
    }
    .section-label {
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #6b7280;
    }
    .signal-prefix {
      font-size: 11px;
      color: #9ca3af;
      font-weight: 500;
    }
    button.toggle {
      background: none;
      border: none;
      cursor: pointer;
      color: #2563eb;
      font-size: 13px;
      padding: 0;
    }
    button.toggle:hover { color: #1d4ed8; text-decoration: underline; }
    .card {
      background: white;
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      padding: 20px 24px;
    }
    .rank-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: #f3f4f6;
      color: #374151;
      font-weight: 700;
      font-size: 14px;
      margin-right: 12px;
    }
    .tier-chip {
      display: inline-block;
      font-size: 11px;
      font-weight: 600;
      padding: 3px 9px;
      border-radius: 999px;
      color: white;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
  </style>
</head>
<body>
  <div class="max-w-5xl mx-auto px-6 py-10">

    <!-- Header -->
    <header class="mb-6">
      <div class="flex items-baseline justify-between flex-wrap gap-y-2">
        <div>
          <h1 class="text-3xl font-bold text-gray-900 mb-1">PostHog: Most Impactful Engineers</h1>
          <p class="text-sm text-gray-600">Ranked across 6 signals over the last 90 days.</p>
        </div>
        <div class="text-xs text-gray-500" id="scope-text"></div>
      </div>
      <button id="methodology-toggle" class="toggle mt-3">▾ See methodology</button>
    </header>

    <!-- Methodology drawer -->
    <section id="methodology" class="collapsible collapsed mb-6">
      <div class="card mt-3">
        <p class="text-sm text-gray-700 mb-5 leading-relaxed" id="methodology-intro"></p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" id="methodology-cards"></div>
      </div>
    </section>

    <!-- Engineer cards -->
    <main id="engineers" class="space-y-4"></main>

    <footer class="mt-10 text-xs text-gray-400 text-center" id="footer-text"></footer>
  </div>

  <script>
    // ─────────────────────────────────────────────────────────────────
    // Data (embedded from engineer-impact-analysis.json)
    // ─────────────────────────────────────────────────────────────────
    const DATA = __DATA_PLACEHOLDER__;

    // ─────────────────────────────────────────────────────────────────
    // Methodology copy — sourced from impact-signals.md
    // ─────────────────────────────────────────────────────────────────
    const METHODOLOGY = [
      {
        number: 1,
        name: "Shipping Consistency",
        captures: "Whether an engineer shows up reliably and ships work at a steady pace.",
        metrics: [
          "PR merge frequency",
          "Commit cadence + weekly consistency",
          "Average PR cycle time (open → merge)",
          "Average review rounds per PR",
        ],
        scored: true,
      },
      {
        number: 2,
        name: "Work Type Mix",
        captures: "Nature of contributions — features, fixes, refactor, churn.",
        metrics: [
          "PR label distribution (feat / fix / refactor / chore / etc.)",
        ],
        scored: false,
      },
      {
        number: 3,
        name: "Ownership Profile",
        captures: "Deep ownership of critical systems and/or cross-team breadth.",
        metrics: [
          "Depth (concentration in top 2 directories)",
          "Breadth (# distinct areas)",
          "Critical-area focus (% of files in high-impact code paths)",
          "Files touched across PRs",
        ],
        scored: true,
      },
      {
        number: 4,
        name: "Review Impact",
        captures: "Whether they make the rest of the team better.",
        metrics: [
          "Review volume",
          "Complexity of PRs reviewed",
          "Review comment depth",
          "Time to first review",
          "Times requested as reviewer",
        ],
        scored: true,
      },
      {
        number: 5,
        name: "Code Reliability",
        captures: "Whether their code sticks or gets reverted.",
        metrics: [
          "Revert rate (count of reverted PRs / total PRs)",
        ],
        scored: true,
        special: "Scored as (1 − revert_rate) × 100, not percentile-ranked.",
      },
      {
        number: 6,
        name: "Communication Quality",
        captures: "Whether they communicate their work clearly.",
        metrics: [
          "PR template section completeness (Problem / Changes / Testing)",
          "Testing-section substantively filled",
          "PR description length",
        ],
        scored: true,
      },
    ];

    // ─────────────────────────────────────────────────────────────────
    // Tier styling
    // ─────────────────────────────────────────────────────────────────
    function tierFromScore(score) {
      if (score >= 75) return "Exceptional";
      if (score >= 65) return "High";
      if (score >= 50) return "Solid";
      if (score >= 40) return "Average";
      return "Below avg.";
    }
    function tierColor(tier) {
      const map = {
        "Exceptional": "var(--tier-exceptional)",
        "High": "var(--tier-high)",
        "Solid": "var(--tier-solid)",
        "Average": "var(--tier-average)",
        "Below avg.": "var(--tier-belowavg)",
        "Emerging": "var(--tier-belowavg)",
      };
      return map[tier] || "var(--tier-solid)";
    }

    // ─────────────────────────────────────────────────────────────────
    // Synthesis: directory → human-readable area label
    // ─────────────────────────────────────────────────────────────────
    function dirToArea(dir) {
      if (!dir) return "the codebase";
      if (dir.startsWith("frontend/")) return "frontend";
      if (dir.startsWith("rust/") || dir === "rust") return "Rust backend";
      if (dir.startsWith("services/mcp")) return "MCP service";
      if (dir.startsWith("ee/hogai")) return "AI / HogAI";
      if (dir.startsWith("services/llm")) return "LLM services";
      if (dir.startsWith("products/llm_analytics")) return "LLM analytics";
      if (dir.startsWith("products/product_analytics")) return "product analytics";
      if (dir.startsWith("products/session_recordings")) return "session recordings";
      if (dir.startsWith("products/replay")) return "session replay";
      if (dir.startsWith("products/")) {
        return dir.replace("products/", "").replace(/_/g, " ");
      }
      if (dir.startsWith("posthog/api")) return "PostHog API";
      if (dir.startsWith("posthog/temporal")) return "Temporal workflows";
      if (dir.startsWith("posthog/hogql")) return "HogQL";
      if (dir.startsWith("posthog/")) return "PostHog core";
      if (dir === "plugin-server") return "plugin server";
      if (dir === "livestream") return "livestream";
      return dir;
    }
    function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }

    function synthesizeNarrative(eng) {
      // Overall summary across ALL scored signals. Qualitative, no raw counts.
      const domain = eng.raw_metrics.signal_3.primary_domain || "the codebase";
      // Use domain-aggregated depth for role descriptor (matches what the
      // dashboard shows); depth_score is the stable scoring metric.
      const depth = eng.raw_metrics.signal_3.primary_domain_share
        ?? eng.raw_metrics.signal_3.depth_score;
      const s3score = eng.signals.signal_3_ownership.score;

      // Role descriptor from primary domain + depth.
      let role;
      if (depth >= 0.7) role = cap(domain) + " specialist";
      else if (depth >= 0.4) role = cap(domain) + " contributor";
      else role = "Cross-domain engineer";

      // Ownership modifier — avoid "specialist with deep ownership" (redundant).
      // Only add a phrase for contributors with notable depth, OR for
      // cross-domain engineers with high overall ownership score (broad reach).
      let ownership = "";
      if (depth >= 0.7) {
        // specialist — depth implicit, no modifier
      } else if (depth >= 0.5) {
        ownership = " with solid ownership";
      } else if (depth < 0.4 && s3score >= 70) {
        ownership = " with broad reach across areas";
      }

      const lead = role + ownership + ".";

      // Per-signal descriptors based on score level.
      const desc = [];

      const s1 = eng.signals.signal_1_consistency.score;
      if (s1 >= 75) desc.push("ships consistently and quickly");
      else if (s1 >= 65) desc.push("steady shipper");

      const s4 = eng.signals.signal_4_review.score;
      if (s4 >= 75) desc.push("trusted code reviewer");
      else if (s4 >= 65) desc.push("active code reviewer");

      const s6 = eng.signals.signal_6_communication.score;
      if (s6 >= 75) desc.push("thorough communicator");
      else if (s6 >= 65) desc.push("clear communicator");

      const r5 = eng.raw_metrics.signal_5;
      if (r5.revert_count === 0 && r5.total_prs >= 50) {
        desc.push("no reverts in the window");
      } else if (eng.signals.signal_5_reliability.score >= 95 && r5.revert_count > 0) {
        desc.push("rare reverts");
      }

      let tail = "";
      if (desc.length > 0) {
        let joined;
        if (desc.length === 1) joined = desc[0];
        else if (desc.length === 2) joined = desc[0] + " and " + desc[1];
        else joined = desc.slice(0, -1).join(", ") + ", and " + desc[desc.length - 1];
        // Capitalize first letter of the descriptor list.
        joined = joined.charAt(0).toUpperCase() + joined.slice(1);
        tail = " " + joined + ".";
      }

      return lead + tail;
    }

    // ─────────────────────────────────────────────────────────────────
    // Natural-language strengths
    // ─────────────────────────────────────────────────────────────────
    const NL_STRENGTHS = {
      // Signal 1
      "PR cycle time": "Merges PRs quickly",
      "weekly consistency": "Ships work consistently week-to-week",
      "review rounds per PR": "Lands changes in few review rounds",
      // Signal 3
      "ownership depth": "Deeply owns their primary domain",
      "ownership breadth": "Works across many distinct areas",
      "critical-area focus": "Spends most time in critical code paths",
      "files touched": "Touches a broad swath of the codebase",
      // Signal 4
      "review volume": "Active code reviewer",
      "complexity reviewed": "Trusted with reviewing complex PRs",
      "review comment depth": "Leaves substantive review feedback",
      "first review speed": "Quick to respond to review requests",
      "times requested as reviewer": "Frequently sought out as reviewer",
      // Signal 6
      "PR template completeness": "Documents work thoroughly in PRs",
      "testing notes": "Explains testing approach clearly",
      "PR description length": "Writes detailed PR descriptions",
    };

    // Per user feedback: don't show volume-y strengths that would pull focus
    // to a single number (and would invite gaming).
    const EXCLUDED_STRENGTHS = new Set([
      "PR merge frequency",
      "commit cadence",
    ]);

    function computeStrengths(eng) {
      const all = [];
      const sigKeys = [
        "signal_1_consistency",
        "signal_3_ownership",
        "signal_4_review",
        "signal_6_communication",
      ];
      for (const sigKey of sigKeys) {
        const sig = eng.signals[sigKey];
        if (!sig || !sig.key_facts) continue;
        for (const fact of sig.key_facts) {
          // Parse "label: ... (NNth pct)"
          const m = fact.match(/^(.+?):\s.*\((\d+)th pct\)$/);
          if (!m) continue;
          all.push({
            label: m[1].trim(),
            percentile: parseInt(m[2]),
            signal: sig.label,
          });
        }
      }
      // Include Signal 5 (reliability) when they have a clean track record.
      const r5 = eng.raw_metrics.signal_5;
      const s5score = eng.signals.signal_5_reliability.score;
      if (r5.revert_count === 0 && r5.total_prs >= 50) {
        all.push({
          label: "Code Reliability",
          percentile: 100,  // direct score
          signal: "Code Reliability",
          _nl: "Code rarely needs reverting",
        });
      }

      const filtered = all.filter(m =>
        !EXCLUDED_STRENGTHS.has(m.label) &&
        m.percentile >= 50 &&
        (m._nl || NL_STRENGTHS[m.label])
      );
      filtered.sort((a, b) => b.percentile - a.percentile);

      // Deduplicate by natural-language phrase.
      const seen = new Set();
      const picked = [];
      for (const m of filtered) {
        const text = m._nl || NL_STRENGTHS[m.label];
        if (seen.has(text)) continue;
        seen.add(text);
        picked.push({ signal: m.signal, text });
        if (picked.length >= 3) break;
      }
      return picked;
    }

    // ─────────────────────────────────────────────────────────────────
    // Render functions
    // ─────────────────────────────────────────────────────────────────
    function renderMethodology() {
      document.getElementById("methodology-intro").innerHTML =
        DATA.scoring_methodology.approach;

      const cardsHtml = METHODOLOGY.map(s => {
        const badge = s.scored
          ? '<span class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded">Scored</span>'
          : '<span class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">Descriptive</span>';
        const metricsList = s.metrics.map(m => `<li>${m}</li>`).join("");
        const special = s.special
          ? `<div class="mt-2 text-[11px] text-gray-500 italic">${s.special}</div>`
          : "";
        return `
          <div class="border border-gray-200 rounded-md p-4 bg-gray-50">
            <div class="flex items-baseline justify-between mb-1">
              <h3 class="font-semibold text-sm text-gray-900">${s.number}. ${s.name}</h3>
              ${badge}
            </div>
            <p class="text-xs text-gray-600 mb-2">${s.captures}</p>
            <div class="section-label mb-1">What we measure</div>
            <ul class="text-xs text-gray-700 list-disc pl-4 space-y-0.5">${metricsList}</ul>
            ${special}
          </div>
        `;
      }).join("");
      document.getElementById("methodology-cards").innerHTML = cardsHtml;
    }

    function renderSignalRow(signalKey, signal) {
      const score = signal.score;
      const color = tierColor(tierFromScore(score));
      const facts = (signal.key_facts || [])
        .map(f => `<li class="text-[13px] text-gray-700 leading-relaxed">${f}</li>`)
        .join("");
      const isReliability = signalKey === "signal_5_reliability";
      const explanation = isReliability && signal.explanation
        ? `<div class="text-[11px] text-gray-500 italic mt-1">${signal.explanation}</div>`
        : "";
      return `
        <div class="border-l-2 pl-4" style="border-color:${color}">
          <div class="flex items-baseline justify-between mb-1">
            <span class="text-sm font-semibold text-gray-900">${signal.label}</span>
            <span class="text-sm font-mono text-gray-700">${score.toFixed(0)} / 100</span>
          </div>
          <div class="tier-bar mb-2">
            <div class="tier-bar-fill" style="width:${score}%; background:${color}"></div>
          </div>
          <ul class="space-y-0.5 list-disc pl-5">${facts}</ul>
          ${explanation}
        </div>
      `;
    }

    function renderWorkMixRow(eng) {
      return `
        <div class="border-l-2 pl-4 border-gray-300">
          <div class="flex items-baseline justify-between mb-1">
            <span class="text-sm font-semibold text-gray-900">Work Type Mix</span>
            <span class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">Descriptive — not scored</span>
          </div>
          <p class="text-[13px] text-gray-700">${eng.work_mix}</p>
        </div>
      `;
    }

    function renderEngineerCard(login, eng, rank) {
      const score = eng.overall_impact;
      const tier = eng.tier;
      const color = tierColor(tier);
      const narrative = synthesizeNarrative(eng);
      const strengths = computeStrengths(eng);
      const strengthsHtml = strengths.map(s => `
        <li class="text-[13px] text-gray-700 leading-relaxed">
          <span class="signal-prefix">[${s.signal}]</span> ${s.text}
        </li>
      `).join("");

      // Signal breakdown order: 1, 2 (work mix), 3, 4, 5, 6
      const signalOrder = [
        ["signal_1_consistency", () => renderSignalRow("signal_1_consistency", eng.signals.signal_1_consistency)],
        ["signal_2_workmix", () => renderWorkMixRow(eng)],
        ["signal_3_ownership", () => renderSignalRow("signal_3_ownership", eng.signals.signal_3_ownership)],
        ["signal_4_review", () => renderSignalRow("signal_4_review", eng.signals.signal_4_review)],
        ["signal_5_reliability", () => renderSignalRow("signal_5_reliability", eng.signals.signal_5_reliability)],
        ["signal_6_communication", () => renderSignalRow("signal_6_communication", eng.signals.signal_6_communication)],
      ];
      const breakdownHtml = signalOrder.map(([k, fn]) => fn()).join('<div class="h-3"></div>');

      const detailsId = `details-${login}`;

      return `
        <article class="card">
          <!-- Top row: rank, login, score, tier -->
          <div class="flex items-start justify-between gap-6">
            <div class="flex-1">
              <div class="flex items-center mb-2">
                <span class="rank-badge">#${rank}</span>
                <h2 class="text-xl font-bold text-gray-900">${login}</h2>
              </div>
              <p class="text-sm text-gray-700 leading-relaxed ml-11">${narrative}</p>
            </div>
            <div class="text-right flex-shrink-0">
              <div class="text-5xl font-bold leading-none mb-1.5" style="color:${color}">${score.toFixed(0)}</div>
              <span class="tier-chip" style="background:${color}">${tier}</span>
            </div>
          </div>

          <!-- Strengths -->
          <div class="mt-5 pt-5 border-t border-gray-100">
            <div class="section-label mb-2">Strengths</div>
            <ul class="space-y-1 list-none">${strengthsHtml}</ul>
          </div>

          <!-- Expand toggle -->
          <div class="mt-4">
            <button class="toggle expand-toggle" data-target="${detailsId}">▾ See signal breakdown</button>
          </div>

          <!-- Expanded details -->
          <div id="${detailsId}" class="collapsible collapsed">
            <div class="mt-5 pt-5 border-t border-gray-100 space-y-1">
              <div class="section-label mb-3">Signal breakdown</div>
              ${breakdownHtml}
            </div>
          </div>
        </article>
      `;
    }

    // ─────────────────────────────────────────────────────────────────
    // Interactions
    // ─────────────────────────────────────────────────────────────────
    function toggleMethodology() {
      const drawer = document.getElementById("methodology");
      const btn = document.getElementById("methodology-toggle");
      drawer.classList.toggle("collapsed");
      btn.textContent = drawer.classList.contains("collapsed")
        ? "▾ See methodology"
        : "▴ Hide methodology";
    }

    function toggleExpand(e) {
      const btn = e.currentTarget;
      const target = document.getElementById(btn.dataset.target);
      target.classList.toggle("collapsed");
      btn.textContent = target.classList.contains("collapsed")
        ? "▾ See signal breakdown"
        : "▴ Hide signal breakdown";
    }

    // ─────────────────────────────────────────────────────────────────
    // Init
    // ─────────────────────────────────────────────────────────────────
    function init() {
      renderMethodology();

      const cards = DATA.ranked_engineers.slice(0, 5).map((login, i) =>
        renderEngineerCard(login, DATA.engineers[login], i + 1)
      ).join("");
      document.getElementById("engineers").innerHTML = cards;

      document.getElementById("scope-text").textContent =
        `Showing top 5 of ${DATA.engineers_analyzed} active engineers`;

      const meta = DATA.metadata;
      const sinceDate = (meta.since || "").slice(0, 10);
      const repo = meta.repo || "";
      document.getElementById("footer-text").textContent =
        `Data: ${repo} · since ${sinceDate} · ${meta.days || 90} days`;

      document.getElementById("methodology-toggle")
        .addEventListener("click", toggleMethodology);
      document.querySelectorAll(".expand-toggle")
        .forEach(b => b.addEventListener("click", toggleExpand));
    }

    init();
  </script>
</body>
</html>
"""


def main():
    data = load_slim_data()
    data_json = json.dumps(data, ensure_ascii=False)
    html = HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
