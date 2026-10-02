#!/usr/bin/env python3
"""Self-test of the subagent guard (.claude/hooks/agent_guard.py + .claude/permissions.json).

WHY it exists. The guard decides what each subagent may do; if it breaks, it either blocks
everyone (nobody works) or lets through what can't be undone (push, merge, shared-state
scripts). Both have happened in real projects: a commit that only NAMED a forbidden
script was blocked while `git -C folder push` passed, and `npm i -D pkg` slipped through.
Every such case is measured here, plus one per rule.

It runs THIS checkout's guard by path (not the one loaded in Claude Code, which is the
main checkout's), as a subprocess, with the JSON Claude Code sends (`agent_type`,
`agent_id`, `tool_name`, `tool_input`, `cwd`); exit 0 = allowed, 2 = blocked.

Built-in mutation: for every `id` in permissions.json (commands, never_edit) it reruns the
cases WITHOUT that rule (in-process, fast); if no case changes, the rule has no test → fail.
Mutation check of this test itself (done when writing it): removing the `-C dir` skip in
agent_guard.git_normal → «git -C folder push» fails; deleting a rule from permissions.json
→ its case fails.

Usage (from the root or a feature folder; stdlib only, runs in CI):
  python3 scripts/verify/guard_selftest.py              # cases + mutation
  python3 scripts/verify/guard_selftest.py --no-mutation
  python3 scripts/verify/guard_selftest.py -v           # list every case
  python3 scripts/verify/guard_selftest.py --corpus cmds.jsonl --old <other>/agent_guard.py \
      --old-root <its CLAUDE_PROJECT_DIR> --out /tmp/diff.txt
      # before changing rules: old vs new over real commands ({agent_type, command} per
      # line); lists what the new one blocks and the old one didn't (and the reverse)
Exits 0 if everything matches, 1 if something fails.
"""
import atexit
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(ROOT, ".claude", "hooks", "agent_guard.py")
PERMISSIONS = os.path.join(ROOT, ".claude", "permissions.json")
W = ".worktrees/012-x"
P_SCRIPT = "scripts/apply-shared-change.sh"  # matches `protected` in permissions.json
I, R, PL = "implementer", "reviewer", "planner"


def bash(c):
    return ("Bash", {"command": c})


def bash_in(cwd, c):  # `_cwd` (self-test only): the agent's cwd, relative to the root
    return ("Bash", {"command": c, "_cwd": cwd})


def write(path):
    return ("Write", {"file_path": path, "content": "x"})


HEREDOC_COMMIT = (
    f"git -C {W} commit -m \"$(cat <<'EOF'\n"
    f"guard: running {P_SCRIPT} is blocked, naming it isn't; git push; cat .env\n"
    "\nCo-Authored-By: X <x@example.com>\nEOF\n)\""
)

# A REAL symlink pointing to a protected script (removed at exit): the guard must judge it
# by where it points, not by where it is.
LINKS = tempfile.mkdtemp(prefix="sdd-guard-link-")
atexit.register(shutil.rmtree, LINKS, True)
open(os.path.join(LINKS, "apply-shared-change.sh"), "w").close()
LINK = os.path.join(LINKS, "harmless.sh")
os.symlink(os.path.join(LINKS, "apply-shared-change.sh"), LINK)
os.symlink(ROOT, os.path.join(LINKS, "link-to-repo"))  # a "temp" path that is really the repo

