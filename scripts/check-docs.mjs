#!/usr/bin/env node
// Line limits for the documentation, and the areas' shape. Runs in CI.
//
// WHY. A doc that grows unchecked stops being read, and an agent reads it only partly in
// long sessions. The limit forces COMPACTING (remove repetition, link instead of copying)
// instead of adding. If a doc goes over, the fix is to compact it; raising a limit is the
// user's decision, not the agent's who hit the warning.
// Each area keeps only its KEEP_DONE most recent closed specs in done/ (the rest live in
// main's history, recoverable: areas/README.md): more fails, so done/ never piles up.
//
// Usage: node scripts/check-docs.mjs   (from the repo root; exits 1 if something is over)
import { readFileSync, readdirSync, existsSync } from "node:fs";

// ── CUSTOMIZE PER PROJECT ────────────────────────────────────────────────────
const DEFAULT_DOCS = 200; // any docs/*.md, areas/<area>/*.md (README included) not listed below
const LIMITS = {
  "AGENTS.md": 150,
  "README.md": 150,
  "docs/STATUS.md": 150,
  "areas/README.md": 130,
  "areas/BACKLOG.md": 80,
  "areas/_template/README.md": 40,
  "areas/_template/spec.md": 40,
  "areas/_template/plan.md": 40,
  "scripts/verify/README.md": 100,
};
// areas/<area>/open/<slug>/spec.md: one feature, not an essay. The plan.md of an open spec
// does NOT count: it is a working document deleted at close, and trimming it to fit only
// took detail away from the implementer. The plan TEMPLATE does have a limit (above).
// No limit either for areas/HISTORY.md (one line per spec, never edited) or done/* (closed
// specs, frozen; KEEP_DONE caps how many).
const SPEC = 120;
const KEEP_DONE = 3;
// ─────────────────────────────────────────────────────────────────────────────

const countLines = (f) => readFileSync(f, "utf8").split("\n").length - 1;
const dirs = (d) => (existsSync(d) ? readdirSync(d, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => e.name) : []);
const mds = (d) => (existsSync(d) ? readdirSync(d).filter((f) => f.endsWith(".md")) : []);
const files = { ...LIMITS };
const header = new Set(["docs/STATUS.md", "areas/README.md", "areas/BACKLOG.md", "areas/HISTORY.md"]);
for (const f of mds("docs")) { files[`docs/${f}`] ??= DEFAULT_DOCS; header.add(`docs/${f}`); }

let bad = 0;
const rows = [];
for (const area of dirs("areas").filter((a) => !a.startsWith("_"))) {
  const base = `areas/${area}`;
  if (!existsSync(`${base}/README.md`)) { bad++; rows.push(`✗ ${base}: an area needs a README.md (areas/_template/README.md)`); }
  for (const f of mds(base)) files[`${base}/${f}`] ??= DEFAULT_DOCS;
  header.add(`${base}/README.md`);
  for (const slug of dirs(`${base}/open`)) files[`${base}/open/${slug}/spec.md`] ??= SPEC;
  const done = mds(`${base}/done`);
  if (done.length > KEEP_DONE) {
    bad++;
    rows.push(`✗ ${base}/done: ${done.length} closed specs, keep the ${KEEP_DONE} most recent (delete the oldest: git history keeps it)`);
  }
}

for (const [f, limit] of Object.entries(files)) {
  if (!existsSync(f)) continue;
  const n = countLines(f);
  if (n > limit) bad++;
  rows.push(`${n <= limit ? "  " : "✗ "}${String(n).padStart(4)} / ${String(limit).padEnd(4)} ${f}`);
}
// Every living doc says what it answers and when to update it (AGENTS.md rule).
for (const f of header) {
  if (existsSync(f) && !/Answers:/.test(readFileSync(f, "utf8").slice(0, 800))) {
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
