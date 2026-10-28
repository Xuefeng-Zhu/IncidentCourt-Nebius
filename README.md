# IncidentCourt

IncidentCourt is a local workspace for investigating incidents across metrics, logs and distributed traces. It builds and challenges service hypotheses, then presents a timeline, supporting evidence, counterevidence, alternatives and uncertainty. It was originally built for the **Open Agent Hackathon** and is being adapted for the Nebius x NVIDIA Global AI Hackathon.

The bundled sample runs offline with deterministic rules and real, sampled [RCAEval](https://huggingface.co/datasets/phamquiluan/RCAEval) telemetry. A separate opt-in mode connects the same telemetry to an NVIDIA model on Nebius Token Factory. H-MEM recalls eligible prior observations locally. On October 27, 2026, a browser-started investigation using the sample telemetry completed with live NVIDIA Nemotron inference through Nebius Token Factory. See [verification](docs/LIVE_VERIFICATION.md) for the evidence and limits.

[Watch the demo](https://youtu.be/AXyv-4xRrsc) for a walkthrough of the investigation and its evidence. The app footage reviews a saved run.

## Run the offline sample

Requires **Python 3.12+** with SQLite and **Node.js 24+**. No pip or npm installation, credentials or network access are needed to run the sample. The bundled fixture contains measured telemetry from controlled experiments; it is not a set of generated incidents or replayed reports. The submission repository is currently private, so cloning requires authorized GitHub access; public release is pending approval.

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

`--sample` selects the offline sample and clears the Nebius sample switch. The sample SQLite database is restored from the committed fixture without network access. `--nebius-sample` uses the same sample telemetry but enables the separately configured hosted model path; `SAMPLE_MODE=true` alone does not distinguish the two when `INCIDENTCOURT_NEBIUS_SAMPLE=1` is also set. Offline and Nebius sample runs share the sample source identity and H-MEM store; their execution modes and provider receipts remain distinct.

## Nebius Token Factory with sample telemetry

The `--nebius-sample` mode combines the bundled RCAEval sample with NVIDIA model inference through Nebius Token Factory. It sends the planner, critic and explanation requests to the fixed Token Factory API, checks that the explicitly configured NVIDIA model is advertised, and rejects a different returned model. Evidence IDs are validated against the investigation. Model-generated explanations remain unreviewed. A provider error fails the investigation rather than silently switching to deterministic rules.

**Status:** on October 27, 2026, one browser-started sample investigation completed with three live Token Factory responses from `nvidia/nemotron-3-super-120b-a12b`. The report contained 21 evidence records and 14 queries; its checked evidence and query references resolved. This is a single integration run, not an accuracy or production claim. Its exact cost and final account billing were not verified. `--sample` remains entirely offline and does not use a model. A key and inference opt-in are required for the Nebius mode; merely configuring a key does not authorize inference. Token Factory requests may consume credits or incur charges, so check your account and pricing before enabling them.

Set `NEBIUS_API_KEY` securely in your environment or the ignored project-local `.env.local` file, without committing it or sharing its value. Restrict the local file to the owner (for example, `chmod 600 .env.local`). Set `NEBIUS_MODEL` to the exact NVIDIA open-source model ID advertised for your account (for example, `nvidia/nemotron-3-super-120b-a12b` **only if available to you**) and explicitly opt in to inference:

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
| [Integrations](docs/INTEGRATIONS.md) | H-MEM and Nebius configuration and verification |
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

Manually imported compatible JSON snapshots persist in the library, remain visibly unverified and unlinked, and cannot change case-queue status. The workspace does not automatically load private historical reports. Original reports remain immutable and exports retain their existing JSON format.

New case/history APIs are `/api/cases`, `/api/cases/{id}`, `/api/investigations`, and `/api/investigations/{id}`. POST starts an investigation with `incident_id` and `idempotency_key`; `/api/investigations/{id}/review` saves `note`, `reviewed`, and the current `version`. `/api/investigations/import` accepts a complete report up to 5 MiB. `/api/cases/refresh` and `/api/connections/check` refresh metadata without inference. The CLI and synchronous endpoints remain available for offline execution; hosted browser runs use the guarded workspace endpoint.

The background UI was exercised with offline sample SQL/rules, including navigation and reload during a gated QA run. A separate October 27 browser-started run exercised the live Nebius path with sample telemetry; see [verification](docs/LIVE_VERIFICATION.md) for the evidence and limits.

## Investigation behavior

1. **Planner** compares the first and last thirds of the observation window. Only metrics with enough non-null samples are compared; baseline-relative changes form hypotheses.
2. **H-MEM recall** searches earlier verified observations for up to three distinct observed services, using the unchanged upstream threshold. Current-incident and holdout memories are filtered before ranking. Retrieved context triggers fresh measurement and log queries.
3. **Evidence Critic** challenges metric-only explanations. **Investigator** compares span durations, parent/child dependencies and bounded later-window log excerpts. Resource and timing checks can revise the service ranking. Stable or decreasing metrics remain visible as counterevidence.
4. **Report** preserves query IDs, returned rows, coverage, observed threshold crossings, alternatives and limitations. Only measured development facts with saved evidence receipts enter memory; a guessed diagnosis is not promoted as a verified fact.

Local mode uses transparent deterministic heuristics. Nebius mode makes separate structured planner, critic and explanation requests. Its planner selects an observed service and its critic selects an actual follow-up query target. Unknown evidence IDs or malformed decisions fail explicitly. Generated prose has reference validation, not automated proof of every causal claim, and remains separately labeled for review. Failed provider calls do not silently become local successes.

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

## Integrations and provenance

The bundled Meterless H-MEM reference recalls eligible observations from earlier investigations and can suggest services for fresh queries. Historical memory is a lead, not evidence for the current incident. H-MEM runs locally through Node.js; its reference embedder is deterministic and is not a neural embedding service. See [integrations](docs/INTEGRATIONS.md) for provenance and verification limits.

The optional Nebius mode is described above. The Zetaris adapter and its historical data-path checks are documented in [Zetaris](docs/ZETARIS.md); those historical checks do not establish a live Nebius investigation.

## Verification

```sh
python3.12 -m unittest discover -s tests -v
python3.12 -m scripts.verify_memory_flow
npm ci --prefix vendor/meterless-hmem --ignore-scripts
npm test --prefix vendor/meterless-hmem
```

Tests cover offline restore, units/nulls, query boundaries, missing telemetry, hypothesis revision, H-MEM behavior/exclusion, provider contracts, citation rejection, redirects and HTTP validation. Synthetic test fixtures are labeled and separate from dataset runs. Upstream H-MEM smoke tests cover ten cases; no full conformance claim is made.

The current checkout’s live Nebius run and the original project’s separate historical verification are summarized in [live verification](docs/LIVE_VERIFICATION.md). The live run’s sanitized summary and provider receipts are private, ignored artifacts; raw receipts contain prompts and outputs and are not committed demo assets.

After importing the larger local dataset, `python3.12 -m scripts.verify_memory_flow` runs the label-blind real-data memory check. It runs cold/history/warm investigations and preserves passing or failed receipts under ignored `artifacts/private/`. Reports are under `artifacts/runs/`; agent/query JSONL traces are under `logs/`. Example outputs never act as canned API responses.

Docker packaging is provided, but **has not been built or run here** because the Docker daemon is unavailable:

```sh
docker build -t incidentcourt .
docker run --rm -p 127.0.0.1:8317:8317 incidentcourt
```

The container defaults to sample mode. Remote adapters require HTTPS. This is a local investigation tool with loopback Host checks, no general SQL API and no remediation actions.

## Event context

This checkout is being prepared for the [Nebius x NVIDIA Global AI Hackathon](https://nebiusglobalaihackathon.devpost.com/). Consult the event's current requirements and [submission draft](devpost-submission.md) before publication. A judge-accessible build and public demo video remain to be prepared.
