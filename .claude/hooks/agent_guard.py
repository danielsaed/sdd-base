#!/usr/bin/env python3
"""PreToolUse: each subagent can only do what its role allows.

An agent's `tools:` decides WHICH tools it has; this decides WHAT it may do with them (the
terminal can't be narrowed from `tools:`). Claude Code passes `agent_type` when the call
comes from a subagent; without it, it's the main session (the orchestrator), governed by
the `deny` rules in settings.json and by asking the user for OK.

WHAT IT PROTECTS AND WHAT IT DOESN'T: it stops MISTAKES by cooperative agents (pushing,
merging, running shared-state scripts, reading secrets, deleting outside their folder, the
reviewer writing); it is not a sandbox against an attacker: known evasions are accepted in
writing under `accepted_risks` in `.claude/permissions.json`.

The rules live in `.claude/permissions.json` (roles, forbidden commands, each with its
why). If it's missing or invalid, EVERYTHING is denied to subagents: a guard that doesn't
know what to allow must not allow everything.

By INTENT, not by words (a commit message that names a forbidden script passes; running
it doesn't): heredoc bodies are dropped (they're data), `$(…)` and `…` are analyzed on
their own, the rest is split with shlex into simple commands (`&& || ; | \\n`), `X=y` and
launchers (env, time, nohup, uv run, xargs, npx…) are skipped, `bash -c`/`eval`/functions
are looked into, and git's `-C dir`/`-c k=v` are skipped. Variables assigned a literal in
the same command (`S=/path; $S/x.sh`) are substituted; `do`/`then`/`{`/`(` are looked into;
relative paths resolve against the hook's REAL cwd (subagents start at the main root),
following the command's `cd`s; inline code (`node -e`, `python3 -c`…) is scanned; scripts
are judged by where their symlinks point. What can't be analyzed (unclosed quotes, a shell
or interpreter reading stdin, a program that is a variable with no known value) is denied.
An `executes` rule's `option` matches a value-less flag (`script.sh --merge`) the same
way: exact, abbreviated (`--m…`), `=value`, or unreadable (`$…`, a substitution, `{}`,
or xargs' stdin) all count as present, so a subagent can't slip it past the rule.
Before changing rules, measure them on real commands: `guard_selftest.py --corpus`.

Deny = exit 2 + reason on stderr (the agent reads it and corrects itself). Self-test:
`python3 scripts/verify/guard_selftest.py` (in CI). `--permissions <path>` only for it.
"""
import fnmatch
import json
import os
import re
import shlex
import sys
import tempfile

PERMISSIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "permissions.json")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
TYPES = {"program", "executes", "token", "redirect", "code"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
PY = re.compile(r"python(\d+(\.\d+)?)?")
# Option that carries inline CODE, per interpreter (`node -e "…"`, `perl -ne '…'`): that text
# is a program; it's scanned with the `code` rules.
CODE_OPT = {"node": r"-e|-p|--eval|--print", "bun": r"-e|-p|--eval|--print",
            "perl": r"-[a-zA-Z0-9]*[eE]", "ruby": r"-[a-zA-Z0-9]*e", "php": r"-r", "python": r"-[a-zA-Z]*c"}
INTERPRETERS = set(CODE_OPT) | {"deno"}
CTX = {"root": "", "cwd": "", "line": ""}  # set by decide(): to resolve relative paths and links
CWD = "\0cwd"  # key in `variables`: folder after the command's `cd`s (None = the agent's; False = unknown)
PUNCT = "();<>|&\n"
SUB = re.compile(r"__SUB\d+__")  # marker of a $(…) substitution: analyzed when its command is reached
XARGS = "\0xargs"  # marker: "the rest of these arguments come from xargs' stdin" (can't be read)
# Shell words that go BEFORE the real command: `do git push` runs git push.
KEYWORDS = {"{", "}", "!", "do", "then", "else", "elif", "if", "while", "until"}
# Environment variables that may appear in a program's path (`$TMPDIR/x.sh`).
KNOWN_VARS = {"TMPDIR", "HOME", "PWD", "OLDPWD", "USER"}
NEVER = "(?!x)x"  # regex that never matches: {protected} when the project defines none
MODULE = "\0module"  # "script" of `python -m x`: something runs (not stdin) but it's no file path


class Denied(Exception):
    pass


def load(path):
    """The permissions JSON, or None if missing or malformed (→ everything is denied)."""
    try:
        with open(path, encoding="utf-8") as f:
            p = json.load(f)
        roles = p["roles"]
        assert isinstance(roles, dict) and "*" in roles
        for v in roles.values():
            v = roles[v] if isinstance(v, str) else v
            assert isinstance(v["edit"], list) and v["terminal"] in (True, False, "read")
        prot = p.get("protected") or NEVER
        re.compile(prot)

        def fill(x):  # {protected} → its regex, so the list of protected scripts lives in one place
            if isinstance(x, str):
                return x.replace("{protected}", f"(?:{prot})")
            if isinstance(x, list):
                return [fill(y) for y in x]
            if isinstance(x, dict):
                return {k: fill(v) for k, v in x.items()}
            return x
        p["commands"] = [fill(r) for r in p["commands"]]
        for r in p["commands"]:
            assert r["type"] in TYPES and r["id"] and r["reason"]
            for k in ("regex", "script", "redirect_to", "line_names", "paths_match", "except", "skip"):
                if k in r:
                    re.compile(r[k])
        for r in p["never_edit"]:
            assert r["id"] and r["reason"]
            re.compile(r["regex"])
        return p
    except Exception:
        return None


# ── Parsing the command ──────────────────────────────────────────────────────

def drop_heredocs(cmd):
    """Drops heredoc bodies: they're data (a commit message), not commands. If a shell or an
    interpreter reads them, that's denied separately (program reading stdin)."""
    lines, out, i = cmd.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in re.finditer(r"(?<!<)<<(-?)\s*(['\"]?)([\w.-]+)\2", line):
            end = m.group(3)
            while i < len(lines) and (lines[i].lstrip("\t") if m.group(1) else lines[i]) != end:
                i += 1
            i += 1  # the delimiter line
    return "\n".join(out)


def closing(s, j):
    """Index after the `)` closing a `$(` opened right before j. Respects quotes
    (`$(grep 'f(' x)`, `awk '/^\\);$/'`) and `$(` nested inside double quotes."""
    depth, q, n = 1, None, len(s)
    while j < n:
        ch = s[j]
        if q == "'":
            q = None if ch == "'" else q
        elif ch == "\\":
            j += 1
        elif q == '"':
            if ch == '"':
                q = None
            elif s.startswith("$(", j):
                j = closing(s, j + 2)
                continue
        elif ch in "'\"":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if not depth:
                return j + 1
        j += 1
    raise Denied("the command can't be analyzed (unclosed parenthesis).")


def extract_subs(s):
    """Pulls out $(…), `…`, <(…) and >(…) outside single quotes → (text with markers,
    [(sub, is_arithmetic)]). `$((1 + $(x)))` is arithmetic: only its $(…) count."""
    out, subs, i, n, state = [], [], 0, len(s), None
    while i < n:
        ch = s[i]
        if state == "'":
            state = None if ch == "'" else state
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(s[i:i + 2])
            i += 2
            continue
        if ch == "'" and state is None:
            state = "'"
        elif ch == '"':
            state = None if state == '"' else '"'
        elif s.startswith("$(", i) or (state is None and ch in "<>" and s.startswith("(", i + 1)):
            j = closing(s, i + 2)
            inner = s[i + 2:j - 1]
            arith = s.startswith("$((", i) and inner.endswith(")")
            subs.append((inner[1:-1] if arith else inner, arith))
            out.append(f"__SUB{len(subs) - 1}__")
            i = j
            continue
        elif ch == "`":
            j = s.find("`", i + 1)
            if j < 0:
                raise Denied("the command can't be analyzed (unclosed backquote).")
            subs.append((s[i + 1:j], False))
            out.append(f"__SUB{len(subs) - 1}__")
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), subs


