#!/usr/bin/env bash
# Waits for a PR to finish its path and reports ONCE (consumption: fewer background notices).
#
# WHY. Each background notice (CI green, merged, deployed, production OK) costs a session
# turn that re-reads the whole context. This script chains the waits in ONE process: the
# progress goes to a log and stdout prints a SINGLE summary line at the end.
#
#   scripts/pr_wait.sh <N>           watches CI; never merges
#   scripts/pr_wait.sh <N> --merge   CI green → merge (squash) → deploy → production
#
# `--merge` ONLY with the user's conditional OK ("merge if it's green"): the script has no
# way to know whether you have it; the skill `sdd` requires it, and subagents are denied it
# by the guard (rule `pr-wait-merge` in .claude/permissions.json — watching without
# `--merge` stays allowed). Red, cancelled or NO checks = not green → it never merges.
#
# Deploy/production check: OFF by default (this is a generic template; no provider is
# assumed). CUSTOMIZE PER PROJECT with:
#   PR_WAIT_DEPLOY=github-deployments   follow the merge commit's GitHub Deployments API
#     (any provider that creates one per commit: e.g. Vercel, Render, Fly, Railway).
#   PR_WAIT_DEPLOY_PATHS='^web/'        skip the deploy wait when the PR touches no path
#     matching this regex ("" = the deploy applies regardless of which files changed).
#   PR_WAIT_CHECK="node scripts/verify/your_production_check.mjs"   your production check;
#     it loads its own secrets — this script never touches one. "" = don't check production.
# An ENOTFOUND/EAI_AGAIN from PR_WAIT_CHECK is reported as this machine's local DNS, not
# production being down: retried a few times and called out separately in the summary.
#
# Exit: 0 all good (or "local DNS") · 1 CI not green · 2 merge failed · 3 deploy failed or
# didn't finish in time · 4 production check failed · 64 usage. `gh` is resolved on PATH
# (the self-test fakes it: scripts/verify/pr_wait_selftest.sh).
set -uo pipefail

# ── Configuration (the environment wins) ──
PR_WAIT_DEPLOY="${PR_WAIT_DEPLOY:-none}"                # none | github-deployments
PR_WAIT_CHECK="${PR_WAIT_CHECK:-}"                       # "" = don't check production
PR_WAIT_DEPLOY_PATHS="${PR_WAIT_DEPLOY_PATHS:-}"         # regex of paths that trigger a deploy; "" = any
PR_WAIT_DEPLOY_TIMEOUT="${PR_WAIT_DEPLOY_TIMEOUT:-900}"  # seconds (~15 min)
PR_WAIT_SLEEP="${PR_WAIT_SLEEP:-20}"                     # between polls
PR_WAIT_CHECKS_TIMEOUT="${PR_WAIT_CHECKS_TIMEOUT:-180}"  # until the CI checks show up

N=""; merge=0
for a in "$@"; do
  case "$a" in
    --merge) merge=1 ;;
    *[!0-9]*|"") echo "usage: scripts/pr_wait.sh <N> [--merge]" >&2; exit 64 ;;
    *) N="$a" ;;
  esac
done
[ -n "$N" ] || { echo "usage: scripts/pr_wait.sh <N> [--merge]" >&2; exit 64; }

cd "$(dirname "$0")/.."
LOG="${TMPDIR:-/tmp}/pr_wait-$N.log"
: > "$LOG"
exec 3>&1 >>"$LOG" 2>&1          # everything goes to the log; the summary uses fd 3 (the real stdout)
ci="?"; mg="not merged"; dep="—"; prod="—"
finish() { echo "PR #$N · CI $ci · $mg · deploy $dep · prod $prod  (log: $LOG)" >&3; exit "$1"; }
log() { echo "[$(date +%H:%M:%S)] $*"; }

# ── 1. CI ──
# Right after the push the checks take a moment to register, and `gh pr checks --watch`
# with no checks yet returns immediately: wait for at least one to show up; if none does,
# it's not green.
buckets=""; t0=$SECONDS
while :; do
  buckets=$(gh pr checks "$N" --json bucket -q '.[].bucket' 2>/dev/null)
  [ -n "$buckets" ] && break
  [ $((SECONDS - t0)) -ge "$PR_WAIT_CHECKS_TIMEOUT" ] && break
  log "no checks yet"; sleep "$PR_WAIT_SLEEP"
