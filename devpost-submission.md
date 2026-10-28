# IncidentCourt

> Working draft for the Nebius x NVIDIA Global AI Hackathon. This is not a submitted entry. Bracketed items are unresolved; replace them only with verified facts. The prior Open Agent Hackathon entry and its Nightshift footage are separate from this entry.

## One-line summary

An incident investigation workspace that connects observations, competing hypotheses, and an auditable evidence trail so responders can review why an assessment was made.

## Problem

Incident responders must piece together metrics, logs, and traces while under pressure. A plausible explanation can hide missing evidence, alternative hypotheses, and uncertainty. Reviewing an answer should not require accepting an opaque conclusion.

## What we built

IncidentCourt brings incident telemetry into a single investigation. It compares observation windows, proposes a service hypothesis, checks alternative explanations, and presents supporting evidence, counterevidence, coverage, and a query trail. Reviewers can inspect cited rows, explore observed service dependencies, save review notes separately from the original report, and export the report.

The intended audience is engineers investigating service incidents and reviewers who need to understand the evidence behind an assessment. The project presents candidates and limitations, not a proven root cause or an automated remediation.

## How it works

1. Select an incident from the case queue and start an investigation.
2. The investigator gathers bounded metrics, logs, and traces; its planner and critic identify follow-up questions.
3. A structured report links observations to their source rows and recorded queries. The user can review the evidence, alternative explanations, coverage, and observed dependencies.
4. The user can save a review note and export the report without changing the underlying generated report.

The bundled offline sample is based on anonymized, measured telemetry from controlled RCAEval experiments. It uses deterministic rules and does not call Nebius or any other hosted model. Optional historical integrations include Zetaris, Nightshift, NVIDIA Nemotron, and the vendored Meterless H-MEM reference. Memory can suggest a service to check; fresh telemetry remains responsible for supporting the current assessment.

### Nebius and NVIDIA integration

**Pending live verification.** The planned Token Factory path uses [exact NVIDIA open-source model ID and variant: TODO] for [planner / critic / explanation calls actually exercised: TODO]. [Describe the actual Token Factory API path and configuration after verification: TODO]. Do not describe a Nebius response, latency, accuracy, or cost until it is observed and supported by a receipt.

Earlier NVIDIA Nemotron results through Nightshift establish a different provider path; they do not establish Nebius usage. Synthetic fixtures and metadata-only connection checks also do not establish a completed Nebius investigation.

## Why this matters

The project makes evidence easier to inspect and challenge in a workflow where a confident but unsupported answer can mislead a responder. It records query and citation provenance and exposes data coverage. This is a practical investigation aid; sampling and missing telemetry can change conclusions, and correlation or observed dependencies do not prove causation.

## How AI and development tools were used

- **Application AI:** [Add the actual model, provider, prompts, and role of each completed model call after a real Nebius run. Do not imply fine-tuning if none occurred.]
- **Development assistance:** Codex was used to develop and iterate on the project. [Add concrete, evidenced examples of how it contributed to this entry.]
- **Historical evidence:** Previous investigations used separate hosted NVIDIA Nemotron responses through Nightshift. This is historical context, not proof of Token Factory use.

## Architecture and built with

The local Python server serves the browser workspace and coordinates the investigation. It uses a telemetry store, a model adapter for the optional hosted path, and the vendored Meterless H-MEM reference through a Node.js bridge. Reports retain evidence and query references; review notes are stored separately. The bundled sample restores local SQLite data from the committed compressed fixture.

Candidate tags: Python, JavaScript, SQLite, Node.js, NVIDIA Nemotron, Nebius Token Factory, Meterless H-MEM, RCAEval. **Only retain tags matching the final verified build.**

## Reviewer and test-build instructions

**Public test-build URL:** [TODO — publish an accessible build after review and approval.]

The current offline sample is a useful first look and does not require credentials or network access. From the final published repository or test build, with Python 3.12+ and Node.js 24+:

```sh
python3.12 run.py --sample
```

Open `http://127.0.0.1:8317`, select an incident, and choose **New investigation**. Explore the report, cited observations, query trail and visuals; stop the server with `Ctrl+C`. This verifies deterministic sample behavior, not the Nebius model path.

**Nebius-enabled testing:** [TODO — document exact prerequisites, secure credential setup, model ID and command after the path is verified. Do not include private credentials. Specify costs and any restrictions honestly.]

## Links

