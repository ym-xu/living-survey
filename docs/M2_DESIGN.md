# M2 design: profiles and a daily digest

Status: proposal, 2026-11-12, for the owner's decision (issue #3). Design only; no code
is written until the owner picks the options marked **Decide** below.
Read with `docs/PRODUCT.md` (milestones, the shared-vs-per-user rule).

## What M2 must do

A researcher describes their work (a few sentences and/or seed papers). Every morning
they get the new arXiv papers that match it, by email or RSS. Private beta: tens of
users, invited. The static template and the public field maps keep working unchanged.

## Constraints this design keeps

1. **Cost grows with papers, not users** (PRODUCT.md). Per-user work is vector math
   and rules only; no per-user LLM call in M2.
2. **A user's text never leaves our server.** Their description and seed list are
   embedded on our machine by a local model. No LLM, embedding API or analytics
   service ever receives them.
3. **No cross-user features.** No "people like you read", no shared profiles, no
   aggregates of what users follow. Each profile is used only for its own digest.
4. **The public pipeline stays standard-library Python.** The backend is a separate
   service with its own dependencies (adding them is the decision asked for here).

## Architecture

```
            once per day, for everyone                       per user, cheap
 arXiv ──> fetch (all new papers in the  ──> papers table ──> match: cosine(profile, paper)
           supported categories)             + embedding        + field/subfield rules
                     │                         (local model)            │
                     └── field maps (today's fetch.py / cards.py)       ▼
                                                               digest: top-k, deduped
                                                                        │
                                                         email (provider) or private RSS
```

- **Fetch** runs once a day over the categories the fields already use
  (cs.CV, cs.CL, cs.IR, cs.AI, cs.LG, cs.DL, cs.MM), not per field and not per user.
  This is the "shared arXiv fetch" that follows PR #2; M2 builds on it.
- **Embed** every new paper (title + abstract) once, with the same local model used
  for profiles. Papers are public, so this step has no privacy cost.
- **Profile** = one or more vectors (the description, each seed paper) plus optional
  include/exclude keywords and followed subfields. Editable by the user; we show the
  papers it would have matched last week so they can tune it.
- **Match** scores each new paper against each profile: max cosine over the
  profile's vectors, plus a bonus for followed subfields, minus exclude hits. Top-k
  above a threshold goes in the digest. Users × new papers × vectors is small
  (50 users × ~2k papers × 5 vectors = 0.5M dot products a day).
