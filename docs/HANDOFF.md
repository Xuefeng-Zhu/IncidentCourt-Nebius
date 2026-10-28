# IncidentCourt submission handoff

This checkout prepares IncidentCourt for the Nebius x NVIDIA Global AI Hackathon. The original [IncidentCourt repository](https://github.com/Xuefeng-Zhu/IncidentCourt) remains a separate project and retains its prior hackathon history. The submission checkout uses an offline sample or an explicitly enabled Nebius Token Factory model with sample telemetry; the former Nightshift integration is not part of its runtime.

## Current capabilities

- The browser workspace persists case histories and investigation status, with separate review notes. Reports retain evidence references, SQL query trails and uncertainty.
- The bundled sample restores a bounded set of anonymized RCAEval telemetry and runs deterministic investigation rules without network access. Existing local or Zetaris telemetry adapters can also be used with deterministic rules.
- The local Meterless H-MEM reference recalls eligible prior observations. Suggested services are rechecked against current telemetry; old findings are not current evidence. The reference uses deterministic hash embeddings and Node.js 24, not a hosted memory or embedding service.
- The optional Nebius sample path sends planner, critic and explanation requests to an explicitly configured NVIDIA model. It requires an API key and explicit inference opt-in. Provider calls are covered by simulated tests; no live Nebius investigation has been established.

See [the README](../README.md) for setup, [data provenance](DATA.md) for sampling and leakage boundaries, [integrations](INTEGRATIONS.md) for H-MEM and Nebius, and [verification](LIVE_VERIFICATION.md) for the distinction between earlier and current evidence.

## Evidence and delivery boundaries

The original project previously demonstrated Zetaris queries, H-MEM recall and hosted NVIDIA responses through a different provider. That historical proof does not establish Token Factory connectivity, Nebius model quality, account billing, or a current browser run. Original receipts are private and are not part of this checkout. Do not promote a simulated provider test to live evidence.

Before submission, verify a real Nebius-backed investigation after explicit usage authorization, provide judges a free way to exercise the qualifying workflow, and prepare a video and public source repository. Keep keys and private evidence out of the repository. Review the event's current requirements and the [submission draft](../devpost-submission.md) for unresolved fields.
