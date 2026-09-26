#!/usr/bin/env bash
# Self-test of the workflow hooks. It protects an invariant (agent permissions and the
# closeout rules), so it earns its place in CI: if someone loosens a regex, this fails.
set -uo pipefail
cd "$(dirname "$0")/.."
export CLAUDE_PROJECT_DIR="$PWD"
fails=0

guard() { # agent tool input-json expected(allow|deny)
  printf '%s' "{\"agent_id\":\"t\",\"agent_type\":\"$1\",\"tool_name\":\"$2\",\"tool_input\":$3,\"cwd\":\"$PWD\"}" \
    | python3 .claude/hooks/agent_guard.py >/dev/null 2>&1
  local got=$([ $? = 2 ] && echo deny || echo allow)
  if [ "$got" != "$4" ]; then echo "✗ $1 $2 $3 → $got (expected $4)"; fails=$((fails+1)); fi
}
W="$PWD/.worktrees/012-x"
guard implementer Bash '{"command":"cd .worktrees/012-x && npm test"}' allow
guard implementer Bash '{"command":"git -C .worktrees/012-x commit -m a"}' allow
guard implementer Bash '{"command":"git push origin feat/012-x"}' deny
guard implementer Bash '{"command":"git switch main"}' deny
guard implementer Bash '{"command":"gh pr merge 3"}' deny
guard implementer Bash '{"command":"cat .env"}' deny
guard implementer Bash '{"command":"cat .env.example"}' allow
guard implementer Bash '{"command":"npm install lodash"}' deny
guard implementer Bash '{"command":"npm ci"}' allow
guard implementer Bash '{"command":"terraform apply"}' deny
guard implementer Bash '{"command":"psql -c \"drop table x\""}' deny
guard implementer Write "{\"file_path\":\"$W/src/a.ts\"}" allow
guard implementer Edit "{\"file_path\":\"$PWD/src/a.ts\"}" deny
guard implementer Write "{\"file_path\":\"$W/.env\"}" deny
guard general-purpose Edit "{\"file_path\":\"$PWD/docs/STATUS.md\"}" deny
guard planner Write "{\"file_path\":\"$W/specs/012-x/plan.md\"}" allow
guard planner Write "{\"file_path\":\"$W/specs/012-x/spec.md\"}" deny
guard planner Bash '{"command":"ls"}' deny
guard reviewer Edit "{\"file_path\":\"$W/src/a.ts\"}" deny
guard reviewer Bash '{"command":"git diff main...feat/012-x --stat"}' allow
guard reviewer Bash '{"command":"node -e \"[1].map(x => x>0)\""}' allow
guard reviewer Bash '{"command":"npm test > /tmp/out.txt"}' allow
guard reviewer Bash '{"command":"echo x > src/a.ts"}' deny
guard reviewer Bash '{"command":"git commit -am x"}' deny
guard reviewer Bash '{"command":"npx eslint . --fix"}' deny
# Main session: the guard doesn't act (settings.json deny rules govern it).
printf '%s' '{"tool_name":"Bash","tool_input":{"command":"git push origin feat/x"}}' | python3 .claude/hooks/agent_guard.py \
  || { echo "✗ main session should not be blocked by the guard"; fails=$((fails+1)); }

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
