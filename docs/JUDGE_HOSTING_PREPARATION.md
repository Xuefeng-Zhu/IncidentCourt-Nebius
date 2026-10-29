# Judge gateway preparation

The judge gateway is a prepared application, not a deployed judge service. Its intended flow lets judges investigate the bundled RCAEval sample using Nebius Token Factory without receiving the provider key. Deployment, provider credential transfer, judge credential creation, and chargeable use each require action-time authorization. The independent offline sample remains available.

## Gateway behavior

`incidentcourt.judge_server` binds to loopback behind an HTTPS ingress, accepts only sample incident IDs, and pins `nvidia/nemotron-3-super-120b-a12b`. It disables imports, review notes, and connection checks; restricts host and origin; and uses private sessions with isolated temporary workspaces, H-MEM stores, and logs. Provider credentials and raw receipt contents are not returned to the browser. One process handles at most one active investigation at a time.

A durable SQLite ledger records every run reservation before dispatch, including unsuccessful or uncertain runs. The default bounded mode requires explicit lifetime and per-session limits. The operator may explicitly select `JUDGE_RUN_LIMIT_MODE=unlimited` with neither numeric limit set; this removes the fixed run-count cap while retaining the ledger. Neither mode prevents provider or hosting charges. Each investigation makes up to three completion calls with output limits of 600, 600, and 1,200 tokens; these are not a dollar ceiling.

Hosted provider receipts are retained separately on private durable storage. A synced `unknown` record is created before each provider request and atomically updated afterward; a timeout or interruption may leave an uncertain record even if the request never reached the provider. The configured API token is redacted, but receipts contain prompts and model outputs and must remain private. Unlimited mode has no fixed receipt-count limit or automatic deletion; individual records remain bounded. Monitor and manage storage capacity and retention. Missing, replaced, or full storage can fail requests closed; do not reset the ledger or retry an uncertain request to conceal a failure.

The gateway checks the correct access code before its shared failed-attempt bucket. That bucket is **not a per-client guessing limit**. Aggregate proxy throttling can itself deny service to judges. Generate the access code from 32 cryptographically secure random bytes; a format check cannot prove entropy. Before exposure, verify trusted ingress, per-client abuse controls, TLS and secure cookies, exact host/origin forwarding, and protection against direct-backend bypass. Do not trust unverified forwarded-IP headers. A private access code may affect the event's free, unrestricted judge-access requirement; confirm with the organizer.

Session data is removed after expiry when active runs finish, or on ordinary shutdown with no active run. A crash can leave temporary data; verify cleanup, storage isolation, and lifecycle behavior on the selected host. The API key and judge access code must be supplied privately, never in the repository or public logs.

## Operator configuration

Supply these values through an approved private environment or supported secret mechanism. Choose session and ingress settings appropriate to the actual deployment.

| Variable | Meaning |
| --- | --- |
| `SAMPLE_MODE` / `INCIDENTCOURT_NEBIUS_SAMPLE` | `true` / `1` for sample telemetry with Nebius inference. |
| `NEBIUS_MODEL` | `nvidia/nemotron-3-super-120b-a12b`. |
| `NEBIUS_ALLOW_INFERENCE` | `1` only after live-use authorization. |
| `NEBIUS_API_KEY` | Existing provider key, transferred only after authorization. |
| `JUDGE_ORIGIN` | Exact HTTPS browser origin, including any port; localhost HTTP is for testing only. |
| `JUDGE_ACCESS_CODE` | Private URL-safe unpadded encoding of 32 cryptographically secure random bytes. |
| `JUDGE_QUOTA_LEDGER` | Absolute path to the existing durable, access-restricted ledger. |
| `JUDGE_RECEIPT_DIR` | Absolute path to an existing private durable receipt directory outside HTTP/static routes. |
| `JUDGE_RUN_LIMIT_MODE` | Defaults to `bounded`; set `unlimited` explicitly for no fixed run-count limit. |
| `JUDGE_MAX_RUNS` / `JUDGE_MAX_RUNS_PER_SESSION` | Positive limits in bounded mode; omit both in unlimited mode. |
| `JUDGE_MAX_SESSIONS` / `JUDGE_SESSION_SECONDS` | Positive session concurrency and lifetime settings. |
| `JUDGE_LOGIN_ATTEMPTS` / `JUDGE_LOGIN_WINDOW_SECONDS` | Bound retention of failed-attempt timestamps, not authentication guesses. |

With systemd, `LoadCredential=` can supply both `judge_access_code` and `nebius_api_key`. If `CREDENTIALS_DIRECTORY` is present, both files are required; there is no fallback to environment secrets. Environment-based startup removes both secrets from its process environment before H-MEM subprocesses start, but does not protect them from the host, hosting provider, privileged users, or same-UID processes.

The one-time command `python -m incidentcourt.judge_server --init-ledger` uses exclusive creation and refuses to overwrite an existing ledger. Use it only on a verified new persistent volume as part of an authorized bootstrap. Normal service startup never initializes missing state. A missing, replaced, corrupt, or restored-old ledger requires inspection and reconciliation, not a fresh counter. Use one process and one writer; the in-process run lock is not distributed.

## Verification and remaining work

- The hosted-preparation suite, including the separate synthetic fixture, passed **145 tests**; the submission checkout suite passed **135 tests**. Tests use synthetic data and fake provider transports; local socket tests require loopback access.
- The judge image was built and run locally without credentials or network access. The bundled sample was readable as UID 10001, `nginx -t` passed, required missing volume/ledger/credential conditions failed startup, and a one-time bootstrap survived a container restart. A separate provider-free bootstrap image was also built and tested locally.
- A separate remote fixture used synthetic data and no provider credentials. A manually initiated stop/start preserved its ledger. This does not establish automatic idle sleep/wake or the behavior of a real judge deployment.
- Before any judge deployment, verify the real target volume identity and persistence, ownership and backup, trusted ingress and abuse controls, health checks, failure and restart behavior, secure receipt retention, and judge access. Obtain action-time approval for resource creation, credential transfer, deployment, and any paid provider or hosting use. Then test the authorized real judge workflow and reconcile provider and platform usage. No real judge app, judge credentials, or live model calls were deployed or executed as part of this hosting preparation.
