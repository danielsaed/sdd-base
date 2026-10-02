#!/usr/bin/env bash
# Self-test of the workflow hooks. It protects an invariant (agent permissions, the
# closeout rules and the areas layout the hooks parse), so it earns its place in CI: if
# someone loosens a rule or moves a path the hooks read, this fails.
#
# Everything except the guard runs in a THROWAWAY git repo built from this working tree
# (uncommitted changes included), so feature folders, branches and commits never touch
# the real checkout.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
bad() { echo "✗ $1"; fails=$((fails+1)); }

# Subagent guard: its own self-test (cases + mutation per rule), in scripts/verify/.
python3 scripts/verify/guard_selftest.py | tail -3 || fails=$((fails+1))

# ── Throwaway repo: this working tree, committed on `main` ──
T="$(mktemp -d "${TMPDIR:-/tmp}/sdd-hooks-XXXXXX")"; B="$(mktemp -d "${TMPDIR:-/tmp}/sdd-hooks-bak-XXXXXX")"; trap 'rm -rf "$T" "$B"' EXIT
git ls-files -z --cached --others --exclude-standard | while IFS= read -r -d '' f; do
  [ -e "$f" ] && printf '%s\0' "$f"; done | tar --null -T - -cf - | tar -xf - -C "$T"
export GIT_AUTHOR_NAME=selftest GIT_AUTHOR_EMAIL=selftest@example.com
export GIT_COMMITTER_NAME=selftest GIT_COMMITTER_EMAIL=selftest@example.com
export CLAUDE_PROJECT_DIR="$T" SDD_MAIN_BRANCH=main
g() { git -C "$1" "${@:2}" >/dev/null 2>&1; }
g "$T" init -q && g "$T" symbolic-ref HEAD refs/heads/main
mkdir -p "$T/areas/data" "$T/areas/data-sync"   # two areas, one prefix of the other
cp "$T/areas/_template/README.md" "$T/areas/data/README.md"; cp "$T/areas/_template/README.md" "$T/areas/data-sync/README.md"
g "$T" add -A && g "$T" commit -qm base || bad "can't build the throwaway repo"
H="$T/.claude/hooks"; WT="$T/.worktrees"
remind() { (cd "$T" && echo '{}' | python3 "$H/reminder.py"); }
close() { (cd "$T" && echo "$2" | python3 "$H/closeout.py" >/dev/null 2>&1); local got=$([ $? = 2 ] && echo block || echo pass)
  [ "$got" = "$1" ] || bad "closeout: $3 → $got (expected $1)"; }
wt() { (cd "$T" && bash scripts/worktree.sh "$@" 2>&1); }

# ── worktree.sh: <area>-<slug>, stable port, unknown area rejected, docs mode ──
base=$(sed -n 's/^BASE_PORT=\([0-9]*\).*/\1/p' scripts/worktree.sh)
port() { echo $((base + $(printf '%s' "$1" | cksum | cut -d' ' -f1) % 100)); }
out=$(wt workflow-demo) || bad "worktree.sh workflow-demo failed: $out"
[ "$(git -C "$WT/workflow-demo" branch --show-current 2>/dev/null)" = feat/workflow-demo ] || bad "workflow-demo isn't on feat/workflow-demo"
[ "$(cat "$WT/workflow-demo/.port" 2>/dev/null)" = "$(port workflow-demo)" ] || bad "workflow-demo port isn't the hash of its name"
out=$(wt nosuch-demo) && bad "worktree.sh accepted an unknown area"
echo "$out" | grep -q "no area matches" || bad "unknown area: no clear message ($out)"
[ -d "$WT/nosuch-demo" ] && bad "unknown area left a folder"
out=$(wt data-sync-fix); echo "$out" | grep -q "area data-sync · spec data-sync/fix" || bad "longest area match (data-sync, not data)"
wt docs-x >/dev/null; [ "$(git -C "$WT/docs-x" branch --show-current 2>/dev/null)" = docs/x ] || bad "docs-x isn't on docs/x"
[ -e "$WT/docs-x/.port" ] && bad "docs mode got a port"
p1=$(cat "$WT/data-sync-fix/.port"); wt data-sync-fix --rm >/dev/null; wt data-sync-fix >/dev/null
[ "$(cat "$WT/data-sync-fix/.port")" = "$p1" ] || bad "port not stable across --rm and re-create"
wt billing-refunds --new-area billing >/dev/null; [ -f "$WT/billing-refunds/areas/billing/README.md" ] || bad "--new-area didn't create the area README"

