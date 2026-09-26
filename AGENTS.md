# <Project name> — project context

> **Entry point for ANY agent/AI/editor** (`AGENTS.md` standard; `CLAUDE.md` just points
> here). All context lives **in the repo** —this file, `docs/`, `specs/` and the code—,
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

## Stack
TODO: languages, frameworks, database, hosting — and where the "why" lives
(e.g. `docs/ARCHITECTURE.md`).

## Repo layout
```
specs/                # features IN PROGRESS + BACKLOG.md (the only pending list)
docs/                 # living docs (map below)
scripts/              # check-docs.mjs, worktree.sh (+ your verification scripts)
.claude/agents|hooks|skills   # permissioned agents, workflow hooks, skills
TODO: your source folders
```

## How we work (SDD flow, detail in [specs/README.md](specs/README.md))
**One feature = one spec = one branch `feat/NNN-slug` = one PR.** The main session is the
**orchestrator**: writes the spec, asks for the OK and delegates; it doesn't code what it
can delegate.

1. **Spec** (`specs/NNN-slug/spec.md` from `specs/_template/`) → **user OK**.
2. **Plan**: `planner` agent (read-only; writes `plan.md`).
3. **Code**: `implementer` agent(s), each in its own folder (`scripts/worktree.sh`).
4. **Verify**: `reviewer` agent (no edits) against the spec's criteria.
5. **Close**: docs + delete the spec folder → PR with green CI → merge (with OK).

Hard rules: shared resources (single DB, infra) are **not** parallelized; only the
orchestrator applies shared changes, with OK; nothing reaches `main` without a PR.
Orchestrator manual: skill `sdd`. The hooks remind the current step on every message.

> **Before touching an area**, read its section of [docs/GOTCHAS.md](docs/GOTCHAS.md).

## How to run
TODO: dev server (in a feature folder use the port in `.port`), database access,
environment files.

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
| `docs/GOTCHAS.md` | stack traps that already bit us |
| `docs/STATUS.md` | what exists today and where · work log (7). In progress = open specs |
| `specs/BACKLOG.md` | the only list of pending work |
| `specs/NNN-*/` | one feature in progress (deleted at close) |
| TODO: `docs/*.md` | one doc per subsystem / decision area |

- Docs are updated **in the same PR** as the code.
- Every doc in `docs/` starts with *what it answers* and *when to update it*.
- If a fact stops being true, fix it or DELETE it; never keep it "just in case".