# (description, agent | None = main session, tool, input, "ok" | "no")
CASES = [
    # ── Blocked: push / merge / main, by any route ──
    ("git push", I, *bash("git push origin feat/012-x"), "no"),
    ("git -C folder push (the classic hole)", I, *bash(f"git -C {W} push"), "no"),
    ("git --no-pager -C x push", I, *bash("git --no-pager -C x push"), "no"),
    ("git -c alias.p=push p", I, *bash("git -c alias.p=push p"), "no"),
    ("git --config-env=alias.", I, *bash("git --config-env=alias.p=X p"), "no"),
    ("GIT_CONFIG_COUNT in the environment", I,
     *bash("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push git p"), "no"),
    ("git config alias.", I, *bash("git config --global Alias.p push"), "no"),
    ("git config user.name (no alias)", I, *bash("git config user.name"), "ok"),
    ("git push inside $(…)", I, *bash("echo $(git push)"), "no"),
    ("git push inside `…`", I, *bash("echo `git push`"), "no"),
    ("git $(echo push)", I, *bash("git $(echo push)"), "no"),
    ("program is a substitution", I, *bash("$(echo git) push"), "no"),
    ("eval git push", I, *bash("eval \"git push\""), "no"),
    ("sh -lc git push", I, *bash("sh -lc 'git push'"), "no"),
    ("bash -o pipefail -c", I, *bash("bash -o pipefail -c 'git push'"), "no"),
    ("bash <(…)", I, *bash("bash <(echo 'git push')"), "no"),
    ("… | sh /dev/stdin", I, *bash("echo 'git push' | sh /dev/stdin"), "no"),
    ("a shell reading a pipe", I, *bash("cat x.sh | bash"), "no"),
    ("a shell with a heredoc", I, *bash("bash <<'EOF'\nls\nEOF"), "no"),
    ("env -S 'git push'", I, *bash("env -S 'git push'"), "no"),
    ("env -iS 'git push'", I, *bash("env -iS 'git push'"), "no"),
    ("env --split-string=", I, *bash("env --split-string='git push origin x'"), "no"),
    ("env -u HOME ls (no -S)", I, *bash("env -u HOME ls"), "ok"),
    ("function f { git push; }", I, *bash("function f { git push; }"), "no"),
    ("\"$@\" as the program", I, *bash("f(){ \"$@\"; }; f git push"), "no"),
    ("nohup … &", I, *bash("nohup git push &"), "no"),
    ("timeout 10 git push", I, *bash("timeout 10 git push"), "no"),
    ("xargs git (subcommand on stdin)", I, *bash("echo push | xargs git"), "no"),
    ("xargs -n1 git push", I, *bash("echo x | xargs -n1 git push"), "no"),
    ("variable holding git", I, *bash("X=git; $X push"), "no"),
    ("variable from $(…) as program", I, *bash("V=$(which git); $V push"), "no"),
    ("loop variable as program", I, *bash("for f in a b; do $f; done"), "no"),
    ("do git push (loop)", I, *bash("for i in 1 2; do git push; done"), "no"),
    ("then git push (if)", I, *bash("if true; then git push; fi"), "no"),
    ("(git push) in a subshell", I, *bash("(cd x && git push)"), "no"),
    ("{ git push; } grouped", I, *bash("{ git push; }"), "no"),
    ("unclosed quotes", I, *bash("echo 'x"), "no"),
    ("git merge", I, *bash("git merge main"), "no"),
    ("gh pr merge", I, *bash("gh pr merge 23 --squash"), "no"),
    ("gh pr close", I, *bash("gh pr close 23"), "no"),
    ("git switch main", I, *bash(f"git -C {W} switch main"), "no"),
    ("git checkout -b feat/x", I, *bash("git checkout -b feat/x"), "ok"),
    ("git branch -D", I, *bash("git branch -D feat/x"), "no"),
    ("git worktree remove", I, *bash(f"git worktree remove {W}"), "no"),
    ("git reset --hard", I, *bash("git reset --hard HEAD~1"), "no"),
    ("git reset --har (prefix)", I, *bash("git reset --har"), "no"),
    ("git reset --soft", I, *bash("git reset --soft HEAD~1"), "ok"),
    # ── Parallel discipline: only YOUR files ──
    ("git add -A", I, *bash("git add -A"), "no"),
    ("git add --al (prefix)", I, *bash("git add --al"), "no"),
    ("git add -u", I, *bash("git add -u"), "no"),
    ("git stage -A", I, *bash("git stage -A"), "no"),
    ("git -C folder add .", I, *bash(f"git -C {W} add ."), "no"),
    ("git add -A limited to paths", I, *bash("git add -A src/a docs/X.md && git commit -qm x"), "ok"),
    ("git add by name", I, *bash(f"git -C {W} add src/a.py src/b.py"), "ok"),
    ("git commit -a", I, *bash("git commit -a -m x"), "no"),
    ("git commit -am", I, *bash("git commit -am 'x'"), "no"),
    ("git commit --al", I, *bash("git commit --al -m x"), "no"),
    ("commit -m mentioning «add -A»", I, *bash("git commit -m 'forbid git add -A and commit -a'"), "ok"),
    # ── Protected (shared-state) scripts: running them, by any route ──
    ("protected as a program", I, *bash(f"./{P_SCRIPT} --prod"), "no"),
    ("protected with bash", I, *bash(f"bash {P_SCRIPT}"), "no"),
    ("protected after cd &&", I, *bash(f"cd /repo && ./{P_SCRIPT} x"), "no"),
    ("protected inside bash -c", I, *bash(f"bash -c \"./{P_SCRIPT} x\""), "no"),
    ("protected with uv run", I, *bash(f"uv run {P_SCRIPT} x"), "no"),
    ("protected in $(…)", I, *bash(f"echo $(./{P_SCRIPT} x)"), "no"),
    ("protected with env X=1", I, *bash(f"env X=1 ./{P_SCRIPT} x"), "no"),
    ("protected via function", I, *bash(f"function d {{ ./{P_SCRIPT} x; }}; d"), "no"),
    ("protected via find -exec", I, *bash(f"find . -name x -exec ./{P_SCRIPT} {{}} \\;"), "no"),
    ("symlink to protected, run", I, *bash(LINK), "no"),
    ("symlink to protected, with bash", I, *bash(f"bash {LINK}"), "no"),
    ("ln -s protected + run", I, *bash(f"ln -s ../{P_SCRIPT} scripts/a.sh; ./scripts/a.sh"), "no"),
    ("cp protected elsewhere", I, *bash(f"cp {P_SCRIPT} scripts/b.sh"), "no"),
    ("cat protected > x.sh", I, *bash(f"cat {P_SCRIPT} > scripts/zz.sh && bash scripts/zz.sh"), "no"),
    ("tee x.sh < protected", I, *bash(f"tee scripts/zz.sh < {P_SCRIPT}"), "no"),
    ("cat protected | tee x.sh", I, *bash(f"cat {P_SCRIPT} | tee scripts/zz.sh >/dev/null"), "no"),
    ("grep protected > /tmp/g.txt", I, *bash(f"grep -n set {P_SCRIPT} > /tmp/sdd-x/g.txt"), "ok"),
    ("tee of a normal log", I, *bash("make test 2>&1 | tee /tmp/sdd-x/test.log"), "ok"),
    ("node -e execSync(protected)", I, *bash(f"node -e \"require('child_process').execSync('{P_SCRIPT}')\""), "no"),
    ("python3 -c subprocess(protected)", I, *bash(f"python3 -c 'import os; os.system(\"{P_SCRIPT}\")'"), "no"),
    ("perl -e exec protected", I, *bash(f"perl -e 'exec \"{P_SCRIPT}\"'"), "no"),
    ("read a protected script", I, *bash(f"cat {P_SCRIPT} | head -20"), "ok"),
    ("git add naming protected", I, *bash(f"git -C {W} add {P_SCRIPT}"), "ok"),
    ("commit -m naming protected", I, *bash(f"git commit -m \"guard: {P_SCRIPT}; git push\""), "ok"),
    ("commit with a heredoc naming everything", I, *bash(HEREDOC_COMMIT), "ok"),
    ("terraform apply", I, *bash("terraform apply -auto-approve"), "no"),
    ("terraform plan", I, *bash("terraform plan"), "ok"),
    # ── Interpreters reading what can't be analyzed ──
    ("python - with heredoc", I, *bash("python3 - <<'EOF'\nprint(1)\nEOF"), "no"),
    ("python reading a pipe", I, *bash("echo 'print(1)' | python3"), "no"),
    ("node reading a heredoc", I, *bash("node <<'EOF'\nrequire('x')\nEOF"), "no"),
    ("python -m pytest", I, *bash("python3 -m pytest -q tests/"), "ok"),
    ("python script", I, *bash("python3 scripts/train.py --epochs 1"), "ok"),
    ("python -c harmless", I, *bash("python3 -c 'print(1)'"), "ok"),
    ("node --version", I, *bash("node --version"), "ok"),
    ("node -e with process.env", I, *bash("node -e \"console.log(process.env.HOME)\""), "ok"),
    # ── Secrets ──
    ("cat .env", I, *bash("cat .env"), "no"),
    ("cat app/.env.local", I, *bash("cat app/.env.local"), "no"),
    ("source .env", I, *bash("source .env && ls"), "no"),
    ("< .env", I, *bash("grep URL < .env"), "no"),
    ("$(cat .env)", I, *bash("echo \"$(cat ../../.env)\""), "no"),
    ("cat app/.env*", I, *bash("cat app/.env*"), "no"),
    ("cat .en?", I, *bash("cat .en?"), "no"),
    ("cat {.env,x}", I, *bash("cat {.env,x}"), "no"),
    ("node -e reads .env", I, *bash("node -e \"require('fs').readFileSync('.env')\""), "no"),
    ("python -c dotenv", I, *bash("python3 -c 'import dotenv; dotenv.load_dotenv()'"), "no"),
    ("ls .env* (listing isn't reading)", I, *bash("ls -la .env* 2>/dev/null"), "ok"),
    ("find -name '.e*' (a find pattern)", I, *bash(f"find {W} -maxdepth 2 -name '.e*'"), "ok"),
    (".env.example isn't secret", I, *bash("cat .env.example"), "ok"),
    # ── Dependencies ──
    ("npm install pkg", I, *bash("npm install foo"), "no"),
    ("npm i -D pkg", I, *bash("cd app && npm i -D foo"), "no"),
    ("npm install --prefix x pkg", I, *bash("npm install --prefix /tmp/x foo"), "no"),
    ("npm install (lockfile only)", I, *bash("npm install"), "ok"),
    ("npm ci", I, *bash("npm ci"), "ok"),
    ("pip install pkg", I, *bash("pip install requests"), "no"),
    ("pip install -r requirements.txt", I, *bash("pip install -r requirements.txt"), "ok"),
    ("pip install -e .", I, *bash("pip3 install -e ."), "ok"),
    ("python -m pip install pkg", I, *bash("python3 -m pip install torch"), "no"),
    ("python -m pip install -r", I, *bash("python3 -m pip install -r requirements.txt"), "ok"),
    ("uv add pkg", I, *bash("uv add numpy"), "no"),
    ("uv sync", I, *bash("uv sync"), "ok"),
    ("conda install pkg", I, *bash("conda install -n ml -c conda-forge opencv"), "no"),
    ("conda install --file", I, *bash("conda install --file env.txt"), "ok"),
    # ── Recursive deletes, resolved against the real cwd (subagents start at the root) ──
    ("rm -rf /", I, *bash("rm -rf /"), "no"),
    ("rm -rf ~", I, *bash("rm -rf ~"), "no"),
    ("rm -fr ..", I, *bash("rm -fr .."), "no"),
    ("rm -rf *", I, *bash("rm -rf *"), "no"),
    ("rm -rf $X with no value", I, *bash("rm -rf $UNKNOWN"), "no"),
    ("cwd root: rm -rf src", I, *bash("rm -rf src"), "no"),
    ("cwd root: cd app && rm -rf build", I, *bash("cd app && rm -rf build"), "no"),
    ("cwd own folder: rm -rf build dist", I, *bash_in(W, "rm -rf build dist"), "ok"),
    ("cwd own folder: rm -rf ../other", I, *bash_in(W, "rm -rf ../other"), "no"),
    ("cwd own folder: rm -rf .", I, *bash_in(W, "rm -rf ."), "no"),
    ("cd - then rm -rf relative", I, *bash_in(W, "cd - && rm -rf src"), "no"),
    ("rm -rf after cd to own folder", I, *bash(f"cd {W}/app && rm -rf build"), "ok"),
    ("rm -rf absolute in own folder", I, *bash(f"rm -rf {os.path.realpath(ROOT)}/{W}/build"), "ok"),
    ("rm -rf going up with ..", I, *bash(f"rm -rf {W}/../../other"), "no"),
    ("rm -rf in $TMPDIR", I, *bash("rm -rf \"$TMPDIR/sdd-x\""), "ok"),
    # ── The guard's own files (main checkout) ──
    ("sed -i on the main permissions.json", I, *bash("sed -i '' 's/a/b/' .claude/permissions.json"), "no"),
    ("cp over the main guard", I, *bash("cp /tmp/g.py .claude/hooks/agent_guard.py"), "no"),
    ("> main permissions.json", I, *bash("echo {} > .claude/permissions.json"), "no"),
    ("sed -i on a worktree's permissions.json", I, *bash(f"sed -i '' 's/a/b/' {W}/.claude/permissions.json"), "ok"),
    ("> a worktree's settings.json", I, *bash(f"echo {{}} > {W}/.claude/settings.json"), "ok"),
    ("Edit the main guard", I, *write(".claude/hooks/agent_guard.py"), "no"),
    # ── Normal work passes ──
    ("tests + lint", I, *bash(f"cd {W} && make test && npx eslint . --max-warnings 0"), "ok"),
    ("git status / diff / log", I, *bash("git status && git diff main...HEAD && git log --oneline -3"), "ok"),
    ("kill by own port", I, *bash("lsof -ti tcp:3112 -sTCP:LISTEN | xargs kill"), "ok"),
    ("path in a variable: S=…; $S/x.sh", I, *bash("S=/tmp/sdd-x; $S/probe.sh | tee $S/b.txt"), "ok"),
    ("$TMPDIR in the program", I, *bash("$TMPDIR/sdd-x/probe.sh"), "ok"),
    ("quoted parens inside $(…)", I, *bash("for f in *.py; do echo \"$(grep -c 'f(' $f)\"; done"), "ok"),
    ("arithmetic $(( $(…) - a ))", I, *bash("a=1; echo \"n=$(( $(wc -l < x.txt) - a ))\""), "ok"),
    # ── Edits ──
    ("implementer edits in its folder", I, *write(f"{W}/src/a.py"), "ok"),
    ("implementer edits in /tmp", I, *write("/tmp/sdd-x/a.txt"), "ok"),
    ("implementer edits outside", I, *write("src/a.py"), "no"),
    ("implementer edits .env in its folder", I, *write(f"{W}/.env"), "no"),
    ("planner writes plan.md", PL, *write("specs/012-x/plan.md"), "ok"),
    ("planner writes plan.md in a folder", PL, *write(f"{W}/specs/012-x/plan.md"), "ok"),
    ("planner writes spec.md", PL, *write("specs/012-x/spec.md"), "no"),
    ("planner uses the terminal", PL, *bash("ls"), "no"),
    ("reviewer edits", R, *write(f"{W}/src/a.py"), "no"),
    ("other subagent: push", "general-purpose", *bash("git push"), "no"),
    ("other subagent: edits in a folder", "general-purpose", *write(f"{W}/src/a.py"), "ok"),
    ("subagent with only agent_id", "", *bash("git push"), "no"),
    ("Read isn't checked", I, "Read", {"file_path": "src/a.py"}, "ok"),
    # ── Reviewer: read-only ──
    ("reviewer git add", R, *bash("git add x"), "no"),
    ("reviewer git stash", R, *bash("git stash"), "no"),
    ("reviewer git checkout branch", R, *bash("git checkout feat/x"), "no"),
    ("reviewer > file", R, *bash("echo x > f.txt"), "no"),
    ("reviewer > /tmp", R, *bash("echo x > /tmp/x"), "ok"),
    ("reviewer > $TMPDIR", R, *bash("make report > \"$TMPDIR/sdd-reviewer/r.txt\""), "ok"),
    ("reviewer > $S with temp S", R, *bash("S=/tmp/rev-x; mkdir -p $S; ls > $S/l.txt"), "ok"),
    ("reviewer 2>&1 and 2>/dev/null", R, *bash("ls 2>&1 | head; ls x 2>/dev/null"), "ok"),
    ("reviewer node -e with =>", R, *bash("node -e \"[1].map(a => a)\""), "ok"),
    ("reviewer sed -i", R, *bash("sed -i '' 's/a/b/' src/a.py"), "no"),
    ("reviewer sed -i in /tmp", R, *bash("sed -i '' 's/a/b/' /tmp/rev/a.py"), "ok"),
    ("reviewer perl -pi", R, *bash("perl -pi -e 's/a/b/' src/a.py"), "no"),
    ("reviewer perl -pi in /tmp", R, *bash("perl -pi -e 's/a/b/' /tmp/rev/a.py"), "ok"),
    ("reviewer tee", R, *bash("ls | tee out.txt"), "no"),
    ("reviewer tee to /tmp", R, *bash("ls | tee /tmp/sdd-reviewer/x.txt"), "ok"),
    ("reviewer rm", R, *bash("rm src/a.py"), "no"),
    ("reviewer touch", R, *bash("touch src/x.py"), "no"),
    ("reviewer mv from /tmp into the repo", R, *bash("mv /tmp/a.py src/a.py"), "no"),
    ("reviewer rm in $TMPDIR", R, *bash("rm -rf \"$TMPDIR/sdd-reviewer-012\""), "ok"),
    ("reviewer cp inside the repo", R, *bash("cp src/a.py src/b.py"), "no"),
    ("reviewer cp to /tmp", R, *bash("cp src/a.py /tmp/rev/a.py"), "ok"),
    ("reviewer cp to the /tmp root", R, *bash("cp src/a.py /tmp/"), "ok"),
    ("reviewer rsync to /tmp", R, *bash("rsync -a src/ /tmp/rev/src/"), "ok"),
    ("reviewer cd /tmp && relative writes", R, *bash("cd /tmp/rev && cp a.py b.py && perl -0pi -e 's/a/b/' b.py"), "ok"),
    ("reviewer: the cd in ( ) doesn't leak", R, *bash("(cd /tmp/rev && ls); touch src/x.py"), "no"),
    ("reviewer removes a link (not its target) in /tmp", R, *bash(f"rm {LINKS}/link-to-repo"), "ok"),
    ("reviewer: /tmp/link-to-repo/x isn't temporary", R, *bash(f"touch {LINKS}/link-to-repo/x.py"), "no"),
    ("reviewer worktree.sh", R, *bash("scripts/worktree.sh 999-x"), "no"),
    ("reviewer baseline.sh", R, *bash("scripts/baseline.sh"), "ok"),
    ("reviewer npm ci", R, *bash("npm ci"), "no"),
    ("reviewer uv sync", R, *bash("uv sync"), "no"),
    ("reviewer --fix", R, *bash("npx eslint src --fix"), "no"),
    ("reviewer prettier --write", R, *bash("npx prettier --write src"), "no"),
    ("reviewer git push (common rule)", R, *bash("git push"), "no"),
    ("reviewer git diff + tests", R, *bash("git diff main...HEAD && make test"), "ok"),
    # ── Main session: the guard doesn't touch it ──
    ("main: git push", None, *bash("git push"), "ok"),
    ("main: protected script", None, *bash(f"./{P_SCRIPT}"), "ok"),
    ("main: edits outside", None, *write("src/a.py"), "ok"),
]


