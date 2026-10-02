# <Project name> — project context

> **Entry point for ANY agent/AI/editor** (`AGENTS.md` standard; `CLAUDE.md` just points
> here). All context lives **in the repo** —this file, `docs/`, `areas/` and the code—,
> never in a tool's memory. Invariants only: no dated entries (that's git).
> **Limit: 150 lines** (`scripts/check-docs.mjs`).
>
> 👉 Fill in every `TODO` below when you bootstrap a project from this template.

## What it is
TODO: one paragraph — what the product is, for whom, and what matters most.

## About the author
TODO: background and how explanations should be pitched. Language for communication.
**Every answer ends with a "Status" block** (3 lines: *Running* · *Pending* · *Need from
you*): during long features the user only reads the last message. Anything left running
is watched with a completion notice (never "waiting for you to write").
**"Need from you" is self-contained**: full steps, where and what to copy; never "step 3"
or "as above". Whatever the user must read goes in that last message, even if said earlier.

## Stack
TODO: languages, frameworks, database, hosting — and where the "why" lives
(e.g. `docs/ARCHITECTURE.md`).

## Repo layout
```
areas/<area>/         # one subsystem: README (how it works · gotchas · pending), open/ specs, done/
areas/                # README.md (how areas/specs work), BACKLOG.md (what's next), HISTORY.md
docs/                 # only what ANY task needs (map below)
scripts/              # check-docs.mjs, worktree.sh, baseline.sh, test-hooks.sh
scripts/verify/       # reusable checks + their catalog (README.md), guard self-test
.claude/agents|hooks|skills   # permissioned agents, workflow hooks, skills
.claude/permissions.json      # what each subagent may do (read by the guard hook)
TODO: your source folders
```

## How we work (SDD flow, detail in [areas/README.md](areas/README.md))
**One feature = one spec = one branch `feat/<area>-<slug>` = one PR.** No numbers: a spec
is `<area>/<slug>`. The main session is the **orchestrator**: writes the spec, asks for
the OK and delegates; it doesn't code what it can delegate.

1. **Spec** (`areas/<area>/open/<slug>/spec.md` from `areas/_template/`) → **user OK**.
2. **Plan**: `planner` agent (read-only; writes `plan.md`).
3. **Code**: `implementer` agent(s), each in its own folder (`scripts/worktree.sh`).
4. **Verify**: `reviewer` agent (no edits) against the spec's criteria.
5. **Close**: area README + spec → `done/` + HISTORY line → PR with green CI → merge (with OK).

Hard rules: shared resources (single DB, infra) are **not** parallelized; only the
orchestrator applies shared changes, with OK; nothing reaches `main` without a PR;
creating, splitting or merging an area needs the user's OK.
Orchestrator manual: skill `sdd`. The hooks remind the current step on every message.

> **Before touching an area**, read its README (`areas/<area>/README.md`, above all
> «Gotchas») and [docs/GOTCHAS.md](docs/GOTCHAS.md).

## How to run
TODO: dev server (in a feature folder use the port in `.port`), database access,
environment files, and the command that re-syncs dependencies after a merge that changed
a lockfile (e.g. `npm ci`, `uv sync`).

## Verification (after ANY change)
TODO: adapt to your stack. The agents run exactly this list.
1. Type check / compile: `TODO`
2. Lint with zero warnings: `TODO`
3. Tests: `TODO`
4. Build, if routes/config/caching changed: `TODO`
5. Check what is actually SERVED/produced, not what you assume (curl, a diff script…).
6. **Tests:** only if they'd catch a bug that already happened or protect an invariant,
   with a mutation check (break the code → the test fails).
7. `node scripts/check-docs.mjs` if you touched docs.

## Documentation: map and rules
**One fact, ONE home.** If you're about to write the same thing in two docs, write a
link. No doc carries a changelog. Line limits in `scripts/check-docs.mjs` (CI): if a doc
goes over, **compact it**; only the user raises a limit.

| Doc | Answers |
|---|---|
| `AGENTS.md` | invariants: what it is, stack, flow, rules |
| `docs/GOTCHAS.md` | traps of the whole stack that already bit us |
| `docs/STATUS.md` | what exists today and where, area by area. In progress = open specs |
| TODO: `docs/*.md` | only what ANY task needs (e.g. ARCHITECTURE, CONVENTIONS) |
| `areas/README.md` | the flow, modes, areas (when to create one), spec lifecycle |
| `areas/<area>/README.md` | how that subsystem works · its gotchas · its pending work |
| `areas/<area>/open/<slug>/` | one feature in progress (spec + plan) |
| `areas/<area>/done/` | the area's 3 most recent closed specs (older: git history) |
| `areas/BACKLOG.md` | what's next, ordered across areas (detail in each area's Pending) |
| `areas/HISTORY.md` | one line per closed spec or docs PR, newest first |
| `areas/workflow/README.md` | roles, permissions, guard, resources per role |
| `scripts/verify/README.md` | which check measures what, and when to use it |

- Docs are updated **in the same PR** as the code.
- Every doc in `docs/` and every area README starts with *what it answers* and *when to
  update it*.
- If a fact stops being true, fix it or DELETE it; never keep it "just in case".
