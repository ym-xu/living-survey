# Lessons

What had to be fixed, so it isn't fixed again. Newest first. Format: the rule, why,
evidence, how often it has been seen. At "Seen 3×" a rule moves into `AGENTS.md`.

## A check that reads exit codes must be tested against the failure it is meant to catch

PR #2 added a final job that turns the daily run red when a field's fetch fails, so
the owner is emailed. On the first deploy arXiv answered 429 to every call, and the
check passed: `fetch.py` keeps the old data and exited 0 when arXiv was unreachable,
so nothing upstream ever reported a failure. `/fields/rag/` went live with no papers
and nobody was told. A check is only as good as the signal under it: fake the exact
failure (here, 429 on every call) and assert the exit code the check reads.

Evidence: run 43213974435 (2026-11-12), found by review of the live site; fixed by
`fetch.py` exiting 3 (UNREACHABLE) with a test that fakes 429 everywhere.
Seen 1×.

## Changing a cache's path list is a data migration

`actions/cache` ties a cache to its exact `path:` list. Adding `data/fields` to the list
in PR #2 meant the next run would restore nothing: every paper card made since the last
commit would be redone with paid LLM calls, and the old files sat at paths nothing read.
Found by an independent review, not by the tests. When a workflow's cached paths
change, add a one-off restore with the old list and move the files, and use a new key
prefix.

Evidence: PR #2 review, 2026-11-12.
Seen 1×.

## Set test environment variables before any script module is imported

`scripts/mapconfig.py` reads `LS_MAP`, `LS_NOTES` and `LS_DATA` once, at import. A test
that imported `cards` first (setting only `LS_MAP`) made the next test run
`fetch.main()` against the real `data/` directory, and it replaced the 503-paper
`data/survey.json` with 4 fixture papers. Every test now imports `tests/_env.py`
first, which asserts the data directory is a temporary one.

Evidence: first test suite, 2026-11-11 (caught locally, data regenerated from arXiv).
Seen 1×.

## Prove a heuristic on real data, in both directions

The venue rule accepted any comment containing "in" or "at". Tightening it was
expected to lower the accepted count; on real data it rose from 106 to 114. Reading
the arXiv comments showed both directions were corrections: bare "ICML 2026" comments
had been missed (no "in"), and "under consideration at Pattern Recognition Letters"
had been counted as accepted. A count moving the "wrong" way is a reason to read the
changed papers, not to revert.

Evidence: venue fix, 2026-11-11 (10 changed papers checked against arXiv).
Seen 1×.
