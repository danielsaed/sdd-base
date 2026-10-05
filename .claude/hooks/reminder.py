#!/usr/bin/env python3
"""UserPromptSubmit: reminds the orchestrator of the flow and its state on EVERY message.

WHY. In long sessions the AGENTS.md loaded at the start loses weight and steps get
skipped (delegating, asking for the OK, closing docs). This re-injects the step each open
spec is at and what gets forgotten most. It goes into the context of EVERY message, so
it's short (<= 600 characters with 1 open spec + 1 pending PR, measured by
scripts/test-hooks.sh): the rest of the rules live in the skill `sdd` and areas/README.md.
State lines (spec + step, PR to merge, docs mode, dirty main) are never trimmed.
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

lines = ["[SDD reminder — rules in skill `sdd` and areas/README.md]"]
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
    lines.append("· No open specs. Long or parallelizable task? Recommend the SDD flow yourself; small? Do it directly.")
for b, d in closed_unmerged_branches():
    name = os.path.basename(d)
    # A docs/… branch never had a spec (docs mode): not a closed spec, but its PR also needs the OK.
    if b.startswith("docs/"):
        lines.append(f"· {b}: docs mode, PR to merge (OK; HISTORY line?) → scripts/worktree.sh {name} --rm.")
    else:
        parts = split_name(b[len("feat/"):], d)
        sid = "/".join(parts) if parts else b
        lines.append(f"· {b}: {sid} closed or not written yet; PR to merge (OK) → scripts/worktree.sh {name} --rm.")
n_areas = len(areas())
if n_areas > MAX_AREAS:
    lines.append(f"· ⚠ {n_areas} areas (healthy: 8-{MAX_AREAS}): propose to the user which to merge (areas/README.md «When to create an area»).")
for a, n in crowded_done():
    lines.append(f"· ⚠ areas/{a}/done/ has {n} specs: keep the {KEEP_DONE} most recent (git history keeps the rest).")
if git("branch", "--show-current") == MAIN_BRANCH and git("status", "--porcelain"):
    lines.append(f"· ⚠ Uncommitted changes on {MAIN_BRANCH}: use a feat/<area>-<slug> or docs/<topic> branch + PR.")
lines += [
    "· Delegate; OK needed for spec, shared changes and merge; chain background waits in ONE process; big outputs → an agent.",
    "· End every answer with «Status» (Running · Pending · Need from you, self-contained).",
]
print("\n".join(lines))
