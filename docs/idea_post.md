**Title:** Tender Matcher: finds the public tenders a small company is eligible for and relevant to, and explains why each one fits

**Problem:** Governments publish thousands of contract opportunities (tenders), many of them reserved for small businesses. Small IT, consulting, construction and services firms miss most of them. No one has time to check tender portals every day, and each tender is a long document full of eligibility rules (certifications, past experience, location, contract size). The free alerts on the portals only match keywords or industry codes. That gives lots of irrelevant results and misses good tenders that are worded differently or filed under the wrong industry code. Paid tools exist, but they're priced for large companies with dedicated bid teams.

**Inputs and outputs:**
- **In:**
  - **Company profile:** a capability statement, website text and past contracts (free text, once), turned into a structured profile.
  - **New tenders, pulled daily from public APIs:** SAM.gov for the MVP, roughly hundreds to a few thousand notices per day. Each has structured fields (deadline, industry code, small-business set-aside, location, agency) and a free-text description.
- **Out:** a daily digest for the company owner or bid manager, listing the top matching tenders. For each:
  - a fit rating (strong / possible / no) with reasons, defined by one shared [rubric](rubric.md)
  - an eligibility checklist (met / not met / unknown), each item quoting the tender text
  - key dates
  - a short summary

**Proposed solution:** A daily pipeline:
1. **Rules filter:** removes tenders that are closed or that the company isn't eligible for, using structured fields such as small-business set-asides.
2. **Meaning-based search (Postgres + pgvector):** ranks what's left by similarity to the company's capabilities.
3. **LLM judgment:** reads the top candidates in full and scores each rubric criterion (every eligibility and experience requirement, scope, size), each with a quote from the tender text.
4. **Checker + scorer:** confirms each quote exists in the tender and each date matches the official API fields. Then **code** applies the rubric to turn the criteria into strong / possible / no, so the LLM never picks the label directly.

The tool never decides to bid or submits anything; the owner does.

**Components:**
1. **Profile builder (LLM + human confirmation):** turns company documents into a structured profile: services, industry codes, certifications, locations, contract size range.
2. **Tender fetcher:** a daily job that pulls new notices from the SAM.gov API and stores them in Postgres.
3. **Hard filter (rules):** deadline, set-aside eligibility, notice type, location.
4. **Retriever (pgvector):** embeds tender descriptions and ranks them against the company's capabilities.
5. **Fit judge (LLM):** scores the rubric criteria with quotes, and writes reasons and a summary.
6. **Checker:** quotes must exist in the text, dates must match the structured fields, and the output must follow the expected format.
7. **Rubric scorer (code):** turns the criteria into strong / possible / no plus a reason code; one unit test per rule.
8. **Digest + feedback:** a daily email or web page; the user marks each tender "pursue" or "not relevant" with a reason code from the same rubric, which improves future matches.

**Tools, models and architecture (and why):**
- **Architecture: a fixed pipeline, not an agent.** The LLM is used in only two places, each a single call with structured output: building the profile and judging fit. Everything else (fetching, filtering, ranking, checking) is plain code. That makes each step testable on its own, keeps cost predictable, and makes failures easy to trace. An agent that reads attachments could come in v2.
- **Cheap steps first, expensive steps last.** Rules and vector search narrow thousands of notices down to a short list per company, so the LLM only reads the tenders worth reading. How many survive the rules alone hasn't been measured yet. If it's only a few dozen, I'll drop the ranking and judge them all (see the cost section of the design doc).
- **Postgres + pgvector:** a daily job has to remember what it already fetched, which tenders changed, and what each company decided. One free database holds tenders (with versions for amendments), profiles, embeddings, matches, feedback and evaluation labels. Rule filters and similarity ranking run in one SQL query, so there's no separate vector database to run or keep in sync.
- **Embeddings: small local model (e.g. `bge-small`):** free, fast enough for thousands of short descriptions a day, and computed once per tender for all companies.
- **Fit judge: frontier model (e.g. Claude Sonnet) first, then Qwen 7–8B via Ollama.** The frontier model sets the quality bar on long, formal tender text. The judge runs once per candidate tender per company every day, so cost grows with every customer. Scoring rubric criteria is a narrow task a small model may handle, and I'll measure that criterion by criterion rather than assume it.
- **Profile builder: frontier model, plus owner confirmation.** It runs once per company, so quality matters more than cost. A wrong profile would spoil every match, so the owner confirms it.
- **Deterministic checker, not a second LLM:** checking that a quote exists and a date matches the API is exact string and field matching. Code does that reliably and for free.
- **Plain SDK calls + Pydantic, no orchestration framework:** two LLM calls don't need one, and Pydantic enforces the output format. **Langfuse** traces tokens, cost and latency for the model comparison. **FastAPI** (or Streamlit) serves the digest; **cron** runs the daily job.

**MVP scope:**
- **In:** SAM.gov only; 2–3 sample company profiles; a daily job plus a simple web digest; tender descriptions only (no attachments).
- **Out:** parsing PDF attachments, other portals (EU TED, UK, India), writing bids, multi-user accounts, payments.

**Evaluation:**
- **About 200 tenders labelled with the rubric, sampled from the full pool, not just my pipeline's picks:** some that reached the judge, some the ranking dropped (mostly just below the cutoff), some the hard filter dropped, and a random set. Results are weighted back by group, so recall isn't inflated by only checking what the pipeline already chose.
- **Award backtest:** for 2–3 real small companies, would the pipeline have surfaced the contracts they actually won? These positives come from history, not from my pipeline.
- **Matching:** recall (strong + possible = should be shown) is the key metric, because missing a good tender is the costly error; top-of-digest precision counts strong only.
- **Criteria:** agreement with human labels per criterion (scope, size, each requirement).
- **Labels:** I label after calibrating the rubric on ~20 tenders. If contractors agree, they label tenders for their own profile, and I measure how often my labels agree with theirs.
- **Grounding:** 100% of quotes and dates must check out.
- **Baselines:** keyword/industry-code alerts (what portals offer today) and embedding similarity alone, without the LLM.
- **Model comparison:** frontier model vs. a small Qwen model on the fit judgment.

**Open questions:**
- Which market should I start with: US (SAM.gov has a clean free API), EU (TED), or my local portal?
- How much of the real requirements sit in PDF attachments rather than the description?
- How many tenders per day are left for one company after the hard filter? That decides whether the ranking step is needed.
- Can I get 1–2 real contractors to label tenders for their own profile in time?
- How many feedback clicks does it take before matches noticeably improve?
