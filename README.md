# Tender Matcher

Finds the US federal tenders a small company is eligible for and relevant to. For each one it
explains the fit with quotes from the notice and its attachments, and emails a daily digest.
The owner decides whether to bid; Tender Matcher never submits a bid.

## What it does

- **Accounts:** each company signs up and sees only its own profile, matches and feedback.
  Includes password reset by email, sign-in lockout after repeated failures, and account
  deletion.
- **Profile builder:** upload a capability statement (PDF, DOCX, text) or paste website text.
  Claude drafts the profile, lists what it guessed, and nothing is saved until the owner
  reviews it.
- **Daily pipeline:** SAM.gov sync, then rules (deadline, notice type, set-aside, location),
  then ranking, then reading the notice and its attachments, then one structured Claude
  judgment per tender. Code checks every quote against the text and computes strong /
  possible / no with the shared [fit rubric](docs/rubric.md).
- **Daily email** of new strong and possible matches, with a link back to the full
  checklists and pursue / not-relevant feedback.
- **Reliability:** judgments are reused, failures skip one notice or one company instead of
  the whole run, SAM.gov calls retry, a missed day is caught up, every run is recorded, the
  admin is emailed on problems, and `/health/ready` is there for uptime monitoring.

## Run locally

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
cp .env.example .env        # set SAM_GOV_API_KEY and ANTHROPIC_API_KEY
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and create an account. The database is a local SQLite file, and
migrations run automatically on start. Run the daily job by hand with
`uv run python -m app.jobs daily`. Emails are skipped until `SMTP_HOST` and `SMTP_FROM` are
set.

## Deploy

```bash
docker compose --profile https up -d --build
```

This starts Postgres, the web app, the daily worker, and Caddy for automatic HTTPS. Before
the first customer, read [docs/operations.md](docs/operations.md): configuration, backups,
monitoring, and what to do when something fails.

## Demo walkthrough

1. **Before the demo:** set both API keys, create an account, draft and save a profile, click
   Sync SAM.gov, then Build digest. The first build reads each shortlisted notice and its
   attachments (about a minute). Later runs reuse saved judgments and are near-instant.
2. **Profile:** upload a real capability statement, show the drafted profile and its
   "please check" notes, then save.
3. **Digest:** open a strong match, expand the eligibility checklist, show a requirement
   quoted from an attachment, and open the official notice to show the same text.
4. **Feedback and email:** mark one tender "Not relevant → Wrong size", then show the daily
   email.

## Tests

```bash
uv run pytest
uv run ruff check .
```

## Limits

See [Known limits](docs/operations.md#7-known-limits). The main ones: SAM.gov only, one user
per company, scanned PDFs are not read, and every match must be confirmed in the official
notice.

## Project docs

- [Operations runbook](docs/operations.md)
- [Idea post](docs/idea_post.md) · [System design](docs/system_design.md) ·
  [Fit rubric](docs/rubric.md)
- [Demo Day guide](docs/demo_day_guide.md) · [Design template](docs/system_design_template.md)
