# Flake policy

How to tell a flake from a real failure, and what to do about each one. This
is a policy doc, not a mechanism — nothing in `.github/workflows/` currently
implements a quarantine system. There's no live flake to quarantine right
now either: the failure history in `ci.yml` is dominated by a since-fixed
GitHub Actions billing incident (see `clean-install`'s job comment), not
code flakiness. This doc exists so there's a rule to follow the day a real
one shows up, not to retrofit anything today.

## Flake vs. real failure

A **real failure** reproduces. Same commit, same inputs, run it again (or
run it locally), it fails the same way. Fix the code or the test.

A **flake** is a test or step that fails intermittently against an unchanged
commit, for reasons outside the code under test — timing, container startup
races, transient network blips, an external service having a bad second.
The signal is reproducibility: if re-running the exact same commit sometimes
passes and sometimes fails with no code change in between, it's a flake
candidate. If it fails the same way every time, it's not a flake, no matter
how much you want it to be.

Don't confuse "I don't understand why this failed" with "this is a flake."
Unexplained is not the same as infra-caused. Read the failure first.

## Blind whole-job retries are banned

No job or workflow in this repo gets a blanket "just retry the whole thing
N times" wrapper — no `nick-invision/retry`-style action around an entire
job, no re-run-on-failure loop around `pnpm turbo run test`, no automatic
re-triggering of a failed workflow run. Confirmed by grepping
`.github/workflows/` for `retry`: zero matches today.

Whole-job retries hide real failures behind noise. A flaky-looking test
that "passes on retry" 80% of the time is still failing 20% of the time for
a reason — retrying it into green just moves the discovery of that reason
from CI to production. If a job needs a retry to go green, that's a signal
to investigate, not a reason to add more retry.

The one existing `continue-on-error: true` in this repo (`ci.yml`'s
`clean-install` job) isn't a flake workaround — it's there because that job
was once blocked by a GitHub Actions billing incident unrelated to the code
under test, and the flag kept an infra-caused red X from blocking merges
while that got sorted out externally. It's a job-level "don't block on this"
switch for a known non-code failure mode, not a retry, and not a pattern to
reach for when a test looks flaky.

## Step-scoped retries: allowed, narrowly

Retrying is fine when it's scoped to a single step and the step is
genuinely infra-flaky — a network install, a container pull, a registry
pull, a service warming up — not when it's wrapping a step that actually
exercises the code under test. The difference: a scoped retry waits out
something outside the repo's control before the real test runs; a whole-job
retry re-runs the real test and hopes.

This repo already does this correctly in a few places in `ci.yml` — these
are the pattern to copy, not something to invent from scratch:

- **`store` job, "Start postgres" step** — starts a throwaway
  `pgvector/pgvector:pg17` container, then polls `pg_isready` in a bounded
  loop (30 attempts, 2s apart) before handing off to the test run itself.
- **`api` job, "Start postgres + redis" step** — same shape, polling both
  `pg_isready` and `redis-cli ping` before the real `uv run pytest` step
  runs.
- **`alembic-check` job, "Start postgres" step** — same `pg_isready` polling
  loop ahead of `alembic upgrade head`.

All three follow the same rules worth keeping: the retry loop is its own
step, bounded (not infinite), and finishes before the step that actually
tests code starts. Nothing about the test logic itself is retried — only
"is the container up yet."

If a new step needs the same treatment (a new container dependency, a
package registry pull that's known to blip), copy this shape: a small
bounded polling or retry loop scoped to that one setup step, with a comment
saying why it's there. Don't wrap the test/build/lint step itself.

## Quarantine mechanism

Use this when a test is confirmed flaky (reproduces as "sometimes fails,
same commit, no code change") and the root cause isn't fixed yet.

1. **File a tracking issue** first. Title it with the test name and repro
   rate if known (e.g. "flaky: `apps/api/tests/test_foo.py::test_bar` —
   fails ~1/10 runs"). Link the failed run(s).
2. **Mark the test non-blocking**, not deleted and not silently skipped.
   The test still runs so its signal isn't lost, but its failure doesn't
   fail the job or block merge. In this repo's stack that means whatever
   the test runner's own non-blocking mechanism is (pytest `xfail(strict=
   False)`, a `bun test` `.skip`/annotate-and-track equivalent, or — as a
   last resort if the framework has nothing finer-grained — a dedicated
   `continue-on-error: true` step isolated to that one test, never the
   whole job). Prefer the narrowest mechanism the test runner offers over
   reaching for `continue-on-error` on a whole step.
3. **Reference the tracking issue** in the quarantine marker (a comment
   next to the `xfail`/skip, or in the step) so anyone reading it lands on
   the issue, not just a bare "known flaky."
4. **30-day max age.** A quarantined test gets 30 days to either get fixed
   (root cause found, test un-quarantined) or deleted (if it's not worth
   keeping). Quarantine is not a place tests go to retire quietly — an
   entry older than 30 days with no resolution is a bug, not a known issue.
   Whoever notices an overdue quarantine entry should either fix it, delete
   the test, or escalate — not extend the clock.

## What this doc doesn't cover

This isn't a CI architecture doc — see the comments in `ci.yml`,
`security.yml`, `extraction-eval.yml`, and `self-host-compose.yml`
themselves for how each workflow is structured and why. This also isn't a
migration or backfill task: there's nothing quarantined today, and landing
this doc doesn't create any new CI mechanism. It's the rule to reach for the
next time a test earns it.