- **Digest** is sent daily (or weekly, user's choice), only when it has papers.

## Stack and hosting — Decide

Recommended: **one small server in the EU** running

| Part | Choice | Why |
|---|---|---|
| Service | Python 3.11+, FastAPI (or Starlette) | Same language as the pipeline; the scripts can be imported, not rewritten |
| Database | Postgres 16 + pgvector | Profiles, papers, vectors and digest log in one place; one backup to manage |
| Jobs | systemd timers (or cron) calling the same Python package | Daily fetch/embed/match/send; no queue needed at beta scale |
| Embeddings | local model in the same process (see below) | Constraint 2 |
| Server | 4 vCPU / 8 GB VPS, EU region (e.g. Hetzner, OVH, Scaleway) | Enough for Postgres + a small embedding model on CPU; EU keeps GDPR simple |
| Static maps | stay on GitHub Pages | Nothing changes for the public site |

Why not serverless or a managed platform: the local embedding model wants a
long-running process with the weights in memory, and the beta is too small to need
autoscaling. Why not SQLite: pgvector gives indexed similarity search and the M3/M4
path (accounts, limits) needs a real database anyway; the jump later is costlier than
starting on Postgres.

Alternative if the owner wants zero server maintenance for the beta: keep everything
on GitHub Actions, store profiles as encrypted files in a private repo, and send
digests from the Action. Workable for ~10 users; rejected as the default because the
profiles would then live in GitHub's infrastructure, not ours.

## Embedding model — Decide (after a measurement)

Local, CPU-friendly, English scientific text. Candidates to compare:

- **SPECTER2** (allenai) — trained on scientific papers and citations; built for
  "papers like these papers", which is the seed-paper case.
- **bge-small-en-v1.5** / **bge-base-en-v1.5** (BAAI) — strong general retrieval
  models, small and fast; better fit for the free-text description.
- **e5-small-v2 / e5-base-v2** — similar class, a second general option.

Pick by measurement, not reputation: take the two existing fields' papers, use each
subfield's papers as "relevant" for a description written from its overview in
`notes.toml`, and compare recall@20 for description→paper and seed→paper. Record
CPU time per 1,000 abstracts on the target server. The same model must embed papers
and profiles; changing it later means re-embedding the papers table (cheap) and every
profile (also cheap, since we keep the profile text).

## LLM provider and budget — Decide

M2 needs **no LLM for users**. The LLM keeps its current job: cards for papers in the
public fields (`cards.py`, via the OpenAI-compatible `llm.py`, DeepSeek by default).
It only ever receives public arXiv metadata.

Measured inputs for a budget:

- Field volume (data/fields/*/survey.json, 26-week window): document-understanding
  503 papers (~19/week), rag 1,119 (~43/week).
- One card: the system prompt is 1,659 characters plus the task/method lists, and an
  abstract is typically 1–2k characters: roughly **1.2k input + 0.4k output tokens**.

| Scope of cards | Papers / month | Tokens / month |
|---|---|---|
| Today's two fields | ~270 | ~0.45M |
| Ten fields of similar size | ~1,500 | ~2.5M |
| Every paper in the seven categories (not proposed) | measure in step 1; tens of thousands | tens of millions |

Multiply by the provider's current per-token prices at decision time (they change
too often to write down here). The first two rows are small at any mainstream
provider; only carding all of arXiv would make the LLM a real cost, and M2 doesn't
need it — matching uses embeddings, not cards.

Proposed rule: a monthly cap set by the owner, enforced in `llm.py` (stop and log
when reached; maps still build from the cards they have, as today without a key).

## Email — Decide

- A transactional provider with an EU region and a data-processing agreement
  (Postmark, Amazon SES eu-west, Brevo, Mailjet are all options); or no email at all
  in the beta: each user gets a **private RSS URL** (an unguessable token), which
  needs no provider and no address. Recommended: start with private RSS plus optional
  email, so users who don't want to give an address don't have to.
- Double opt-in, one-click unsubscribe (List-Unsubscribe header), plain-text + simple
  HTML, **no open or click tracking** (turn it off at the provider).
- The email address is the only personal identifier we store; sign-in is a magic
  link to it (no passwords in M2).

## Privacy architecture

| Data | Where it lives | Who sees it | Retention |
|---|---|---|---|
| Email address | Postgres | us, the email provider (to deliver) | until the account is deleted |
| Description, seed list, keywords | Postgres | nobody else; embedded locally | until the user edits or deletes it |
| Profile vectors | Postgres | nobody else | replaced on edit, deleted with the account |
| Digest log (which paper ids were sent) | Postgres | nobody else | 90 days, for dedup only |
| Papers, embeddings, cards | Postgres / public data | public | indefinite |

Rules:

- **Seed papers resolve locally.** An arXiv id or URL is looked up in our papers
  table; if missing, we fetch that paper's public metadata from arXiv by id. A
  Semantic Scholar author page is fetched only if the user asks for that import, with
  a note that S2 then sees which public author id was requested.
- **No third-party scripts** on the profile pages (no analytics, fonts from our own
  server, as the static site already does).
- **Logs** carry request ids and timings, never profile text or email addresses.
- **Export and delete**: one button each; delete removes the row and its vectors at
  once, backups age out within 14 days.
- **Encrypted at rest** (disk) and nightly encrypted backups to EU object storage.
- A one-page privacy policy states exactly this table. Because the owner is in the
  EU, GDPR applies from the first user: the table above is the record of processing.

## Deliberate change to PRODUCT.md (M3) — Decide

PRODUCT.md plans a weekly per-user LLM call for research points. With constraint 2
that call could send only public papers, but *which* papers we send still reveals
the user's interests to the provider. Proposed instead: research points are
generated **per field** (public, the same for everyone, cost grows with fields), and
each user's digest shows the points nearest their profile, ranked locally. Zero
per-user LLM calls, nothing about a user leaves the server. If the owner prefers
per-user points, the provider must have a no-training, no-retention agreement and
the privacy table above gains a row.

## Not in M2

Accounts beyond magic-link email, payments, limits, teams, research points (M3),
anything shared between users, a mobile app, non-arXiv sources.

## Build order, once decided

1. Shared daily fetch over the seven categories (the issue that follows PR #2);
   record real daily volume, which fills the "measure" row above.
2. Embedding benchmark (section above) and model choice.
3. Postgres schema + embed/match job, run offline against 2–3 hand-written test
   profiles; read their digests for two weeks before any user sees one.
4. Profile page + magic link + private RSS. Invite 5 users.
5. Email delivery. Then widen the beta.

## Decisions for the owner

| # | Decision | Proposal |
|---|---|---|
| 1 | Stack | Python + FastAPI + Postgres/pgvector, systemd timers |
| 2 | Hosting | one 4 vCPU / 8 GB VPS in the EU |
| 3 | Embedding model | chosen by the measurement above (SPECTER2 vs bge vs e5) |
| 4 | LLM | keep the OpenAI-compatible client, public data only; set a monthly cap |
| 5 | Delivery | private RSS first, email optional via an EU provider, no tracking |
| 6 | M3 research points | per field, ranked locally per user (changes PRODUCT.md) |
| 7 | Privacy | the table above as the policy and GDPR record |