def skip_options(argv, with_value=()):
    """Drops leading options (those in `with_value` take the next token)."""
    while argv and argv[0].startswith("-") and argv[0] != "-":
        argv = argv[2:] if argv[0] in with_value else argv[1:]
    return argv


def strip_launchers(argv):
    """`env X=1 nohup uv run git push` → `git push`: the program that actually runs."""
    while argv:
        a, b = argv[0], os.path.basename(argv[0])
        if re.fullmatch(r"[A-Za-z_]\w*=.*", a, re.S) or a in KEYWORDS:
            argv = argv[1:]
        elif a == "function":  # `function f { …; }`: the body is the command (the name is skipped)
            argv = argv[2:]
        elif b == "env":
            # `env -S 'git push'` (also `-iS`, `-u X -S`, `--split-string=`): -S splits its
            # argument into a command. The values of -u/-C are skipped.
            k = 1
            while k < len(argv) and argv[k].startswith("-") and argv[k] != "-":
                x = argv[k]
                if x in ("-u", "-C", "--unset", "--chdir"):
                    k += 2
                    continue
                m = re.fullmatch(r"--split-string(?:=(.*))?|-([a-zA-Z]*?)S(.*)", x, re.S)
                if m:
                    glued = m.group(1) if x.startswith("--") else m.group(3)
                    if glued:
                        val, rest = glued, argv[k + 1:]
                    else:
                        val, rest = (argv[k + 1] if k + 1 < len(argv) else ""), argv[k + 2:]
                    try:
                        argv = ["env"] + shlex.split(val) + rest
                    except ValueError:
                        raise Denied("env -S with an argument that can't be analyzed.")
                    k = 1
                    continue
                k += 1
            argv = argv[k:]
        elif b in ("time", "nohup", "exec", "command", "builtin", "sudo", "caffeinate"):
            argv = skip_options(argv[1:], ("-u", "-g", "-w"))
        elif b == "nice":
            argv = skip_options(argv[1:], ("-n",))
        elif b == "timeout":
            argv = skip_options(argv[1:], ("-s", "-k", "--signal", "--kill-after"))[1:]
        elif b == "xargs":
            argv = skip_options(argv[1:], ("-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a", "-J", "-R"))
            # `echo push | xargs git`: the subcommand arrives on stdin, it can't be analyzed.
            if argv and os.path.basename(argv[0]) == "git" and len(git_normal(argv)) < 2:
                raise Denied("xargs git without a literal subcommand: can't be analyzed.")
            # Anything else gets EXTRA arguments from stdin after the given ones: mark them
            # so a flag rule (`option`) treats the command as unreadable, not as "no flag"
            # (`echo --merge | xargs pr_wait.sh 30`).
            if argv:
                argv = argv + [XARGS]
        elif b == "npx":
            argv = skip_options(argv[1:], ("-p", "--package", "-c", "--call"))
        elif b == "uv" and argv[1:2] == ["run"]:
            argv = skip_options(argv[2:], ("--with", "--python", "-p", "--project", "--directory",
                                           "--env-file", "--group", "--extra", "--package"))
        else:
            break
    return argv


