#!/usr/bin/env bash
# Isolated working folder for a feature: its branch, its dependencies and its port.
#
#   scripts/worktree.sh 012-flag-cache          → creates .worktrees/012-flag-cache on feat/012-flag-cache
#   scripts/worktree.sh 012-flag-cache --rm     → removes it (the branch stays; the PR decides)
#
# WHY clone dependencies instead of symlinking: some bundlers reject a symlinked
# node_modules. On APFS/btrfs `cp -c` / reflink clones without copying bytes. Each folder
# gets its own port in `.port` so two agents running a dev server don't collide.
set -euo pipefail

# ── CUSTOMIZE PER PROJECT ────────────────────────────────────────────────────
MAIN_BRANCH="main"
ENV_FILES=(".env" ".env.local")        # copied (never committed); e.g. "web/.env.local"
DEP_DIRS=("node_modules")              # cloned if present; e.g. "web/node_modules", ".venv"
BASE_PORT=3100                         # port = BASE_PORT + (NNN % 100)
# ─────────────────────────────────────────────────────────────────────────────

slug="${1:?usage: scripts/worktree.sh NNN-slug [--rm]}"
[[ "$slug" =~ ^[0-9]{3}-[a-z0-9-]+$ ]] || { echo "✗ the name must be NNN-slug (e.g. 012-flag-cache)"; exit 2; }
root="$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
dir="$root/.worktrees/$slug"
branch="feat/$slug"

if [[ "${2:-}" == "--rm" ]]; then
  git -C "$root" worktree remove --force "$dir" && echo "· removed $dir (branch $branch still exists)"
  exit 0
fi
[[ -d "$dir" ]] && { echo "· already exists: $dir (port $(cat "$dir/.port"))"; exit 0; }

if git -C "$root" show-ref --quiet "refs/heads/$branch"; then
  git -C "$root" worktree add "$dir" "$branch"
else
  git -C "$root" worktree add -b "$branch" "$dir" "$MAIN_BRANCH"
fi

clone() { cp -Rc "$1" "$2" 2>/dev/null || cp -R --reflink=auto "$1" "$2" 2>/dev/null || cp -R "$1" "$2"; }
for f in "${ENV_FILES[@]}"; do [[ -f "$root/$f" ]] && { mkdir -p "$(dirname "$dir/$f")"; cp "$root/$f" "$dir/$f"; }; done
for d in "${DEP_DIRS[@]}"; do [[ -d "$root/$d" ]] && clone "$root/$d" "$dir/$d"; done

num=$((10#${slug%%-*}))
echo $((BASE_PORT + num % 100)) > "$dir/.port"
echo "· $dir  branch $branch  port $(cat "$dir/.port")"
