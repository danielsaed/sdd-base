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
  `PR_WAIT_DEPLOY=none|github-deployments` · `PR_WAIT_DEPLOY_PATHS='^web/'` ·
  `PR_WAIT_CHECK="…"`.

## TODO: your project's checks
One entry per script, grouped by area (output, data, performance, security…):
- **`name.ext`** — what it measures (one line). When to use it.
  `typical command --with --flags` · notable options.
