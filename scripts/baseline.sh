#!/usr/bin/env bash
# A copy of the main branch to compare "before / after" against, without touching the
# main checkout.
#
#   scripts/baseline.sh          → temporary worktree of origin/main (or main) + run_baseline
#   scripts/baseline.sh --rm     → removes it (and its worktree metadata)
#
# Run it from a feature folder (or the root). It prints the folder; what you measure there
# is up to the project (run_baseline below): build and serve it on your role's reserved
# resource, compute metrics, export a model's scores…
#
# WHY. Comparing against main by switching or building in the main checkout dirties the
# user's working copy and can stop what the user has running there. A detached worktree in
# a temp folder is disposable: shared files (secrets) are LINKED from the root, dependency
# folders cloned, exactly like scripts/worktree.sh — whose CUSTOMIZE block is read from
# there, so the list of shared files has one home.
set -euo pipefail

here="$(git rev-parse --show-toplevel)"
root="$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
eval "$(sed -n '/^# ── CUSTOMIZE PER PROJECT/,/^# ─────/p' "$here/scripts/worktree.sh")"
: "${MAIN_BRANCH:?no CUSTOMIZE block in scripts/worktree.sh}"

# ── CUSTOMIZE PER PROJECT ────────────────────────────────────────────────────
# What runs in the baseline folder once it exists ($1 = the folder). Empty by default.
run_baseline() { :; }
# ─────────────────────────────────────────────────────────────────────────────

# One baseline per feature folder: two features comparing at once don't share it.
dir="${TMPDIR:-/tmp}"; dir="${dir%/}/sdd-baseline-$(basename "$root")-$(basename "$here")"

if [[ "${1:-}" == "--rm" ]]; then
  git -C "$root" worktree remove --force "$dir" 2>/dev/null || rm -rf "$dir"
  git -C "$root" worktree prune
  echo "· baseline removed: $dir"
  exit 0
fi
[[ -z "${1:-}" ]] || { echo "usage: scripts/baseline.sh [--rm]"; exit 2; }
[[ -d "$dir" ]] && { echo "· already exists: $dir ($(git -C "$dir" rev-parse --short HEAD)); --rm to remove it"; exit 0; }

ref="$MAIN_BRANCH"
if git -C "$root" remote get-url origin >/dev/null 2>&1 && git -C "$root" fetch -q origin "$MAIN_BRANCH" 2>/dev/null; then
  ref="origin/$MAIN_BRANCH"
fi
# If anything fails halfway, nothing is left behind.
trap 'echo "✗ failed; removing $dir"; git -C "$root" worktree remove --force "$dir" 2>/dev/null || rm -rf "$dir"' ERR
git -C "$root" worktree add -q --detach "$dir" "$ref"

for f in "${SHARED_FILES[@]}"; do
  if [[ -e "$root/$f" && ! -e "$dir/$f" ]]; then mkdir -p "$(dirname "$dir/$f")"; ln -s "$root/$f" "$dir/$f"; fi
done
for d in "${DEP_DIRS[@]}"; do
  if [[ -d "$root/$d" ]]; then cp -Rc "$root/$d" "$dir/$d" 2>/dev/null || cp -R "$root/$d" "$dir/$d"; fi
done

run_baseline "$dir"
trap - ERR
echo "· baseline of $ref ($(git -C "$dir" rev-parse --short HEAD)) → $dir"
echo "  remove: scripts/baseline.sh --rm"
