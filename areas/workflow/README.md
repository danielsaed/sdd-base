# Workflow

> **Answers:** who may do what (roles, the permission guard), which resources each role
> reserves, how feature folders share files, and how Claude Code and OpenCode run the same
> workflow. **Update when:** a role, a permission,
> a reserved resource or a hook changes. The flow itself: [../README.md](../README.md).

## How it works

### Roles and permissions

| Role (model) | Does | Cannot |
|---|---|---|
| **orchestrator** (main session) | writes the spec, delegates, merges the PR, applies shared changes, closes docs | apply shared changes or merge without the user's OK; code what it can delegate |
| **reader** (`haiku`) | reads large outputs (logs, sweeps, long docs, query results) and returns ≤ ~15 lines with `file:line` | edit anything; same terminal rules as the reviewer |
| **planner** (`sonnet`) | reads the repo, writes `areas/<area>/open/<slug>/plan.md` | edit anything else, use the terminal |
| **implementer** (`sonnet`; `haiku` if the task is mechanical; `opus` if it gets stuck, or on a shared resource/security) | code + commits on ITS branch, in ITS folder; runs checks | push, merge, touch `main`, read `.env`, add dependencies, run protected commands |
| **reviewer** (`opus`) | runs the checks and the acceptance criteria | edit anything, install dependencies |

Each agent's `model:` header sets its default; the orchestrator may pass `model: haiku`
(mechanical task: texts, docs, renames, copying an existing pattern) or `model: opus`
(delicate task, implementer stuck) on the call — in OpenCode, whose task tool takes no
model, it launches the generated `implementer-haiku` / `implementer-opus` instead.

Permissions are enforced, not just written: each agent's `tools:` (`.claude/agents/`),
the `deny` rules in `.claude/settings.json` and the `agent_guard.py` hook, which reads
**`.claude/permissions.json`** (what each role edits and which commands it's denied, each
rule with its why; self-test with mutation in CI: `scripts/verify/guard_selftest.py`).
It stops mistakes by cooperative agents, not an attacker. The `reader` shares the
reviewer's read-only rules. **One fixed rule applies to everyone, the main session
included:** this repo's main checkout never leaves `main` — every session loads hooks,
guard, agents and scripts from it, so a `git switch`/`checkout` of another branch there
(also via `cd` or `git -C`) is blocked; switching back to `main`, `checkout -- <file>` and
anything inside a worktree stay allowed; other repos aren't affected. A branch = its folder
(`scripts/worktree.sh`). `main` means `MAIN_BRANCH`, whose one home is the CUSTOMIZE block
of `scripts/worktree.sh` (the hooks read it from there).

Hooks (in OpenCode, run by `.opencode/plugins/sdd.js`: «Claude Code and OpenCode» below):
`reminder.py` re-injects each open spec's step on every message, trimmed to stay under 600
characters (the rest of the rules live in the skill `sdd`), and shows a ⚠ when
the main checkout is on another branch (also seen from a worktree); `closeout.py` won't
let a turn end on a skipped step or an incomplete close, and recalls the close ritual (new
user preferences → `AGENTS.md`, pending → `BACKLOG.md`); both read `sdd_state.py`.
Self-test of all of them: `scripts/test-hooks.sh` (CI). `scripts/pr_wait.sh N [--merge]`
chains the CI/merge/deploy waits for a PR into ONE background notice instead of one per
step (self-test: `scripts/verify/pr_wait_selftest.sh`; its options, in
[scripts/verify/README.md](../../scripts/verify/README.md)); the guard denies subagents
`--merge` (rule `pr-wait-merge`).

### Resources per role
Agents only start and stop **their own** processes, never what the user has running.
Each role gets reserved resources so nobody steps on anyone; stop yours by its resource
(e.g. by port), never by process name. TODO: fill in for your project.

