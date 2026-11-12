#!/usr/bin/env node
// End-to-end check of the workflow under the REAL OpenCode binary (no API key, no network
// to a model): a local fake model (OpenAI-compatible, scripted) drives a session in a
// throwaway copy of this repo and every request it receives is recorded and asserted.
//
// WHY. .opencode/plugins/sdd.js relies on OpenCode's plugin API (some of it `experimental.`)
// and on its task tool: an OpenCode upgrade can silently disconnect the guard, the reminder
// or the closeout. opencode_selftest.mjs checks the adapter's translation with a fake client;
// this checks that OpenCode still calls it. Run it after upgrading OpenCode or touching the
// plugin, the generator or the agents. Not in CI: it needs `opencode` (and npm, for the
// provider package OpenCode installs on first use).
//
// What the scripted session does, and what must happen:
//   main: `git switch -c e2e-x`        → blocked for everyone (the main checkout stays on main)
//   main: task → reader: `echo x > f`  → blocked by the guard as role reader (reviewer-redirect)
//   main: task → reviewer              → its tool list has the browser allowlist, no edit tool
//   main ends with main dirty          → ONE closeout notice comes back as a message
//   every main request carries the reminder in its system prompt; no subagent request does.
//
// Usage: node scripts/verify/opencode_e2e.mjs [-v]   (OPENCODE_BIN=… to pick the binary)
// Exit 0 all good · 1 something fails · 2 can't be set up (no opencode, timeout).
import { execFileSync, spawn, spawnSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const BIN = process.env.OPENCODE_BIN || "opencode";
const verbose = process.argv.includes("-v");
const setupFail = (m) => { console.error(`✗ can't set up: ${m}`); process.exit(2); };
if (spawnSync(BIN, ["--version"], { encoding: "utf8" }).status !== 0) setupFail(`no «${BIN}» on the PATH (npm i -g opencode-ai, or OPENCODE_BIN=…)`);

// ── Throwaway repo: this working tree, committed on main ──
const T = mkdtempSync(path.join(os.tmpdir(), "sdd-oc-e2e-"));
if (verbose) console.log(`· throwaway repo: ${T}`);
const cleanup = () => { if (!process.env.KEEP) rmSync(T, { recursive: true, force: true }); };
process.on("exit", cleanup);
const files = execFileSync("git", ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], { cwd: ROOT, encoding: "utf8" })
  .split("\0").filter(Boolean);
for (const f of files) {
  try { mkdirSync(path.dirname(path.join(T, f)), { recursive: true }); cpSync(path.join(ROOT, f), path.join(T, f)); } catch { /* deleted in the tree */ }
}
for (const f of readdirSync(path.join(T, ".opencode", "agents"))) { // subagents on the fake model too
  const p = path.join(T, ".opencode", "agents", f);
  writeFileSync(p, readFileSync(p, "utf8").replace(/^model: .*$/m, "model: fake/m"));
}
const env = { ...process.env, GIT_AUTHOR_NAME: "e2e", GIT_AUTHOR_EMAIL: "e2e@example.com", GIT_COMMITTER_NAME: "e2e", GIT_COMMITTER_EMAIL: "e2e@example.com" };
const g = (...a) => execFileSync("git", a, { cwd: T, env, stdio: "pipe" });
g("init", "-q"); g("symbolic-ref", "HEAD", "refs/heads/main"); g("add", "-A"); g("commit", "-qm", "base");
writeFileSync(path.join(T, "stray.txt"), "x\n"); // dirty main: the closeout must block once

