#!/usr/bin/env bash
# Self-test of scripts/pr_wait.sh with a FAKE `gh` (never talks to GitHub). It protects
# the invariant that matters: without --merge it never merges, and with a red, cancelled
# or checkless CI it doesn't either. And that the summary is ONE line (one session turn).
# Also the deploy tracking: the PR's file list read whole and paginated (a `| grep -q` under
# pipefail once said "no matching path" exactly when there was one), and the fallback by
# served version (PR_WAIT_VERSION_CMD) for providers that don't create GitHub deployments.
#
# The fake `gh` goes first on PATH: it logs every call and answers from FAKE_* variables.
# It never talks to GitHub, so it can't merge anything real. A fake version command (`ver`)
# stands in for PR_WAIT_VERSION_CMD.
# Built-in mutation: with each guarded line removed or reverted, its case fails.
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
files() {
  if [ -n "${FAKE_FILES_BIG:-}" ]; then echo web/a.ts; seq -f 'docs/%g.md' 1 30000   # >64 KB: SIGPIPE if the reader stops early
  elif [ -n "${FAKE_FILES_LATE:-}" ]; then seq -f 'docs/%g.md' 1 150; echo web/a.ts  # the match is past file 100
  else printf '%s\n' ${FAKE_FILES:-docs/x.md}; fi; }
case "$*" in
  "pr checks "*--watch*) exit "${FAKE_WATCH_RC:-0}" ;;
  "pr checks "*--json*)  [ -n "${FAKE_BUCKETS:-}" ] && printf '%s\n' $FAKE_BUCKETS; exit 0 ;;
  "pr merge "*)          [ "${FAKE_MERGE_RC:-0}" = 0 ] && touch "$FAKE_LOG.merged"; exit "${FAKE_MERGE_RC:-0}" ;;
  "pr view "*"headRefOid"*) echo head123 ;;
  "pr view "*"files"*)   files | head -n 100 ;;   # like GitHub: `pr view --json files` stops at 100
  "pr view "*"state"*)   [ -e "$FAKE_LOG.merged" ] && echo MERGED || echo OPEN ;;
  "api "*"/pulls/"*"/files"*) [ "${FAKE_FILES_RC:-0}" = 0 ] || exit "$FAKE_FILES_RC"; files ;;
  "pr view "*"mergeCommit"*) echo abc1234def5678 ;;
  "api "*"/statuses"*)   echo "${FAKE_DEPLOY_STATE:-success}" ;;
  "api "*"deployments"*) [ -n "${FAKE_NO_DEPLOY:-}" ] || echo 7 ;;
  *) echo "fake gh: unexpected call: $*" >&2; exit 99 ;;
esac
GH
# Fake PR_WAIT_VERSION_CMD: prints the commit "production serves".
cat > "$T/bin/ver" <<'VER'
#!/usr/bin/env bash
echo ver >> "$FAKE_LOG.ver"
[ -n "${FAKE_VER_ERR:-}" ] && echo "$FAKE_VER_ERR" >&2
echo "${FAKE_VER:-}"; exit "${FAKE_VER_RC:-0}"
VER
chmod +x "$T/bin/gh" "$T/bin/ver"

# run <script> <args…>: leaves stdout in $out, the exit code in $rc and the fake gh's log in $L.
n=0
run() { local s="$1"; shift; n=$((n+1)); L="$T/gh-$n.log"; : > "$L"
  out=$(PATH="$T/bin:$PATH" FAKE_LOG="$L" TMPDIR="$T" PR_WAIT_SLEEP=0 PR_WAIT_CHECKS_TIMEOUT=0 \
        PR_WAIT_DEPLOY_TIMEOUT="${PR_WAIT_DEPLOY_TIMEOUT:-5}" bash "$s" "$@"); rc=$?; }
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
grep -q 'deployments?sha=abc1234def5678' "$L" || bad "didn't look up the deployment by the merge commit's sha"
grep -q 'pulls/30/files --paginate' "$L" || bad "didn't read the PR's files from the paginated API"
# 7. no matching path → doesn't wait for a deploy or check production
FAKE_BUCKETS=pass FAKE_FILES="docs/x.md" PR_WAIT_DEPLOY=github-deployments PR_WAIT_DEPLOY_PATHS='^web/' PR_WAIT_CHECK=false run $S 30 --merge
echo "$out" | grep -q "not applicable (no matching path)" || bad "no matching path: $out"; grep -q 'deployments' "$L" && bad "no matching path still queried deployments"; [ $rc = 0 ] || bad "no matching path: exit $rc"
# 7b. a huge list with the match FIRST (a `| grep -q` died of SIGPIPE there) → the deploy is followed
FAKE_BUCKETS=pass FAKE_FILES_BIG=1 PR_WAIT_DEPLOY=github-deployments PR_WAIT_DEPLOY_PATHS='^web/' PR_WAIT_CHECK=true run $S 30 --merge
echo "$out" | grep -q "deploy ok · prod ok" || bad "big list with the match first: $out"
# 7c. the match past file 100 (`pr view --json files` stops at 100) → the deploy is followed
FAKE_BUCKETS=pass FAKE_FILES_LATE=1 PR_WAIT_DEPLOY=github-deployments PR_WAIT_DEPLOY_PATHS='^web/' PR_WAIT_CHECK=true run $S 30 --merge
echo "$out" | grep -q "deploy ok · prod ok" || bad "match past file 100: $out"
# 7d. gh can't read the list → exit 3, and it's not mistaken for "no matching path"
FAKE_BUCKETS=pass FAKE_FILES_RC=1 PR_WAIT_DEPLOY=github-deployments PR_WAIT_DEPLOY_PATHS='^web/' PR_WAIT_CHECK=false run $S 30 --merge
echo "$out" | grep -q "couldn't read the PR's file list" || bad "unreadable list: $out"; [ $rc = 3 ] || bad "unreadable list: exit $rc"
echo "$out" | grep -q "no matching path" && bad "unreadable list was reported as «no matching path»"
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

