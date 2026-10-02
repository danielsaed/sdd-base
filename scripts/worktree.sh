#!/usr/bin/env bash
# Isolated working folder for a feature: its branch, its dependencies and its port.
#
#   scripts/worktree.sh 012-flag-cache          → .worktrees/012-flag-cache on feat/012-flag-cache
#   scripts/worktree.sh docs-gotchas            → .worktrees/docs-gotchas on docs/gotchas
#                                                 (docs mode: no dependencies, no port)
#   scripts/worktree.sh 012-flag-cache --rm     → removes it (the branch stays; the PR decides)
#
# WHY shared files are LINKED, not copied: a copy goes stale as soon as a key rotates in
# the root (and you'd have to remember every folder). Relative links keep working if the
# repo moves; .gitignore covers them inside the folder too.
# WHY dependencies are CLONED, not linked: some tools reject a symlinked dependency folder.
# On APFS/btrfs `cp -c` / reflink clones without copying bytes. Each folder gets its own
# port in `.port` so two agents running a server don't collide.
set -euo pipefail

# ── CUSTOMIZE PER PROJECT (scripts/baseline.sh reads this block too) ─────────
MAIN_BRANCH="main"
SHARED_FILES=(".env")                  # linked from the root, never committed; e.g. "app/.env.local"
DEP_DIRS=("node_modules")              # cloned if present; e.g. "app/node_modules", ".venv"
BASE_PORT=3100                         # port = BASE_PORT + (NNN % 100)
# ─────────────────────────────────────────────────────────────────────────────

slug="${1:?usage: scripts/worktree.sh NNN-slug|docs-topic [--rm]}"
if [[ "$slug" =~ ^[0-9]{3}-[a-z0-9-]+$ ]]; then
  branch="feat/$slug"; docs=0
elif [[ "$slug" =~ ^docs-([a-z0-9-]+)$ ]]; then
  branch="docs/${BASH_REMATCH[1]}"; docs=1
else
  echo "✗ the name must be NNN-slug (e.g. 012-flag-cache) or docs-topic (e.g. docs-gotchas)"; exit 2
fi
root="$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
dir="$root/.worktrees/$slug"

if [[ "${2:-}" == "--rm" ]]; then
  git -C "$root" worktree remove --force "$dir" && echo "· removed $dir (branch $branch still exists)"
  exit 0
fi
[[ -d "$dir" ]] && { echo "· already exists: $dir$([[ -f "$dir/.port" ]] && echo " (port $(cat "$dir/.port"))")"; exit 0; }

if git -C "$root" show-ref --quiet "refs/heads/$branch"; then
  git -C "$root" worktree add "$dir" "$branch"
else
  git -C "$root" worktree add -b "$branch" "$dir" "$MAIN_BRANCH"
fi

for f in "${SHARED_FILES[@]}"; do
  [[ -e "$root/$f" && ! -e "$dir/$f" ]] || continue
  up="../.."; d="$(dirname "$f")"
  while [[ "$d" != "." ]]; do up="../$up"; d="$(dirname "$d")"; done
  mkdir -p "$(dirname "$dir/$f")" && ln -s "$up/$f" "$dir/$f"
done

if [[ "$docs" == 1 ]]; then
  echo "· $dir  branch $branch  (docs mode: no dependencies, no port)"
  exit 0
fi

clone() { cp -Rc "$1" "$2" 2>/dev/null || cp -R --reflink=auto "$1" "$2" 2>/dev/null || cp -R "$1" "$2"; }
for d in "${DEP_DIRS[@]}"; do [[ -d "$root/$d" ]] && clone "$root/$d" "$dir/$d"; done

num=$((10#${slug%%-*}))
echo $((BASE_PORT + num % 100)) > "$dir/.port"
echo "· $dir  branch $branch  port $(cat "$dir/.port")"
