# Verification record and limits

## Current Nebius submission checkout

The offline `--sample` mode uses deterministic investigation rules and bundled, anonymized telemetry from controlled RCAEval experiments. It does not call a model or remote telemetry service. The separate `--nebius-sample` mode uses that telemetry and live Token Factory inference when explicitly configured and enabled.

On October 27, 2026, a browser-started investigation of sample incident `IC-001` completed as run `1e0a06316d68` using `nvidia/nemotron-3-super-120b-a12b` through Nebius Token Factory. Three dispatched provider calls completed for the planner, critic and explanation, each reporting the requested model. Together they reported 2,308 input tokens and 1,765 output tokens, with no cached input tokens. The report contained 21 evidence records and 14 queries; 29 checked evidence references and all evidence query references resolved. The model explanation contained 11 citations. These checks establish identifier resolution, not that each generated claim is factually correct or that the proposed cause is accurate.

The ignored local summary is `artifacts/private/nebius-e2e-20261027/summary.json`; it points to the private report and three private per-call receipts. The report and receipts contain prompts or model outputs and must be reviewed before sharing. No real-time screenshot or video was saved during this run; a later offline review of the saved report was recorded for the demo. The immediately inspected billing dashboard had not updated since before the test, so the exact cost, credit deduction and any delayed charge are unverified; token usage is not an independent billing statement. This one run does not establish diagnostic accuracy, production readiness, deployment or judge access.

Simulated-provider tests separately cover the investigation pipeline and evidence-reference validation; model discovery and simulated tests alone do not establish a live run. Preserve failed and successful private receipts and review them for sensitive content before sharing.

## Historical verification in the original project

On October 25, 2026, the original IncidentCourt project recorded two command-line investigations using Zetaris queries, the local H-MEM reference and hosted NVIDIA responses through its former Nightshift provider. The historical receipt reported 11 verification layers, including query provenance and citation checks. A saved target report was subsequently imported and inspected in a browser without a new provider call. The separate original checkout retains the historical material; its private receipts are not included in this submission repository.

Those results do not verify the Nebius client or establish diagnostic accuracy, production readiness or deployment. The prior model's critic also produced at least one inconsistent narrative about a selected service, so valid structured identifiers and citations are not proof that every generated statement is correct. The historical runtime's reported cost was an estimate, not an independent invoice.

See [data provenance](DATA.md), [integrations](INTEGRATIONS.md), and [Zetaris](ZETARIS.md) for the source data and individual integration boundaries.
