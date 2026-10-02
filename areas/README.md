# How we work: areas, and one spec = one branch = one PR

> **Answers:** the agent workflow (who does what, in which order) and how areas and specs
> are organized, named and closed. **Update when:** a step, a mode or an area rule
> changes. Roles, permissions and resources: [workflow/README.md](workflow/README.md).
> The orchestrator's operating manual is `.claude/skills/sdd/SKILL.md`.

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
  branch `docs/<topic>` → PR + CI + a [HISTORY.md](HISTORY.md) line. No spec, no
  reviewer; merged with OK like any PR.
- **Merge OK:** explicit, or **conditional** («merge if green»): CI is watched in the
  background; green → merge and tell the user; red → don't merge, tell the user why.
- **Parallel:** several features at once only if they don't touch a **shared resource**
  (a single database, shared infra). Those go one at a time. Within a feature, large
  disjoint tasks run in parallel with **one folder per agent** when possible; if agents
  share a folder, each one `git add`s **only its own files** (never `-A`, `.` or
  `commit -a`) and the orchestrator doesn't commit while they run.

## Areas

An **area** is a subsystem with everything about it in one folder: how it works, its
traps, its pending work and its last closed specs. `docs/` keeps only what ANY task needs.

```
areas/<area>/README.md                 How it works · Gotchas · Pending · Done
areas/<area>/open/<slug>/spec.md       open spec (5-step checklist at the top)
areas/<area>/open/<slug>/plan.md       written by the planner; deleted at close
areas/<area>/done/YYYY-MM-<slug>.md    the 3 most recent closed specs of the area
areas/BACKLOG.md · HISTORY.md          cross-area order of what's next · every closed spec
areas/_template/                       README.md (area), spec.md, plan.md
```

**When to create an area** — creating, splitting or merging one needs the **user's OK**:
- **Use an existing one** if most of the spec falls in it; mixed → the main one.
- **Create a new one** only if all three hold: (a) it fits none; (b) it will have its own
  permanent "how it works", not a one-off fix; (c) more specs are expected there.
  Otherwise it goes to the closest; the **third misfit spec on the same topic** justifies
  the area. `scripts/worktree.sh <area>-<slug> --new-area <area>` creates it on the branch.
- **Split** when its README is over the limit even after compacting and has two halves
  nobody reads together. **Merge** when its README is under ~30 lines and it has had no
  specs in a long time.
- **Name:** a noun for the concept the user sees, not an implementation detail
  (`billing`, not `stripe-webhooks`). `docs` is reserved (docs mode).
- **Healthy range: 8-15 areas** once a project matures. Over 15, the reminder asks to review.

## Spec lifecycle

- **No numbers.** A spec is `<area>/<slug>`: branch `feat/<area>-<slug>`, folder
  `scripts/worktree.sh <area>-<slug>` (its `.port` comes from a stable hash of the name).
  The area is the longest existing area folder that prefixes the name, so area and slug
  may both contain hyphens. Plans of several specs name them by slug and order them in
  [BACKLOG.md](BACKLOG.md): reordering renumbers nothing. A unique id, if ever needed,
  is the PR number.
- A spec describes **the change** and is temporary; the area README describes **how
  things work** and is permanent (one fact, one home).
- Pending work that isn't a spec yet: the **Pending** section of its area's README;
  [BACKLOG.md](BACKLOG.md) only orders what's next across areas.

```
areas/billing/open/refunds/spec.md   ← open, on branch feat/billing-refunds
areas/billing/open/refunds/plan.md   ← written by the planner
        │ close (step 5, in the PR's last commit)
        ▼
what lasts → areas/billing/README.md (How it works · Gotchas · Pending) · docs/STATUS.md
spec       → areas/billing/done/2026-10-refunds.md + «Outcome» (3-5 lines: PR, what deviated)
plan.md    → deleted (a working document)
HISTORY.md → one line at the top: 2026-10-14 · billing/refunds · what · PR #57
done/      → keep the 3 most recent; delete the oldest (main's history keeps it)
```

**History with balance.** PRs are squash-merged, so only what reaches `main` survives in
its history: that's why the spec is moved, not deleted. A pruned spec is recovered with:

```
git log --all --oneline --name-only --diff-filter=D -- 'areas/*/done/*<slug>*'   # commit + path
git show <commit>^:<path>
```

The closeout hook blocks a close that deleted the spec instead of moving it, left
`plan.md`, skipped the HISTORY line or left more than 3 specs in `done/`;
`scripts/check-docs.mjs` (CI) also fails on more than 3.

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
