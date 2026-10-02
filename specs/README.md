# How we work: one feature = one spec = one branch = one PR

> **Answers:** the agent workflow — who does what, in which order, with which
> permissions. **Update when:** a step, role or permission changes. The orchestrator's
> operating manual is `.claude/skills/sdd/SKILL.md`.

## Flow

```
idea ─► 1 SPEC ─► ⏸ OK ─► 2 PLAN ─► 3 CODE ─► 4 VERIFY ─► 5 CLOSE ─► ⏸ OK ─► merge
        orchestrator       planner   implementer  reviewer    orchestrator
                           (reads)   (own folder) (no edits)  docs + PR
                                        ▲            │
                                        └──── ✗ ─────┘
```

- **Quick mode** (small fix, < ~1 h, no shared-resource change): 5-line spec →
  implementer → reviewer → close. Skips the planner, never the reviewer or the PR.
- **Docs mode** (only documentation changes): `scripts/worktree.sh docs-<topic>` →
  branch `docs/<topic>` → PR + CI. No spec, no reviewer; merged with OK like any PR.
- **Merge OK:** explicit, or **conditional** («merge if green»): CI is watched in the
  background; green → merge and tell the user; red → don't merge, tell the user why.
- **Parallel:** several features at once only if they don't touch a **shared resource**
  (a single database, shared infra). Those go one at a time. Within a feature, large
  disjoint tasks run in parallel with **one folder per agent** when possible; if agents
  share a folder, each one `git add`s **only its own files** (never `-A`, `.` or
  `commit -a`) and the orchestrator doesn't commit while they run.

## Roles and permissions

| Role | Does | Cannot |
|---|---|---|
| **orchestrator** (main session) | writes the spec, delegates, merges the PR, applies shared changes, closes docs | apply shared changes or merge without the user's OK; code what it can delegate |
| **planner** | reads the repo, writes `plan.md` | edit anything else, use the terminal |
| **implementer** | code + commits on ITS branch, in ITS folder; runs checks | push, merge, touch `main`, read `.env`, add dependencies, run protected commands |
| **reviewer** | runs the checks and the acceptance criteria | edit anything, install dependencies |

Permissions are enforced, not just written: each agent's `tools:` (`.claude/agents/`),
the `deny` rules in `.claude/settings.json` and the `agent_guard.py` hook, which reads
**`.claude/permissions.json`** (what each role edits and which commands it's denied, each
rule with its why; self-test with mutation in CI). It stops mistakes by cooperative
agents, not an attacker. Guard, agents and hooks load from the main checkout: **the main
branch's apply**; a change on a branch applies to everyone once merged. Subagents start
with their cwd at the main root, so their relative paths point there, not to their folder.

## Resources per role
Agents only start and stop **their own** processes, never what the user has running.
Each role gets reserved resources so nobody steps on anyone; stop yours by its resource
(e.g. by port), never by process name. TODO: fill in for your project.

| Who | Reserved (example) | How |
|---|---|---|
| implementer | port `P` (the folder's `.port`), its folder | TODO: dev server / job |
| reviewer | `P`+200, `$TMPDIR/<project>-reviewer-*` | TODO |
| baseline of `main` | `P`+300, `scripts/baseline.sh` folder | TODO: what `run_baseline` does |
| user | TODO (e.g. port 3000, the GPU, the main checkout) | **nobody else uses or stops it** |

Shared files (secrets) are **linked** into each folder, not copied. What each check
measures: [scripts/verify/README.md](../scripts/verify/README.md).

## Spec lifecycle

```
specs/012-flag-cache/spec.md   ← open (5-step checklist at the top)
specs/012-flag-cache/plan.md   ← written by the planner
        │ close
        ▼
what lasts → its topic doc (docs/*.md) · docs/STATUS.md
STATUS log: "012 flag cache: … (PR #34)"     ← one line
folder DELETED in the PR's last commit (git keeps it: git log --all -- specs/012-*)
```

Only **open** specs live in `specs/`: never a hundred. A spec describes **the change**
and is temporary; `docs/` describes **how things work** and is permanent (one fact, one home).

- Number: next free one (look at `specs/`, `.worktrees/` and `git log --oneline | grep 'spec '`).
- Branch: `feat/NNN-slug` (`docs/<topic>` in docs mode). Folder: `scripts/worktree.sh NNN-slug`.
- Pending work that isn't a spec yet: **[BACKLOG.md](BACKLOG.md)** (the only list).

## Rules most often forgotten

- **Shared changes** (database migrations, infra): only the orchestrator applies them,
  with the user's OK — before verification if they're backward compatible with `main`
  (so the reviewer measures against real state), otherwise right at merge.
- **Tests:** only if they'd catch a bug that already happened or protect an invariant
  (permissions, data contracts, security). Mutation check required: break the code on
  purpose and the test must fail; if it doesn't, it doesn't go in. Verifying ONE feature
  belongs in a reusable script, not a new test.
- **Docs:** line limits per doc in `scripts/check-docs.mjs` (runs in CI). Over the limit
  → compact; only the user raises a limit.
- **Memory:** the repo is the source of truth. Tool memories only hold session
  continuity; anything that matters later is written to a doc.
- **Nothing runs unwatched:** CI, builds and agents run in the background with a
  completion notice; never "waiting for the user to write".
