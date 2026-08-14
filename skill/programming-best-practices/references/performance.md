# Performance

## Contents

1. Measure before optimizing
2. Baselines, not budgets
3. What to measure per stack
4. Common findings worth reporting
5. Reporting performance work

## Measure before optimizing

Performance is the area where confident guessing is most common and least
reliable. The same rule that governs every other category here applies without
exception: **instrumented evidence before heuristic opinion.**

- Record a measurement before the change and after it. A claim of "faster" with
  only an after-number is not evidence.
- Measure the thing the user waits for, not a proxy for it. Time-to-first-render,
  frames rendered while idle, and server CPU per request are outcomes; lines of
  code and cyclomatic complexity are not.
- Prefer a synthetic, repeatable measurement (call the hot function N times) for
  comparing versions, and an observational one (what the running system actually
  does) for deciding whether the problem is real. They answer different
  questions and you usually want both.
- Beware of measuring your own harness. A browser-automation `mouse.move()`
  round-trip costs more than the handler under test; a metric dominated by
  test-rig overhead will not move no matter what you fix.
- State the scale the measurement was taken at. An algorithm that is fine at 100
  nodes and unusable at 7 000 is a different finding from one that is always slow.

## Baselines, not budgets

Do not invent thresholds. "Bundle must stay under 250 KB" or "p95 under 200 ms"
are opinions unless the project agreed to them, and failing a build on an
invented number is the classic failure mode of performance tooling.

Compare against the repository's own recorded baseline instead
(`compare_perf_baseline.py`). The only claim that needs no agreement is *this
got slower than it was*, which is a fact about the repository.

- Commit the baseline next to the code so it moves with it.
- Regenerate it deliberately, in the same commit that intentionally changes
  performance, so the diff records the decision.
- Without a baseline, report the measurements and say a verdict is not possible.
  That is incomplete evidence, never a pass.
- Use a tolerance band. Machine noise of a few percent is not a regression.

If a project *does* have agreed budgets (a documented SLO, a CI gate already in
the repository), honor them — that is a repository convention, not an invention.

## What to measure per stack

| Stack | Cheap signal | Deeper signal |
| --- | --- | --- |
| Web frontend | shipped bytes per build (`js.bundle-size`) | frames while idle, long tasks, time-to-interactive |
| Canvas / render loop | work per frame; does the loop stop when nothing changes | frames rendered during a fixed idle window |
| Backend HTTP | server CPU per request; payload bytes | queries per request, cache hit rate |
| Database | queries per operation; presence of an index for the actual filter | rows examined vs. returned |
| Library / CPU code | `pytest-benchmark`, `cargo bench` | profiler output on the hot path |

## Common findings worth reporting

These recur across languages and are worth naming explicitly because each has a
concrete, verifiable fix:

- **A loop that never idles.** An animation or polling loop that keeps running
  with nothing to do. Costs battery and CPU permanently and is invisible in a
  screenshot. Ask: with the input static, does the process go quiet?
- **Superlinear algorithm on user-scaled data.** All-pairs work over a collection
  the user controls the size of. Fine in the demo, unusable in production.
- **Recomputing derived state per frame or per event.** A value that only changes
  when its inputs change, recomputed unconditionally. Fix with a cache keyed on
  a version counter, not with a timer.
- **N+1 and serial awaits.** `await` inside a loop turns N independent requests
  into N round-trips. Gather then `Promise.all`/`asyncio.gather`.
- **Re-opening a connection per call.** Connection plus session setup routinely
  costs more than the query itself.
- **Serializing the same payload twice.** Frameworks that re-validate and re-encode
  a response the code already built.
- **Walking the filesystem on every request.** Especially when the walk includes
  generated output, caches, or the application's own data directory.
- **Missing index for the filter actually used.** A composite index is not used
  for a query that filters only on a later column.
- **Writing to storage inside a move/scroll handler.** Synchronous serialization,
  or worse a network round-trip, per input event.

Report a finding only with a measurement attached. "This looks O(n²)" is a
hypothesis; "402 753 pair iterations per frame at the project's real data size"
is evidence.

## Reporting performance work

- Keep `severity` about user impact and `confidence` about the strength of the
  measurement, as everywhere else. A slow path nobody hits is low severity even
  when the number is dramatic.
- Give before and after in the same units, at the same scale, in the same run.
- Name what you did *not* measure. Cold start, low-end hardware, and large
  tenants are the usual gaps.
- A change that improves a benchmark while changing observable behaviour is a
  behaviour change, not an optimization. Say so, and verify the behaviour
  separately.
