# M2 design: profiles and a daily digest

Status: proposal, revised 2026-11-17, for the owner's decision (issue #3). Design only;
no code is written until the owner decides to start M2 (next section) and picks the
options marked **Decide** below.
Read with `docs/PRODUCT.md` (phase 1, milestones, the shared-vs-per-user rule).

## M2 is a prepared option, not a go

PRODUCT.md decided on 2026-11-11 that phase 1 asks for nothing about the user: no
accounts, nothing stored, "we store no addresses". Personalised recommendations come
later, and only if phase 1 shows people need them. M2 breaks that rule on purpose: it
stores a description, seed papers and (optionally) an email address on a server.

So this document prepares M2; it does not start it. M2 starts only when the owner
decides phase 1 has shown the need, and records that decision in PRODUCT.md (a new
"Phase 2" section, through a reviewed PR).

Phase 1 has no analytics, by design, so the evidence has to come from what people
send us, not from watching them. Proposed start conditions (the numbers are
placeholders for the owner to set, not measurements):

1. **Explicit requests.** At least ~10 different people ask, in issues or through the
   feedback link, for something public fields can't give them: their own keywords,
   "papers like mine", a digest across fields. Counted over ~3 months.
2. **Fields don't stretch far enough.** "New field" requests that are really one
   person's narrow topic (too small to be a public field) keep coming, e.g. a third of
   requests over the same period.
3. **Phase 1 is used.** People follow the public feeds: My feed links shared in
   issues, people reporting they read the RSS feeds, stars and forks. Weak signals,
   but the only ones that cost no privacy. An opt-in "I would use a personal digest"
   issue template is a cheap way to collect condition 1 without tracking anyone.
4. **The owner accepts the obligations.** A server to maintain (see Cost and
   operations), a privacy policy, and GDPR duties from the first user.

If conditions 1–3 don't hold, the cheaper next step is more and better public fields,
not M2.

## What M2 must do

A researcher describes their work (a few sentences and/or seed papers). Every morning
they get the new arXiv papers that match it, by private RSS or email. Private beta:
tens of users, invited. The static template and the public field maps keep working
unchanged.

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
5. **An email address is optional.** A user can have a profile and a digest without
   giving any identifier (see Sign-in).

## Architecture

```
            once per day, for everyone                       per user, cheap
 arXiv ──> fetch (all new papers in the  ──> papers table ──> match: cosine(profile, paper)
           supported categories)             + embedding        + field/subfield rules
                     │                         (local model)            │
                     └── field maps (today's fetch.py / cards.py)       ▼
                                                               digest: top-k, deduped
                                                                        │
                                                         private RSS or email (provider)
```

