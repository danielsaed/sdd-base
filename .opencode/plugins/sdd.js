// OpenCode adapter of the SDD workflow: the SAME hooks Claude Code runs, so both tools
// behave alike. Nothing here decides a rule; it only translates OpenCode's events into the
// JSON Claude Code sends to .claude/hooks/*.py and acts on their answer:
//
//   Claude Code hook                    OpenCode (this plugin)
//   PreToolUse   → agent_guard.py       tool.execute.before: exit 2 → throw (the agent reads why)
//   UserPromptSubmit → reminder.py      chat.message (main session) → its output goes into the
//                                       system prompt of that turn (experimental.chat.system.transform)
//   Stop         → closeout.py          event session.idle (main session): exit 2 → the reason is
//                                       sent back as a message, once per turn (`stop_hook_active`)
//   Bash run_in_background + notice     tools bg_run / bg_check (a notice arrives as a message)
//
// WHY one adapter instead of a port: the rules (.claude/permissions.json), the reminder and the
// close checks keep ONE home and ONE self-test (scripts/test-hooks.sh); this file only has to
// keep the translation right (scripts/verify/opencode_selftest.mjs, with a mutation case).
// Subagent = a session with a parent (OpenCode's task tool); its role is the agent's name,
// as `agent_type` in Claude Code. Generated variants (`implementer-haiku`) take their base role.
// Only exit 2 blocks, as in Claude Code: if python3 can't run, the hook is skipped.
import { spawn } from "node:child_process";
import { appendFileSync, createWriteStream, existsSync, mkdirSync, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const HOOKS = path.join(ROOT, ".claude", "hooks");
const EDITS = { edit: "Edit", write: "Write", multiedit: "MultiEdit" };
const PATCHES = new Set(["apply_patch", "patch"]);
const VARIANT = /-(haiku|sonnet|opus)$/; // scripts/sync-opencode.mjs, VARIANTS
// SDD_PLUGIN_LOG=/tmp/sdd.log opencode → one line per decision (which session, role, hook, exit).
const debug = (...a) => {
  if (process.env.SDD_PLUGIN_LOG) try { appendFileSync(process.env.SDD_PLUGIN_LOG, `${a.map((x) => typeof x === "string" ? x : JSON.stringify(x)).join(" ")}\n`); } catch { /* no log */ }
};

// Runs .claude/hooks/<script> with Claude Code's JSON on stdin → {code, out, err}.
function hook(script, payload, timeoutMs = 10000) {
  return new Promise((resolve) => {
    let out = "", err = "", done = false;
    const finish = (code) => { if (!done) { done = true; resolve({ code, out, err }); } };
    let p;
    try {
      p = spawn("python3", [path.join(HOOKS, script)], {
        cwd: ROOT, env: { ...process.env, CLAUDE_PROJECT_DIR: ROOT }, stdio: ["pipe", "pipe", "pipe"],
      });
    } catch { return finish(-1); }
    const timer = setTimeout(() => { p.kill(); finish(-1); }, timeoutMs);
    p.stdout.on("data", (d) => { out += d; });
    p.stderr.on("data", (d) => { err += d; });
    p.on("error", () => { clearTimeout(timer); finish(-1); });
    p.on("close", (code) => { clearTimeout(timer); finish(code); });
    p.stdin.on("error", () => {});
    p.stdin.end(JSON.stringify(payload));
  });
}

// Paths an apply_patch touches (`*** Add|Update|Delete File: p`, `*** Move to: p`).
function patchPaths(text) {
  return [...String(text ?? "").matchAll(/^\*\*\* (?:Add File|Update File|Delete File|Move to):\s*(.+?)\s*$/gm)].map((m) => m[1]);
}

// OpenCode tool call → the calls Claude Code would have sent to PreToolUse ([] = not guarded).
function claudeCalls(tool, args, directory) {
  args = args ?? {};
  const cwd = args.workdir ? path.resolve(directory, args.workdir) : directory;
  if (tool === "bash" || tool === "bg_run") return [{ tool_name: "Bash", tool_input: { command: String(args.command ?? "") }, cwd }];
  if (EDITS[tool]) return [{ tool_name: EDITS[tool], tool_input: { file_path: String(args.filePath ?? args.file_path ?? "") }, cwd }];
  if (PATCHES.has(tool)) {
    const paths = patchPaths(args.patchText ?? args.patch);
    // A patch whose files can't be read is judged as a write to an unknown file (the guard denies it to subagents).
    return (paths.length ? paths : [""]).map((p) => ({ tool_name: "Edit", tool_input: { file_path: p }, cwd }));
  }
  return [];
}

const tail = (file, n = 15) => {
  try { return readFileSync(file, "utf8").trimEnd().split("\n").slice(-n).join("\n"); } catch { return ""; }
};

export const SddWorkflow = async ({ client, directory }) => {
  directory = directory || ROOT;
  const parents = new Map(); // sessionID → parentID (null = main session)
  const agents = new Map(); // sessionID → agent name
  const reminders = new Map(); // sessionID → reminder.py output for the current turn
  const stopActive = new Set(); // main sessions that already got their closeout notice this turn
  const ours = new Map(); // sessionID → closeout notices sent and not yet received back
  const aborted = new Set(); // turns the user interrupted: stopping is theirs
  const agentDirs = [path.join(ROOT, ".claude", "agents")];

  async function parentOf(id) {
    if (!parents.has(id)) {
      try {
        const r = await client.session.get({ path: { id } });
        if (!r?.data) return undefined;
        parents.set(id, r.data.parentID ?? null);
      } catch { return undefined; }
    }
    return parents.get(id);
  }

  async function agentOf(id) {
    if (!agents.has(id)) {
      try {
        const r = await client.session.messages({ path: { id } });
        const a = (r?.data ?? []).map((m) => m.info?.agent ?? m.info?.mode).filter(Boolean).pop();
        if (a) agents.set(id, a);
      } catch { /* unknown: role `*` */ }
    }
    const a = agents.get(id) ?? "";
    const base = a.replace(VARIANT, "");
    return base !== a && agentDirs.some((d) => existsSync(path.join(d, `${base}.md`))) ? base : a;
  }

  // `continuing`: the message continues the current turn (the closeout notice, like Claude Code's
  // stop_hook_active); otherwise it opens a new one (a background job's notice).
  async function send(id, text, continuing) {
    if (continuing) ours.set(id, (ours.get(id) ?? 0) + 1);
    try {
      await client.session.promptAsync({ path: { id }, body: { parts: [{ type: "text", text }] } });
    } catch { if (continuing) ours.set(id, Math.max(0, (ours.get(id) ?? 1) - 1)); }
  }

  // ── Background jobs (Claude Code: Bash run_in_background + its completion notice) ──
  const jobs = new Map();
  let tools;
  try {
    const { tool } = await import("@opencode-ai/plugin");
    const z = tool.schema;
    const status = (j) => `job ${j.id} («${j.description}»): ${j.code === null ? "running" : `finished, exit ${j.code}`}` +
      ` · log ${j.log}\n${tail(j.log)}`;
    tools = {
      bg_run: tool({
        description: "Run a shell command in the BACKGROUND (CI watch `scripts/pr_wait.sh N`, builds, long suites). " +
          "Returns at once with a job id; in the main session a message arrives when it ends (exit code + last log lines): " +
          "don't sleep or poll for it. Subagents read the result with bg_check. Same permissions as bash.",
        args: {
          command: z.string().describe("The command, as you would give it to bash"),
          description: z.string().describe("5-10 words: what it waits for"),
          workdir: z.string().optional().describe("Working directory (default: the project)"),
        },
        async execute(args, ctx) {
          await ctx.ask({ permission: "bash", patterns: [args.command], always: [`${args.command.split(/\s+/)[0]} *`], metadata: { command: args.command } });
          const id = `bg${jobs.size + 1}-${Date.now().toString(36)}`;
          const logDir = path.join(os.tmpdir(), "opencode-bg");
          mkdirSync(logDir, { recursive: true });
          const j = { id, description: args.description, log: path.join(logDir, `${id}.log`), code: null, exited: null };
          const out = createWriteStream(j.log);
          const p = spawn("bash", ["-c", args.command], {
            cwd: args.workdir ? path.resolve(ctx.directory || directory, args.workdir) : ctx.directory || directory,
            env: { ...process.env, CLAUDE_PROJECT_DIR: ROOT }, stdio: ["ignore", "pipe", "pipe"],
          });
          p.stdout.pipe(out, { end: false });
          p.stderr.pipe(out, { end: false });
          j.exited = new Promise((res) => p.on("close", (code) => { j.code = code ?? -1; out.end(res); }));
          jobs.set(id, j);
          j.exited.then(async () => {
            if ((await parentOf(ctx.sessionID)) === null) await send(ctx.sessionID, `[background] ${status(j)}`, false);
          });
          return `Started ${id} in the background (log ${j.log}). ` +
            ((await parentOf(ctx.sessionID)) === null ? "A message will tell you when it ends: carry on." : "Read its result with bg_check.");
        },
      }),
      bg_check: tool({
        description: "State and last log lines of a bg_run job. `wait` (seconds, max 540) waits for it to end first.",
        args: { id: z.string(), wait: z.number().optional() },
        async execute(args) {
          const j = jobs.get(args.id);
          if (!j) return `No job ${args.id} (jobs: ${[...jobs.keys()].join(", ") || "none"}).`;
          if (args.wait && j.code === null) {
            await Promise.race([j.exited, new Promise((r) => setTimeout(r, Math.min(args.wait, 540) * 1000))]);
          }
          return status(j);
        },
      }),
    };
  } catch { /* @opencode-ai/plugin not installed (e.g. the self-test under node): hooks only */ }

  return {
    ...(tools ? { tool: tools } : {}),

    "tool.execute.before": async (input, output) => {
      const calls = claudeCalls(input.tool, output.args, directory);
      if (!calls.length) return;
      const parent = await parentOf(input.sessionID);
      // A session whose parent can't be read is judged as a subagent: a guard that doesn't know mustn't allow.
      const sub = parent !== null ? { agent_type: await agentOf(input.sessionID), agent_id: input.sessionID } : {};
      for (const c of calls) {
        const r = await hook("agent_guard.py", { session_id: input.sessionID, hook_event_name: "PreToolUse", ...c, ...sub });
        debug("guard", input.sessionID, { parent, ...sub, tool: input.tool, call: c, code: r.code });
        if (r.code === 2) throw new Error(r.err.trim() || "[guard] Blocked.");
      }
    },

    "chat.message": async (input, output) => {
      const id = input.sessionID;
      const agent = input.agent ?? output?.message?.agent;
      if (agent) agents.set(id, agent);
      debug("chat.message", id, { agent, parent: await parentOf(id) });
      if ((await parentOf(id)) !== null) return; // UserPromptSubmit is the main session's
      if (ours.get(id)) ours.set(id, ours.get(id) - 1);
      else { stopActive.delete(id); aborted.delete(id); } // a real user message opens a new turn
      const r = await hook("reminder.py", { session_id: id, hook_event_name: "UserPromptSubmit" });
      if (r.code === 0 && r.out.trim()) reminders.set(id, r.out.trim());
    },

    "experimental.chat.system.transform": async (input, output) => {
      const r = input?.sessionID && reminders.get(input.sessionID);
      if (r && Array.isArray(output?.system)) output.system.push(r);
    },

    event: async ({ event }) => {
      const id = event?.properties?.sessionID;
      if (!id) return;
      if (event.type === "session.error" && event.properties.error?.name === "MessageAbortedError") aborted.add(id);
      if (event.type !== "session.idle") return;
      if (aborted.delete(id) || (await parentOf(id)) !== null) return; // Stop is the main session's
      const active = stopActive.has(id);
      const r = await hook("closeout.py", { session_id: id, hook_event_name: "Stop", stop_hook_active: active });
      debug("closeout", id, { active, code: r.code });
      if (r.code === 2) { // closeout.py passes when stop_hook_active: the notice goes once per turn
        stopActive.add(id);
        await send(id, r.err.trim(), true);
      }
    },
  };
};