def git_normal(argv):
    """`git -C dir -c k=v --no-pager push` → `git push` (otherwise `git -C … push` slips through)."""
    if not argv or os.path.basename(argv[0]) != "git":
        return argv
    rest = argv[1:]
    while rest and rest[0].startswith("-"):
        cfg = rest[0].split("=", 1)[1] if rest[0].startswith("--config-env=") else (
            rest[1] if rest[0] == "--config-env" and len(rest) > 1 else "")
        if cfg.lower().startswith("alias."):
            raise Denied("git --config-env=alias.… can't be analyzed (it renames subcommands).")
        if rest[0] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"):
            if rest[0] == "-c" and len(rest) > 1 and rest[1].lower().startswith("alias."):
                raise Denied("git -c alias.… can't be analyzed (it renames subcommands).")
            rest = rest[2:]
        else:
            rest = rest[1:]
    # `git $(echo push)`, `git $X`, `xargs -I{} git {}`: a non-literal subcommand is unknown.
    if rest and not re.fullmatch(r"[A-Za-z][\w.-]*", rest[0]):
        raise Denied(f"non-literal git subcommand («{rest[0]}»): can't be analyzed.")
    if rest and rest[0] == "stage":  # `git stage` is `git add` (built-in alias)
        rest = ["add"] + rest[1:]
    return ["git"] + rest


class Cmd:
    def __init__(self, argv, redir, cwd=None):
        self.argv = git_normal(argv)
        self.raw = argv
        self.redir = redir  # [(operator, target)]
        self.cwd = cwd  # folder it runs in (after the command's `cd`s); None = the agent's


def expand(t, variables):
    """Replaces $X / ${X} with its value if a literal was assigned earlier in the same command."""
    def value(m):
        v = variables.get(m.group(1) or m.group(2))
        return m.group(0) if v is None else v
    return re.sub(r"\$\{(\w+)\}|\$(\w+)", value, t)


def assign(tokens, variables):
    """Records `X=literal` (also after export/local). Whatever depends on something unknown
    ($(…), $1, another variable without a value) stays unknown (None)."""
    for t in tokens:
        m = re.fullmatch(r"([A-Za-z_]\w*)=(.*)", t, re.S)
        if m:
            v = expand(m.group(2), variables)
            variables[m.group(1)] = None if (SUB.search(v) or re.search(r"\$\{?\w", v)) else v


def commands(cmd, depth=0, variables=None):
    """Every simple command (also those nested in $(…), bash -c, eval, find -exec)."""
    if depth > 6:
        raise Denied("the command can't be analyzed (nested too deep).")
    variables = {} if variables is None else variables
    variables.setdefault(CWD, None)
    stack = []  # `( cd x; … )`: the cd doesn't leave the parenthesis
    cmd, subs = extract_subs(drop_heredocs(cmd.replace("\\\n", " ")))
    pending = dict(enumerate(subs))  # analyzed when their command is reached (with its variables)

    def subs_of(tokens):
        for t in tokens:
            for n in re.findall(r"__SUB(\d+)__", t):
                s, arith = pending.pop(int(n), (None, None))
                if s is None:
                    continue
                if arith:  # $((…)) isn't a command; its inner $(…) are
                    for s2, _ in extract_subs(s)[1]:
                        yield from commands(s2, depth + 1, variables)
                else:
                    yield from commands(s, depth + 1, variables)
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=PUNCT)
    lex.whitespace, lex.whitespace_split, lex.commenters = " \t\r", True, ""
    try:
        toks = list(lex)
    except ValueError:
        raise Denied("the command can't be analyzed (unclosed quotes).")
    current, redir, i = [], [], 0
    while i < len(toks):
        t = toks[i]
        if t and all(c in PUNCT for c in t):
            if "<" in t or ">" in t:
                if current and current[-1].isdigit():
                    current.pop()  # the descriptor of `2>`
                redir.append((t, toks[i + 1] if i + 1 < len(toks) else ""))
                i += 2
                continue
            if current or redir:
                yield from subs_of(current + [d for _, d in redir])
                yield from simple(current, redir, depth, variables)
            current, redir = [], []
            for ch in t:
                if ch == "(":
                    stack.append(variables.get(CWD))
                elif ch == ")" and stack:
                    variables[CWD] = stack.pop()
        else:
            current.append(t)
        i += 1
    if current or redir:
        yield from subs_of(current + [d for _, d in redir])
        yield from simple(current, redir, depth, variables)
    yield from subs_of(f"__SUB{n}__" for n in list(pending))  # any left loose


