# sdd-base

A starter repo for **spec-driven development with Claude Code**: the main session acts as
an **orchestrator** that writes a spec, gets your OK and delegates the work to three
permissioned subagents — **planner**, **implementer** and **reviewer** — one feature per
branch and per pull request.

It's stack-agnostic: you plug in your own verification commands.

## Why

- **Parallel features, longer context.** The orchestrator delegates, so its context window
  lasts and independent features run side by side in isolated git worktrees.
- **Nothing reaches `main` unverified.** An independent reviewer tries to prove each
  feature does *not* meet its spec, measuring with commands, not opinions.
- **Permissions are enforced, not just written.** A hook knows which agent issues each
  command and judges what it *does* (through variables, `bash -c`, `$(…)`, symlinks…):
  the reviewer can't edit, the planner only writes its plan, the implementer can't push,
  merge, touch `main`, read `.env` or add dependencies. Rules live in one JSON file, each
  with its why, and a self-test with mutation checks every rule in CI.
- **Agents don't step on each other or on you.** One folder per feature (secrets linked,
  not copied), `git add` only of your own files, reserved resources per role, and
  comparisons against `main` in a disposable copy, never in your checkout.
- **The orchestrator doesn't forget the rules in long sessions.** A hook re-injects the
  flow and each open spec's current step on every message, and another won't let a turn
  end with a verified-but-unclosed spec or a skipped step.
- **Consumption is a design constraint.** Each role runs on the model its job needs
  (planner and implementer on a cheaper one, the reviewer on the strongest); chained
  background waits (`scripts/pr_wait.sh`) end in ONE notice instead of one per step; and
  the per-message reminder stays under 600 characters, with the rest of the rules living
  in the skill and the docs instead of repeating on every turn.
- **Docs live next to their work.** Each subsystem is an *area* folder: how it works, its
  traps, its pending work, its open specs and its last closed ones. Specs are named
  `<area>/<slug>`, never numbered, so reordering a plan of ten specs renumbers nothing.
- **Closed specs aren't lost, nor piled up.** A closed spec moves to its area's `done/`
  (the last 3 stay; older ones remain in `main`'s history, even with squash merges), and
  `areas/HISTORY.md` keeps one line per spec. Line limits per doc, checked in CI.
- **Tests that earn their place.** Only tests that catch a bug that already happened or
  protect an invariant, with a mutation check.

## The flow

```
idea ─► 1 SPEC ─► ⏸ OK ─► 2 PLAN ─► 3 CODE ─► 4 VERIFY ─► 5 CLOSE ─► ⏸ OK ─► merge
        orchestrator       planner   implementer  reviewer    orchestrator
                           (reads)   (own folder) (no edits)  docs + PR
                                        ▲            │
                                        └──── ✗ ─────┘
```

Details: [areas/README.md](areas/README.md) · orchestrator manual:
[.claude/skills/sdd/SKILL.md](.claude/skills/sdd/SKILL.md).

## What's inside

```
AGENTS.md                      project context template (fill in every TODO; Claude Code
                                reads it natively — no CLAUDE.md needed)
areas/README.md                the flow, modes, when to create an area, spec lifecycle
areas/BACKLOG.md · HISTORY.md  what's next across areas · one line per closed spec
areas/_template/               area README, spec.md (5-step checklist) and plan.md
areas/workflow/                example area: roles, permissions, resources per role
docs/STATUS.md · GOTCHAS.md    what exists today · stack-wide traps that already bit you
.claude/agents/                planner, implementer, reviewer
.claude/hooks/                 reminder (every message), closeout (end of turn),
                               agent_guard (per-agent permissions), sdd_state
.claude/permissions.json       what each role may edit and run, with accepted risks
.claude/settings.json          deny rules + hook registration
.claude/skills/sdd/            the orchestrator's manual
scripts/worktree.sh            isolated folder + branch + port per <area>-<slug> (or docs-<topic>)
scripts/baseline.sh            disposable copy of main to compare before/after
scripts/check-docs.mjs         doc line limits and at most 3 closed specs per area (CI)
scripts/test-hooks.sh          self-test of the hooks (CI)
scripts/pr_wait.sh             watches a PR's CI (and, with --merge, merges + deploy) in ONE background process
scripts/verify/                guard self-test + catalog of your reusable checks, incl. pr_wait_selftest.sh
```

## Getting started

Requirements: [Claude Code](https://claude.com/claude-code), `git`, `python3`, `node`
and the [GitHub CLI](https://cli.github.com/) (`gh auth login`).

1. Click **Use this template** on GitHub (or clone it) to create your project.
2. Fill in every `TODO` in `AGENTS.md` — above all the **Verification** list: it's
   exactly what the implementer and reviewer run.
3. Adjust the `CUSTOMIZE PER PROJECT` blocks:
   - `scripts/worktree.sh`: shared files to link, dependency folders to clone, base port;
   - `scripts/baseline.sh`: what runs in the copy of `main` (`run_baseline`);
   - `.claude/permissions.json`: your protected scripts (`protected`) and shared-state
     commands; then `python3 scripts/verify/guard_selftest.py`;
   - `areas/workflow/README.md`: the «Resources per role» table;
   - `scripts/check-docs.mjs`: line limits.
4. Add your project's jobs to `.github/workflows/ci.yml`.
5. Create your first areas from `areas/_template/README.md` (one per subsystem; a few to
   start, 8-15 once mature — rules in `areas/README.md`) and list them in `docs/STATUS.md`.
6. Open Claude Code in the repo and ask for your first feature. It will write
   `areas/<area>/open/<slug>/spec.md` and wait for your OK.

Agents defined in `.claude/agents/` load when a session starts; hooks apply immediately.

## Known limits

- The guard stops mistakes by cooperative agents, not an attacker: an agent could still
  write a script that does something forbidden. Known evasions are listed, with their
  why, under `accepted_risks` in `.claude/permissions.json`.
- The guard, agents and hooks that apply are the ones on your main branch: a change made
  on a feature branch takes effect once merged.
- Features that change a **shared resource** (a single database, shared infra) run one
  at a time: worktrees isolate code, not external state.
- Branch protection on GitHub isn't part of this (it needs a paid plan for private
  repos); the deny rules and the guard cover what agents can do.

## License

[MIT](LICENSE)
