# System Design Document Template

This is the template for the system design document referenced in Step 3 of the [Demo Day guide](README.md). Copy the headers below into your own document and fill in each section. Delete the instructional text as you go. It's mainly for reference, it's not required to take it and fill it out line-by-line. 

It doesn't need to be long. A concise document that matches what you're actually building is better than a generated one. Finalizing it around demo day, or alongside an initial implementation, is fine.

---


## Problem and current process

Who has this problem today, how often it comes up, and what it costs them in time, errors, or delays. Describe how it's handled now and which part is hard. Then split the task into the parts that rules can handle and the parts that need judgment. The judgment parts are where the LLM belongs. For each one, note what it needs around it to work reliably: the tools and data it can reach, checks on its output, and human review where mistakes are costly.

## Inputs and outputs

For each input: what it is (file, JSON, image, free-text query, API response, etc), how it enters the system, its structure, and its volume (one per run or thousands, real-time or batch). 

For each output: what it is, who or what consumes it, and what "correct" looks like. If you can't describe how you'd verify the output, this section isn't done yet, since without a clear output definition there's no way to evaluate the system. 

## Data flow

Describe the path from input to output step by step. If you scoped this as a pipeline during ideation, write it as one: Step 1 -> Step 2 -> Step 3. Note what happens at each step and what state changes.

## Data sources per input

For each step/component, list the data sources, tools, and APIs needed to complete this step. This surfaces brittleness: scraping without a stable API can break whenever the target site changes, and may need rework every few months. Use this to estimate effort and viability.

## Components and diagram

Draw every component: databases, agents, services, the UI if there is one. Where two components exchange data (for example, two agents communicating through a JSON file), write down the format of that data.

For each component, note where it sits on the spectrum between a deterministic pipeline step and an agent that decides non-deterministically which tools to use. This makes design errors easier to catch later.

## Model and tool choices

Which models or services you're using and why. Frontier model vs. small language model (1-10B, e.g. Qwen) is a real choice, not a default, since some tasks are handled accurately by a cheaper model. Include what you observed from your first implementation pass with a strong model, if you've run one.

## The stack

Which database and why. If you already have Postgres or MongoDB elsewhere, it may make more sense to use the vector extension in that ecosystem than to stand up a separate vector database. Any orchestration framework is fine, including plain API calls.

## Human-in-the-loop

Which steps need a human check before the next one runs, and why. In general, for a complex system, it's not the best idea to evaluate the final output only. HITL should be present at the important steps that have a direct influence on the flow. 

## Evaluation

State how you'll know the system behaves the way you want, tied back to the "correct" definitions from the inputs/outputs section. Human feedback is fine for the first iterations, especially with no golden dataset yet. Automated metrics can come later.

## Cost estimation

Estimate the cost of a single run. Once Langfuse tracing is in place this is straightforward to pull. Note any one-time costs separately, such as embedding a large document collection, especially if the data updates and can go stale. Back-of-envelope numbers are enough.

## Privacy and compliance

State whether the project touches medical, legal, or otherwise regulated data, or data that must stay in a specific jurisdiction. This constrains both storage and model deployment. Local models satisfy strict requirements but trail frontier model quality on consumer hardware, so the choice is between a cloud provider's compliant endpoints and designing around the absence of frontier models.

## Infrastructure

Cloud or local. This intersects with the compliance section above.

## Tradeoffs and limitations

What you're not solving, and why. What would break the system, and what you're accepting as a known gap for now. For each step that uses an LLM, name the non-LLM alternative and why you didn't choose it.

## Open questions

Anything you haven't figured out yet.