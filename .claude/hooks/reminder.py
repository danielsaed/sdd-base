#!/usr/bin/env python3
"""UserPromptSubmit: reminds the orchestrator of the flow and its state on EVERY message.

WHY. In long sessions the AGENTS.md loaded at the start loses weight and steps get
skipped (delegating, asking for the OK, closing docs). This re-injects ~15 lines with the
essentials and the step each open spec is at. Whatever it prints goes into the context.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from sdd_state import (KEEP_DONE, MAIN_BRANCH, MAX_AREAS, STEPS, areas, closed_unmerged_branches,  # noqa: E402
                       crowded_done, current_step, git, open_specs, split_name)

try:
    json.load(sys.stdin)
except Exception:
    pass

lines = ["[SDD flow · automatic reminder — details in areas/README.md and skill `sdd`]"]
specs = open_specs()
if specs:
    for sid, where, checks, branch in specs:
        i = current_step(checks)
        nxt = STEPS[i] if i < len(STEPS) else "closed: move the spec to done/"
        lines.append(f"· spec {sid} ({branch or where}) → next step: {i + 1} {nxt}")
        want = "feat/" + sid.replace("/", "-", 1)
        if branch and branch != MAIN_BRANCH and branch != want:
            lines.append(f"  ⚠ spec {sid} is on {branch}; its branch must be {want} (one spec = one branch).")
else:
    lines.append("· No open specs. Long/complex or parallelizable task? RECOMMEND the SDD flow yourself, don't wait to be asked. Small, one-off task? Do it directly with whatever tools fit.")
for b, d in closed_unmerged_branches():
    name = os.path.basename(d)
    # A docs/… branch never had a spec (docs mode): not a closed spec, but its PR also needs the OK.
    if b.startswith("docs/"):
        lines.append(f"· {b}: docs mode, PR to merge (with OK; HISTORY line added?) → then scripts/worktree.sh {name} --rm.")
    else:
        parts = split_name(b[len("feat/"):], d)
        sid = "/".join(parts) if parts else b
        lines.append(f"· {b}: no open spec ({sid} closed or not written yet); closed → PR to merge (with OK) → then scripts/worktree.sh {name} --rm.")
n_areas = len(areas())
if n_areas > MAX_AREAS:
    lines.append(f"· ⚠ {n_areas} areas (healthy: 8-{MAX_AREAS}): propose to the user which to merge (areas/README.md «When to create an area»).")
for a, n in crowded_done():
    lines.append(f"· ⚠ areas/{a}/done/ has {n} specs: keep the {KEEP_DONE} most recent (git history keeps the rest).")
if git("branch", "--show-current") == MAIN_BRANCH and git("status", "--porcelain"):
    lines.append(f"· ⚠ Uncommitted changes on {MAIN_BRANCH}: everything goes through a feat/<area>-<slug> (or docs/<topic>) branch + PR.")
lines += [
    "· You orchestrate: planner (plan) → implementer (code, in .worktrees/) → reviewer (verify). Don't code what you can delegate.",
    "· New spec: areas/<area>/open/<slug>/spec.md, branch feat/<area>-<slug> (scripts/worktree.sh <area>-<slug>). No numbers: refer to specs by slug.",
    "· Area: the existing one where most of the spec falls. Creating, splitting or merging an area needs the user's OK (areas/README.md).",
    "· Docs mode: ONLY docs change → branch docs/<topic> (scripts/worktree.sh docs-<topic>) + PR + CI, no spec or reviewer.",
    "· In parallel: one folder per agent or disjoint files; each agent git adds ONLY its files; you never commit -a while agents run.",
    "· User OK needed for: the spec, applying shared changes (DB/infra) and merging the PR. Shared changes one feature at a time.",
    "· Conditional OK («merge if green»): gh pr checks N --watch in the background; green → merge and tell the user; red → don't merge, tell them.",
    "· Agents start/stop only THEIR resources (areas/workflow/README.md «Resources per role»); never what the user has running.",
    "· Tests only if they catch a real bug or an invariant, with a mutation check. Feature verification → scripts/verify/.",
    "· End EVERY answer with «Status»: Running (what's still going) · Pending · Need from you (or «nothing»).",
    "· «Need from you» SELF-CONTAINED: full steps (where, what to copy), never «step 3» or «as above». The user only reads the last message.",
    "· Anything left running (CI, build, agent) goes to the background WITH a completion notice; never «waiting for you».",
    f"· Close: area README + STATUS + BACKLOG; spec → areas/<area>/done/YYYY-MM-<slug>.md with «Outcome», delete plan.md, keep {KEEP_DONE} done per area, line at the top of areas/HISTORY.md; check-docs green.",
]
print("\n".join(lines))
