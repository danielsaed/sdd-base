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
  command: the reviewer can't edit, the planner only writes its plan, the implementer
  can't push, merge, touch `main`, read `.env` or add dependencies.
- **The orchestrator doesn't forget the rules in long sessions.** A hook re-injects the
  flow and each open spec's current step on every message, and another won't let a turn
  end with a verified-but-unclosed spec or a skipped step.
- **Docs stay small and current.** Line limits per doc, checked in CI. Specs are deleted
  when closed (git keeps them), so `specs/` never piles up.
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

Details: [specs/README.md](specs/README.md) · orchestrator manual:
[.claude/skills/sdd/SKILL.md](.claude/skills/sdd/SKILL.md).

## What's inside

```
AGENTS.md · CLAUDE.md          project context template (CLAUDE.md → @AGENTS.md)
specs/README.md                the flow, roles and permissions
specs/BACKLOG.md               the only list of pending work
specs/_template/               spec.md (with a 5-step checklist) and plan.md
docs/STATUS.md · GOTCHAS.md    what exists today · traps that already bit you
.claude/agents/                planner, implementer, reviewer
.claude/hooks/                 reminder (every message), closeout (end of turn),
                               agent_guard (per-agent permissions), sdd_state
.claude/settings.json          deny rules + hook registration
.claude/skills/sdd/            the orchestrator's manual
scripts/worktree.sh            isolated folder + branch + port per feature
scripts/check-docs.mjs         doc line limits (CI)
scripts/test-hooks.sh          self-test of the hooks (CI)
```

## Getting started

Requirements: [Claude Code](https://claude.com/claude-code), `git`, `python3`, `node`
and the [GitHub CLI](https://cli.github.com/) (`gh auth login`).

1. Click **Use this template** on GitHub (or clone it) to create your project.
2. Fill in every `TODO` in `AGENTS.md` — above all the **Verification** list: it's
   exactly what the implementer and reviewer run.
3. Adjust the `CUSTOMIZE PER PROJECT` blocks:
   - `scripts/worktree.sh`: env files to copy, dependency folders to clone, base port;
   - `.claude/hooks/agent_guard.py`: commands that change shared state (DB, infra);
   - `scripts/check-docs.mjs`: line limits.
4. Add your project's jobs to `.github/workflows/ci.yml`.
5. Open Claude Code in the repo and ask for your first feature. It will write
   `specs/001-…/spec.md` and wait for your OK.

Agents defined in `.claude/agents/` load when a session starts; hooks apply immediately.

## Known limits

- An agent with a terminal could still write a script that does something forbidden;
  the guard closes the obvious paths, not every possible one.
- Features that change a **shared resource** (a single database, shared infra) run one
  at a time: worktrees isolate code, not external state.
- Branch protection on GitHub isn't part of this (it needs a paid plan for private
  repos); the deny rules and the guard cover what agents can do.

## License

[MIT](LICENSE)