- **Public repository:** [TODO — final URL and commit after publication.]
- **Working demo or downloadable test build:** [TODO — public, judge-accessible URL.]
- **Public YouTube demo:** [TODO — approved upload, less than three minutes.]

## Demo video outline

Record a new demonstration after a real Nebius-backed investigation is authorized and succeeds; never relabel the existing Nightshift capture as Nebius.

- **0:00–0:15:** Show the incident and the review problem; present the final evidence view early.
- **0:15–0:45:** Start a genuine investigation and identify the configured NVIDIA model and Nebius Token Factory connection without showing credentials.
- **0:45–1:25:** Show the resulting hypothesis, evidence and counterevidence; open source rows and the query trail. Label any edited wait or cut.
- **1:25–1:50:** Show coverage, alternatives and review/export. Explain that the output is a candidate, not proof of root cause.
- **1:50–2:10:** Explain the model's actual role and known limitations; show where judges can run the test build.

Capture a matching receipt separately, review every visible frame for sensitive information, confirm the YouTube upload is public and playable, and verify the actual runtime is under three minutes. Do not publish private receipts or expose credentials.

## Screenshot shot list

Capture from the verified final build and review for private information:

1. Case queue and incident selection.
2. Assessment with evidence and counterevidence.
3. Expanded cited observation and its query trail.
4. Coverage and observed service-dependency view.
5. Model/provider status with secrets and private identifiers concealed.

## Official form fields — working notes

Field labels and IDs are from the live Devpost requirements checked October 27, 2026. Confirm the live form before copying answers.

| ID | Field | Draft / remaining input |
| --- | --- | --- |
| 28261 | Submitter type | Individual (confirmed by user). |
| 28262 | Organization name | [User to confirm; form says N/A if not representing an organization.] |
| 28265 | Country of residence | United States, subject to user confirmation for the entrant. |
| 28266 | Canadian province | [Confirm whether any team member resides in Canada; form says N/A otherwise.] |
| 28267 | Track | Best apps and agents. |
| 28268 | New or existing before August 26, 2026 | [Confirm project provenance; local Git history begins October 25, 2026, but it does not establish all earlier work.] |
| 28269 | Significant updates for existing projects | [Complete only if applicable and supported by history.] |
| 28270 | Public code repository | [TODO: final public repository URL.] |
| 28271 | Working demo / test build | [TODO: public URL. Required by the event description for this track.] |
| 28272 | Models and why this size/variant | [TODO: exact model and evidence-based rationale.] |
| 28273 | Nemotron output quality, 1–10 | [User rating and specific observed strengths/limitations after use.] |
| 28274 | Fine-tuning, prompt engineering or out-of-box | [Describe verified implementation; confirm no fine-tuning if applicable.] |
| 28275 | Comparison with other models | [User's supported comparison or explicitly state no comparable evaluation.] |
| 28276 | Valuable Nebius capabilities and setup | [Describe actual API, model and deployment configuration after verification.] |
| 28277 | Recommendation likelihood, 1–10 | [User's rating and reasons.] |
| 28278 | Experience versus prior environments, 1–10 | [User's rating and reasons.] |
| 28279 | Nebius/Nemotron improvements | [User's experience-based feedback.] |
| 28280 | What to see next from Nemotron | [User's preference.] |
| 28282 | Tavily use | [Confirm against final runtime; the inspected current code had no Tavily call.] |
| 28281 | Builders & Brews city | [Optional; user to confirm attendance, otherwise leave blank.] |
| 28283 | Age attestation | [User must confirm the exact attestation for all applicable teammates.] |
| 28284 | Promotion-entity employee attestation | [User must confirm the exact attestation for all applicable teammates.] |
| 29059 | AI tools used on the project | [Complete from verified project and development history.] |
| 29060 | Learning level | [User to choose None, Moderate, or Significant.] |
| 29061 | Career value | [User to choose Yes or No.] |

## Readiness checklist

- [ ] Verify an actual Nebius Token Factory + NVIDIA model investigation, retaining sanitized evidence and failed attempts.
- [ ] Verify clean-environment test-build instructions and publish a judge-accessible build with approval.
- [ ] Review repository history, attribution, first-party license and secrets before making the final source public.
- [ ] Capture new Nebius-backed demo footage and screenshots, review privacy, and publish the video with approval.
- [ ] Complete user-specific feedback, team and eligibility fields and inspect the full Devpost preview.
- [ ] Submit only after explicit final approval. Deadline: October 30, 2026 at 10:00 a.m. Pacific. Organizer says not to edit submission materials after the deadline.