// ── Fake model: decides by who is asking (system prompt) and how far the chat got ──
const log = [];
const text = (c) => (typeof c === "string" ? c : Array.isArray(c) ? c.map((p) => p.text ?? "").join("") : "");
function decide(body) {
  const sys = body.messages.filter((m) => m.role === "system").map((m) => text(m.content)).join("\n");
  const tools = (body.tools ?? []).map((t) => t.function?.name);
  const results = body.messages.filter((m) => m.role === "tool");
  const users = body.messages.filter((m) => m.role === "user");
  const lastUser = text(users.at(-1)?.content);
  const who = !tools.length ? "aux" : sys.includes("You are the **reader**") ? "reader"
    : sys.includes("You are the **reviewer**") ? "reviewer" : "main";
  log.push({ who, sys, tools, results: results.map((m) => text(m.content)), lastUser, turn: users.length });
  const call = (name, args) => ({ tool: { name, args } });
  if (who === "aux") return { text: "e2e" };
  // `git add` is denied to the reader wherever the repo lives (a path rule wouldn't do: the throwaway repo is in /tmp).
  if (who === "reader") return results.length ? { text: "reader done" } : call("bash", { command: "git add stray.txt", description: "stage a file" });
  if (who === "reviewer") return { text: "APPROVED (e2e)" };
  if (lastUser !== "E2E-START") return { text: "Noted; waiting for the user (e2e)." };
  const steps = [
    () => call("bash", { command: "git switch -c e2e-x", description: "leave main" }),
    () => call("task", { description: "e2e reader", prompt: "probe", subagent_type: "reader" }),
    () => call("task", { description: "e2e reviewer", prompt: "probe", subagent_type: "reviewer" }),
    () => call("bg_run", { command: "sleep 1; echo bg-ok", description: "e2e background job" }),
  ];
  const done = body.messages.filter((m) => m.role === "assistant" && m.tool_calls?.length).length;
  return done < steps.length ? steps[done]() : { text: "main done" };
}
let n = 0;
const fake = http.createServer((req, res) => {
  let raw = "";
  req.on("data", (d) => { raw += d; });
  req.on("end", () => {
    let r;
    try { r = decide(JSON.parse(raw)); } catch (e) { r = { text: `fake error ${e}` }; }
    const id = `c${++n}`, base = { id, object: "chat.completion.chunk", created: 1, model: "m" };
    const chunk = (delta, finish) => `data: ${JSON.stringify({ ...base, choices: [{ index: 0, delta, finish_reason: finish ?? null }] })}\n\n`;
    res.writeHead(200, { "content-type": "text/event-stream" });
    if (r.tool) {
      res.write(chunk({ role: "assistant", tool_calls: [{ index: 0, id: `call_${n}`, type: "function", function: { name: r.tool.name, arguments: JSON.stringify(r.tool.args) } }] }));
      res.write(chunk({}, "tool_calls"));
    } else {
      res.write(chunk({ role: "assistant", content: r.text }));
      res.write(chunk({}, "stop"));
    }
    res.write(`data: ${JSON.stringify({ ...base, choices: [], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } })}\n\n`);
    res.end("data: [DONE]\n\n");
  });
});
const listen = (srv) => new Promise((r) => srv.listen(0, "127.0.0.1", () => r(srv.address().port)));
const port = await listen(fake);
const probe = http.createServer(); // a free port for `opencode serve`
const ocPort = await listen(probe);
await new Promise((r) => probe.close(r));

