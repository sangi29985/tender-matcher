# Graduation Project × Demo Day Guide

## What Is a Graduation Project?

Your Graduation Project is an AI tool, assistant, or solution built around a real problem — at work, in your team, or for personal use. Focus on problems in domains you already know.

The project doesn't need to be finished or deployed. What matters is that you can explain the problem, your approach, and the tradeoffs you considered.

Your project can be:

- A working prototype (even a simple one)
- A system design or architecture proposal
- A concept with a clear problem statement and proposed solution

---

## What Is Demo Day?

Demo Day is the final milestone of the bootcamp. Each participant presents their Graduation Project and receives feedback from AI engineers at Hyperskill.

At Demo Day, walk through:

- The problem you're solving and for whom
- Your proposed solution
- Your choice of tools, models, or architecture and why
- Limitations and tradeoffs
- What success looks like

> Demo Day takes place the week of November 23–29. Exact date, time, and presentation format are coming soon.

---

## Project Requirements

**You don't need to:**

- Have a fully production-ready solution
- Deploy anything
- Have a complete GitHub repository

**You do need to:**

- Have a clear problem statement
- Be able to explain your solution and the reasoning behind your decisions
- Present it at Demo Day

Code is welcome, but the presentation focuses on your reasoning, not just the implementation. When scoping your project, consider:

| Dimension | Questions to Consider |
|---|---|
| **LLM Fit** | Does this problem actually call for an LLM, or is there a simpler solution? Is a chatbot interface suitable, or does something else fit better? |
| **Evaluation** | How will you measure quality — both of the system as a whole and its individual components? |
| **Infrastructure** | What does it realistically take to build and run this? |
| **Privacy & Safety** | Are there sensitive data concerns? Do any regulatory frameworks apply (e.g. HIPAA)? |
| **Model Selection** | Consider frontier models vs. small language models (1–10B parameters, e.g. the Qwen range) — some tasks can be handled accurately with a smaller, cheaper model. |

---
One more thing: think carefully about retrieval. We'll cover it in the RAG and vector search modules — it's a tool for getting relevant context to the LLM, not a default ingredient in every AI system.

