#!/usr/bin/env node
// Line limits for the documentation. Runs in CI.
//
// WHY. A doc that grows unchecked stops being read, and an agent reads it only partly in
// long sessions. The limit forces COMPACTING (remove repetition, link instead of copying)
// instead of adding. If a doc goes over, the fix is to compact it; raising a limit is the
// user's decision, not the agent's who hit the warning.
//
// Usage: node scripts/check-docs.mjs   (from the repo root; exits 1 if something is over)
import { readFileSync, readdirSync, existsSync } from "node:fs";

// ── CUSTOMIZE PER PROJECT ────────────────────────────────────────────────────
const DEFAULT_DOCS = 200; // any docs/*.md not listed below
const LIMITS = {
  "AGENTS.md": 150,
  "README.md": 150,
  "docs/STATUS.md": 150,
  "specs/README.md": 100,
  "specs/BACKLOG.md": 80,
  "specs/_template/spec.md": 40,
  "specs/_template/plan.md": 40,
  "scripts/verify/README.md": 100,
};
// specs/NNN-*/spec.md: one feature, not an essay. The plan.md of an open spec does NOT count:
// it is a working document deleted at close, and trimming it to fit only took detail away
// from the implementer. The plan TEMPLATE does have a limit (above).
const SPEC = 120;
// ─────────────────────────────────────────────────────────────────────────────

const countLines = (f) => readFileSync(f, "utf8").split("\n").length - 1;
const files = { ...LIMITS };
if (existsSync("docs")) for (const f of readdirSync("docs")) if (f.endsWith(".md")) files[`docs/${f}`] ??= DEFAULT_DOCS;
if (existsSync("specs")) for (const d of readdirSync("specs", { withFileTypes: true })) {
  if (!d.isDirectory() || d.name.startsWith("_")) continue;
  files[`specs/${d.name}/spec.md`] ??= SPEC;
}

let bad = 0;
const rows = [];
for (const [f, limit] of Object.entries(files)) {
  if (!existsSync(f)) continue;
  const n = countLines(f);
  if (n > limit) bad++;
  rows.push(`${n <= limit ? "  " : "✗ "}${String(n).padStart(4)} / ${String(limit).padEnd(4)} ${f}`);
  // Every doc in docs/ says what it answers and when to update it (AGENTS.md rule).
  if (f.startsWith("docs/") && !/Answers:/.test(readFileSync(f, "utf8").slice(0, 800))) {
    bad++;
    rows.push(`✗ ${f}: missing the "Answers / Update when" header`);
  }
}
console.log(rows.join("\n"));
if (bad) {
  console.error(`\n${bad} problem(s). Compact the doc (repetition → links); only the user raises a limit.`);
  process.exit(1);
}
console.log(`\nDocs within their limits (${rows.length}).`);
