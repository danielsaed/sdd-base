# Gotchas — each one was a real bug

> **Answers:** which traps of this stack already bit us and how to avoid them.
> **Update when:** you learn a new one (1-5 lines, in its section). The implementer and
> the reviewer read the relevant section before touching an area; the planner cites the
> ones that apply. If one stops being true (the stack changed), delete it.

## Workflow

- **A test that SKIPS a case it can't set up lies in its summary.** If a check can't be
  set up (missing credentials, missing fixture), the script must stop with an error, not
  shrink silently and report "all green".
- **Permission tests that run as the owner prove nothing.** Make sure the test actually
  runs as the restricted role/user (and assert it) before trusting a "denied" result.
