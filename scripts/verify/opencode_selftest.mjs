#!/usr/bin/env node
// Self-test of .opencode/plugins/sdd.js, the adapter that runs Claude Code's hooks under
// OpenCode. The RULES are tested elsewhere (guard_selftest.py, test-hooks.sh); this tests
// the TRANSLATION, which is what breaks silently: a tool name OpenCode spells differently,
// a subagent taken for the main session, a closeout notice sent twice per turn.
// No OpenCode binary needed (CI): the plugin is called with a fake client, in a throwaway
// repo OUTSIDE temp folders (the guard allows writes in temp folders, so /tmp would hide
// path rules). Real OpenCode end to end: opencode_e2e.mjs.
//
// Built-in mutation: each MUTANTS entry breaks one piece of the adapter; some case must
// fail on it, or this test doesn't cover that piece.
//
// Usage: node scripts/verify/opencode_selftest.mjs [-v]   (exit 0 ok · 1 fails · 2 setup)
import { execFileSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const verbose = process.argv.includes("-v");
const base = path.join(os.homedir(), ".cache");
mkdirSync(base, { recursive: true });
const T = mkdtempSync(path.join(base, "sdd-opencode-selftest-"));
process.on("exit", () => rmSync(T, { recursive: true, force: true }));
const env = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.com", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.com" };
const g = (...a) => execFileSync("git", a, { cwd: T, env, stdio: "pipe" }).toString().trim();
try {
  for (const f of execFileSync("git", ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], { cwd: ROOT, encoding: "utf8" }).split("\0").filter(Boolean)) {
    try { mkdirSync(path.dirname(path.join(T, f)), { recursive: true }); cpSync(path.join(ROOT, f), path.join(T, f)); } catch { /* deleted */ }
  }
  g("init", "-q"); g("symbolic-ref", "HEAD", "refs/heads/main"); g("add", "-A"); g("commit", "-qm", "base");
  // The mutant lives next to the plugin (its root is found from its own path) but mustn't dirty main.
  writeFileSync(path.join(T, ".git", "info", "exclude"), ".opencode/plugins/mutant.js\n", { flag: "a" });
} catch (e) { console.error(`✗ can't build the throwaway repo: ${e}`); process.exit(2); }
const PLUGIN = path.join(T, ".opencode", "plugins", "sdd.js");
const SOURCE = readFileSync(PLUGIN, "utf8");

// Sessions: M = main, R/RV/PL/I = subagents (reader, reader-haiku, planner, implementer-haiku), X = unreadable.
const PARENTS = { M: null, R: "M", RV: "M", PL: "M", I: "M", I2: "M" };
const AGENTS = { R: "reader", RV: "reader-haiku", PL: "planner", I: "implementer-haiku", I2: "implementer" };
function fakeClient() {
  const sent = [];
  return {
    sent,
    session: {
      get: async ({ path: { id } }) => { if (!(id in PARENTS)) throw new Error("unreadable"); return { data: { id, parentID: PARENTS[id] ?? undefined } }; },
      messages: async ({ path: { id } }) => ({ data: AGENTS[id] ? [{ info: { role: "user", agent: AGENTS[id] } }] : [] }),
      promptAsync: async ({ path: { id }, body }) => { sent.push({ id, text: body.parts.map((p) => p.text).join("") }); },
    },
  };
}

