# Reusable verifications (`scripts/verify/`)

What each script measures, when to use it and its typical command. The detail (every
case, the why) lives in each file's header: **that is the truth**; this is only the index,
so the planner can name a script per acceptance criterion and the reviewer can run it.
Run them from the root or from a feature folder.

**Conventions** (keep them in every new script):
- Exit **0** all good · **1** something fails · **2** the check couldn't be set up. Never
  skip a case silently and report green ([docs/GOTCHAS.md](../../docs/GOTCHAS.md)).
- Side effects only on your role's reserved resources and temp folders
  ([areas/workflow/README.md](../../areas/workflow/README.md#resources-per-role)); shared
  state only with rollback or a dry run.
- A feature's verification goes here as a reusable script, not as a new test.

## Verify just enough
Measured upstream: ~80% of a spec's time went into verification, inflated by matrices
and repeated builds, not by the code.
- **Variants:** only the ones the spec touches (screen sizes, roles, inputs, configs). No
  matrices "just in case".
- **Where:** the implementer iterates in dev mode; **one** production build + pass, the
  reviewer's.
- **Caps:** a spec's verify script ≤ ~200 lines and ≤ 90 s.
- **Mutations:** required where a test protects an invariant; in UI, at most one per spec,
  in dev mode.
- **Regression:** only the reviewer runs other specs' checks, once, those related to the
  diff ([reviewer](../../.claude/agents/reviewer.md)). Waits:
  [implementer](../../.claude/agents/implementer.md) · [reviewer](../../.claude/agents/reviewer.md).

## Workflow
- **`guard_selftest.py`** — the subagent guard (`.claude/hooks/agent_guard.py` +
  `.claude/permissions.json`): every case against the real hook, plus mutation per rule
  (removing any rule must change some case). Runs in CI via `scripts/test-hooks.sh`. When
  touching permissions or the guard.
  `python3 scripts/verify/guard_selftest.py [--no-mutation] [-v]` · before changing rules,
  old vs new over real commands: `--corpus cmds.jsonl --old <agent_guard.py> --old-root <root> --out f.txt`.
  The guard that applies is the main checkout's: a branch's is measured by running its hook by path.
- **`../test-hooks.sh`** — the guard self-test plus, in a throwaway copy of the repo, the
  reminder and closeout hooks and `worktree.sh` over the areas layout (open spec, steps,
  close moved vs deleted, HISTORY, >3 done, >15 areas); the reminder stays <= 600
  characters with 1 open spec + 1 pending PR, and every state line (spec + step, PR to
  merge, docs mode, dirty main) survives, with a mutation case for the length cap. Runs in
  CI. `bash scripts/test-hooks.sh`.
- **`../worktree.sh`** — feature folder: `<area>-<slug>` (branch `feat/…`, the area must
  exist, dependencies cloned, `.port` from a hash of the name) · `--new-area <area>` ·
  `docs-topic` (branch `docs/…`, no port) · `… --rm`. Links the shared files.
- **`../baseline.sh`** — disposable worktree of `main` in a temp folder, to compare
  before/after without touching the main checkout. `scripts/baseline.sh` · `--rm`.
- **`pr_wait_selftest.sh`** — self-test of `scripts/pr_wait.sh` with a fake `gh` on the
  PATH (never talks to GitHub): without `--merge` it doesn't merge, a red/cancelled/
  checkless CI doesn't either, the summary is 1 line; built-in mutation. Runs in CI.
  `bash scripts/verify/pr_wait_selftest.sh`
- **`../pr_wait.sh`** — watches a PR's CI (and, with `--merge`, only the orchestrator with
  the user's OK: merges, follows the deploy and runs your production check); one summary
  line, log in `$TMPDIR/pr_wait-N.log`. `scripts/pr_wait.sh N [--merge]` ·
  `PR_WAIT_DEPLOY=none|github-deployments` · `PR_WAIT_DEPLOY_PATHS='^web/'` (matched
  against the PR's full file list; exits 3 if it can't read it) · `PR_WAIT_CHECK="…"` ·
  `PR_WAIT_VERSION_CMD="…"` (optional, with `github-deployments`: prints on its last line
  the commit production serves — short sha of 7+ ok, any case; the fallback when the host
  doesn't create GitHub deployments; its rc 2 = no credentials → exit 3).

- **`opencode_selftest.mjs`** — the OpenCode adapter (`.opencode/plugins/sdd.js`) with a fake
  client in a throwaway repo: guard per role (bash/edit/write/apply_patch, `workdir`, model
  variants, unknown parent = subagent), reminder only in the main session, closeout once per
  turn; built-in mutation (8 mutants). Runs in CI. `node scripts/verify/opencode_selftest.mjs [-v]`
- **`opencode_e2e.mjs`** — the REAL `opencode` binary driven by a scripted fake model: guard
  blocks (main + reader), reminder, closeout notice, `bg_run` notice, per-agent tool and
  browser allowlists. Not in CI (needs `opencode` + npm). After upgrading OpenCode or
  touching the plugin/generator/agents. `node scripts/verify/opencode_e2e.mjs [-v]`
- **`../sync-opencode.mjs`** — generates OpenCode's agents and `opencode.json` from
  `.claude/agents`, `.claude/settings.json` and `.mcp.json`. `--check` in CI (exit 1 if stale).
- **`../setup.sh`** — prerequisites, the CLIs (`--cli`), the Playwright MCP's browser
  (`--with-deps` on Linux) and the OpenCode sync. `scripts/setup.sh [--check]`.

## TODO: your project's checks
One entry per script, grouped by area (output, data, performance, security…):
- **`name.ext`** — what it measures (one line). When to use it.
  `typical command --with --flags` · notable options.
