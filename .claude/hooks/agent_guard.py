#!/usr/bin/env python3
"""PreToolUse: each subagent can only do what its role allows.

An agent's `tools:` decides WHICH tools it has; this decides WHAT it may do with them (the
terminal can't be narrowed from `tools:`). Claude Code passes `agent_type` when the call
comes from a subagent; without it, it's the main session (the orchestrator), governed by
the `deny` rules in settings.json and by asking the user for OK.

  planner      → only writes specs/*/plan.md; no terminal.
  reviewer     → edits nothing; terminal only to read, run and verify.
  implementer  → edits ONLY inside .worktrees/; no push, merge, main, .env,
  (and any       new dependencies or protected commands.
   other subagent)

Deny = exit 2 + reason on stderr (the agent reads it and corrects itself).
Known limit: an agent with a terminal could still write a script that does something
forbidden; this closes the obvious paths, not every possible one.
"""
import json
import os
import re
import sys

# ── CUSTOMIZE PER PROJECT ────────────────────────────────────────────────────
# Commands that change SHARED state (database, infra, deploys). Only the orchestrator
# runs them, with the user's OK. Regexes over the whole command line.
PROTECTED_COMMANDS = [
    r"\bpsql\b",
    r"\bsupabase\s+db\s+(push|reset)\b",
    r"\bprisma\s+migrate\s+(deploy|reset)\b",
    r"\bterraform\s+(apply|destroy)\b",
    r"\bkubectl\s+(apply|delete)\b",
    r"scripts/(db_)?apply",          # e.g. a scripts/db_apply.py you add later
]
MAIN_BRANCH = "main"
# ─────────────────────────────────────────────────────────────────────────────

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

agent = d.get("agent_type") or ""
if not d.get("agent_id") and not agent:
    sys.exit(0)  # main session

ROOT = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
tool = d.get("tool_name", "")
inp = d.get("tool_input") or {}


def deny(reason):
    print(f"[guard · {agent or 'subagent'}] Blocked: {reason}", file=sys.stderr)
    sys.exit(2)


def resolve(p):
    return os.path.realpath(p if os.path.isabs(p) else os.path.join(d.get("cwd") or ROOT, p))


# ── File edits ───────────────────────────────────────────────────────────────
if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
    p = resolve(inp.get("file_path") or inp.get("notebook_path") or "")
    rel = os.path.relpath(p, ROOT)
    if agent == "reviewer":
        deny("the reviewer doesn't edit files: report the failure and the implementer fixes it.")
    if agent == "planner":
        if not re.fullmatch(r"(\.worktrees/[^/]+/)?specs/\d{3}-[^/]+/plan\.md", rel):
            deny(f"the planner only writes specs/NNN-slug/plan.md (tried {rel}).")
        sys.exit(0)
    if re.search(r"(^|/)\.env(\.[\w-]+)?$", rel) and not rel.endswith(".example"):
        deny(".env files are off limits.")
    outside = not rel.startswith(".worktrees/")
    temporary = p.startswith(("/tmp/", "/private/tmp/"))
    if outside and not temporary:
        deny(f"a subagent only edits inside its feature folder (.worktrees/NNN-slug/); tried {rel}. "
             "Ask the orchestrator to create it with scripts/worktree.sh.")
    sys.exit(0)

if tool != "Bash":
    sys.exit(0)

c = " ".join((inp.get("command") or "").split())

if agent == "planner":
    deny("the planner doesn't use the terminal.")

# ── All subagents ────────────────────────────────────────────────────────────
RULES = [
    (r"\bgit\s+push\b", "push: only the orchestrator pushes branches."),
    (r"\bgit\s+merge\b|\bgh\s+pr\s+(merge|close)\b", "merging belongs to the orchestrator, with the user's OK."),
    (rf"\bgit\s+(checkout|switch)\s+(-\S+\s+)*{MAIN_BRANCH}\b", f"{MAIN_BRANCH} is off limits for subagents."),
    (r"\bgit\s+(branch\s+-D|worktree\s+remove|reset\s+--hard\s+origin)", "destructive git operation."),
    (r"(^|[\s/'\"=])\.env(\.local)?(\s|$|['\"])", ".env files are not read (scripts load them themselves)."),
    (r"\bnpm\s+(i|install|add)\s+[^-\s]|\byarn\s+add\b|\bpnpm\s+add\b|\bpip\s+install\s+[^-\s]|\bpoetry\s+add\b",
     "a new dependency goes in the spec and the user approves it."),
    (r"\brm\s+-\w*r\w*f?\s+(/|~|\.\.|\*)(\s|$)", "rm -rf out of place."),
] + [(p, "shared-state command: only the orchestrator runs it, with the user's OK.") for p in PROTECTED_COMMANDS]
for pattern, reason in RULES:
    if re.search(pattern, c):
        deny(reason)

# ── Reviewer: read-only ──────────────────────────────────────────────────────
if agent == "reviewer":
    WRITES = [
        r"\bgit\s+(add|commit|reset|restore|rm|mv|stash|rebase|cherry-pick|checkout\s+--|tag)\b",
        r"\bsed\s+(-\S*\s+)*-i", r"\btee\b", r"\brm\s", r"\bmv\s", r"\bnpm\s+(ci|update)\b",
        r"--fix\b", r"(^|[^2&])>>?\s*(?!/dev/null|&)(?!/tmp/|/private/tmp/)\S",
    ]
    # Quoted text is code or data (`node -e "x => y"`), not a redirection.
    unquoted = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", c)
    for pattern in WRITES:
        if re.search(pattern, unquoted):
            deny("the reviewer modifies nothing (it may only write to /tmp). Report it; the implementer fixes it.")

sys.exit(0)
