"""SDD workflow state, shared by the hooks: which specs are open, at which step, and how
the areas look.

A spec is `areas/<area>/open/<slug>/spec.md` and lives on its feature branch
`feat/<area>-<slug>`, in the folder `.worktrees/<area>-<slug>` — so we look in the main
checkout and in every folder under `.worktrees/`. The current step is the first `- [ ]`
of its checklist. No numbers anywhere: a spec is named `<area>/<slug>`.
"""
import glob
import os
import re
import subprocess

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
HERE = os.path.dirname(os.path.abspath(__file__))


def _main_branch():
    """The main branch's name lives in ONE place: the CUSTOMIZE block of scripts/worktree.sh
    (baseline.sh reads it too). SDD_MAIN_BRANCH overrides it (used by scripts/test-hooks.sh)."""
    if os.environ.get("SDD_MAIN_BRANCH"):
        return os.environ["SDD_MAIN_BRANCH"]
    try:
        with open(os.path.join(HERE, "..", "..", "scripts", "worktree.sh"), encoding="utf-8") as f:
            m = re.search(r'^MAIN_BRANCH="([^"]+)"', f.read(), re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    return "main"


MAIN_BRANCH = _main_branch()
STEPS = ["spec approved", "plan", "code", "verified",
         "close (docs + spec to done/ + HISTORY) and PR"]
MAX_AREAS = 15  # healthy range 8-15 (areas/README.md)
KEEP_DONE = 3   # closed specs kept per area in areas/<area>/done/


def git(*args, cwd=ROOT):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def main_checkout(cwd=ROOT):
    """Real path of the project's MAIN checkout (git lists it first, also when asked from a
    worktree), or "" outside a repo. Every session loads hooks, guard and scripts from it."""
    first = git("worktree", "list", "--porcelain", cwd=cwd).split("\n", 1)[0]
    return os.path.realpath(first[len("worktree "):]) if first.startswith("worktree ") else ""


def worktrees():
    return sorted(d for d in glob.glob(os.path.join(ROOT, ".worktrees", "*")) if os.path.isdir(d))


def areas(base=ROOT):
    """Area names under base/areas/ (folders not starting with `_`, e.g. `_template`)."""
    return sorted(os.path.basename(d) for d in glob.glob(os.path.join(base, "areas", "*"))
                  if os.path.isdir(d) and not os.path.basename(d).startswith("_"))


def split_name(name, base=ROOT):
    """`<area>-<slug>` → (area, slug). Both may contain hyphens, so the area is the LONGEST
    existing area folder that prefixes the name. None if no area matches."""
    for a in sorted(areas(base), key=len, reverse=True):
        if name.startswith(a + "-") and len(name) > len(a) + 1:
            return a, name[len(a) + 1:]
    return None


def checklist(path):
    return [m.group(1).lower() == "x" for m in re.finditer(r"^- \[( |x|X)\] \d", open(path).read(), re.M)]


def open_specs():
    """[(id 'area/slug', where, checks[bool], branch)] for each open spec."""
    out, seen = [], set()
    for base in [ROOT, *worktrees()]:
        for f in sorted(glob.glob(os.path.join(base, "areas", "[!_]*", "open", "*", "spec.md"))):
            slug_dir = os.path.dirname(f)
            sid = f"{os.path.basename(os.path.dirname(os.path.dirname(slug_dir)))}/{os.path.basename(slug_dir)}"
            if sid in seen:
                continue
            seen.add(sid)
            out.append((sid, os.path.relpath(base, ROOT), checklist(f), git("branch", "--show-current", cwd=base)))
    return out


def current_step(checks):
    for i, ok in enumerate(checks):
        if not ok:
            return i
    return len(checks)


def closed_unmerged_branches():
    """[(branch, folder)] for folders under .worktrees/ without an open spec whose branch isn't
    merged: a closed spec (feat/…), docs mode (docs/…, which never has a spec) or a folder
    whose spec isn't written yet. They wait for their PR (or for the spec)."""
    out = []
    merged = set(git("branch", "--merged", MAIN_BRANCH, "--format=%(refname:short)").split())
    for d in worktrees():
        if glob.glob(os.path.join(d, "areas", "[!_]*", "open", "*", "spec.md")):
            continue
        branch = git("branch", "--show-current", cwd=d)
        if branch and branch not in merged:
            out.append((branch, d))
    return out


def close_problems(branch, folder):
    """What's missing in a feat/<area>-<slug> folder whose spec was closed: the spec must have
    been MOVED to done/ (not deleted), plan.md deleted, a HISTORY line added and the area
    pruned to KEEP_DONE. [] if the spec never existed on the branch (folder just created)."""
    parts = split_name(branch[len("feat/"):], folder) if branch.startswith("feat/") else None
    if not parts:
        return []
    area, slug = parts
    spec = f"areas/{area}/open/{slug}/spec.md"
    if not git("log", "--format=%h", f"{MAIN_BRANCH}..HEAD", "--", spec, cwd=folder):
        return []
    sid, adir, out = f"{area}/{slug}", os.path.join(folder, "areas", area), []
    if not glob.glob(os.path.join(adir, "done", f"[0-9][0-9][0-9][0-9]-[0-9][0-9]-{slug}.md")):
        out.append(f"{sid}: the spec left open/ but isn't in areas/{area}/done/YYYY-MM-{slug}.md "
                   "(move it there with its Outcome section; never delete it)")
    if glob.glob(os.path.join(adir, "open", slug, "*")):
        out.append(f"{sid}: areas/{area}/open/{slug}/ still has files (delete plan.md)")
    hist = os.path.join(folder, "areas", "HISTORY.md")
    if not (os.path.exists(hist) and sid in open(hist).read()):
        out.append(f"{sid}: no line in areas/HISTORY.md (date · {sid} · what · PR, at the top)")
    done = glob.glob(os.path.join(adir, "done", "*.md"))
    if len(done) > KEEP_DONE:
        out.append(f"{sid}: areas/{area}/done/ has {len(done)} specs; keep the {KEEP_DONE} most recent "
                   "(the older one stays in git history)")
    return out


def crowded_done(base=ROOT):
    """[(area, n)] for areas with more than KEEP_DONE closed specs in done/."""
    out = []
    for a in areas(base):
        n = len(glob.glob(os.path.join(base, "areas", a, "done", "*.md")))
        if n > KEEP_DONE:
            out.append((a, n))
    return out
