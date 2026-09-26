#!/usr/bin/env python3
"""Stop: won't let the turn end while a workflow step is being skipped.

It only blocks states that are a SURE omission, not "work in progress":
  1. uncommitted changes on the main branch (everything goes through a branch + PR);
  2. a VERIFIED spec (step 4 ticked) whose docs aren't closed (step 5): closing doesn't
     need the user, so stopping there is leaving it half done;
  3. a spec with a step ticked while an earlier one isn't (a step was skipped).
Blocks ONCE per turn (`stop_hook_active`): if after the notice there's a real reason to
stop (waiting for the user), it stops.
Output: exit 2 + reason on stderr → Claude receives it and continues.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from sdd_state import MAIN_BRANCH, STEPS, git, open_specs  # noqa: E402

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
if data.get("stop_hook_active"):
    sys.exit(0)

reasons = []
if git("branch", "--show-current") == MAIN_BRANCH:
    dirty = git("status", "--porcelain")
    if dirty:
        reasons.append(f"UNCOMMITTED changes on {MAIN_BRANCH}:\n" + dirty[:400]
                       + "\n→ move them to a feat/NNN-slug branch (git switch -c) and open a PR.")

for slug, where, checks, branch in open_specs():
    if len(checks) >= 5 and checks[3] and not checks[4]:
        reasons.append(f"Spec {slug} is VERIFIED but not closed: topic docs, STATUS, BACKLOG, "
                       f"check-docs and delete specs/{slug} (step 5), then the PR.")
    if any(checks[j] and not all(checks[:j]) for j in range(len(checks))):
        missing = [f"{i + 1} {STEPS[i]}" for i, ok in enumerate(checks) if not ok and any(checks[i + 1:])]
        reasons.append(f"Spec {slug} has skipped steps: {', '.join(missing)}. Do them or explain why they don't apply.")

if reasons:
    print("[SDD flow] Before finishing:\n- " + "\n- ".join(reasons)
          + "\n(If you really must stop to wait for the user, say so explicitly in your answer.)",
          file=sys.stderr)
    sys.exit(2)
sys.exit(0)
