# Fit Rubric

**Version:** v1-draft (freeze as `v1` after calibration, see below)

This is the **one** definition of `strong` / `possible` / `no`. It's used everywhere a fit label appears:
- the LLM judge
- hand labels (mine and contractors')
- the feedback buttons
- evaluation

Every label and every match stores the rubric version it was made with.

---

## Step 1: score each criterion

Each criterion is scored by comparing the tender with the confirmed company profile. Every score that isn't `unknown` must come with a **quote from the tender**.

| Criterion | Values | Meaning |
|---|---|---|
| **Eligibility** (one row per stated requirement: set-aside, certification, clearance, licence, location) | `met` / `not_met` / `unknown` | `unknown` = the tender mentions it but the profile doesn't say, or the requirement probably lives in an attachment. Each requirement is also tagged `minor` (routine to get: registration, standard insurance) or `major` (certification, clearance, set-aside status) |
| **Scope** | `core` / `partial` / `none` | `core` = most of the work is a service the company already delivers. `partial` = some of the work, or a closely related service. `none` = mostly outside its services, or listed in its `exclusions` |
| **Size** | `in_range` / `near` / `far` / `unknown` | Estimated contract value compared with the profile's `contract_size_usd`. `near` = within 2× of the range (above max or below min). `far` = beyond that |
| **Experience** (one row per stated requirement, e.g. "3 similar contracts", "federal past performance") | `met` / `not_met` / `unknown` | Compared with the profile's `past_contracts` |
| **Teaming needed** | `true` / `false` | Part of the scope is clearly outside the company's services but the core is covered, so it would need a partner or subcontractor |

---

## Step 2: compute the label (code, not the LLM)

The rules are applied **in this order**. The first rule that matches decides the label.

**1. `no`**: any of these:
- an eligibility or experience requirement is `not_met`
- scope = `none`
- size = `far`

**2. `strong`**: all of these:
- scope = `core`
- no `not_met` requirements, and at most **one** `unknown`, which must be `minor`
- size = `in_range` (or `unknown` when the tender doesn't state a value)
- teaming needed = `false`

**3. `possible`**: everything else.

### Reason codes

Every label gets exactly one **primary** reason code: the first rule that fired, in the order listed below.

| Label | Reason codes (in priority order) |
|---|---|
| `no` | `NO_ELIGIBILITY`, `NO_EXPERIENCE`, `NO_SCOPE`, `NO_SIZE` |
| `possible` | `POSS_UNKNOWN_REQ`, `POSS_PARTIAL_SCOPE`, `POSS_SIZE`, `POSS_TEAMING` |
| `strong` | `STRONG` |

When a human label and the LLM label disagree, the criterion-level scores show which criterion caused it.

---

## Where it's used

| Place | How |
|---|---|
| **LLM judge** | The model fills in **step 1 only** (each criterion + quote). Code applies step 2. The LLM never chooses `strong` / `possible` / `no` directly |
| **Hand labels** | The labeller fills in the same step-1 criteria; the same code produces the label |
| **Feedback** | "Not relevant" asks for one reason from the `NO_*` codes, or "other: free text" |
| **Evaluation** | **Recall:** `strong` + `possible` count as "should be shown". **Top-of-digest precision:** `strong` only. Humans and the LLM are compared per criterion as well as on the final label |
| **Unit tests** | Step 2 is a pure function: `criteria → (label, reason_code)`. Every row in this file gets a test |

---

## Versioning

- The version is stored with every label (`labels.rubric_version`) and every match (`matches.rubric_version`).
- **If only step 2 changes** (e.g. the "within 2×" threshold): re-run the code on the stored step-1 scores. No relabelling needed.
- **If the meaning of a step-1 criterion changes:** flag the affected labels for relabelling.

---

## Calibration (before the main labelling)

1. Label about 20 tenders with this draft.
2. Write down every case where I hesitated, along with the criterion that caused it.
3. Tighten the wording and thresholds, then freeze as `v1`.
4. If a contractor takes part, these 20 are the first ones I ask them to check.

**Open thresholds to check during calibration:**
- "within 2×" for `near`
- "at most one minor unknown" for `strong`
- whether `teaming needed` should ever allow `strong`

---

## Examples

| Tender (summary) | Company | Criteria | Label |
|---|---|---|---|
| Cloud migration for an agency, small-business set-aside, $400k, remote OK | Acme IT (cloud migration, SBA, $25k–2M) | eligibility all met · scope core · size in range · no teaming | `strong` / `STRONG` |
| Same, but requires FedRAMP Moderate authorization | Acme IT (no FedRAMP) | FedRAMP `not_met` (major) | `no` / `NO_ELIGIBILITY` |
| Web app + on-site hardware installation, $1.5M | Acme IT (excludes hardware) | scope core for the app, hardware needs a partner · teaming needed | `possible` / `POSS_TEAMING` |
| IT helpdesk, "see attached SOW for requirements" | Acme IT | key requirements `unknown` (in attachment) | `possible` / `POSS_UNKNOWN_REQ` |
| Road resurfacing | Acme IT | scope none | `no` / `NO_SCOPE` |
