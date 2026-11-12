# Lessons

What had to be fixed, so it isn't fixed again. Newest first. Format: the rule, why,
evidence, how often it has been seen. At "Seen 3×" a rule moves into `AGENTS.md`.

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
