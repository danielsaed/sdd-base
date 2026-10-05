# Workflow

> **Answers:** who may do what (roles, the permission guard), which resources each role
> reserves, and how feature folders share files. **Update when:** a role, a permission,
> a reserved resource or a hook changes. The flow itself: [../README.md](../README.md).

## How it works

### Roles and permissions

| Role (model) | Does | Cannot |
|---|---|---|
| **orchestrator** (main session) | writes the spec, delegates, merges the PR, applies shared changes, closes docs | apply shared changes or merge without the user's OK; code what it can delegate |
| **planner** (`sonnet`) | reads the repo, writes `areas/<area>/open/<slug>/plan.md` | edit anything else, use the terminal |
| **implementer** (`sonnet`; `opus` if it gets stuck, or on a shared resource/security) | code + commits on ITS branch, in ITS folder; runs checks | push, merge, touch `main`, read `.env`, add dependencies, run protected commands |
| **reviewer** (`opus`) | runs the checks and the acceptance criteria | edit anything, install dependencies |

Each agent's `model:` header sets its default; the orchestrator may pass `model: opus` on
the call for a delicate task or when the implementer is stuck.

Permissions are enforced, not just written: each agent's `tools:` (`.claude/agents/`),
the `deny` rules in `.claude/settings.json` and the `agent_guard.py` hook, which reads
**`.claude/permissions.json`** (what each role edits and which commands it's denied, each
rule with its why; self-test with mutation in CI: `scripts/verify/guard_selftest.py`).
It stops mistakes by cooperative agents, not an attacker.

Hooks: `reminder.py` re-injects each open spec's step on every message, trimmed to stay
under 600 characters (the rest of the rules live in the skill `sdd`); `closeout.py` won't
let a turn end on a skipped step or an incomplete close, and recalls the close ritual (new
user preferences → `AGENTS.md`, pending → `BACKLOG.md`); both read `sdd_state.py`.
Self-test of all of them: `scripts/test-hooks.sh` (CI). `scripts/pr_wait.sh N [--merge]`
chains the CI/merge/deploy waits for a PR into ONE background notice instead of one per
step (self-test: `scripts/verify/pr_wait_selftest.sh`); the guard denies subagents
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

### Shared files
Shared files (secrets) are **linked** into each feature folder, not copied: a copy goes
stale as soon as a key rotates. Dependency folders are cloned. Both lists live in the
`CUSTOMIZE PER PROJECT` block of `scripts/worktree.sh` (also read by `scripts/baseline.sh`).
What each check measures: [scripts/verify/README.md](../../scripts/verify/README.md).

## Gotchas

- **The guard, agents and hooks that apply are the main branch's.** A change made on a
  feature branch applies to everyone once merged; measure a branch's guard by running
  its hook by path (`guard_selftest.py` does).
- **Subagents start with their cwd at the main root**, so their relative paths point to
  the user's checkout, not to their folder: give them absolute paths or `cd .worktrees/<name>`.

## Pending
- …

## Done
Last closed specs of this area: [done/](done/). Every one: [../HISTORY.md](../HISTORY.md).
