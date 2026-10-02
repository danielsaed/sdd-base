#!/usr/bin/env bash
# Self-test of the workflow hooks. It protects an invariant (agent permissions and the
# closeout rules), so it earns its place in CI: if someone loosens a rule, this fails.
set -uo pipefail
cd "$(dirname "$0")/.."
export CLAUDE_PROJECT_DIR="$PWD"
fails=0

# Subagent guard: its own self-test (cases + mutation per rule), in scripts/verify/.
python3 scripts/verify/guard_selftest.py | tail -3 || fails=$((fails+1))

# Closeout hook with a throwaway spec.
S="specs/999-selftest"; mkdir -p "$S"; sed 's/NNN · Short title/999 · selftest/' specs/_template/spec.md > "$S/spec.md"
close() { echo "${2:-{\}}" | SDD_MAIN_BRANCH="${MAINB:-__none__}" python3 .claude/hooks/closeout.py >/dev/null 2>&1; local got=$([ $? = 2 ] && echo block || echo pass)
  [ "$got" = "$1" ] || { echo "✗ closeout: $3 → $got (expected $1)"; fails=$((fails+1)); }; }
tick() { for n in "$@"; do sed -i.bak "s/- \[ \] $n/- [x] $n/" "$S/spec.md"; done; rm -f "$S/spec.md.bak"; }
close pass '{}' "fresh spec"
# The throwaway spec is an uncommitted change: on the main branch that must block.
MAINB="$(git branch --show-current)"; [ -n "$MAINB" ] && close block '{}' "uncommitted changes on main"; MAINB=""
tick 1 2 3 4; close block '{}' "verified but not closed"
close pass '{"stop_hook_active":true}' "blocks only once per turn"
sed -i.bak 's/- \[x\] 2/- [ ] 2/' "$S/spec.md"; rm -f "$S/spec.md.bak"; close block '{}' "skipped step"
echo '{}' | python3 .claude/hooks/reminder.py | grep -q "spec 999-selftest" || { echo "✗ reminder doesn't list the open spec"; fails=$((fails+1)); }
rm -rf "$S"

[ $fails = 0 ] && echo "✓ hooks self-test passed" || { echo "$fails failure(s)"; exit 1; }
