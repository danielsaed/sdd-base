---
name: sdd
description: Orchestrator manual for the SDD flow (spec → plan → code → verify → close; one feature = one branch = one PR). Use it when starting any feature or fix that changes code, shared resources or docs, and when resuming an open spec.
---

# Orchestrating a feature (SDD flow)

You are the **orchestrator**: you decide, delegate and close. Whatever can be delegated is
delegated, so your context lasts and features move in parallel. Rules, roles and resources
per role: [specs/README.md](../../../specs/README.md).

## 0. Which mode?
**You decide and propose it**: if the task is long, complex or parallelizable, recommend
the flow to the user without waiting to be asked; if it's small and one-off, just do it.
- **Normal:** anything with shared resources, more than ~1 h, or several areas.
- **Quick:** small fix with no shared change. 5-line spec, no planner (tick step 2
  "n/a"). **Never** without reviewer or PR.
- **Docs:** only documentation → `scripts/worktree.sh docs-<topic>` (branch `docs/<topic>`,
  no port), commit, PR, green CI and OK. No spec, no reviewer.
- **Question or analysis with no changes:** no spec; just answer.

## 1. Spec  (you)
1. Number: next after those in `specs/`, `.worktrees/` and `git log --oneline | grep -o 'spec [0-9]*'`.
2. `scripts/worktree.sh NNN-slug` → folder + branch `feat/NNN-slug` + port; shared files linked.
3. Copy `specs/_template/spec.md` to `.worktrees/NNN-slug/specs/NNN-slug/spec.md` and fill
   it in. **Measurable** criteria, each with its script/command. Say what does NOT change.
4. **Show it to the user and wait for the OK.** Tick `[x] 1` and commit on the branch.

## 2. Plan  (`planner` agent)
Launch it with the spec path. Read its summary (not the whole plan unless needed). If it
raises doubts, settle them with the user first. Tick `[x] 2`.

## 3. Code  (`implementer` agent(s))
- One call per group of tasks; in **parallel** only the ones the plan marks disjoint.
- Give it: the folder, the spec, the plan and ITS tasks. Not your whole context.
- Several features in parallel = several folders. **Shared resources: one feature at a time.**
- **Agents sharing a folder:** remind them to `git add` only their own files; you don't
  commit (least of all `commit -a`) while they run. Large tasks: one folder per agent.
- Tell it its reserved resources (specs/README «Resources per role») and the checks that
  apply ([scripts/verify/README.md](../../../scripts/verify/README.md)).
- Read its report. If it says something couldn't be done, you decide; don't hide it. Tick `[x] 3`.

## 4. Verify  (`reviewer` agent)
- If there's a shared change **compatible with `main`**: ask the user for OK and apply it
  now, so the reviewer measures against real state. If it would break `main`, apply it at merge.
- Launch the reviewer with the folder and the spec. To compare with `main` it uses
  `scripts/baseline.sh` (a temp copy), never the main checkout.
- **NOT APPROVED** → back to step 3 with its findings (to the implementer; don't fix them
  yourself). If a finding reveals a gap in the spec, add the criterion to the spec first.
- **Two-stage review:** the next round gets the previous findings and focuses on them
  (each re-measured) plus the diff since that round; it doesn't redo what was approved.
  After ~3 rounds you may narrow the scope and accept the residual risks **in writing**
  (in the spec, with the why) instead of looping.
- **APPROVED** → tick `[x] 4`.

## 5. Close  (you, in the feature folder)
1. What lasts → its topic doc; `docs/STATUS.md` (what exists + one log line, rotating at 7);
   `specs/BACKLOG.md` (remove what's done, add what was discovered); a new gotcha if one
   was learned.
2. `node scripts/check-docs.mjs` green (if a doc goes over, compact it).
3. **Delete `specs/NNN-slug/`** (git keeps it). Commit "spec NNN: close".
4. `git push -u origin feat/NNN-slug` and `gh pr create` (what, why, how it was verified).
5. Watch CI in the background → when green, **ask the user for OK** → `gh pr merge --squash --delete-branch`.
   **Conditional OK** («merge if green»): `gh pr checks N --watch` in the background;
   green → merge and tell the user; red → don't merge, tell the user with the failure.
   Check the PR state first: the user may have merged it from GitHub.
6. `git pull` on main. **If the PR changed a dependency lockfile** (`package-lock.json`,
   `uv.lock`, `poetry.lock`, `requirements*.txt`, `Cargo.lock`…), re-sync dependencies in
   the main checkout (the command in AGENTS.md «How to run»): they aren't in git, and the
   user's checkout breaks otherwise. Then `scripts/worktree.sh NNN-slug --rm`.

## Non-negotiable rules
- Nothing reaches `main` without a PR. No shared change applied and no merge without explicit OK.
- The repo is the source of truth; tool memory only remembers where we were.
- Subagent reports: short and with measurements. A "done" without a measurement isn't done.
- **Nothing runs unwatched:** CI (`gh pr checks N --watch`), builds and agents go to the
  background with a completion notice; act on the notice, don't wait for the user.
- **Don't touch the user's environment:** agents (and you) start and stop only your own
  processes and resources; what the user has running is theirs.
- The guard, agents and hooks that govern are the **main branch's**
  (`.claude/permissions.json`): a change on a branch applies once merged. Subagents start
  with cwd at the main root: give them absolute paths or `cd .worktrees/NNN-slug`.
- **Every answer ends with a Status block:** Running · Pending · Need from you. «Need from
  you» is self-contained (full steps, where, what to copy; never «step 3» or «as above»).
- If the closeout hook blocks you, do the step; if you truly must wait for the user, say so.
