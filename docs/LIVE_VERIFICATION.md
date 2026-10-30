# Verification record and limits

## Current Nebius submission checkout

The offline `--sample` mode uses deterministic investigation rules and bundled, anonymized telemetry from controlled RCAEval experiments. It does not call a model or remote telemetry service. The separate `--nebius-sample` mode uses that telemetry and live Token Factory inference when explicitly configured and enabled.

On October 27, 2026, a browser-started investigation of sample incident `IC-001` completed as run `1e0a06316d68` using `nvidia/nemotron-3-super-120b-a12b` through Nebius Token Factory. Three dispatched provider calls completed for the planner, critic and explanation, each reporting the requested model. Together they reported 2,308 input tokens and 1,765 output tokens, with no cached input tokens. The report contained 21 evidence records and 14 queries; 29 checked evidence references and all evidence query references resolved. The model explanation contained 11 citations. These checks establish identifier resolution, not that each generated claim is factually correct or that the proposed cause is accurate.

A private local summary links the report and three private per-call receipts. The report and receipts contain prompts or model outputs and must be reviewed before sharing. No real-time screenshot or video was saved during this run; a later offline review of the saved report was recorded for the demo. The immediately inspected billing dashboard had not updated since before the test, so the exact cost, credit deduction and any delayed charge are unverified; token usage is not an independent billing statement. This local run does not establish diagnostic accuracy, production readiness, deployment or judge access.

Simulated-provider tests separately cover the investigation pipeline and evidence-reference validation; model discovery and simulated tests alone do not establish a live run. Preserve failed and successful private receipts and review them for sensitive content before sharing.

## Hosted judge verification

On October 29, 2026, one HTTPS API-driven investigation completed on the deployed code-protected judge service as run `4979ec7c49de`. It used sample telemetry and made three real Token Factory calls with `nvidia/nemotron-3-super-120b-a12b`, reporting 2,308 input and 1,594 output tokens. The report contained 21 evidence records and 14 queries; checked citations resolved. Its candidate was `checkoutservice` with limited confidence. This is an observed lead, not an independently verified root cause. Provider failures are not automatically retried.

This was an HTTPS API-driven test, not a hosted browser-flow test. At the time of this test the service used code-protected access; judges did not need a provider API key. It supported one concurrent investigation and temporary sessions. The hosting Free plan may pause the service if credit is exhausted, and automatic idle wake for the actual service had not been tested. Provider token usage does not establish account billing or diagnostic accuracy.

Later on October 29, a browser-started investigation of sample incident `IC-001` completed on the deployed passwordless service as run `0bbc22744ece`. Three retained provider receipts record completed Token Factory calls served by `nvidia/nemotron-3-super-120b-a12b`, reporting 2,308 input and 1,583 output tokens. The report contained 21 evidence records and 14 queries and passed report lineage validation. Its candidate was `checkoutservice` with limited confidence; this is a lead, not a proven root cause. The browser test also opened an evidence link to its corresponding entry. These checks do not establish diagnostic accuracy or a billing amount.

Public entry allows anyone to initiate provider requests and incur charges. Sessions are temporary and only one investigation can run at a time. The hosting Free plan may pause the service if credit is exhausted; automatic idle wake for the real service had not been verified as of October 29. Per-client abuse controls remain unverified.

## Historical verification in the original project

On October 25, 2026, the original IncidentCourt project recorded two command-line investigations using Zetaris queries, the local H-MEM reference and hosted NVIDIA responses through its former Nightshift provider. The historical receipt reported 11 verification layers, including query provenance and citation checks. A saved target report was subsequently imported and inspected in a browser without a new provider call. The separate original checkout retains the historical material; its private receipts are not included in this submission repository.

Those results do not verify the Nebius client or establish diagnostic accuracy, production readiness or deployment. The prior model's critic also produced at least one inconsistent narrative about a selected service, so valid structured identifiers and citations are not proof that every generated statement is correct. The historical runtime's reported cost was an estimate, not an independent invoice.

See [data provenance](DATA.md), [integrations](INTEGRATIONS.md), and [Zetaris](ZETARIS.md) for the source data and individual integration boundaries.