async function suite(file, loud = false) {
  const mod = await import(`${pathToFileURL(file).href}?v=${Math.random()}`);
  const plugin = Object.values(mod).find((x) => typeof x === "function");
  const client = fakeClient();
  const h = await plugin({ client, directory: T, worktree: T });
  const fails = [];
  const check = (cond, what) => { if (!cond) fails.push(what); if (loud) console.log(`  ${cond ? "✓" : "✗"} ${what}`); };
  const blocked = async (sid, tool, args) => {
    try { await h["tool.execute.before"]({ tool, sessionID: sid, callID: "c" }, { args }); return ""; } catch (e) { return String(e.message); }
  };
  const W = path.join(T, ".worktrees", "workflow-x");

  // ── Guard: OpenCode tool calls → Claude Code's PreToolUse JSON ──
  check((await blocked("R", "bash", { command: "git add stray.txt" })).includes("[guard · reader] Blocked"), "reader: bash `git add` → blocked as reader");
  check((await blocked("M", "bash", { command: "git add stray.txt" })) === "", "main session: the same command → allowed");
  check((await blocked("RV", "bash", { command: "git add stray.txt" })).includes("[guard · reader] Blocked"), "reader-haiku (a variant) → its base role, reader");
  check((await blocked("PL", "bash", { command: "ls" })).includes("planner doesn't use the terminal"), "planner: bash → blocked");
  check((await blocked("I", "edit", { filePath: path.join(T, "src", "x.js") })).includes("only edits inside its feature folder"), "implementer-haiku: edit in the main checkout → blocked");
  check((await blocked("I", "write", { filePath: path.join(W, "x.js") })) === "", "implementer-haiku: write in its feature folder → allowed");
  check((await blocked("I2", "apply_patch", { patchText: "*** Begin Patch\n*** Update File: src/x.js\n@@\n-a\n+b\n*** End Patch" })) !== "", "implementer: apply_patch on a main-checkout file → blocked");
  check((await blocked("I2", "apply_patch", { patchText: `*** Begin Patch\n*** Add File: ${W}/y.js\n+a\n*** End Patch` })) === "", "implementer: apply_patch inside its folder → allowed");
  check((await blocked("I2", "apply_patch", { patchText: "garbage" })) !== "", "implementer: a patch whose files can't be read → blocked");
  check((await blocked("I2", "bash", { command: "rm -rf build" })).includes("rm -r outside"), "implementer: `rm -rf build` from the main root → blocked");
  check((await blocked("I2", "bash", { command: "rm -rf build", workdir: ".worktrees/workflow-x" })) === "", "implementer: the same with workdir = its folder → allowed (workdir is the cwd)");
  check((await blocked("X", "bash", { command: "git push" })).includes("Blocked"), "a session whose parent can't be read → judged as a subagent");
  check((await blocked("I2", "bg_run", { command: "git push" })).includes("push"), "bg_run goes through the guard like bash");
  check((await blocked("R", "read", { filePath: "x" })) === "", "tools the guard doesn't judge (read) → untouched");

  // ── Reminder: UserPromptSubmit → the system prompt of the turn, main session only ──
  await h["chat.message"]({ sessionID: "M", agent: "build" }, { message: {}, parts: [] });
  const sys = { system: [] };
  await h["experimental.chat.system.transform"]({ sessionID: "M" }, sys);
  check(sys.system.some((s) => s.includes("[SDD reminder")), "main session: the reminder goes into the system prompt");
  await h["chat.message"]({ sessionID: "R", agent: "reader" }, { message: {}, parts: [] });
  const sub = { system: [] };
  await h["experimental.chat.system.transform"]({ sessionID: "R" }, sub);
  check(sub.system.length === 0, "subagent: no reminder");

  // ── Closeout: Stop → session.idle; exit 2 → the notice comes back as a message, once per turn ──
  const idle = (id) => h.event({ event: { type: "session.idle", properties: { sessionID: id } } });
  const notices = () => client.sent.filter((s) => s.text.includes("[SDD flow] Before finishing")).length;
  writeFileSync(path.join(T, "stray.txt"), "x\n"); // uncommitted changes on main: closeout blocks
  await idle("M");
  check(notices() === 1 && client.sent[0]?.text.includes("UNCOMMITTED changes on main"), "dirty main: idle → one closeout notice");
  await h["chat.message"]({ sessionID: "M", agent: "build" }, { message: {}, parts: [] }); // the notice itself arrives
  await idle("M");
  check(notices() === 1, "…not again in the same turn (stop_hook_active)");
  await h["chat.message"]({ sessionID: "M", agent: "build" }, { message: {}, parts: [] }); // the user writes
  await idle("M");
  check(notices() === 2, "a new user message → a new turn → notified again");
  await idle("R");
  check(notices() === 2, "a subagent going idle → no closeout");
  await h["chat.message"]({ sessionID: "M", agent: "build" }, { message: {}, parts: [] });
  await h.event({ event: { type: "session.error", properties: { sessionID: "M", error: { name: "MessageAbortedError" } } } });
  await idle("M");
  check(notices() === 2, "the user interrupted the turn → no closeout");
  rmSync(path.join(T, "stray.txt"));
  await h["chat.message"]({ sessionID: "M", agent: "build" }, { message: {}, parts: [] });
  await idle("M");
  check(notices() === 2, "clean state → no notice");
  return fails;
}

const MUTANTS = [
  ["bash isn't translated", 'if (tool === "bash" || tool === "bg_run")', 'if (tool === "Bash" || tool === "bg_run")'],
  ["the subagent's role isn't passed", "agent_type: await agentOf(input.sessionID)", 'agent_type: ""'],
  ["variants keep their own name", 'return base !== a && agentDirs', "return false && agentDirs"],
  ["workdir ignored", "const cwd = args.workdir ? path.resolve(directory, args.workdir) : directory;", "const cwd = directory;"],
  ["unknown parent = main session", "const sub = parent !== null ?", "const sub = parent ?"],
  ["stop_hook_active not passed", "stop_hook_active: active", "stop_hook_active: false"],
  ["reminder to subagents too", 'if ((await parentOf(id)) !== null) return; // UserPromptSubmit', "if (false) return; // UserPromptSubmit"],
  ["unreadable patch passes", '(paths.length ? paths : [""])', "paths"],
];

let bad = 0;
const fails = await suite(PLUGIN, verbose);
for (const f of fails) console.log(`✗ ${f}`);
bad += fails.length;
console.log(`${fails.length ? "✗" : "✓"} adapter cases (${fails.length} failing)`);
if (!process.argv.includes("--no-mutation")) {
  for (const [name, from, to] of MUTANTS) {
    if (!SOURCE.includes(from)) { console.log(`✗ mutation «${name}»: its code isn't in the plugin anymore (update MUTANTS)`); bad++; continue; }
    const file = path.join(T, ".opencode", "plugins", "mutant.js");
    writeFileSync(file, SOURCE.replace(from, to));
    g("checkout", "-q", "--", "."); // each mutant starts from a clean main
    const failed = await suite(file);
    if (!failed.length) { console.log(`✗ mutation «${name}»: no case fails (the test doesn't cover it)`); bad++; }
    else if (verbose) console.log(`  ✓ mutation «${name}» caught by: ${failed.join(" · ")}`);
  }
  console.log(`${bad ? "✗" : "✓"} mutation: ${MUTANTS.length} mutants`);
}
console.log(bad ? `\n${bad} failure(s)` : "\n✓ OpenCode adapter self-test passed");
process.exit(bad ? 1 : 0);
