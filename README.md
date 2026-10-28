# IncidentCourt

IncidentCourt is a local workspace for investigating incidents across metrics, logs and distributed traces. It builds and challenges service hypotheses, then presents a timeline, supporting evidence, counterevidence, alternatives and uncertainty. It was originally built for the **Open Agent Hackathon** and is being adapted for the Nebius x NVIDIA Global AI Hackathon.

The bundled sample runs offline with deterministic rules and real, sampled [RCAEval](https://huggingface.co/datasets/phamquiluan/RCAEval) telemetry. An optional live path connects Zetaris, Meterless H-MEM and Nightshift. On October 25, 2026, two command-line investigations passed the documented live verification checks with hosted NVIDIA Nemotron; a saved live report's citations, query trail and JSON export were also checked in the browser. Browser-triggered hosted generation, diagnostic accuracy, production readiness and deployment were not established. See [live verification](docs/LIVE_VERIFICATION.md) for the evidence and limits.

## Run the offline sample

Requires **Python 3.12+** with SQLite and **Node.js 24+**. No pip or npm installation, credentials or network access are needed to run the sample. The bundled fixture contains measured telemetry from controlled experiments; it is not a set of generated incidents or replayed reports.

```sh
git clone https://github.com/Xuefeng-Zhu/IncidentCourt-Nebius.git
cd IncidentCourt-Nebius
python3.12 run.py --sample
```

Open <http://127.0.0.1:8317>, select an incident and choose **New investigation**. You can leave and reopen the run while it executes. Evidence references open their source rows, **Query trail** shows executed SQL and critic decisions, and **Visuals** explores saved observations. Export JSON preserves the original computed report. Stop the server with `Ctrl+C`.

If Python 3.12 is not the default, one option is to create an environment with [uv](https://docs.astral.sh/uv/):

```sh
uv venv --python 3.12 .venv
.venv/bin/python run.py --sample
```

To run an investigation directly from a JSON input, use the CLI. The report goes to stdout; execution summaries go to stderr and `logs/`:

```sh
python3.12 run.py --sample --input input_examples/example_1.json > report.json
```

With the sample server running, the synchronous HTTP endpoint accepts the same input:

```sh
curl -s http://127.0.0.1:8317/run \
  -H 'Content-Type: application/json' \
  -d '{"incident_id":"IC-001","model":"local"}'
```

`SAMPLE_MODE=true` also selects offline mode. A small SQLite file is restored from the committed fixture without network access. It never calls Zetaris or Nightshift. Sample, full local and live modes have distinct receipts and separate sample memory stores.

## Nebius Token Factory with sample telemetry

The `--nebius-sample` mode combines the bundled RCAEval sample with NVIDIA model inference through Nebius Token Factory. It sends the planner, critic and explanation requests to the fixed Token Factory API, checks that the explicitly configured NVIDIA model is advertised, and rejects a different returned model. Evidence IDs are validated against the investigation. Model-generated explanations remain unreviewed. A provider error fails the investigation rather than silently switching to deterministic rules.

**Status:** this integration has contract tests with a simulated provider. A real Nebius investigation, its cost, and model availability have not yet been verified. `--sample` remains entirely offline and does not use a model. A key and inference opt-in are required for the Nebius mode; merely configuring a key does not authorize inference. Token Factory requests may consume credits or incur charges, so check your account and pricing before enabling them.

Set `NEBIUS_API_KEY` securely in your environment, without committing it. Set `NEBIUS_MODEL` to the exact NVIDIA open-source model ID advertised for your account (for example, `nvidia/nemotron-3-super-120b-a12b` **only if available to you**) and explicitly opt in to inference:

```sh
export NEBIUS_MODEL='nvidia/nemotron-3-super-120b-a12b' # replace if necessary
export NEBIUS_ALLOW_INFERENCE=1
python3.12 run.py --nebius-sample
```

Open <http://127.0.0.1:8317>, check the connection in Settings, then start an investigation. The model discovery check makes a network request but does not generate text. Each generation writes a private success or failure receipt under ignored `artifacts/private/nebius-calls/`; receipts contain prompts and output and should not be published without review. The client does not include authentication headers or the API key in receipts. Clear `NEBIUS_ALLOW_INFERENCE` or stop the process when finished.

A judge-supplied API key or account may not meet the hackathon's unrestricted-access requirement. The final submission must provide an approved, free-to-judges way to use the qualifying workflow; this local setup alone does not establish that requirement.

## Documentation

| Guide | Contents |
| --- | --- |
| [Data and provenance](docs/DATA.md) | RCAEval source, sampling, normalization and leakage boundaries |
| [Integrations](docs/INTEGRATIONS.md) | H-MEM and Nightshift configuration and verification |
| [Zetaris data path](docs/ZETARIS.md) | Table preparation, registration and connection details |
| [Live verification](docs/LIVE_VERIFICATION.md) | Dated execution evidence and its limits |
| [Implementation overview](docs/IMPLEMENTATION.md) | Components, execution flow and workspace APIs |
| [Handoff](docs/HANDOFF.md) | Project status and development context |

## Persistent workspace

- **Incidents:** search and filter the current source's case queue by investigation/review status. Cached case metadata remains available when telemetry cannot be refreshed.
- **Investigations:** reopen completed, failed, and interrupted work using stable URLs. One background run executes at a time, sharing the legacy API's lock; idempotency keys prevent duplicate dispatch. Actual stages and query counts persist. Unfinished runs become Interrupted on server restart and are never automatically resubmitted.
- **Review:** save private notes and mark individual runs reviewed. Notes survive reloads and restarts, never modify generated reports, and never enter telemetry SQL, model prompts, or H-MEM. Concurrent stale review saves return a conflict rather than overwriting newer notes.
- **Visual evidence:** open **Visuals** from a completed report to compare baseline and later metric/span means, inspect telemetry coverage, and explore observed service dependencies. Focus on a service or switch the coverage display between the full, baseline, and later windows; selections are retained in the report URL. Display ranges do not recompute the saved means. Every plotted comparison and dependency links back to evidence and executed SQL. Values and sample counts remain visible without hover; the dependency list also works on narrow screens.
- **Settings:** inspect the source/model and perform explicit metadata-only connection checks. The main workflow has no model selector or credential form.

Visuals read the report's saved rows without requesting telemetry or inference. Each comparison has its own zero-inclusive scale; unrelated metrics are not placed on one shared numeric axis. Metric units are labeled as source units when the record does not declare a unit, while trace durations use milliseconds. Coverage bars show first/last observation bounds, not continuous availability. New reports retain the exact baseline and later-window boundaries with their incident-query reference; older reports show only the recorded telemetry extent. The dependency map shows observed parent/child spans and does not establish causation. Original JSON exports remain unchanged when browsing or filtering.

Private data is stored in ignored `data/workspace.sqlite3` (including its SQLite sidecars). Run one application-server process per workspace database. The source identity excludes credentials and partitions sample, local, and Zetaris history. Stop the server before copying the database for a simple filesystem backup.

When a valid private verification receipt and its reports are explicitly configured, the live workspace can bootstrap those two hash-verified historical reports as unreviewed history. Those private files are not included in a public clone. The workspace does not scan private directories or index unrelated legacy test outputs. Manually imported JSON snapshots persist in the library, remain visibly unverified/unlinked, and cannot change case-queue status. Original reports remain immutable and exports retain their existing JSON format.

New case/history APIs are `/api/cases`, `/api/cases/{id}`, `/api/investigations`, and `/api/investigations/{id}`. POST starts an investigation with `incident_id` and `idempotency_key`; `/api/investigations/{id}/review` saves `note`, `reviewed`, and the current `version`. `/api/investigations/import` accepts a complete report up to 5 MiB. `/api/cases/refresh` and `/api/connections/check` refresh metadata without inference. The CLI and synchronous endpoints remain available for offline execution; hosted browser runs use the guarded workspace endpoint.

The background UI was exercised end to end using isolated offline sample SQL/rules, including navigation/reload during a gated QA run and eventual completion. This does not constitute a new hosted-provider verification.

## Investigation behavior

1. **Planner** compares the first and last thirds of the observation window. Only metrics with enough non-null samples are compared; baseline-relative changes form hypotheses.
2. **H-MEM recall** searches earlier verified observations for up to three distinct observed services, using the unchanged upstream threshold. Current-incident and holdout memories are filtered before ranking. Retrieved context triggers fresh measurement and log queries.
3. **Evidence Critic** challenges metric-only explanations. **Investigator** compares span durations, parent/child dependencies and bounded later-window log excerpts. Resource and timing checks can revise the service ranking. Stable or decreasing metrics remain visible as counterevidence.
4. **Report** preserves query IDs, returned rows, coverage, observed threshold crossings, alternatives and limitations. Only measured development facts with saved evidence receipts enter memory; a guessed diagnosis is not promoted as a verified fact.

Local mode uses transparent deterministic heuristics. Nightshift mode makes separate structured planner, critic and explanation requests. Its planner selects an observed service and its critic selects an actual follow-up query target. Unknown evidence IDs or malformed decisions fail explicitly. Generated prose has reference validation, not automated proof of every causal claim, and remains separately labeled for review. Failed provider calls do not silently become local successes.

## Data and leakage boundaries

[RCAEval](https://huggingface.co/datasets/phamquiluan/RCAEval), by Pham et al., provides controlled fault-injection experiments. The imported subset is **3 RE2-OB cases**, pinned to revision `afeacb11bcc94dadfd1c8f483ee4377b2b8b614e`: **21,225,701 compressed source bytes**, below a 50 MiB hard cap. The full collection was not downloaded. The MIT license is retained in `LICENSES/RCAEval-MIT.txt`.

The committed sample contains 28,126 metrics, 1,498 logs and 15,000 spans, sampled across three anonymous incidents. Sampling can miss brief events and change rankings. Original paths, labels, injection times and answer keys remain ignored/private. The runtime exposes only `incidents`, `metrics`, `logs` and `traces`; no evaluation tables, file tools or shell are available. IC-001 is development; IC-002 and IC-003 are held out from memory writes. Labels were not used to tune the investigator.

Nulls remain missing. Trace times are normalized to epoch seconds and durations to milliseconds. Missing severity/status is not converted into an error. IC-001 traces end about 170 seconds before its metrics. Correlation or missing spans do not prove a cause or recovery. No deployment history or support tickets were supplied or synthesized.

To regenerate the larger local subset, first create `.venv` as shown above if you do not already have a Python 3.12 environment. The following commands install optional data dependencies and download the bounded source subset:

```sh
uv pip install --python .venv/bin/python -r requirements-data.txt
.venv/bin/python scripts/import_rcaeval.py
.venv/bin/python -m scripts.prepare_sample
```

See [data provenance](docs/DATA.md) and the manifests under `data/public/`.

## Sponsor connections

In the hosted investigation path, each component has a distinct role:

1. **Zetaris** serves the incident, metric, log and trace tables. The investigator issues bounded SELECT queries and records their results as evidence.
2. **Meterless H-MEM** recalls eligible findings from earlier investigations. Recalled service names prompt fresh Zetaris queries; historical memory is a lead, not current evidence.
3. **Nightshift** is the gateway for the planner, critic and explanation requests. The planner chooses an observed service and the critic can direct a follow-up query.
4. **NVIDIA Nemotron** supplies the hosted model responses through Nightshift. The historical verification used `nvidia/nemotron-3.5-lightning-30b-a3b`; local sample mode uses deterministic rules instead of this model.

The table describes the October 25, 2026 verification, not a guarantee that those services or credentials are currently available:

| Component | Verified layer | Remaining layer |
| --- | --- | --- |
| Meterless H-MEM | Official reference recalled history and triggered two actual Zetaris queries; holdout memory unchanged | Full conformance and production engine behavior not claimed |
| Zetaris | Four native NDP tables, 44,627 real sampled rows, 45 SELECTs with actual query receipts | Broader datasets, production scale and deployment not tested |
| Nightshift | Six distinct uncached planner/critic/explanation responses across two real investigations | Saved live record browser citation/query/export checks passed; new generation disabled after the approved budget |
| NVIDIA | Every response named the exact approved `nvidia/nemotron-3.5-lightning-30b-a3b` route through Nightshift | Runtime cost reports do not independently prove account billing |

For optional integrations, configure an existing Zetaris instance and Nightshift gateway. Start with a local settings file, preserving it if one already exists:

```sh
test -e .env.local || cp .env.example .env.local
```

Set `SAMPLE_MODE=false`, `INCIDENTCOURT_DATA_MODE=zetaris`, the Zetaris connection and registered table namespace, and the existing Nightshift gateway token and advertised model ID. The H-MEM reference is already vendored and uses Node.js; it does not require a separate hosted memory service. Configure the NVIDIA provider key in Nightshift, not in this repository. Environment variables take precedence over `.env.local` values; keep credentials out of Git.

```sh
python3.12 -m scripts.check_integrations
```

This preflight performs read-only discovery and SELECT checks; it does not send inference requests or create resources. Configuring a connection or passing preflight does not itself verify an end-to-end hosted investigation. For registration and live-run prerequisites, see [Zetaris data path](docs/ZETARIS.md) and [Meterless/Nightshift details](docs/INTEGRATIONS.md).

The earlier six-call allowance was consumed. Those responses reported zero estimated cost and 890 output tokens in total; the runtime figures are not an invoice. The receipts do not establish the number or route of every internal model call, including any cross-check or tool loop.

The browser's hosted path requires an explicitly configured NVIDIA Nemotron route and inference opt-in. It retains per-call receipts and checks each returned route and cost estimate. The selected route and its winning-route receipt do not establish which auxiliary models Nightshift may use; those depend on Nightshift's own configuration. Runtime cost estimates cannot guarantee free-credit-only billing. See [live verification](docs/LIVE_VERIFICATION.md) for the evidence and limitations. An NVIDIA key belongs in Nightshift, not this app. `METERLESS_BASE_URL`, `METERLESS_RUNTIME_TOKEN`, and `METERLESS_MODEL` are supported aliases; `NIGHTSHIFT_ALLOW_INFERENCE=1` is only appropriate after provider usage is authorized.

## Verification

```sh
python3.12 -m unittest discover -s tests -v
python3.12 -m scripts.verify_memory_flow
npm ci --prefix vendor/meterless-hmem --ignore-scripts
npm test --prefix vendor/meterless-hmem
```

Tests cover offline restore, units/nulls, query boundaries, missing telemetry, hypothesis revision, H-MEM behavior/exclusion, provider contracts, citation rejection, redirects and HTTP validation. Synthetic test fixtures are labeled and separate from dataset runs. Upstream H-MEM smoke tests cover ten cases; no full conformance claim is made.

The completed live receipt is `artifacts/private/live-flow-20261025-nvidia-01/receipt.json`. History `IC-001` (`3c24d86ae0a5`) produced 14 remote queries and 21 evidence records; target `IC-003` (`99f570d82daa`) produced 16 remote queries and 33 evidence records. All citations resolved. One same-service historical match caused target queries `Q03` and `Q09`; memory membership stayed at two records. See [the live verification record and limits](docs/LIVE_VERIFICATION.md). Private receipts retain real data and provider outputs; they are not committed demo assets.

After importing the larger local dataset, `python3.12 -m scripts.verify_memory_flow` runs the label-blind real-data memory check. It runs cold/history/warm investigations and preserves passing or failed receipts under ignored `artifacts/private/`. Reports are under `artifacts/runs/`; agent/query JSONL traces are under `logs/`. Example outputs never act as canned API responses.

Docker packaging is provided, but **has not been built or run here** because the Docker daemon is unavailable:

```sh
docker build -t incidentcourt .
docker run --rm -p 127.0.0.1:8317:8317 incidentcourt
```

The container defaults to sample mode. Remote adapters require HTTPS. This is a local investigation tool with loopback Host checks, no general SQL API and no remediation actions.

## Event context

The [organizer event page](https://hackathon.genai.works/event/open-agent-hackathon-2026) and signed-in [resources](https://hackathon.genai.works/resources) were checked October 25, 2026. At that time the listed submission deadline was **October 27 at 23:45 UTC (4:45 p.m. Pacific)**, and the requirements included Zetaris, a working Meterless Engine feature, Nightshift as primary AI provider, a 1–4 minute real-running demo, slides and an explanation of sponsor use. Consult the organizer for current requirements and submission status.