# 12. No GitHub deployment: the served version (PR_WAIT_VERSION_CMD) decides.
export PR_WAIT_DEPLOY=github-deployments FAKE_BUCKETS=pass FAKE_FILES=web/a.ts
FAKE_NO_DEPLOY=1 PR_WAIT_VERSION_CMD="$T/bin/ver" FAKE_VER=abc1234def5678 PR_WAIT_CHECK=true run $S 30 --merge
echo "$out" | grep -q "deploy ok (served version) · prod ok" || bad "served version matches: $out"; [ $rc = 0 ] || bad "served version matches: exit $rc"; one_line "served version"
FAKE_NO_DEPLOY=1 PR_WAIT_VERSION_CMD="$T/bin/ver" FAKE_VER=deadbee0 PR_WAIT_DEPLOY_TIMEOUT=1 run $S 30 --merge
[ $rc = 3 ] || bad "old served version: exit $rc ($out)"; echo "$out" | grep -q "DIDN'T FINISH.*production serves deadbee0" || bad "old served version: $out"
FAKE_NO_DEPLOY=1 PR_WAIT_VERSION_CMD="$T/bin/ver" FAKE_VER_ERR="missing SITE_TOKEN" FAKE_VER_RC=2 run $S 30 --merge
[ $rc = 3 ] || bad "no credentials: exit $rc ($out)"; echo "$out" | grep -q "no credentials: missing SITE_TOKEN" || bad "no credentials: the message isn't shown ($out)"
for v in ABC1234DEF5678 abc1234 ABC1234DEF5678aaaa; do   # upper case · short sha (7) · a longer served one
  FAKE_NO_DEPLOY=1 PR_WAIT_VERSION_CMD="$T/bin/ver" FAKE_VER=$v PR_WAIT_DEPLOY_TIMEOUT=1 run $S 30 --merge
  echo "$out" | grep -q "deploy ok (served version)" || bad "sha $v should match: $out"
done
FAKE_NO_DEPLOY=1 PR_WAIT_VERSION_CMD="$T/bin/ver" FAKE_VER=abc123 PR_WAIT_DEPLOY_TIMEOUT=1 run $S 30 --merge   # 6-char prefix: not enough
[ $rc = 3 ] || bad "a 6-character prefix matched (exit $rc)"
FAKE_NO_DEPLOY=1 PR_WAIT_VERSION_CMD="" PR_WAIT_DEPLOY_TIMEOUT=1 run $S 30 --merge   # feature off: as before
[ $rc = 3 ] || bad "no deployment, no version command: exit $rc"; [ -e "$L.ver" ] && bad "an empty PR_WAIT_VERSION_CMD ran something"
PR_WAIT_VERSION_CMD="$T/bin/ver" FAKE_VER=abc1234def5678 run $S 30 --merge   # a deployment exists: it decides
echo "$out" | grep -q "deploy ok · prod" || bad "with a deployment: $out"; [ -e "$L.ver" ] && bad "with a deployment, the version command still ran"
unset PR_WAIT_DEPLOY FAKE_BUCKETS FAKE_FILES