def payload(agent, tool, inp, root):
    # The agent's cwd: the root by default (where subagents start), or `_cwd` relative to it.
    cwd = os.path.join(root, inp["_cwd"]) if "_cwd" in inp else root
    inp = {k: v for k, v in inp.items() if k != "_cwd"}
    d = {"tool_name": tool, "tool_input": inp, "cwd": cwd, "session_id": "selftest"}
    if agent is not None:
        d["agent_id"] = "a1"
        if agent:
            d["agent_type"] = agent
    return d


def run_hook(d, root, perms=None, hook=HOOK):
    """Exit code of the real guard (subprocess), the way Claude Code calls it."""
    cmd = [sys.executable, hook] + (["--permissions", perms] if perms else [])
    r = subprocess.run(cmd, input=json.dumps(d), capture_output=True, text=True,
                       env=dict(os.environ, CLAUDE_PROJECT_DIR=root), timeout=20)
    return r.returncode, r.stderr.strip()


def load_guard():
    spec = importlib.util.spec_from_file_location("agent_guard", HOOK)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


def corpus(path, old, old_root, out):
    """This guard vs another one (e.g. main's) over real commands ({agent_type, command} per line)."""
    g = load_guard()
    perms = g.load(PERMISSIONS)
    root = os.path.realpath(old_root)  # same root for both (in Claude Code, CLAUDE_PROJECT_DIR)
    new_blocks, freed, total = [], [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            total += 1
            d = payload(c["agent_type"], "Bash", {"command": c["command"]}, root)
            new = g.decide(d, perms, root)
            code, err = run_hook(d, old_root, hook=old)
            if new and code != 2:
                new_blocks.append((c, new))
            elif code == 2 and not new:
                freed.append((c, err))
    with open(out, "w", encoding="utf-8") as f:
        for title, lst in (("NEW BLOCKS", new_blocks), ("FREED (the old one blocked)", freed)):
            f.write(f"##### {title}: {len(lst)}\n")
            for c, m in lst:
                f.write(f"[{c['agent_type']}] {c['command']}\n    → {m}\n\n")
    print(f"Corpus: {total} commands · new blocks {len(new_blocks)} · freed {len(freed)} → {out}")
    return 0


def main():
    a = sys.argv
    if "--corpus" in a:
        return corpus(a[a.index("--corpus") + 1], a[a.index("--old") + 1],
                      a[a.index("--old-root") + 1], a[a.index("--out") + 1])
    verbose, mutate = "-v" in a, "--no-mutation" not in a
    # Root = this checkout (not a temp folder: there everything "is temporary" and edits would pass).
    root = os.path.realpath(ROOT)
    tmp = tempfile.mkdtemp(prefix="sdd-guard-")
    fails = 0

    # 1) Cases against the real guard, by subprocess.
    for desc, agent, tool, inp, expected in CASES:
        code, err = run_hook(payload(agent, tool, inp, root), root)
        got = {0: "ok", 2: "no"}.get(code, f"exit {code}")
        who = "main" if agent is None else (agent or "no agent_type")
        good = got == expected
        fails += not good
        if verbose or not good:
            print(f"{'ok ' if good else 'BAD'} [{who}] {desc}: expected {expected}, got {got}"
                  f"{(' · ' + err) if err and not good else ''}")

    # 2) Without permissions.json, or broken: every subagent is denied; the main session stays free.
    broken = os.path.join(tmp, "broken.json")
    with open(broken, "w") as f:
        f.write("{not json")
    for desc, perms, agent, expected in [
        ("no permissions.json: subagent", os.path.join(tmp, "missing.json"), I, 2),
        ("broken permissions.json: subagent", broken, I, 2),
        ("broken permissions.json: main session", broken, None, 0),
    ]:
        code, _ = run_hook(payload(agent, "Bash", {"command": "ls"}, root), root, perms)
        good = code == expected
        fails += not good
        if verbose or not good:
            print(f"{'ok ' if good else 'BAD'} {desc}: expected exit {expected}, got {code}")
    print(f"Cases: {len(CASES) + 3 - fails}/{len(CASES) + 3} right.")

    # 3) Mutation: removing any rule must change some case.
    if mutate:
        g = load_guard()
        base = g.load(PERMISSIONS)
        if base is None:
            print("BAD permissions.json doesn't load.")
            return 1

        def results(perms):
            return [g.decide(payload(ag, t, i, root), perms, root) is None for _, ag, t, i, _ in CASES]

        ref = results(base)
        if ref != [e == "ok" for *_, e in CASES]:
            print("BAD the in-process guard doesn't match the cases (does the subprocess one?).")
            fails += 1
        lists = [("commands", base["commands"]), ("never_edit", base["never_edit"])]
        ids = [r["id"] for _, lst in lists for r in lst]
        if len(ids) != len(set(ids)):
            print(f"BAD repeated ids in permissions.json: {sorted({i for i in ids if ids.count(i) > 1})}")
            fails += 1
        untested = []
        for name, lst in lists:
            for k, r in enumerate(lst):
                perms = copy.deepcopy(base)
                del perms[name][k]
                if results(perms) == ref:
                    untested.append(r["id"])
        for i in untested:
            print(f"BAD mutation: removing rule «{i}» changes no case (add one that tests it).")
        fails += len(untested)
        print(f"Mutation: {len(ids) - len(untested)}/{len(ids)} rules change some case when removed.")

    shutil.rmtree(tmp, ignore_errors=True)
    print("OK" if not fails else f"FAIL: {fails} problem(s).")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