done
if [ -n "$buckets" ]; then
  log "watching CI"; gh pr checks "$N" --watch --interval 15; rc=$?
  # The commit the CI verified is read BEFORE the checks: if someone pushes another one
  # afterwards, its checks come back pending (not green), or the merge is rejected by
  # --match-head-commit below.
  head=$(gh pr view "$N" --json headRefOid -q .headRefOid 2>/dev/null)
  buckets=$(gh pr checks "$N" --json bucket -q '.[].bucket' 2>/dev/null)
  # Green = the watch succeeded AND every check is pass/skipping (a cancelled one isn't green).
  if [ $rc = 0 ] && [ -n "$head" ] && [ -n "$buckets" ] && ! echo "$buckets" | grep -qvE '^(pass|skipping)$'; then ci="green"
  else ci="RED ($(echo "$buckets" | sort | uniq -c | awk '{printf "%s%s %s", s, $1, $2; s=", "}'))"; fi
else
  ci="NO CHECKS"
fi
[ "$ci" = green ] || finish 1            # mutation: red — never merges without a green CI
[ "$merge" = 1 ] || finish 0             # mutation: no-merge — without --merge it only watches

# ── 2. Merge ──
log "merging $head"; gh pr merge "$N" --squash --delete-branch --match-head-commit "$head"
# --delete-branch can fail locally when run from a .worktrees/ folder (the branch is
# checked out there) even though the merge on GitHub went through: the PR's state decides
# this, not the exit code.
[ "$(gh pr view "$N" --json state -q .state 2>/dev/null)" = MERGED ] || { mg="MERGE FAILED"; finish 2; }  # mutation: merged
mg="merged"

# ── 3. Deploy ──
if [ "$PR_WAIT_DEPLOY" != github-deployments ]; then dep="not tracked"
elif [ -n "$PR_WAIT_DEPLOY_PATHS" ] && ! gh pr view "$N" --json files -q '.files[].path' | grep -qE "$PR_WAIT_DEPLOY_PATHS"; then
  dep="not applicable (no matching path)"
else
  sha=$(gh pr view "$N" --json mergeCommit -q .mergeCommit.oid); log "commit $sha"
  id=""; state=""; t0=$SECONDS
  while [ $((SECONDS - t0)) -lt "$PR_WAIT_DEPLOY_TIMEOUT" ]; do
    [ -n "$id" ] || id=$(gh api "repos/{owner}/{repo}/deployments?sha=$sha" -q '.[0].id // empty' 2>/dev/null)
    if [ -n "$id" ]; then
      state=$(gh api "repos/{owner}/{repo}/deployments/$id/statuses" -q '.[0].state // empty' 2>/dev/null)
      log "deployment $id: ${state:-no state}"
      case "$state" in success|failure|error) break ;; esac
    else log "no deployment yet"; fi
    sleep "$PR_WAIT_SLEEP"
  done
  case "$state" in
    success) dep="ok" ;;
    failure|error) dep="FAILED ($state)"; finish 3 ;;
    *) dep="DIDN'T FINISH after ${PR_WAIT_DEPLOY_TIMEOUT}s (${state:-no deployment})"; finish 3 ;;
  esac
fi

# ── 4. Production ── (only if there was a deploy: without one, nothing changed)
if [ "$dep" != ok ] || [ -z "$PR_WAIT_CHECK" ]; then prod="not checked"; finish 0; fi
for i in 1 2 3; do
  out=$(bash -c "$PR_WAIT_CHECK" 2>&1); rc=$?; echo "$out"
  [ $rc = 0 ] && { prod="ok"; finish 0; }
  echo "$out" | grep -qE 'ENOTFOUND|EAI_AGAIN|getaddrinfo' || { prod="FAILS (rc $rc)"; finish 4; }
  log "DNS not resolving (attempt $i/3)"; sleep "$PR_WAIT_SLEEP"
done
prod="not measured: local DNS (this machine can't resolve the domain)"; finish 0
