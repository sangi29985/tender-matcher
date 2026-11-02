# Tender Matcher

Finds the public tenders a small company is eligible for and relevant to, explains why each one fits, and lists its eligibility requirements with quotes from the tender. The owner decides whether to bid; the tool never bids.

Graduation project for the AI Engineer bootcamp (Demo Day, Nov 2026).

## How it works

1. **Fetch:** a daily job pulls new notices from the SAM.gov Opportunities API.
2. **Hard filter:** rules drop closed tenders and ones the company isn't eligible for.
3. **Retrieve:** pgvector ranks the rest by similarity to the company's capabilities.
4. **Judge:** an LLM scores each [rubric](docs/rubric.md) criterion (requirements, scope, size), each with a quote.
5. **Check + score:** quotes must exist in the tender text; dates come from the official API fields; code applies the rubric to give strong / possible / no.
6. **Digest:** a daily list for the owner, who marks each tender "pursue" or "not relevant" (with a reason code).

## Stack

Python 3.12 · PostgreSQL + pgvector · Claude (frontier) vs. Qwen 7–8B via Ollama · FastAPI · Langfuse

## Docs

- [Idea post](docs/idea_post.md)
- [System design](docs/system_design.md)
- [Fit rubric](docs/rubric.md): the one definition of strong / possible / no
- [Demo Day guide](docs/demo_day_guide.md) · [Design template](docs/system_design_template.md)

## Status

Design stage. Next:
1. Measure how many tenders per day survive the hard filter for 2–3 sample profiles.
2. First pass with a strong model on ~50 real SAM.gov notices.
3. Calibrate the rubric on ~20 tenders and freeze v1.
