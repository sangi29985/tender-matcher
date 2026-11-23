# Tender Matcher

Find public tenders relevant to a small company's capabilities, explain the fit with quotes
from the notice, and surface eligibility requirements for human review. The owner decides
whether to bid; Tender Matcher never submits a bid.

## Run locally

Requires Python 3.12+. Syncing notices requires a SAM.gov API key; judging the digest requires
an Anthropic API key.

```bash
uv sync --extra dev
cp .env.example .env
# Set SAM_GOV_API_KEY and ANTHROPIC_API_KEY in .env
uv run uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Create/edit the company profile in the
page, then sync notices and build the digest. The default database is a local SQLite file.
To use the included PostgreSQL container, run `docker compose up -d db` and set
`DATABASE_URL=postgresql+psycopg://tender_matcher:local-dev-only@localhost:5432/tender_matcher`.

The app also exposes interactive API docs at `/docs`. It is intended for local development;
it has no authentication and should not be exposed to a public network.

## Demo walkthrough

1. **Before the demo:** put both API keys in `.env`, start the app, and run steps 2–4 once.
   The first digest run reads each shortlisted notice with the AI judge (about a minute for
   30 notices). Judgments are saved, so later runs during the demo are near-instant.
2. **Profile:** show the form filled in for a realistic small IT firm (services, set-asides,
   states, contract size, exclusions). Saving creates a new profile version.
3. **Sync SAM.gov:** pulls the last three days of notices (typically hundreds to thousands).
4. **Build digest:** rules drop closed, wrong-type and ineligible notices; the shortlist is
   judged; every quote is checked against the notice text; code assigns strong / possible / no.
5. **Open one strong match:** expand the eligibility checklist and point out that every
   status carries a quote from the notice, then click "Open the official notice" to show the
   quote in the original.
6. **Close with feedback:** mark one tender "Not relevant → Wrong size" to show the
   learning loop.

If a notice is skipped (no description, failed quote check, model error), the digest says so
under "notices skipped — why?" instead of failing the whole run.

## Current MVP

- SAM.gov opportunity search with a three-day overlap, page traversal, and idempotent upserts.
- Editable, validated company profile.
- Deterministic deadline, notice-type, set-aside, and location hard filters.
- A lightweight lexical capability ranker to limit the judge candidates (not semantic embeddings yet).
- Full notice text downloaded from SAM.gov only for shortlisted notices, converted from HTML.
- One structured Claude judgment per candidate (run a few at a time, reused on later runs);
  code verifies quotes (ignoring whitespace, case and typographic quotes) and computes the
  `strong` / `possible` / `no` label using the shared [fit rubric](docs/rubric.md).
- Browser digest with a profile form, quote-backed checklists, original-notice links and
  pursue / not-relevant feedback.

This is the first working slice, not the complete design. Amended notices replace the stored
notice and are judged again, but version history is not kept; there is no profile-builder call,
pgvector embedding pipeline, scheduled daily job, email digest, user authentication, or PDF
attachment parsing yet. Treat every match as a reading aid and confirm all details in the
official notice.

## Tests

```bash
uv run pytest
uv run ruff check .
```

## Project docs

- [Idea post](docs/idea_post.md)
- [System design](docs/system_design.md)
- [Fit rubric](docs/rubric.md)
- [Demo Day guide](docs/demo_day_guide.md) · [Design template](docs/system_design_template.md)