def simple(argv, redir, depth, variables):
    # GIT_CONFIG_COUNT/KEY_n/VALUE_n in the environment = `git -c …`: they can define aliases.
    if any(re.fullmatch(r"GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+|PARAMETERS)=.*", t, re.S) for t in argv):
        raise Denied("GIT_CONFIG_* in the environment can rename git subcommands: can't be analyzed.")
    assign(argv[:next((k for k, t in enumerate(argv) if not re.fullmatch(r"[A-Za-z_]\w*=.*", t, re.S)),
                      len(argv))], variables)
    argv = strip_launchers(argv)
    # `R="python3 x.py"; $R -c …`: the program is the variable → its value is split, as the shell does.
    m = re.fullmatch(r"\$\{?(\w+)\}?", argv[0]) if argv else None
    if m and variables.get(m.group(1)):
        try:
            argv = strip_launchers(shlex.split(variables[m.group(1)]) + argv[1:])
        except ValueError:
            raise Denied("the value of the variable used as a program can't be analyzed.")
    argv = [expand(t, variables) for t in argv]
    redir = [(op, expand(d, variables)) for op, d in redir]
    if not argv:
        yield Cmd([], redir, variables.get(CWD))
        return
    a0, b = argv[0], os.path.basename(argv[0])
    # `$@`, `$*`, `$1`, `$X` with no value: the program is unknown (`f(){ "$@"; }; f git push`).
    if SUB.search(a0) or any(v not in KNOWN_VARS for v in re.findall(r"\$\{?([^\s/}]+)", a0)):
        raise Denied("the program is a variable with no known value or a substitution: can't be analyzed.")
    if b in ("for", "select", "case"):
        if b != "case" and len(argv) > 1:
            variables[argv[1]] = None  # the loop variable: unknown value
        return
    if b == "cd":  # the folder is followed: `cd /tmp/x && cp a b` writes into a temp folder
        dest = os.path.expanduser(argv[1] if len(argv) > 1 else "~")
        # Relative to the agent's REAL cwd (the hook JSON's): subagents start at the main
        # root, so `cd src && rm -rf x` is the user's checkout, not the agent's folder.
        base = CTX["cwd"] or CTX["root"] if variables.get(CWD) is None else variables.get(CWD)
        variables[CWD] = (False if "$" in dest or SUB.search(dest) or dest == "-"  # `cd -`: unknown
                          or (base is False and not dest.startswith("/"))
                          else os.path.normpath(os.path.join(base or "/", dest)))
    if b in ("export", "local", "declare", "readonly", "typeset"):
        assign(argv[1:], variables)
    if b == "eval":
        yield from commands(" ".join(argv[1:]), depth + 1, variables)
        return
    if b in SHELLS:
        args = argv[1:]
        if any(re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", x) for x in args if x.startswith("-")):
            rest = skip_options(args, ("-o", "+o"))
            yield from commands(rest[0] if rest else "", depth + 1, variables)
            return
        if not skip_options(args, ("-o", "+o")):
            raise Denied(f"{b} without a script or -c reads stdin: can't be analyzed.")
        # `cat x.sh | bash -s 30 --merge`: with -s the script arrives on stdin and what
        # follows are ITS arguments (not a script to look for), like `bash <`.
        if any(re.fullmatch(r"-[a-zA-Z]*s[a-zA-Z]*", x) for x in args if x.startswith("-")):
            raise Denied(f"{b} -s reads the script from stdin: can't be analyzed.")
    if b in SHELLS or interpreter(b) or b in ("source", "."):
        s, _, _ = parts(argv)
        # `bash <(curl …)`, `… | sh /dev/stdin`: the script arrives through a pipe, like stdin.
        if s and (SUB.search(s) or s == "-" or s.startswith(("/dev/stdin", "/dev/fd/", "/proc/self/fd/"))):
            raise Denied(f"{b} reading its script from a pipe or substitution: can't be analyzed.")
    if interpreter(b):
        s, _, code = parts(argv)
        info = any(x in ("-v", "-V", "--version", "-h", "--help") for x in argv[1:])
        if not s and not code and not info:
            raise Denied(f"{b} without a script or inline code reads stdin: can't be analyzed.")
    if b == "find":
        for k, x in enumerate(argv):
            if x in ("-exec", "-execdir", "-ok", "-okdir"):
                end = next((j for j in range(k + 1, len(argv)) if argv[j] in (";", "+")), len(argv))
                yield from simple(argv[k + 1:end], [], depth + 1, variables)
    yield Cmd(argv, redir, variables.get(CWD))


def interpreter(b):
    return "python" if PY.fullmatch(b) else b if b in INTERPRETERS else None


def parts(argv):
    """→ (script, its arguments, [inline code]) of `python3 X`, `node -e "…"`, `bash X`,
    `source X`… or (X, args, []) when X is the program itself."""
    if not argv:
        return None, [], []
    b = os.path.basename(argv[0])
    i = interpreter(b)
    if not (i or b in SHELLS or b in ("source", ".")):
        return argv[0], argv[1:], []
    args, code = argv[1:], []
    if i == "deno" and args[:1] == ["eval"]:
        return None, [], args[1:2]
    while args and args[0].startswith("-") and args[0] != "-":
        a = args[0]
        if a.startswith(("--eval=", "--print=")):
            code.append(a.split("=", 1)[1])
            args = args[1:]
        elif i in CODE_OPT and re.fullmatch(CODE_OPT[i], a) and len(args) > 1:
            code.append(args[1])
            args = args[2:]
        elif a == "-m" and i == "python":  # `python -m module`: a module runs, not a script nor stdin
            return MODULE, args[2:], []
        else:
            args = args[2:] if a in ("-W", "-X", "-r", "--require", "--import", "-I", "-M") else args[1:]
    if code:
        return None, [], code
    return (args[0], args[1:], []) if args else (None, [], [])


def resolved(s, cwd=None):
    """A script's real path (follows symlinks): a link to a protected script doesn't slip through."""
    p = os.path.normpath(os.path.join(cwd or CTX["cwd"] or CTX["root"], os.path.expanduser(s)))
    return os.path.realpath(p)


# ── Rules ────────────────────────────────────────────────────────────────────

TMPS = ("/tmp/", "/private/tmp/", "/private/var/folders/", "/var/folders/",
        os.path.realpath(tempfile.gettempdir()) + "/")


def absolute(p, cwd):
    """Absolute path WITHOUT following the LAST link (rm/ln act on the link, not its target)
    but following the folder's: `/tmp/link-to-repo/x` isn't temporary. None if unknown."""
    p = os.path.expanduser(p)
    if not p.startswith("/"):
        if cwd is False:
            return None
        p = os.path.join(cwd or CTX["cwd"] or CTX["root"], p)
    p = os.path.normpath(p)
    return os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))


