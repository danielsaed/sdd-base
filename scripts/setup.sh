#!/usr/bin/env bash
# Prepares a machine to run this workflow with Claude Code, OpenCode or both: checks the
# prerequisites, installs what the project's MCP servers need and syncs OpenCode's config.
# Idempotent: run it after cloning and whenever .mcp.json or the agents change.
#
#   scripts/setup.sh              check + install the MCP's browser + sync OpenCode
#   scripts/setup.sh --cli        also install the missing CLIs (claude, opencode) with npm -g
#   scripts/setup.sh --with-deps  also the browser's system libraries (Linux; uses sudo)
#   scripts/setup.sh --check      only report (exit 1 if something is missing); installs nothing
#
# WHY a script and not a README list: the MCP's browser must be the exact build its Playwright
# version expects (installed with that same version), and a forgotten step only shows up
# mid-feature, when an agent first opens the browser.
set -uo pipefail
cd "$(dirname "$0")/.."

# ── CUSTOMIZE PER PROJECT ────────────────────────────────────────────────────
PW_BROWSER="chromium"                  # the --browser of the playwright server in .mcp.json
# ─────────────────────────────────────────────────────────────────────────────

check=0; cli=0; deps=""
for a in "$@"; do case "$a" in
  --check) check=1 ;; --cli) cli=1 ;; --with-deps) deps="--with-deps" ;;
  *) echo "usage: scripts/setup.sh [--check] [--cli] [--with-deps]"; exit 2 ;;
esac; done
missing=0
ok()   { echo "✓ $1"; }
miss() { echo "✗ $1"; missing=$((missing+1)); }
has()  { command -v "$1" >/dev/null 2>&1; }

# ── Prerequisites of the workflow (hooks, guard, scripts) ──
for c in git python3 node npx; do has "$c" && ok "$c" || miss "$c (required)"; done
if has node && [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 18 ]; then miss "node >= 18 (have $(node -v))"; fi
if has gh; then gh auth status >/dev/null 2>&1 && ok "gh (logged in)" || miss "gh: not logged in → gh auth login"
else miss "gh (GitHub CLI, for PRs and scripts/pr_wait.sh) → https://cli.github.com"; fi

# ── The agent CLIs: at least one ──
install_cli() { # <bin> <npm package> <official installer>
  if has "$1"; then ok "$1 ($("$1" --version 2>/dev/null | head -1))"; return; fi
  if [ "$cli" = 1 ] && [ "$check" = 0 ]; then
    npm install -g "$2" && ok "$1 installed" || miss "$1: npm install -g $2 failed"
  else echo "· $1 not installed (optional if you use the other): npm install -g $2  — or: $3"; fi
}
install_cli claude "@anthropic-ai/claude-code" "curl -fsSL https://claude.ai/install.sh | bash"
install_cli opencode "opencode-ai" "curl -fsSL https://opencode.ai/install | bash"
has claude || has opencode || miss "neither claude nor opencode is installed (scripts/setup.sh --cli)"

# ── MCP servers (.mcp.json, one home for both tools) ──
# Playwright MCP: its npm version is pinned in .mcp.json; the browser comes from the
# Playwright version THAT package depends on (another version = another browser build).
spec=$(node -e 'const s=require("./.mcp.json").mcpServers?.playwright; const a=s?.args?.find(x=>x.startsWith("@playwright/mcp")); console.log(a||"")' 2>/dev/null)
if [ -n "$spec" ]; then
  pw=$(npm view "$spec" dependencies.playwright 2>/dev/null | tail -1)
  if [ -z "$pw" ]; then miss "can't read the Playwright version of $spec (npm offline?)"
  elif [ "$check" = 1 ]; then
    loc=$(npx -y "playwright@$pw" install --dry-run "$PW_BROWSER" 2>/dev/null | sed -n 's/^ *Install location: *//p' | head -1)
    if [ -n "$loc" ] && [ -d "$loc" ]; then ok "$spec → $PW_BROWSER of playwright $pw ($loc)"
    else miss "$spec: the $PW_BROWSER of playwright $pw isn't installed${loc:+ ($loc)} → scripts/setup.sh"; fi
  else
    echo "· $spec needs playwright $pw: installing its $PW_BROWSER…"
    npx -y "$spec" --version >/dev/null 2>&1 || true   # warm npx's cache: the first agent call doesn't wait
    if npx -y "playwright@$pw" install $deps "$PW_BROWSER"; then ok "playwright MCP ($spec) + $PW_BROWSER"
    else miss "the $PW_BROWSER of playwright@$pw didn't install (on Linux try --with-deps)"; fi
  fi
else echo "· no playwright server in .mcp.json: nothing to install for it"; fi

# ── OpenCode's config, generated from Claude Code's ──
if [ "$check" = 1 ]; then node scripts/sync-opencode.mjs --check >/dev/null && ok "OpenCode config in sync" || miss "OpenCode config stale → node scripts/sync-opencode.mjs"
else node scripts/sync-opencode.mjs | tail -1; fi

echo
if [ "$missing" = 0 ]; then
  echo "✓ ready. Claude Code: run \`claude\` here (the first time it asks to trust the folder and to approve"
  echo "  the playwright MCP server of .mcp.json: accept both). OpenCode: run \`opencode\` here."
else
  echo "$missing thing(s) to fix (above)."; exit 1
fi
