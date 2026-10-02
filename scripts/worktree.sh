#!/usr/bin/env bash
# Isolated working folder for a feature: its branch, its dependencies and its port.
#
#   scripts/worktree.sh workflow-port-hash      → .worktrees/workflow-port-hash on
#                                                 feat/workflow-port-hash (area workflow,
#                                                 spec slug port-hash)
#   scripts/worktree.sh billing-refunds --new-area billing
#                                               → same, creating areas/billing/ from
#                                                 areas/_template/README.md (user OK first)
#   scripts/worktree.sh docs-gotchas            → .worktrees/docs-gotchas on docs/gotchas
#                                                 (docs mode: no dependencies, no port)
#   scripts/worktree.sh workflow-port-hash --rm → removes it (the branch stays; the PR decides)
#
# The name is <area>-<slug>. Both may contain hyphens: the area is the LONGEST existing
# folder under areas/ (on the main branch) that prefixes the name. An unknown area is
# rejected, so a typo doesn't create a stray area; `docs` is reserved for docs mode.
# WHY shared files are LINKED, not copied: a copy goes stale as soon as a key rotates in
# the root (and you'd have to remember every folder). Relative links keep working if the
# repo moves; .gitignore covers them inside the folder too.
# WHY dependencies are CLONED, not linked: some tools reject a symlinked dependency folder.
# On APFS/btrfs `cp -c` / reflink clones without copying bytes. Each folder gets its own
# port in `.port` so two agents running a server don't collide. The port comes from a
# hash of the name (stable: the same name always gets the same port), moved to the next
# free one only if another folder already has it.
set -euo pipefail

# ── CUSTOMIZE PER PROJECT (scripts/baseline.sh reads this block too) ─────────
MAIN_BRANCH="main"
SHARED_FILES=(".env")                  # linked from the root, never committed; e.g. "app/.env.local"
DEP_DIRS=("node_modules")              # cloned if present; e.g. "app/node_modules", ".venv"
BASE_PORT=3100                         # port = BASE_PORT + (hash(name) % 100)
# ─────────────────────────────────────────────────────────────────────────────

name="${1:?usage: scripts/worktree.sh <area>-<slug>|docs-<topic> [--new-area <area> | --rm]}"
root="$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
dir="$root/.worktrees/$name"

if [[ "${2:-}" == "--rm" ]]; then
  git -C "$root" worktree remove --force "$dir" && echo "· removed $dir (branch still exists)"
  exit 0
fi
new_area=""
if [[ "$name" =~ ^docs-([a-z0-9][a-z0-9-]*)$ ]]; then
  branch="docs/${BASH_REMATCH[1]}"; docs=1
elif [[ "$name" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  branch="feat/$name"; docs=0; area=""
  existing="$(git -C "$root" ls-tree -d --name-only "$MAIN_BRANCH:areas" 2>/dev/null | grep -v '^_' || true)"
  if [[ "${2:-}" == "--new-area" ]]; then
    new_area="${3:?--new-area needs the area name}"
    [[ "$name" == "$new_area"-?* && "$new_area" != docs && "$new_area" != _* ]] \
      || { echo "✗ $name must be $new_area-<slug> (and the area can't be «docs» or start with _)"; exit 2; }
    area="$new_area"
  else
    # Longest existing area that prefixes the name (areas as they are on the main branch).
    for a in $(echo "$existing" | awk '{ print length, $0 }' | sort -rn | cut -d' ' -f2-); do
      [[ "$name" == "$a"-?* ]] && { area="$a"; break; }
    done
    [[ -n "$area" ]] || { echo "✗ no area matches «${name}». Existing areas: $(echo $existing)"
      echo "  Use <area>-<slug> with one of them, or (with the user's OK, areas/README.md) --new-area <area>."; exit 2; }
  fi
  echo "· area $area · spec $area/${name#"$area"-} · branch $branch"
else
  echo "✗ the name must be <area>-<slug> (e.g. workflow-port-hash) or docs-<topic> (e.g. docs-gotchas): lowercase, digits, hyphens"; exit 2
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

if [[ -n "$new_area" && ! -d "$dir/areas/$new_area" ]]; then
  mkdir -p "$dir/areas/$new_area"
  sed "s/<Area>/$new_area/g" "$dir/areas/_template/README.md" > "$dir/areas/$new_area/README.md"
  echo "· new area: $dir/areas/$new_area/README.md (fill it in; add it to docs/STATUS.md)"
fi

if [[ "$docs" == 1 ]]; then
  echo "· $dir  branch $branch  (docs mode: no dependencies, no port)"
  exit 0
fi

clone() { cp -Rc "$1" "$2" 2>/dev/null || cp -R --reflink=auto "$1" "$2" 2>/dev/null || cp -R "$1" "$2"; }
for d in "${DEP_DIRS[@]}"; do [[ -d "$root/$d" ]] && clone "$root/$d" "$dir/$d"; done

# Stable port: hash of the name; on a clash with another folder's .port, the next free one.
h=$(printf '%s' "$name" | cksum | cut -d' ' -f1)
taken=" $(cat "$root"/.worktrees/*/.port 2>/dev/null | tr '\n' ' ' || true) "
for i in $(seq 0 99); do
  port=$((BASE_PORT + (h + i) % 100))
  [[ "$taken" == *" $port "* ]] || break
done
echo "$port" > "$dir/.port"
echo "· $dir  branch $branch  port $port"