def temporary(p, cwd=None, root_ok=False):
    """Is the path in a temp folder? `root_ok=True` also accepts the root (/tmp/) as a cp target."""
    if p.startswith(("$TMPDIR", "${TMPDIR}")):
        return True
    if "$" in p:  # `/tmp/rev/out-$p.txt` (a loop variable): the literal folder in front counts
        pre = p[:p.index("$")]
        if "/.." in p[len(pre):] or not os.path.dirname(pre):
            return False
        p = os.path.join(os.path.dirname(pre), "x")
    rp = absolute(p, cwd)
    return bool(rp) and (rp + "/").startswith(TMPS) and (root_ok or (rp + "/") not in TMPS)


def outside(p, cwd):
    """Does the path leave a feature folder? Resolved against the real cwd (and its `cd`s):
    outside is anything not under `.worktrees/<slug>/…` nor in a temp folder (`.`, `*`, `$X` too)."""
    if temporary(p, cwd):
        return False
    if p in (".", "./", "*") or p.startswith("$"):
        return True
    rp = absolute(p, cwd)
    return not rp or not re.match(re.escape(CTX["root"]) + r"/\.worktrees/[^/]+/.", rp)


def under_root(p, cwd, regex):
    """Does the path, relative to the main root, match `regex`? (`paths_match`). Unknown → no."""
    if "$" in p or SUB.search(p):
        return False
    rp = absolute(p, cwd)
    if not rp:
        return False
    rel = os.path.relpath(rp, CTX["root"])
    return not rel.startswith("..") and bool(re.search(regex, rel))