# ── Mutation: without the condition, its case must fail (otherwise the test protects nothing) ──
mkdir -p "$T/m/scripts"
M="$T/m/scripts/pr_wait.sh"
grep -v 'mutation: red' $S > "$M"
FAKE_BUCKETS="pass fail" FAKE_WATCH_RC=1 run "$M" 30 --merge
[ "$(merges)" = 0 ] && bad "mutation «red»: without the condition, case 2 still doesn't merge (the test doesn't cover it)"
grep -v 'mutation: no-merge' $S > "$M"
FAKE_BUCKETS="pass pass" run "$M" 30
[ "$(merges)" = 0 ] && bad "mutation «no-merge»: without the condition, case 1 still doesn't merge (the test doesn't cover it)"
grep -v 'mutation: merged' $S > "$M"
FAKE_BUCKETS=pass FAKE_MERGE_RC=1 PR_WAIT_DEPLOY=none run "$M" 30 --merge
[ $rc = 2 ] && bad "mutation «merged»: without checking MERGED, case 10 still comes back 2 (the test doesn't cover it)"
sed 's/(pass|skipping)/(pass|skipping|pending)/' $S > "$M"
FAKE_BUCKETS="pass pending" run "$M" 30 --merge
[ "$(merges)" = 0 ] && bad "mutation «pending»: with pending counted as green, case 9 still doesn't merge (the test doesn't cover it)"
export PR_WAIT_DEPLOY=github-deployments PR_WAIT_DEPLOY_PATHS='^web/' FAKE_BUCKETS=pass PR_WAIT_CHECK=true
# «pipe»: back to `gh … | grep -q` (the SIGPIPE bug) → case 7b must break.
sed -e '/# mutation: files-list/{N;d;}' \
    -e "/# mutation: files-grep/s#grep -qE \"\$PR_WAIT_DEPLOY_PATHS\" <<<\"\$files\"#gh api \"repos/{owner}/{repo}/pulls/\$N/files\" --paginate -q '.[].filename' | grep -qE \"\$PR_WAIT_DEPLOY_PATHS\"#" $S > "$M"
grep -q 'filename'"'"' | grep -qE' "$M" || bad "mutation «pipe»: couldn't build the pipe"
FAKE_FILES_BIG=1 run "$M" 30 --merge
echo "$out" | grep -q "deploy ok" && bad "mutation «pipe»: with the pipe to grep -q, case 7b is still green (the test doesn't cover it)"
# «pr-view»: back to `gh pr view --json files` (100 files at most) → case 7c must break.
sed "s#gh api \"repos/{owner}/{repo}/pulls/\$N/files\" --paginate -q '\.\[\]\.filename'#gh pr view \"\$N\" --json files -q '.files[].path'#" $S > "$M"
grep -q 'pr view "$N" --json files' "$M" || bad "mutation «pr-view»: couldn't build it"
FAKE_FILES_LATE=1 run "$M" 30 --merge
echo "$out" | grep -q "deploy ok" && bad "mutation «pr-view»: with pr view's 100 files, case 7c is still green (the test doesn't cover it)"
# «unreadable»: an unreadable list no longer stops with exit 3 → case 7d must break.
sed "/dep=\"couldn't read the PR's file list\"; finish 3/s/.*/  :/" $S > "$M"
FAKE_FILES_RC=1 PR_WAIT_CHECK=false run "$M" 30 --merge
[ $rc = 3 ] && bad "mutation «unreadable»: without the exit 3, case 7d still exits 3 (the test doesn't cover it)"
export FAKE_NO_DEPLOY=1 PR_WAIT_VERSION_CMD="$T/bin/ver" FAKE_FILES=web/a.ts
grep -v 'mutation: version' $S > "$M"
FAKE_VER=abc1234def5678 PR_WAIT_DEPLOY_TIMEOUT=1 run "$M" 30 --merge
echo "$out" | grep -q "served version" && bad "mutation «version»: without comparing the sha, case 12 is still green (the test doesn't cover it)"
sed 's/same_sha "\$served" "\$sha"/[ "$served" = "$sha" ]/' $S > "$M"   # literal comparison
grep -q '\[ "$served" = "$sha" \]' "$M" || bad "mutation «sha»: couldn't build it"
FAKE_VER=ABC1234DEF5678 PR_WAIT_DEPLOY_TIMEOUT=1 run "$M" 30 --merge
echo "$out" | grep -q "served version" && bad "mutation «sha»: with a literal comparison, the upper-case sha still matches (the test doesn't cover it)"
grep -v 'mutation: creds' $S > "$M"
FAKE_VER_ERR="missing SITE_TOKEN" FAKE_VER_RC=2 PR_WAIT_DEPLOY_TIMEOUT=1 run "$M" 30 --merge
echo "$out" | grep -q "no credentials" && bad "mutation «creds»: without stopping on rc 2, the credentials case still says so (the test doesn't cover it)"
unset PR_WAIT_DEPLOY PR_WAIT_DEPLOY_PATHS FAKE_BUCKETS PR_WAIT_CHECK FAKE_NO_DEPLOY PR_WAIT_VERSION_CMD FAKE_FILES

[ $fails = 0 ] && echo "✓ pr_wait.sh self-test passed ($n runs, 10 mutations)" || { echo "$fails failure(s)"; exit 1; }
