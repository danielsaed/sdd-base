"""SDD workflow state, shared by the hooks: which specs are open and at which step.

A spec lives on its feature branch, so we look in the main checkout and in every folder
under `.worktrees/`. The current step is the first `- [ ]` of its checklist.
"""
import glob
import os
import re
import subprocess

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
MAIN_BRANCH = os.environ.get("SDD_MAIN_BRANCH", "main")  # env override: used by scripts/test-hooks.sh
STEPS = ["spec approved", "plan", "code", "verified", "close (docs + delete spec) and PR"]


def git(*args, cwd=ROOT):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def open_specs():
    """[(slug, where, checks[bool], branch)] for each open spec."""
    out, seen = [], set()
    patterns = [os.path.join(ROOT, "specs", "[0-9]*", "spec.md"),
                os.path.join(ROOT, ".worktrees", "*", "specs", "[0-9]*", "spec.md")]
    for pat in patterns:
        for f in sorted(glob.glob(pat)):
            slug = os.path.basename(os.path.dirname(f))
            if slug in seen:
                continue
            seen.add(slug)
            checks = [m.group(1).lower() == "x" for m in re.finditer(r"^- \[( |x|X)\] \d", open(f).read(), re.M)]
            base = f.split("/specs/")[0]
            out.append((slug, os.path.relpath(base, ROOT) or ".", checks, git("branch", "--show-current", cwd=base)))
    return out


def current_step(checks):
    for i, ok in enumerate(checks):
        if not ok:
            return i
    return len(checks)


def closed_unmerged_branches():
    """Folders under .worktrees/ without an open spec whose branch isn't merged: a closed spec
    (feat/…) or docs mode (docs/…, which never has a spec). Both wait for their PR."""
    out = []
    merged = set(git("branch", "--merged", MAIN_BRANCH, "--format=%(refname:short)").split())
    for d in sorted(glob.glob(os.path.join(ROOT, ".worktrees", "*"))):
        if glob.glob(os.path.join(d, "specs", "[0-9]*", "spec.md")):
            continue
        branch = git("branch", "--show-current", cwd=d)
        if branch and branch not in merged:
            out.append(branch)
    return out