def expands_to(t, names):
    """Is the token one of `names`? With wildcards too (`.env*`, `.en?`, `{.env,x}`): the shell expands them."""
    if not names:
        return False
    base = os.path.basename(t)
    # Same first character: a bare `*` doesn't expand to dotfiles in the shell.
    if re.search(r"[*?\[]", base) and any(fnmatch.fnmatchcase(n, base) and base[:1] == n[:1] for n in names):
        return True
    alt = "|".join(re.escape(n) for n in names)
    return bool(re.search(rf"(^|[/{{,=])({alt})([}},]|$)", t))


def matches(r, c):
    t = r["type"]
    if t == "token":
        if r.get("except") and c.argv and re.fullmatch(r["except"], os.path.basename(c.argv[0])):
            return False
        # `find -name '.e*'`: a find pattern (quoted), not expanded by the shell.
        find_pattern = {k + 1 for k, x in enumerate(c.raw)
                        if os.path.basename(c.raw[0]) == "find" and x in ("-name", "-iname", "-path", "-wholename")}
        return any(re.fullmatch(r["regex"], x) or (k not in find_pattern and expands_to(x, r.get("wildcards")))
                   for k, x in enumerate(c.raw + [d for _, d in c.redir]))
    if t == "redirect":
        writes = [d for op, d in c.redir if ">" in op and not re.fullmatch(r"\d+|-", d)]
        if r.get("paths_match"):
            return any(under_root(d, c.cwd, r["paths_match"]) for d in writes)
        return any(not (d == "/dev/null" or temporary(d, c.cwd)) for d in writes)
    if t == "code":
        _, _, code = parts(c.argv)
        return any(re.search(r["regex"], x) for x in code)
    if t == "executes":
        s, args, _ = parts(c.argv)
        if not s or s == MODULE or not (re.search(r["script"], s) or re.search(r["script"], resolved(s, c.cwd))):
            return False
        if "option" in r:
            # A value-less flag (`pr_wait.sh N --merge`): the exact flag, a `--` prefix of
            # it (argparse abbreviates long options), `--merge=…`, or an argument that
            # can't be read: it has `$`, is a $(…)/`…` substitution (marker __SUBn__), is
            # the `{}` xargs/find use for their placeholder, or is what xargs reads from
            # stdin (marker XARGS).
            o = r["option"]
            for a in args:
                name = a.split("=", 1)[0]
                if ("$" in a or SUB.search(a) or a in ("{}", XARGS) or name == o
                        or (len(name) > 2 and name.startswith("--") and o.startswith(name))):
                    return True
            return False
        if "option_prefix" not in r:
            return True
        for k, a in enumerate(args):  # an option that only matters with a given value
            if not a.startswith(r["option_prefix"]):
                continue
            v = a.split("=", 1)[1] if "=" in a else (args[k + 1] if k + 1 < len(args) else "")
            if v == r["value"] or "$" in v:
                return True
        return False
    # program
    pats, argv = r["argv"], c.argv
    if len(argv) < len(pats) or not re.fullmatch(pats[0], os.path.basename(argv[0])):
        return False
    if not all(re.fullmatch(p, x) for p, x in zip(pats[1:], argv[1:])):
        return False
    rest, skip, script_given = [], False, False
    for x in argv[len(pats):]:
        if skip:
            skip = False
        elif r.get("skip") and re.fullmatch(r["skip"], x):
            skip = script_given = True
        else:
            # git accepts long-option prefixes: `--al` = `--all`, `--upd` = `--update`.
            longs = [lg for lg in r.get("longs", []) if len(x) > 2 and "=" not in x and lg.startswith(x)]
            rest.append(longs[0] if x.startswith("--") and longs else x)
    # `cat X | tee target`: what goes into tee comes from another command on the same line.
    if r.get("line_names") and not re.search(r["line_names"], CTX.get("line", "")):
        return False
    if r.get("redirect_to"):  # `cat X > target`: the input (`< X`) counts as an argument
        if not any(">" in op and re.search(r["redirect_to"], d) for op, d in c.redir):
            return False
        rest = rest + [d for op, d in c.redir if "<" in op]
    if not all(any(re.fullmatch(p, x) for x in rest) for p in r.get("any", [])):
        return False
    paths = [x for x in rest if not x.startswith("-") and x]
    if r.get("first_is_script") and not script_given and paths:
        paths = paths[1:]  # `sed -i 's/a/b/' f`: without -e, the first argument is the script, not a file
    if r.get("no_paths") and paths:
        return False
    if r.get("paths_outside") and not any(outside(x, c.cwd) for x in paths):
        return False
    if r.get("paths_match") and not any(under_root(x, c.cwd, r["paths_match"]) for x in paths):
        return False
    if r.get("except_temp") and paths and all(temporary(x, c.cwd) for x in paths):
        return False
    if r.get("dest_temp") and paths and temporary(paths[-1], c.cwd, root_ok=True):
        return False
    return True