| Who | Reserved (example) | How |
|---|---|---|
| implementer | port `P` (the folder's `.port`), its folder | TODO: dev server / job |
| reviewer | `P`+200, `$TMPDIR/<project>-reviewer-*` | TODO |
| baseline of `main` | `P`+300, `scripts/baseline.sh` folder | TODO: what `run_baseline` does |
| user | TODO (e.g. a fixed port, the GPU, the main checkout) | **nobody else uses or stops it** |

`P` comes from a stable hash of the folder name (`scripts/worktree.sh`, `BASE_PORT`).

### Browser
The **Playwright MCP** is a project server (`.mcp.json`, pinned version, `--headless
--isolated --browser chromium`: no window, in-memory profile), generated into
`opencode.json` (OpenCode starts it as is; Claude Code asks you once to approve it);
`scripts/setup.sh` installs the exact Chromium its Playwright version needs. Who gets it:
the orchestrator, the implementer and the reviewer (an allowlist of `browser_*` tools in
`tools:`; no `browser_run_code_unsafe`, which runs code outside the page, nor
`browser_file_upload`, which reads local files); planner and reader don't. **One browser per
session**, shared by its agents: never two agents with it at once (the orchestrator says
who); `browser_close` when done. For most checks a command-line request is enough. Remove
`--headless` to watch it; another MCP server = one more entry in `.mcp.json`, then
`node scripts/sync-opencode.mjs`.

### Shared files
Shared files (secrets) are **linked** into each feature folder, not copied: a copy goes
stale as soon as a key rotates. Dependency folders are cloned. Both lists live in the
`CUSTOMIZE PER PROJECT` block of `scripts/worktree.sh` (also read by `scripts/baseline.sh`).
What each check measures: [scripts/verify/README.md](../../scripts/verify/README.md).

### Claude Code and OpenCode
One workflow, two tools. What Claude Code reads is the **source**; OpenCode either reads it
too or gets it from `scripts/sync-opencode.mjs` (generated files say so in their header;
CI checks they're in sync) or from the adapter `.opencode/plugins/sdd.js`, which runs the
same `.claude/hooks/*.py`:

| Piece | Claude Code | OpenCode |
|---|---|---|
| context, skill `sdd` | `AGENTS.md`, `.claude/skills/` | the same files (read natively) |
| agents | `.claude/agents/*.md` | `.opencode/agents/*.md`: generated; `tools:` → `permission:`, model alias → `MODELS` |
| main session's deny rules | `.claude/settings.json` | `opencode.json` `permission`: generated |
| MCP servers | `.mcp.json` | `opencode.json` `mcp`: generated |
| guard (PreToolUse) | `agent_guard.py` | the plugin, on `tool.execute.before` (subagent = session with a parent) |
| reminder (UserPromptSubmit) | `reminder.py` | the plugin: into the turn's system prompt |
| closeout (Stop) | `closeout.py` | the plugin, on `session.idle`: the notice comes back as a message, once per turn |
| background + notice | Bash `run_in_background` | tools `bg_run` (notice as a message) / `bg_check` |
| new session | `/clear` | `/new` |

Self-tests: `scripts/verify/opencode_selftest.mjs` (the adapter, CI) and
`opencode_e2e.mjs` (the real binary with a fake model; after upgrading OpenCode).
`SDD_PLUGIN_LOG=/tmp/sdd.log opencode` logs each decision of the plugin.

## Gotchas

- **The guard, agents and hooks that apply are the main branch's.** A change made on a
  feature branch applies to everyone once merged; measure a branch's guard by running
  its hook by path (`guard_selftest.py` does).
- **OpenCode doesn't hot-reload:** after `sync-opencode.mjs` or a plugin change, restart it.
  It takes the project folder from `$PWD` (not the process cwd) and installs
  `@opencode-ai/plugin` into `.opencode/` on start (without it, no `bg_run`/`bg_check`).
- **Subagents start with their cwd at the main root**, so their relative paths point to
  the user's checkout, not to their folder: give them absolute paths or `cd .worktrees/<name>`.

## Pending
- …

## Done
Last closed specs of this area: [done/](done/). Every one: [../HISTORY.md](../HISTORY.md).
