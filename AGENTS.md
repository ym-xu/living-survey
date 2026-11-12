# Notes for coding agents

This repository is developed mostly by agents. A person sets the direction (issues,
`docs/PRODUCT.md`) and owns the field content; agents write, test, review and merge
the code. These rules exist so that works without someone watching every commit.
Read `LESSONS.md` before changing code: it is what went wrong before.

## Before you start

- Claim the issue (comment "taking this") before working on it, so two sessions don't
  build the same thing.
- One session, one checkout. Work in your own git worktree; never commit files you
  did not change yourself.
- Read the docstring at the top of the script you are changing. It says how the
  pipeline works and why.

## What a change must carry

- **Tests first-class.** New behaviour comes with a test in `tests/`; a fix comes with
  a test that fails without it. Run `python3 -m unittest discover -s tests` before
  every commit. Tests never touch the network or the real `data/` directory —
  import `tests/_env.py` first, as the existing tests do.
- **A commit says what was run.** Any commit that changes behaviour has a body listing
  the commands run and their result (tests, a real `fetch.py` run into a scratch
  `LS_DATA`, `hugo` build). "Should work" is not a result.
- **Check real output, not just tests.** For filing, venue or trend logic, run
  `LS_DATA=<scratch dir> python3 scripts/fetch.py` and compare with the current
  `data/survey.json`; explain every changed paper in the commit body.

## Boundaries

- `map.toml` and `notes.toml` are the author's description of their field. Don't edit
  their content unless an issue asks for it; tests use `tests/fixtures/map.toml`.
- Generated data is not committed (`data/survey.json`, `scripts/.cache/`), except
  `data/survey_cards.json`, which the template ships on purpose.
- The pipeline scripts use the Python standard library only (3.11+). Adding a
  dependency is a product decision: open an issue instead.
- Be a good citizen to free APIs: at least 3 s between arXiv calls, a real User-Agent,
  batch Semantic Scholar requests. Never send anything but public metadata to an LLM.
- Secrets live in GitHub Actions secrets only. Never print, log or commit a key.
- Merge only a green `Test` run at the head you reviewed. Deploys happen from `main`
  through `.github/workflows/daily.yml`, which runs the tests first.

## Keeping lessons

When something had to be fixed twice, or a review found a problem the tests missed,
add a lesson to `LESSONS.md`: the rule, why, the evidence (commit or issue), and
"Seen 1×". Bump the count when it happens again; at 3× move the rule into this file.