If your project needs a dataset, [Kaggle](https://www.kaggle.com/datasets) is the easiest starting point. It has a large collection across most domains — finance, healthcare, NLP, tabular, time series, and more — and the datasets are typically either already cleaned or have a community-contributed preprocessed version. Unless data engineering is something you want to practice, don't spend your time on it: find a dataset that's close enough to your use case and focus on the AI part of the problem.

## Starter Repo

If your project is an end-to-end code implementation, the [ai-eng-project-template](https://github.com/hyperskill-content/ai-eng-project-template) repo gives you a reproducible project skeleton to build on, so you don't have to design the structure yourself. It's optional and only relevant for the full-implementation route, skip it if your project is a system design or concept.

## More Project Ideas

A quick sense of the range of topics past cohorts have tackled. These are one-line summaries, not the level of detail expected in your initial idea submission, see [Two Real Submissions](#two-real-submissions) below for that.

- **Mind mapper**: turns long-form text into structured mind maps by combining LLM-based semantic extraction with deterministic graph rendering.
- **QA Assistant**: reads task tracker issues and generates test case checklists, plus researches how competitors handle similar features.
- **CSAT Analyzer**: connects an LLM to an internal survey database via MCP for natural language questions about customer satisfaction.
- **Automated Crash Analysis**: an agent that triages production crashes, reconstructs the user journey from breadcrumbs, and posts a root cause analysis with a proposed fix.
- **Accidental American tax assistant**: guides US expats through IRS filing requirements, with a RAG-backed assistant grounded in an IRS document corpus.

---

## Scoping Your Idea

Before posting a proposal, work through these questions. The clearer your inputs and outputs, the more useful the feedback.

### Is this the right problem for an LLM?

LLMs work best when there's an existing workflow to assist or extend. If the underlying process is broken (no shared definition of what "correct" looks like, no agreed data format, no one owning the review step), automating it won't fix that. Define the human process first, even roughly.

### How complex should it be?

Most projects land at the right level as-is, so treat this section as a check. The complexity is in the problem you choose to solve, not in how many components you build around it.

A good problem is hard or tiresome to handle today, for someone specific: you, your team, or your users. Signs of that:

- Someone matches or cross-references information across sources by hand.
- The same approximate judgment gets made over and over, such as triage or sorting against fuzzy criteria.
- Inputs are messy or inconsistent: mixed formats, proprietary schemas, several languages.
- The volume makes manual work slow: thousands of documents, tickets, or reviews.
- Mistakes are costly, so outputs have to be grounded in sources or checked.

Then find where the LLM fits: split the task into the parts that rules can handle and the parts that need judgment, such as reading unstructured input, matching against fuzzy categories, or choosing the next step. If no part needs dynamic judgment, you don't need an LLM. 

The judgment parts are where the LLM goes, and each one needs something around it to work reliably: the tools and data it can reach, a check on its output before the next step uses it, and a person reviewing it where mistakes are costly. If the whole task is a single judgment that needs none of it, the problem is too simple to build around.

For each LLM step, be ready to say what the non-LLM alternative was and what you traded for it: accuracy, cost, latency, privacy, or human review.

**Too simple**
- A single classification call, such as sorting incoming email into folders. One prompt, or a mail filter, already does it.
- An app where the LLM is incidental, such as a habit tracker where AI fills in one field. The hard part is building the app, not the AI.
- A chatbot over a set of documents, built because it might be useful, with no specific question it is meant to answer.

**About right**
- Triaging production crashes: reconstruct the user journey from logs, pull the code at the crashed version, and draft a root-cause analysis for an engineer to review.
- Correlating crash telemetry with product analytics to write an incident summary, with every cited number traced back to the source data.
- Scoring second-hand electronics listings for repairability and resale profit before a small repair shop buys them.
- Auditing a 300,000-page website for duplicate content and compliance issues.

**Too broad**
- A full platform for building, deploying, monitoring, and billing AI agents across a company. Each part could be a project on its own; together they can't be finished or evaluated in the time available. Pick the part whose behavior you are least sure of and build that.
- An existing project with an LLM call added that doesn't change the result, such as a computer vision pipeline that does all the work, with an LLM restating its output at the end. Reusing and adapting earlier work is fine. What makes it a course project is giving the LLM part a real job, for example benchmarking a vision language model (VLM) against the existing pipeline and showing where they differ.

If you're unsure where your idea falls, post it anyway. Adjusting the scope in either direction is what the feedback step is for.

### Inputs and outputs

Being precise here helps understand the actual problem and the scope.

For each input:
- **What is it?** A PDF, a database record, a free-text query, an API response, a code file, etc?
- **What structure does it have?** Structured (JSON, CSV, fixed-format report) or unstructured (free text, scanned document)?
- **What's the volume?** One document per run or thousands? Real-time or batch?
- **How clean is it?** Will inputs always be complete, or do you need to handle missing fields, inconsistent formats, noise?

For each output:
- **What is it?** A markdown file, a database entry, an API call, a rendered UI element?
- **Who or what consumes it?** A human, another system, a frontend, a database?
- **What does "correct" look like?** If you can't describe how you'd verify the output, the problem isn't scoped yet.

### Brainstorming your approach

1. **Find the atomic unit of work.** What is the smallest thing the system needs to do? A tool should do one thing. If you can write a unit test for it, it's scoped correctly.
2. **Understand the automation problem.** What exactly are you automating? If there's an existing manual process, describe it precisely, including what works and what doesn't.
3. **Start with workflow, not agents.** An LLM assisting a person through a step is often more reliable than a fully agentic solution. Start there.
4. **Can it be a pipeline?** Describe the system as Step 1 → Step 2 → Step 3. If you can't sequence the steps, the problem isn't defined enough yet.
5. **Find the reliable units.** Which components can you verify work correctly? Those are your foundation and the starting point for building eval data to measure the full pipeline.
6. **Decide where humans stay in the loop.** Which steps need a human check before the next one runs?
7. **Bootstrap with a capable model.** Before writing code, put all your inputs (documents, scripts, data, requirements) into a single prompt and ask the model to lay out the step-by-step workflow, flag missing information, and note where it would be guessing. Use that output to find blind spots in your design early. (By "capable" — something like Claude Sonnet 5 on medium effort, not a smaller or distilled model.)
8. **Run the first implementation pass with a strong model.** Before optimizing for cost or size, run the first iteration with the best model you have access to — this tells you what the output should look like. It's much easier to then tune a smaller model toward a known target than to iterate without one.

---

## How Your Project Develops

**Step 1 — Submit your initial idea.**
Post your idea to the learning help channel. If you're still early and only have a rough direction, that's fine — a problem you've noticed or a painful workflow is enough to start a conversation.

If you already have a clearer picture, use the format below. The more structure you give upfront, the more specific the feedback you'll get back.

---

**Title:** One line describing what the system does.

**Problem:** What's broken or missing, and for whom. If relevant, why existing tools don't solve it.

**Inputs and outputs:** What goes into the system and in what form (file type, structure, volume). What comes out and who or what consumes it.

**Proposed solution:** What your system does at a high level — the core idea in 2–4 sentences.

**Components:** The main pieces of the system — agents, tools, modules — each with a one-line responsibility and how it connects to the others.

**MVP scope:** What's in scope for the version you're building, and what you're explicitly leaving out.

**Open questions:** Anything you already know you haven't figured out yet. Save the detailed answers for the system design document.

---

It should be closer to a structured Slack post than a spec doc.

### Two Real Submissions

Paraphrased from actual initial ideas submitted in past cohorts. Neither one fills out the fields above as a labeled form, the problem, approach, components, and scope are all there, just written as organized thinking.

**AI Governance Review Assistant**

As organizations build more generative AI and agentic applications, each one needs review for security, privacy, responsible AI, data handling, human oversight, and operational risk. Today that review is manual and depends heavily on the reviewer's expertise.

The idea: an AI-assisted system for a first-pass governance review. A product owner describes their use case through a structured questionnaire (architecture, data sources, models, RAG, agents, tools, human oversight), and the system evaluates it with a hybrid approach instead of leaving the whole call to one LLM.

Deterministic rules check what can be checked explicitly, for example whether sensitive data is involved or an agent can take write actions. An Intake Agent normalizes the submitted information and flags what's missing. A Risk Review Agent analyzes the use case against security, privacy, and responsible-AI criteria, using RAG to ground its findings in actual policy rather than the model's general knowledge. A Governance Report Agent reconciles the deterministic and AI-generated findings into one risk assessment, with severity, evidence, recommended controls, and whether the case needs further human review.

The AI never approves anything, it only produces a structured review for a human to act on. To evaluate it, the plan is a set of synthetic use cases with known risks, checking that the system actually catches them rather than just producing a plausible-looking report.

*Why this works:* a specific user and a recurring pain point, not "governance is hard." The hybrid design choice is argued, not just stated. Each agent has one job and a clear handoff. An explicit non-goal (the AI won't approve anything) and a real plan for checking the system works, not just that it looks convincing.

**Repair and Profitability Analysis Agent**

A multi-agent system that evaluates repair feasibility and profitability for a small electronics repair business, covering both mail-in repair and buy/repair/sell flows.

- Locator Agent: scans trading and auction sites for repairable candidates matching a defined profile, and passes them to the profitability agent.
- Profitability Agent: checks whether a candidate is likely to return a profit under the buy/repair/sell model, or sets a fair quote range for a mail-in repair.
- Recommendation Agent: consolidates candidates that clear both checks into a database a frontend can read from.

Tooling and API details are left for the project outline rather than guessed at here.

*Why this works:* grounded in a business the author already runs, so the constraints are real, not assumed. Each agent's job and handoff is one line. Deferring implementation detail to the project outline is the right call this early, not a gap.

**Step 2 — Get feedback.**
We'll review your idea and follow up with questions about the scope and approach.

**Step 3 — Write a system design document.**
If you've worked through the [Scoping Your Idea](#scoping-your-idea) questions, most of this is already in front of you. Describe how your system is structured. It doesn't need to be long, but it should cover:

- **Inputs and outputs** — what goes in, what comes out, and what "correct" looks like for each
- **Components** — what each piece of the system does (e.g., LLM, embedding model, retrieval layer, API, UI); map these to the atomic units you identified during scoping
- **Data flow** — how a request moves through the system from input to output; if you scoped it as a pipeline, describe it as one
- **Model and tool choices** — which models or services you're using and why; include what you observed from your first implementation pass with a strong model
- **Human-in-the-loop** — which steps need a human check and why
- **Evaluation** — how you'll know the system is working; tie this back to your reliable units and the definition of "correct" you established
- **Tradeoffs and limitations** — what you're not solving, and why

A diagram is helpful but not required. The goal is for someone unfamiliar with your project to understand how it works after reading it.

A [template](system_design_template.md) is available if you want a starting structure to fill in. It's a reference, not a requirement.

You don't need a complete design before you start building. It's fine to experiment first and update the document as your understanding of the problem changes.

**Step 4 — Build it out.**
Once the design is clear, move into implementation. Depending on your project, this could be:

- A working code demo
- A defined architecture with component breakdown
- A detailed requirements spec

Aim to produce something concrete each week: a refined problem statement, architecture sketch, or evaluation criteria — not just more planning.

| Step | Timeline |
|---|---|
| 1 — Submit your initial idea | October 19–25 |
| 2 — Get feedback | About 24 hours after submission(s) |
| 3 — Write a system design document | October 19–November 1 |
| 4 — Build it out | Until ~November 25 |

---

## FAQ

**Do I need to have a finished product?**
No. A concept or system design is fine — what matters is that you can explain your reasoning.

**Can I work on something I'm building at work or for a personal project?**
Yes.

**How complex should my project be?**
Complex in the problem, not in the architecture. See [How complex should it be?](#how-complex-should-it-be) for the criteria and examples.

**What if I don't have an idea yet?**
Reach out and we'll help you brainstorm.

**Will this affect my certificate?**
Demo Day is a required part of the bootcamp experience. It will be listed as an extra completed project on it.

**How long is the presentation?**
Be ready to give a 10 minute pitch.