const config = {
  model: "fake/m", small_model: "fake/m",
  provider: { fake: { npm: "@ai-sdk/openai-compatible", name: "fake", options: { baseURL: `http://127.0.0.1:${port}/v1`, apiKey: "x" },
    models: { m: { name: "m", tool_call: true, limit: { context: 100000, output: 4000 } } } } },
};
// `serve`, not `run`: like the TUI, it stays alive after the turn (`run` exits before session.idle).
// PWD too: OpenCode takes its project folder from $PWD, not from the process cwd.
const pluginLog = path.join(T, ".git", "sdd-plugin.log");
const oc = spawn(BIN, ["serve", "--port", String(ocPort), "--hostname", "127.0.0.1"], {
  cwd: T, env: { ...env, PWD: T, SDD_PLUGIN_LOG: pluginLog, OPENCODE_CONFIG_CONTENT: JSON.stringify(config) }, stdio: ["ignore", "pipe", "pipe"],
});
let out = "";
oc.stdout.on("data", (d) => { out += d; });
oc.stderr.on("data", (d) => { out += d; });
process.on("exit", () => oc.kill());
const api = async (p, body, ms) => {
  const r = await fetch(`http://127.0.0.1:${ocPort}${p}`, {
    method: body ? "POST" : "GET", headers: { "content-type": "application/json" }, body: body && JSON.stringify(body),
    ...(ms ? { signal: AbortSignal.timeout(ms) } : {}),
  });
  return r.json();
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ready = false, session;
for (let i = 0; i < 120 && !ready; i++) { try { ready = Boolean((await api("/path", null, 3000)).directory); } catch { await sleep(500); } }
for (let i = 0; i < 5 && !session?.id; i++) { try { session = await api("/session", {}, 30000); } catch { await sleep(1000); } }
if (!session?.id) setupFail(`opencode serve didn't answer. It said:\n${out.slice(-1500)}`);
const kill = setTimeout(() => setupFail("timeout (240 s)"), 240000);
await api(`/session/${session.id}/message`, { parts: [{ type: "text", text: "E2E-START" }] });
// The closeout and background notices arrive as new messages after the turn: give them time.
const has = (s) => log.some((l) => l.who === "main" && l.lastUser.includes(s));
for (let i = 0; i < 60 && !(has("[SDD flow] Before finishing") && has("[background]")); i++) await sleep(500);
await sleep(3000); // a second closeout notice in the same turn would show up here
clearTimeout(kill);
fake.close();
oc.kill();
if (verbose) console.log(readFileSync(pluginLog, { encoding: "utf8", flag: "a+" }));
if (verbose) console.log(out.slice(-2000), JSON.stringify(log.map(({ sys, ...l }) => ({ ...l, tools: l.tools.length })), null, 1));
if (!log.some((l) => l.who === "main")) setupFail(`the fake model got no main request. opencode said:\n${out.slice(-1500)}`);

// ── Assertions ──
let fails = 0;
const ok = (cond, what) => { console.log(`${cond ? "✓" : "✗"} ${what}`); if (!cond) fails++; };
const main = log.filter((l) => l.who === "main"), reader = log.filter((l) => l.who === "reader"), reviewer = log.filter((l) => l.who === "reviewer");
const results = main.flatMap((l) => l.results);
ok(results.some((r) => /\[guard · main session\] Blocked: the main checkout .* ALWAYS stays on main/.test(r)), "main session: `git switch -c` in the main checkout is blocked");
ok(g("branch", "--show-current").toString().trim() === "main", "the throwaway main checkout is still on main");
ok(reader.some((l) => l.results.some((r) => r.includes("[guard · reader] Blocked"))), "reader subagent: `git add` blocked by the guard as role reader");
ok(!g("diff", "--cached", "--name-only").toString().trim(), "nothing got staged");
const turn1 = main.filter((l) => l.lastUser === "E2E-START");
ok(turn1.length > 0 && turn1.every((l) => l.sys.includes("[SDD reminder")), `every request of the user's turn carries the reminder (${turn1.length})`);
ok(reader.length > 0 && [...reader, ...reviewer].every((l) => !l.sys.includes("[SDD reminder")), "no subagent request carries it");
// Turns in order (a turn = a new user-side message); the closeout notice comes once per turn: never twice in a row.
const turns = [...new Map(main.map((l) => [l.turn, l.lastUser])).values()];
const notices = turns.filter((t) => t.includes("[SDD flow] Before finishing"));
ok(notices.length >= 1 && notices[0].includes("UNCOMMITTED changes on main"), "the closeout notice came back as a message (dirty main)");
ok(!turns.some((t, i) => i && t.includes("[SDD flow]") && turns[i - 1].includes("[SDD flow]")), `…once per turn, never twice in a row (turns: ${turns.map((t) => t.slice(0, 14)).join(" | ")})`);
ok(turns.some((t) => /^\[background\] job .*finished, exit 0[\s\S]*bg-ok/.test(t)), "bg_run: its end came back as a message with exit code and log");
const rt = reviewer[0]?.tools ?? [];
ok(rt.includes("bash") && !rt.includes("edit") && !rt.includes("write"), `reviewer: bash, no edit/write (${rt.filter((t) => !t.startsWith("playwright_")).join(" ")})`);
const mcpUp = main.some((l) => l.tools.some((t) => t.startsWith("playwright_")));
if (mcpUp) {
  ok(rt.includes("playwright_browser_navigate") && !rt.includes("playwright_browser_run_code_unsafe"), "reviewer: browser allowlist (navigate yes, run_code_unsafe no)");
  ok(!(reader[0]?.tools ?? []).some((t) => t.startsWith("playwright_")), "reader: no browser tools");
} else console.log("· the Playwright MCP didn't connect (npx offline?): browser allowlist not measured");
console.log(fails ? `\n${fails} failure(s)` : "\n✓ OpenCode e2e passed");
process.exit(fails ? 1 : 0);
