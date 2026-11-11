# Product plan: from one living map to a hosted service

Status: draft, 2026-11-11. The owner decides direction; agents implement it.
Change this file through a reviewed PR, not in passing.

## The goal

A researcher describes what they work on, in plain words or with a few papers. Every
morning they get the new papers that matter to them, a map of their area, and — once
a week — concrete open research points, each backed by papers they can check.

Today's repository is a **template**: one field per fork, configured by hand in
`map.toml`. That stays (it is the free, self-hosted edition), but most researchers
will not write regular expressions. The hosted service removes that step.

## The key design choice: shared work vs per-user work

Cost must grow with the number of **papers**, not the number of **users**.

| Layer | Done once for everyone | Done per user |
|---|---|---|
| Fetch | all new arXiv papers in the supported categories | — |
| Understand | one card per paper (today's `cards.py`), one embedding per paper | — |
| Match | — | rank papers against the user's interest profile (cheap: vectors + rules) |
| Map | subfield maps per field (today's `fetch.py`) | their own slice of a map |
| Research points | trend and gap signals per field (quiet cells, rising terms) | an LLM turns the signals near *their* work into suggestions, weekly |

Only the last row needs a per-user LLM call, and it runs weekly, not daily.

## What "research points" means — and the rule that keeps it honest

A research point is a short, specific suggestion: *"RL is common in document QA and
common in table recognition, but only 1 of 140 table papers uses it (expected ~9)."*
Inputs are signals the pipeline already computes: quiet method × task pairs, rising
terms, subfields that are starting to meet, benchmarks nobody has reported on yet.

The same rule as the cards: **every claim cites papers in the index, and a claim whose
citations don't check out is dropped.** No point is shown without its evidence.
Users rate points (useful / not / already done); that feedback tunes what is shown.

## Milestones

- **M0 — Foundation (done in this round).** Tests that run without network, CI on
  every push, the daily deploy gated on tests, `AGENTS.md` / `LESSONS.md`.
- **M1 — Several fields, one pipeline.** `fetch.py` runs over a list of maps and
  shares fetching and cards between them. Still static pages.
- **M2 — Profiles and a daily digest (private beta).** A user gives a description
  and/or seed papers (or their Semantic Scholar author page); we generate their
  profile (embedding + rules, editable) and send a daily email / RSS. Needs a small
  backend and database for the first time.
- **M3 — Research points.** Weekly, evidence-checked suggestions with feedback.
- **M4 — Accounts and paying for the LLM.** Sign-in, limits, and a way to cover costs.

## Decisions still open (owner)

- Backend stack and hosting for M2 (proposal: Python service + Postgres with pgvector,
  one small server; the static template keeps working as today).
- Which LLM and embedding provider, and the monthly budget.
- Email provider, and the privacy policy for user profiles.

## How the development itself is automated

Modelled on projects where agents write, review, merge and release the code:

1. Work arrives as GitHub issues (from the owner, or users via a feedback link).
2. An agent session claims an issue, works in its own worktree, writes the change and
   its tests, and opens a PR whose body says what was run.
3. A second, fresh agent reviews the PR against `AGENTS.md`. It merges only on a green
   `Test` run at the reviewed head.
4. `main` deploys itself (`daily.yml`, tests first).
5. Each night a session reviews the day's commits — what had to be fixed again, what
   shouldn't have merged — and updates `LESSONS.md`.

The owner keeps: product direction, field content (`map.toml`, `notes.toml`), secrets,
spending, and anything that reaches users for the first time (a new email, a new page).

Not set up yet: the scheduled agent sessions for steps 2, 3 and 5 (they need an agent
runner with a repository token and an LLM budget), and branch protection on `main`.
