#!/usr/bin/env bash
# Self-test of scripts/pr_wait.sh with a FAKE `gh` (never talks to GitHub). It protects
# the invariant that matters: without --merge it never merges, and with a red, cancelled
# or checkless CI it doesn't either. And that the summary is ONE line (one session turn).
#
# The fake `gh` goes first on PATH: it logs every call and answers from FAKE_* variables.
# It never talks to GitHub, so it can't merge anything real.
# Built-in mutation: with the line of the red (or no-merge) case removed, its case fails.
# Usage: bash scripts/verify/pr_wait_selftest.sh   (exits 1 if something fails)
set -uo pipefail
cd "$(dirname "$0")/../.."
fails=0
bad() { echo "✗ $1"; fails=$((fails+1)); }

T="$(mktemp -d "${TMPDIR:-/tmp}/sdd-prwait-XXXXXX")"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
cat > "$T/bin/gh" <<'GH'
#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$*" in
  "pr checks "*--watch*) exit "${FAKE_WATCH_RC:-0}" ;;
  "pr checks "*--json*)  [ -n "${FAKE_BUCKETS:-}" ] && printf '%s\n' $FAKE_BUCKETS; exit 0 ;;
  "pr merge "*)          [ "${FAKE_MERGE_RC:-0}" = 0 ] && touch "$FAKE_LOG.merged"; exit "${FAKE_MERGE_RC:-0}" ;;
  "pr view "*"headRefOid"*) echo head123 ;;
  "pr view "*"state"*)   [ -e "$FAKE_LOG.merged" ] && echo MERGED || echo OPEN ;;
  "pr view "*"files"*)   printf '%s\n' ${FAKE_FILES:-docs/x.md} ;;
  "pr view "*"mergeCommit"*) echo abc123 ;;
  "api "*"/statuses"*)   echo "${FAKE_DEPLOY_STATE:-success}" ;;
  "api "*"deployments"*) echo 7 ;;
  *) echo "fake gh: unexpected call: $*" >&2; exit 99 ;;
esac
GH
chmod +x "$T/bin/gh"

# run <script> <args…>: leaves stdout in $out, the exit code in $rc and the fake gh's log in $L.
n=0
run() { local s="$1"; shift; n=$((n+1)); L="$T/gh-$n.log"; : > "$L"
  out=$(PATH="$T/bin:$PATH" FAKE_LOG="$L" TMPDIR="$T" PR_WAIT_SLEEP=0 PR_WAIT_CHECKS_TIMEOUT=0 \
        PR_WAIT_DEPLOY_TIMEOUT=5 bash "$s" "$@"); rc=$?; }
merges() { grep -c '^pr merge' "$L"; }
one_line() { [ "$(printf '%s\n' "$out" | wc -l | tr -d ' ')" = 1 ] || bad "$1: stdout was $(printf '%s\n' "$out" | wc -l | tr -d ' ') lines, not 1"; }
S=scripts/pr_wait.sh

# 0. Line 1 = the bash shebang: launched as `scripts/pr_wait.sh N`, without it Linux would
# run it with dash (no $SECONDS, no pipefail). An edit broke this once.
shebang() { [ "$(head -1 "$1")" = '#!/usr/bin/env bash' ]; }
shebang $S || bad "line 1 of $S isn't «#!/usr/bin/env bash»: $(head -1 $S)"
tail -n +2 $S > "$T/no-shebang.sh"; shebang "$T/no-shebang.sh" && bad "mutation «shebang»: without line 1, the check doesn't fail"

