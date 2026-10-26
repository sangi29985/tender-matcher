**Title:** Tender Matcher: finds the public tenders a small company can actually win, and explains why each one fits

**Problem:** Governments publish thousands of contract opportunities (tenders), many of them reserved for small businesses. Small IT, consulting, construction and services firms miss most of them. No one has time to check tender portals every day, and each tender is a long document full of eligibility rules (certifications, past experience, location, contract size). The free alerts on the portals only match keywords or industry codes. That gives lots of irrelevant results and misses good tenders that are worded differently or filed under the wrong industry code. Paid tools exist, but they're priced for large companies with dedicated bid teams.

**Inputs and outputs:**
- **In:**
  - **Company profile:** a capability statement, website text and past contracts (free text, once), turned into a structured profile.
  - **New tenders, pulled daily from public APIs:** SAM.gov for the MVP, roughly hundreds to a few thousand notices per day. Each has structured fields (deadline, industry code, small-business set-aside, location, agency) and a free-text description.
- **Out:** a daily digest for the company owner or bid manager, listing the top matching tenders. For each:
  - a fit rating (strong / possible / no) with reasons
  - an eligibility checklist (met / not met / unknown), each item quoting the tender text
  - key dates
  - a short summary

**Proposed solution:** A daily pipeline:
1. **Rules filter:** removes tenders that are closed or that the company isn't eligible for, using structured fields such as small-business set-asides.
2. **Meaning-based search (Postgres + pgvector):** ranks what's left by similarity to the company's capabilities.
3. **LLM judgment:** reads the top candidates in full and decides whether the company fits, pulling out every eligibility requirement with a quote from the tender text.
4. **Checker:** confirms each quote exists in the tender and each date matches the official API fields.

The tool never decides to bid or submits anything; the owner does.

**Components:**
1. **Profile builder (LLM + human confirmation):** turns company documents into a structured profile: services, industry codes, certifications, locations, contract size range.
2. **Tender fetcher:** a daily job that pulls new notices from the SAM.gov API and stores them in Postgres.
3. **Hard filter (rules):** deadline, set-aside eligibility, notice type, location.
4. **Retriever (pgvector):** embeds tender descriptions and ranks them against the company's capabilities.
5. **Fit judge (LLM):** returns the fit rating, reasons, eligibility checklist with quotes, and a summary.
6. **Checker:** quotes must exist in the text, dates must match the structured fields, and the output must follow the expected format.
7. **Digest + feedback:** a daily email or web page; the user marks each tender "pursue" or "not relevant (reason)", which improves future matches.

**Tools, models and architecture (and why):**
- **Architecture: a fixed pipeline, not an agent.** The LLM is used in only two places, each a single call with structured output: building the profile and judging fit. Everything else (fetching, filtering, ranking, checking) is plain code. That makes each step testable on its own, keeps cost predictable, and makes failures easy to trace. An agent that reads attachments could come in v2.
- **Cheap steps first, expensive steps last.** Rules and vector search cut thousands of notices down to about 30–50 per company, so the LLM only reads the tenders worth reading.
- **Postgres + pgvector:** one free database for tenders, profiles, embeddings, matches and feedback. Rule filters and similarity ranking run in one SQL query, so there's no separate vector database to run or keep in sync.
- **Embeddings: small local model (e.g. `bge-small`):** free, fast enough for thousands of short descriptions a day, and computed once per tender for all companies.
- **Fit judge: frontier model (e.g. Claude Sonnet) first, then Qwen 7–8B via Ollama.** The frontier model sets the quality bar on long, formal tender text. The judge runs 30–50 times a day per company, so cost grows with every customer. Fit / no fit is a narrow decision a small model may handle, and I'll measure that rather than assume it.
- **Profile builder: frontier model, plus owner confirmation.** It runs once per company, so quality matters more than cost. A wrong profile would spoil every match, so the owner confirms it.
- **Deterministic checker, not a second LLM:** checking that a quote exists and a date matches the API is exact string and field matching. Code does that reliably and for free.
- **Plain SDK calls + Pydantic, no orchestration framework:** two LLM calls don't need one, and Pydantic enforces the output format. **Langfuse** traces tokens, cost and latency for the model comparison. **FastAPI** (or Streamlit) serves the digest; **cron** runs the daily job.

**MVP scope:**
- **In:** SAM.gov only; 2–3 sample company profiles; a daily job plus a simple web digest; tender descriptions only (no attachments).
- **Out:** parsing PDF attachments, other portals (EU TED, UK, India), writing bids, multi-user accounts, payments.

**Evaluation:**
- About 200 real tenders hand-labelled as fit / no fit for each sample company.
- **Matching:** how many good tenders appear in the top 10, and how many results are noise. Missing a good tender is the costly error.
- **Eligibility checklist:** accuracy on about 30 tenders.
- **Grounding:** 100% of quotes and dates must check out.
- **Baselines:** keyword/industry-code alerts (what portals offer today) and embedding similarity alone, without the LLM.
- **Model comparison:** frontier model vs. a small Qwen model on the fit judgment.

**Open questions:**
- Which market should I start with: US (SAM.gov has a clean free API), EU (TED), or my local portal?
- How much of the real requirements sit in PDF attachments rather than the description?
- How many feedback clicks does it take before matches noticeably improve?