# ── reminder + closeout over an open spec at areas/workflow/open/demo ──
D="$WT/workflow-demo"; S="$D/areas/workflow/open/demo"; mkdir -p "$S"
sed 's|<area>/<slug> · Short title|workflow/demo · selftest|' "$T/areas/_template/spec.md" > "$S/spec.md"
tick() { for n in "$@"; do sed -i.bak "s/- \[ \] $n/- [x] $n/" "$S/spec.md"; done; rm -f "$S/spec.md.bak"; }
remind | grep -q "spec workflow/demo (feat/workflow-demo) → next step: 1" || bad "reminder doesn't list the open spec"
close pass '{}' "fresh spec"
echo x > "$T/stray.txt"; close block '{}' "uncommitted changes on main"; rm "$T/stray.txt"
tick 1 2 3 4; close block '{}' "verified but not closed"
close pass '{"stop_hook_active":true}' "blocks only once per turn"
sed -i.bak 's/- \[x\] 2/- [ ] 2/' "$S/spec.md"; rm -f "$S/spec.md.bak"; close block '{}' "skipped step"; tick 2
mkdir -p "$D/areas/workflow/open/other"; cp "$S/spec.md" "$D/areas/workflow/open/other/"
remind | grep -q "spec workflow/other is on feat/workflow-demo" || bad "reminder doesn't flag a spec on the wrong branch"
rm -rf "$D/areas/workflow/open/other"

# ── close: spec MOVED to done/ + HISTORY line + at most 3 done ──
g "$D" add areas && g "$D" commit -qm "workflow/demo: spec" || bad "can't commit the spec"
tick 5; mkdir -p "$D/areas/workflow/done"; g "$D" mv "$S/spec.md" "$D/areas/workflow/done/2026-10-demo.md"
rm -rf "$S"
H2="$D/areas/HISTORY.md"; cp "$H2" "$B/hist.bak"
hist() { { echo "- 2026-10-01 · workflow/demo · selftest · PR #1"; cat "$B/hist.bak"; } > "$H2"; }  # content, not position, is checked
hist; close pass '{}' "closed properly"
remind | grep -q "workflow/demo closed or not written yet" || bad "reminder doesn't show the closed branch"
mkdir -p "$S"; echo x > "$S/plan.md"; close block '{}' "plan.md left behind"; rm -rf "$S"
cp "$B/hist.bak" "$H2"; close block '{}' "no HISTORY line"; hist
for m in 01 02 03; do echo x > "$D/areas/workflow/done/2026-$m-old$m.md"; done; close block '{}' "4 specs in done/"
rm -f "$D"/areas/workflow/done/2026-0[123]-old*.md
mv "$D/areas/workflow/done/2026-10-demo.md" "$B/demo.bak"; close block '{}' "spec deleted instead of moved"
mv "$B/demo.bak" "$D/areas/workflow/done/2026-10-demo.md"; close pass '{}' "closed properly (again)"

# ── reminder: >3 done in an area, >15 areas ──
mkdir -p "$T/areas/workflow/done"; for m in 01 02 03 04; do echo x > "$T/areas/workflow/done/2026-$m-x$m.md"; done
remind | grep -q "areas/workflow/done/ has 4 specs" || bad "reminder doesn't warn about 4 done specs"
rm -rf "$T/areas/workflow/done"
remind | grep -q "areas (healthy" && bad "reminder warns about too many areas with only 3"
for i in $(seq 1 13); do mkdir -p "$T/areas/fake$i"; done   # 3 real + 13 = 16
remind | grep -q "16 areas (healthy: 8-15)" || bad "reminder doesn't warn about 16 areas"

[ $fails = 0 ] && echo "✓ hooks self-test passed" || { echo "$fails failure(s)"; exit 1; }