# 1. green WITHOUT --merge → doesn't merge, exit 0
FAKE_BUCKETS="pass pass" run $S 30
[ "$(merges)" = 0 ] || bad "green without --merge called pr merge"; [ $rc = 0 ] || bad "green without --merge: exit $rc"; one_line "green without --merge"
# 2. red WITH --merge → doesn't merge, exit≠0
FAKE_BUCKETS="pass fail" FAKE_WATCH_RC=1 run $S 30 --merge
[ "$(merges)" = 0 ] || bad "red with --merge called pr merge"; [ $rc != 0 ] || bad "red with --merge: exit 0"; one_line "red with --merge"
# 3. the watch exits 0 but a check is cancelled → not green
FAKE_BUCKETS="pass cancel" run $S 30 --merge
[ "$(merges)" = 0 ] || bad "cancelled with --merge called pr merge"; [ $rc != 0 ] || bad "cancelled: exit 0"
# 4. NO checks with --merge → doesn't merge
FAKE_BUCKETS="" run $S 30 --merge
[ "$(merges)" = 0 ] || bad "no checks with --merge called pr merge"; [ $rc != 0 ] || bad "no checks: exit 0"
echo "$out" | grep -q "NO CHECKS" || bad "no checks: the summary doesn't say so ($out)"
# 5. green WITH --merge and PR_WAIT_DEPLOY=none → one merge, exit 0
FAKE_BUCKETS="pass skipping" PR_WAIT_DEPLOY=none run $S 30 --merge
[ "$(merges)" = 1 ] || bad "green with --merge: $(merges) merges, not 1"; [ $rc = 0 ] || bad "green with --merge: exit $rc"; one_line "green with --merge"
# 6. with deploy tracking: a matching path → deployments + statuses → prod (check simulated)
FAKE_BUCKETS=pass FAKE_FILES="web/a.ts" PR_WAIT_DEPLOY=github-deployments PR_WAIT_DEPLOY_PATHS='^web/' PR_WAIT_CHECK=true run $S 30 --merge
echo "$out" | grep -q "deploy ok · prod ok" || bad "deploy + prod: $out"; one_line "deploy + prod"
grep -q 'deployments?sha=abc123' "$L" || bad "didn't look up the deployment by the merge commit's sha"
# 7. no matching path → doesn't wait for a deploy or check production
FAKE_BUCKETS=pass FAKE_FILES="docs/x.md" PR_WAIT_DEPLOY=github-deployments PR_WAIT_DEPLOY_PATHS='^web/' PR_WAIT_CHECK=false run $S 30 --merge
echo "$out" | grep -q "not applicable (no matching path)" || bad "no matching path: $out"; grep -q '^api' "$L" && bad "no matching path still queried deployments"; [ $rc = 0 ] || bad "no matching path: exit $rc"
# 8. failed deploy → exit 3; DNS that doesn't resolve → "local DNS", exit 0
FAKE_BUCKETS=pass FAKE_FILES="web/a.ts" PR_WAIT_DEPLOY=github-deployments PR_WAIT_DEPLOY_PATHS='^web/' FAKE_DEPLOY_STATE=failure run $S 30 --merge
[ $rc = 3 ] || bad "failed deploy: exit $rc ($out)"
FAKE_BUCKETS=pass FAKE_FILES="web/a.ts" PR_WAIT_DEPLOY=github-deployments PR_WAIT_DEPLOY_PATHS='^web/' PR_WAIT_CHECK='echo "getaddrinfo ENOTFOUND x"; exit 1' run $S 30 --merge
echo "$out" | grep -q "local DNS" || bad "ENOTFOUND: $out"; [ $rc = 0 ] || bad "ENOTFOUND: exit $rc"
# 9. a pending check isn't green; the merge pins the commit the CI verified
FAKE_BUCKETS="pass pending" run $S 30 --merge
[ "$(merges)" = 0 ] || bad "pending with --merge called pr merge"; [ $rc != 0 ] || bad "pending: exit 0"
FAKE_BUCKETS=pass PR_WAIT_DEPLOY=none run $S 30 --merge
grep -q '^pr merge 30 .*--match-head-commit head123' "$L" || bad "the merge doesn't carry --match-head-commit of the verified commit"
# 10. the merge fails (e.g. someone pushed another commit): state not MERGED → not "merged", exit 2
FAKE_BUCKETS=pass FAKE_MERGE_RC=1 PR_WAIT_DEPLOY=none run $S 30 --merge
[ $rc = 2 ] || bad "failed merge: exit $rc ($out)"; echo "$out" | grep -q "MERGE FAILED" || bad "failed merge: $out"
# 11. usage
run $S 2>/dev/null; [ $rc = 64 ] || bad "no number: exit $rc"

# ── Mutation: without the condition, its case must fail (otherwise the test protects nothing) ──
mkdir -p "$T/m/scripts"
grep -v 'mutation: red' $S > "$T/m/scripts/pr_wait.sh"
FAKE_BUCKETS="pass fail" FAKE_WATCH_RC=1 run "$T/m/scripts/pr_wait.sh" 30 --merge
[ "$(merges)" = 0 ] && bad "mutation «red»: without the condition, case 2 still doesn't merge (the test doesn't cover it)"
grep -v 'mutation: no-merge' $S > "$T/m/scripts/pr_wait.sh"
FAKE_BUCKETS="pass pass" run "$T/m/scripts/pr_wait.sh" 30
[ "$(merges)" = 0 ] && bad "mutation «no-merge»: without the condition, case 1 still doesn't merge (the test doesn't cover it)"
grep -v 'mutation: merged' $S > "$T/m/scripts/pr_wait.sh"
FAKE_BUCKETS=pass FAKE_MERGE_RC=1 PR_WAIT_DEPLOY=none run "$T/m/scripts/pr_wait.sh" 30 --merge
[ $rc = 2 ] && bad "mutation «merged»: without checking MERGED, case 10 still comes back 2 (the test doesn't cover it)"
sed 's/(pass|skipping)/(pass|skipping|pending)/' $S > "$T/m/scripts/pr_wait.sh"
FAKE_BUCKETS="pass pending" run "$T/m/scripts/pr_wait.sh" 30 --merge
[ "$(merges)" = 0 ] && bad "mutation «pending»: with pending counted as green, case 9 still doesn't merge (the test doesn't cover it)"

[ $fails = 0 ] && echo "✓ pr_wait.sh self-test passed ($n runs, 4 mutations)" || { echo "$fails failure(s)"; exit 1; }
