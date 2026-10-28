# Sponsor integrations

This document describes the local H-MEM reference and the Nebius submission checkout. The original project previously verified a separate Zetaris and hosted-provider path; its private receipts are not included here and do not demonstrate Nebius usage. See [historical verification](LIVE_VERIFICATION.md).

## Zetaris connectivity and native registration

At the time of verification, the existing compute cluster was active and the configured SQL UI origin was reachable. Actual authenticated `SELECT 1`, native NDP previews, all four table registrations and their counts succeeded. The verified remote tables contained 3 incidents, 28,126 metrics, 1,498 logs and 15,000 spans, totaling 44,627 genuine sampled rows. Two complete investigations then executed against them through the actual adapter.

The application uses its Zetaris SQL adapter with credentials only in ignored `.env.local`. No password, account identifier, bucket detail or credential is required in public documentation. No AWS access key was created and no IAM permission was changed. Private setup evidence is retained under `artifacts/private/zetaris-setup/` and `artifacts/private/zetaris-registration-*/`. The completed live verifier retained 45 actual remote SELECTs including preflight, with returned-row hashes and resolving citations; no SQLite fallback was accepted. See `docs/LIVE_VERIFICATION.md` for the full receipt summary, procedure and limits.

## Meterless H-MEM

IncidentCourt executes the **official deterministic H-MEM reference implementation**, not a renamed local search function. The vendored files are unchanged from [Meterless/Meterless](https://github.com/Meterless/Meterless/tree/1742dec56a66e58eef9dda2d2b865823758ca8cd/engines/hmem/reference), commit `1742dec56a66e58eef9dda2d2b865823758ca8cd`. `vendor/meterless-hmem/PROVENANCE.json` records individual SHA-256 hashes; its Apache 2.0 license is retained beside the source.

The Python `HMemStore` adapter invokes `scripts/hmem_bridge.ts` with Node.js 24. The bridge calls upstream `HMEM.add` and `HMEM.query`; provenance, tiered persistence, retrieval scoring, context formatting and the trust ledger come from that upstream implementation. The reference uses deterministic lexical hash embeddings; it does not use a neural embedding model. Upstream describes this as a minimal reference, not a production library.

Only evidence-cited findings from earlier development/history incidents can be saved through `remember_verified`. The application automatically records measured development aggregates after generating query receipts; this does not require a human review flag. The caller is responsible for checking each cited evidence ID against that earlier incident. The adapter is not an independent verifier of the factual narrative. Holdout findings are rejected. Recall filters out the currently investigated incident and any holdout records **before** the upstream ranker runs. An explicit service scope further restricts eligible memories to matching service tags. The upstream ranker retains its default threshold of 0.35 and recall is logged with the upstream trust ledger. Historical recall provides a lead for further checks; it does not become current-incident evidence or establish causation.

The application consumes recalled service tags by querying their current metric coverage and logs, recording the resulting SQL receipts. In Nebius mode it also passes the returned context to the critic prompt. `tests/test_investigation.py` verifies the local behavior with declared synthetic telemetry: a verified earlier finding adds a reserve-service log query in a fresh incident, while the current evidence still controls the conclusion. This is real Engine execution and application behavior on a synthetic fixture, not a live Nebius or RCAEval accuracy claim.

Verification completed:

- Upstream reference smoke suite: **10/10 tests passed** using `npm test --prefix vendor/meterless-hmem` after `npm ci --prefix vendor/meterless-hmem --ignore-scripts`.
- IncidentCourt integration suite: **21/21 tests passed**, including real reference persistence/recall, current-incident exclusion, holdout rejection, audit lineage and duplicate avoidance.
- Investigation behavior suite: **8/8 tests passed** on declared synthetic SQLite telemetry, including memory-triggered SQL, hypothesis revision, citation lineage, missing-data uncertainty and rejection of unsupported provider citations.
- All 16 vendored files matched recorded upstream SHA-256 hashes.

These are reference smoke and application contract checks. The separate complete upstream conformance runner has not been run; no full engine conformance claim is made. Dreaming, sleep maintenance and conflict resolution are not invoked by IncidentCourt's current application adapter.

Official contracts: [H-MEM spec](https://github.com/Meterless/Meterless/blob/1742dec56a66e58eef9dda2d2b865823758ca8cd/engines/hmem/AGENTS.md), [reference facade](https://github.com/Meterless/Meterless/blob/1742dec56a66e58eef9dda2d2b865823758ca8cd/engines/hmem/reference/src/index.ts), [reference retrieval](https://github.com/Meterless/Meterless/blob/1742dec56a66e58eef9dda2d2b865823758ca8cd/engines/hmem/reference/src/memoryRetrieval.ts).

## Earlier local real-data memory behavior receipt

`scripts/verify_memory_flow.py` verifies the flow using only anonymous public telemetry tables and fresh separate memory stores. It does not open evaluator labels, injection metadata or original case paths. The latest strict run used development incident `IC-001` as history and holdout incident `IC-003` as a fresh target:

| Check | Observed result |
| --- | --- |
| Cold target investigation | 14 SQL queries, no recalled history |
| Target after earlier measured findings were stored | 16 SQL queries, one historical match |
| Additional actual SQL | Current metric coverage and later log checks for a recalled service |
| Threshold | Upstream default 0.35, unchanged |
| Eligibility | Current incident/holdout excluded, explicit service tags matched before ranking |
| Holdout promotion | None; historical-memory count unchanged |
| Receipt checks | 8/8 passed |

The complete private receipt is `artifacts/private/memory-flow-f96164826298/receipt.json`; report IDs are `de2d7b210130` (cold), `4a476009ca50` (earlier development investigation), and `7d54b4363d46` (warm). This demonstrates local application behavior on real controlled-experiment telemetry. It is not an accuracy benchmark or live Nebius proof. The earlier failed strict run is also retained at `artifacts/private/memory-flow-77cf389c9ba6/receipt.json`: spending all recall slots on repeated metric quantiles missed a relevant service. Distinct-service recall coverage fixed that issue without changing the threshold.

Reproduce locally with `.venv/bin/python3.12 scripts/verify_memory_flow.py`. Each run preserves independent memory stores and actual query reports under a fresh ignored private directory.

## Nebius Token Factory

The submission checkout includes an opt-in Nebius client for the sample telemetry workflow. It uses the fixed Token Factory endpoint with an explicitly configured NVIDIA model and retains private per-call success or failure receipts. Configuration and testing instructions are in the [README](../README.md#nebius-token-factory-with-sample-telemetry).

The implementation has simulated-provider tests; no live Nebius investigation, billing result, or production-readiness claim is established. Receipts may contain investigation prompts and outputs and must be reviewed before sharing. API keys must remain outside Git and public artifacts.