- **Fetch.** The shared arXiv fetch exists on `main` (PR #7, "Share one arXiv download
  between fields (#5)"): `scripts/pool.py` asks arXiv once per run for the union of
  every field's categories *and* search terms, caches it as
  `scripts/.cache/arxiv_pool.json`, and `fetch.py` files each field from it. Full
  refresh weekly, otherwise only the last 14 days are re-read; each run logs its
  volume (calls, entries read, new, unique papers) to the job summary.
  M2 needs one thing the pool doesn't do: a free-text profile can match papers that
  no field's search terms catch, so M2 needs **every new paper in the categories**
  (cs.CV, cs.CL, cs.IR, cs.AI, cs.LG, cs.DL, cs.MM), not only those matching the
  terms. That is one more category-only stream, read incrementally by date (a full
  26-week refresh of all seven categories would hit the pool's 20,000-result cap).
  It reuses `scripts/arxiv.py` (rate limits, retries); not per field, not per user.
- **Embed** every new paper (title + abstract) once, with the same local model used
  for profiles. Papers are public, so this step has no privacy cost.
- **Profile** = one or more vectors (the description, each seed paper) plus optional
  include/exclude keywords and followed subfields. Editable by the user; we show the
  papers it would have matched last week so they can tune it.
- **Match** scores each new paper against each profile: max cosine over the
  profile's vectors, plus a bonus for followed subfields, minus exclude hits. Top-k
  above a threshold goes in the digest. Users × new papers × vectors is small
  (50 users × ~2k papers × 5 vectors = 0.5M dot products a day; the ~2k is an
  estimate until step 1 measures it).
- **Digest** is built daily (or weekly, user's choice), only when it has papers.

## Sign-in and the private link — Decide

The problem: delivery is RSS-first so users needn't give an email, but a magic link
needs an email. Options:

- **A. The private link is the credential (recommended).** No accounts and no
  passwords. Creating a profile gives the user two unguessable links:
  - a **feed link** (read-only), for their RSS reader;
  - a **manage link** (edit, export, delete), to bookmark or keep in a password
    manager.
  They are separate because a feed link ends up in RSS readers, often hosted
  services; anyone holding it can read the digest, but should not be able to change
  or delete the profile.
- **B. M2 requires an email.** Simpler (magic link, recovery by email), but it stores
  an identifier for every user, and contradicts the RSS-first reason for having
  private RSS at all.

How option A works:

- **Tokens**: 128 random bits, URL-safe. We store only a hash of each, so a leaked
  database doesn't hand out working links.
- **Rotate**: the manage page has "new feed link" and "new manage link". The old link
  stops working at once. Rotating the feed link means updating the RSS reader.
- **Revoke**: deleting the profile revokes both links.
- **Lost manage link**: without an email there is no recovery; the user makes a new
  profile. An abandoned profile is not kept forever: if its feed has not been fetched
  (and no email sent) for 90 days (owner-adjustable), it is deleted.
- **Optional email**: a user who adds an address gets email delivery and recovery
  ("send me my manage link"), with double opt-in. Email is never required.
- **Link hygiene**: `Referrer-Policy: no-referrer` on every page, no third-party
  resources, and token paths are stripped from logs.

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
on GitHub Actions, store profiles as encrypted files in a private repo, and publish
digests from the Action. Workable for ~10 users; rejected as the default because the
profiles would then live in GitHub's infrastructure, not ours.

## Cost and operations

**Server price (check at decision time).** Published prices seen in November 2026 for
a 4 vCPU / 8 GB VPS in the EU with shared vCPUs: roughly **€5–15 a month** before
VAT, depending on provider and plan (cheaper with a 12-month commitment). Dedicated
vCPUs cost several times more and are not needed for the beta. Add about €1–5 a month
for encrypted backups in object storage, and a public IPv4 address if not included.
Prices changed more than once in 2025–2026; read them off the provider's own page
when deciding.

**Maintenance duties** this creates, for whoever runs the server:

- OS security updates (unattended-upgrades for security fixes, a reboot when the
  kernel needs one).
- Postgres minor updates; a major upgrade (e.g. 16 → 17) about once a year, with
  pgvector rebuilt for the new version.
- Backups: nightly, encrypted, off the server; a **restore test** once a month into a
  scratch database, written down when done. A backup never restored is not a backup.
- TLS certificate renewal (automatic, but check it runs).
- Disk space and the daily job: an alert when the job fails or the disk is 80% full.
- Embedding model updates: only when the benchmark says so; it means re-embedding.
- Answering export and delete requests (the buttons do it; the duty is checking they
  still work).

## Embedding model — Decide (after a measurement)

Local, CPU-friendly, English scientific text. Candidates to compare:

- **SPECTER2** (allenai) — trained on scientific papers and citations; built for
  "papers like these papers", which is the seed-paper case.
- **bge-small-en-v1.5** / **bge-base-en-v1.5** (BAAI) — strong general retrieval
  models, small and fast; better fit for the free-text description.
- **e5-small-v2 / e5-base-v2** — similar class, a second general option.

Pick by measurement, not reputation. Two checks:

1. **Subfield labels.** Take the two existing fields' papers, use each subfield's
   papers as "relevant" for a description written from its overview in `notes.toml`,
   and compare recall@20 for description→paper and seed→paper. Cheap, but biased:
   the subfield labels come from regex rules over title and abstract, so they reward
   models that match words, not meaning.
2. **A small hand-labelled set.** 3–5 descriptions written like a real user would
   (not copied from `notes.toml`). For each, pool the top 30 papers from every
   candidate model, mix them, and have a person mark each relevant / not without
   seeing which model found it. Compare precision@20 and nDCG@20. About 300–500
   judgments; an afternoon's work.

If the two checks disagree, the hand-labelled set wins. Record CPU time per 1,000
abstracts on the target server. The same model must embed papers and profiles;
changing it later means re-embedding the papers table (cheap) and every profile
(also cheap, since we keep the profile text).

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

- Private RSS is the default and needs no provider and no address. Email is an
  option a user turns on by adding an address.
- For email: a transactional provider with an EU region and a data-processing
  agreement (Postmark, Amazon SES eu-west, Brevo, Mailjet are all options).
- Double opt-in, one-click unsubscribe (List-Unsubscribe header), plain-text + simple
  HTML, **no open or click tracking** (turn it off at the provider).
- Email can wait: the beta can start RSS-only and add email in the last build step.

## Privacy architecture

| Data | Where it lives | Who sees it | Retention |
|---|---|---|---|
| Feed and manage tokens | Postgres, hashed only | nobody; the user holds the links | replaced on rotate, deleted with the profile |
| Email address (optional) | Postgres | us, the email provider (to deliver) | until removed or the profile is deleted |
| Description, seed list, keywords | Postgres | nobody else; embedded locally | until the user edits or deletes it |
| Profile vectors | Postgres | nobody else | replaced on edit, deleted with the profile |
| Digest log (which paper ids were sent) | Postgres | nobody else | 90 days, for dedup only |
| Last feed fetch / last send date | Postgres | nobody else | to delete abandoned profiles (90 days) |
| Web server logs (IP, time, path without tokens) | server disk | us | 7 days |
| Papers, embeddings, cards | Postgres / public data | public | indefinite |

Rules:

- **Seed papers resolve locally.** An arXiv id or URL is looked up in our papers
  table; if missing, we fetch that paper's public metadata from arXiv by id. A
  Semantic Scholar author page is fetched only if the user asks for that import, with
  a note that S2 then sees which public author id was requested.
- **RSS readers see the digest.** If a user puts their feed link into a hosted
  reader, that service sees the papers in it, and so learns their interests. The
  manage page says so; a self-hosted or desktop reader avoids it.
- **No third-party scripts** on the profile pages (no analytics, fonts from our own
  server, as the static site already does).
- **Logs** carry request ids and timings, never profile text, tokens or email
  addresses.
- **Export and delete**: one button each; delete removes the row and its vectors at
  once, backups age out within 14 days.
- **Encrypted at rest** (disk) and nightly encrypted backups to EU object storage.
- A one-page privacy policy states exactly this table. Because the service is run
  from the EU, GDPR applies from the first user: the table above is the record of
  processing.

## Research points (M3): resolve an inconsistency in PRODUCT.md — Decide

PRODUCT.md already says, in its phase 1 section, that research points are per field
and public, so LLM cost grows with fields, not users. The same file says the
opposite further down: the shared-vs-per-user table and the M3 milestone describe a
weekly per-user LLM call. This is not a new proposal; PRODUCT.md needs to pick one.

Recommended: resolve it **in favour of per field**, as phase 1 says. Research points
are generated once per field; each M2 user's digest shows the points nearest their
profile, ranked locally. Zero per-user LLM calls. A per-user call would also clash
with constraint 2: even if it sent only public papers, *which* papers we send reveals
the user's interests to the provider.

Concretely: change the last row of the PRODUCT.md table ("Done per user" becomes
"ranked locally against the profile, no LLM") and the M3 line, through a reviewed PR.
If the owner prefers per-user points instead, the phase 1 sentence changes, the
provider must have a no-training, no-retention agreement, and the privacy table above
gains a row.

## Not in M2

Accounts (beyond the private links and an optional email), passwords, payments,
limits, teams, research points (M3), anything shared between users, a mobile app,
non-arXiv sources.

## Build order, once the owner says go

1. **Measure real daily volume on the existing shared fetch.** The pool already logs
   it per run (job summary: calls, entries read, new, unique papers). Add a one-off,
   measure-only run of a category-only stream over the seven categories for a few
   days, to learn how many papers M2 would embed per day and how many arXiv calls
   that costs. Fills the "measure" row above.
2. Embedding benchmark (both checks above) and model choice.
3. Postgres schema + embed/match job, run offline against 2–3 hand-written test
   profiles; read their digests for two weeks before any user sees one.
4. Manage page + feed and manage links + private RSS. Invite 5 users.
5. Optional email delivery. Then widen the beta.

## Decisions for the owner

| # | Decision | Proposal |
|---|---|---|
| 0 | Start M2 at all | not yet; start when the conditions in "M2 is a prepared option" hold (owner sets the numbers), recorded in PRODUCT.md |
| 1 | Stack | Python + FastAPI + Postgres/pgvector, systemd timers |
| 2 | Hosting | one 4 vCPU / 8 GB shared-vCPU VPS in the EU (about €5–15/month, check at decision time) and the maintenance duties listed |
| 3 | Embedding model | chosen by both measurements above (SPECTER2 vs bge vs e5); the hand-labelled set wins if they disagree |
| 4 | LLM | keep the OpenAI-compatible client, public data only; set a monthly cap |
| 5 | Sign-in | no accounts: a read-only feed link and a separate manage link, both rotatable; email optional |
| 6 | Delivery | private RSS by default, email optional via an EU provider, no tracking |
| 7 | M3 research points | fix PRODUCT.md's inconsistency in favour of per field, ranked locally per user |
| 8 | Privacy | the table above as the policy and GDPR record; abandoned profiles deleted after 90 days |
