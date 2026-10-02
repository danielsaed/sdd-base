#!/usr/bin/env python3
"""UserPromptSubmit: reminds the orchestrator of the flow and its state on EVERY message.

WHY. In long sessions the AGENTS.md loaded at the start loses weight and steps get
skipped (delegating, asking for the OK, closing docs). This re-injects ~13 lines with the
essentials and the step each open spec is at. Whatever it prints goes into the context.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from sdd_state import MAIN_BRANCH, STEPS, closed_unmerged_branches, current_step, git, open_specs  # noqa: E402

try:
    json.load(sys.stdin)
except Exception:
    pass

lines = ["[SDD flow · automatic reminder — details in specs/README.md and skill `sdd`]"]
specs = open_specs()
if specs:
    for slug, where, checks, branch in specs:
        i = current_step(checks)
        nxt = STEPS[i] if i < len(STEPS) else "closed: delete the folder"
        lines.append(f"· spec {slug} ({branch or where}) → next step: {i + 1} {nxt}")
else:
    lines.append("· No open specs. Long/complex or parallelizable task? RECOMMEND the SDD flow yourself, don't wait to be asked. Small, one-off task? Do it directly with whatever tools fit.")
for b in closed_unmerged_branches():
    # A docs/… branch never had a spec (docs mode): not a closed spec, but its PR also needs the OK.
    if b.startswith("docs/"):
        lines.append(f"· {b}: docs mode, PR to merge (with OK) → then scripts/worktree.sh docs-{b[5:]} --rm.")
    else:
        lines.append(f"· {b}: spec closed, PR to merge (with OK) → then scripts/worktree.sh <slug> --rm.")
if git("branch", "--show-current") == MAIN_BRANCH and git("status", "--porcelain"):
    lines.append(f"· ⚠ Uncommitted changes on {MAIN_BRANCH}: everything goes through a feat/NNN (or docs/<topic>) branch + PR.")
lines += [
    "· You orchestrate: planner (plan) → implementer (code, in .worktrees/) → reviewer (verify). Don't code what you can delegate.",
    "· Docs mode: ONLY docs change → branch docs/<topic> (scripts/worktree.sh docs-<topic>) + PR + CI, no spec or reviewer.",
    "· In parallel: one folder per agent or disjoint files; each agent git adds ONLY its files; you never commit -a while agents run.",
    "· User OK needed for: the spec, applying shared changes (DB/infra) and merging the PR. Shared changes one feature at a time.",
    "· Conditional OK («merge if green»): gh pr checks N --watch in the background; green → merge and tell the user; red → don't merge, tell them.",
    "· Agents start/stop only THEIR resources (specs/README «Resources per role»); never what the user has running.",
    "· Tests only if they catch a real bug or an invariant, with a mutation check. Feature verification → scripts/verify/.",
    "· End EVERY answer with «Status»: Running (what's still going) · Pending · Need from you (or «nothing»).",
    "· «Need from you» SELF-CONTAINED: full steps (where, what to copy), never «step 3» or «as above». The user only reads the last message.",
    "· Anything left running (CI, build, agent) goes to the background WITH a completion notice; never «waiting for you».",
    "· Close: topic docs + STATUS (what exists + log) + BACKLOG + delete specs/NNN; check-docs green.",
]
print("\n".join(lines))