def decide(d, perms, root):
    """→ None if allowed; otherwise the reason. Pure: the self-test calls it in-process too."""
    agent = d.get("agent_type") or ""
    if not d.get("agent_id") and not agent:
        return None  # main session
    if perms is None:
        return "no valid .claude/permissions.json: without it no subagent acts (tell the orchestrator)."
    roles = perms["roles"]
    role = roles.get(agent, roles["*"])
    role = roles[role] if isinstance(role, str) else role
    tool, inp = d.get("tool_name", ""), d.get("tool_input") or {}
    CTX["root"], CTX["cwd"] = root, os.path.realpath(d.get("cwd") or root)
    CTX["line"] = inp.get("command", "") if tool == "Bash" else ""

    if tool in EDIT_TOOLS:
        raw = inp.get("file_path") or inp.get("notebook_path") or ""
        p = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(d.get("cwd") or root, raw))
        rel = os.path.relpath(p, root)
        for r in perms["never_edit"]:
            if re.search(r["regex"], rel):
                return r["reason"]
        if any(re.fullmatch(x, rel) for x in role["edit"]) or (role.get("temp") and temporary(p)):
            return None
        return f"{role.get('reason_edit', 'you may not edit that file.')} (tried {rel})"

    if tool != "Bash":
        return None
    if role["terminal"] is False:
        return role.get("reason_terminal", "no terminal.")
    try:
        cmds = list(commands(inp.get("command", "")))
    except Denied as e:
        return str(e)
    for r in perms["commands"]:
        who = r.get("roles", ["*"])
        if "*" not in who and agent not in who:
            continue
        if any(matches(r, c) for c in cmds):
            return r["reason"]
    return None


def main():
    path = sys.argv[sys.argv.index("--permissions") + 1] if "--permissions" in sys.argv else PERMISSIONS
    try:
        d = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    root = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    reason = decide(d, load(path), root)
    if reason:
        print(f"[guard · {d.get('agent_type') or 'subagent'}] Blocked: {reason}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
