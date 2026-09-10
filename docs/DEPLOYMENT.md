# Docker and Railway deployment

This guide describes the unreleased cloud deployment work: a single Streamlit
instance, DeepSeek report generation, and local CPU embeddings with embedded
Qdrant and BM25 retrieval. It is a password-protected demonstration, with
browser sessions isolated in memory. Shared credentials do not establish
individual user identity, role-based access control or production multitenancy.

The existing `v0.6.0` release artifacts are historical local-model evidence.
They do not validate the new CPU embedding model, DeepSeek reports or Railway
deployment. The cloud acceptance record at the end of this document remains
pending until those checks are actually performed. No external user pilot has
been completed.

The Windows double-click workflow is unchanged: use
[`Start BushfireReadyGPT.bat`](../Start%20BushfireReadyGPT.bat) and the existing
local `.env`. Keep cloud settings in a separate `.env.cloud` file or Railway
Variables so they do not replace the local Ollama configuration.

## Configuration

Use [`.env.cloud.example`](../.env.cloud.example) as the configuration template.
It deliberately contains empty credential values and cannot start an open
cloud application by accident. Configure a DeepSeek API key and a separate
application access password before starting the container.

| Variable | Value or requirement |
| --- | --- |
| `LLM_PROVIDER` | `deepseek` |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` |
| `DEEPSEEK_API_KEY` | Operator's API credential, supplied as a secret at runtime |
| `BUSHFIRE_ACCESS_PASSWORD` | 16-1024 characters with at least 8 distinct characters |
| `BUSHFIRE_ADMIN_PASSWORD` | Optional, different administrator credential |
| `BUSHFIRE_DEPLOYMENT_MODE` | `cloud` |
| `BUSHFIRE_RUNTIME_DIR` | `/data`, backed by a persistent volume |
| `RAILWAY_RUN_UID` | `0` on Railway; the entrypoint subsequently drops privileges |
| `BUSHFIRE_ALLOW_EXTERNAL_MODEL` | `true`, plus each session's separate acknowledgement |
| `BUSHFIRE_MODEL_MAX_CONCURRENT` | `1` |
| `BUSHFIRE_MODEL_DAILY_CALL_LIMIT` | `100`, shared across visitors and reset at 00:00 UTC |
| `BUSHFIRE_MODEL_MAX_RETRIES` | `0` to disable hidden SDK retries |

DeepSeek documents the HTTPS endpoint, API-key authentication and
`deepseek-v4-flash` model name in its [API quick start](https://api-docs.deepseek.com/).
The provider can update the model behind that name; record the evaluation date
and configuration when comparing cloud results.

The model key belongs to the operator. Visitors enter the demonstration access
password, not the model key, and share its model-call allowance. Every completion
attempt admitted by the application consumes one call, including structural
repairs and failed attempts. A report can require multiple calls. The daily
allowance is not a token limit or monetary spending cap; review provider billing
and Railway usage separately. A timeout retains its concurrency slot while the
underlying worker is still running.

For a stored password hash, generate it with a hidden local prompt:

```console
poetry run python -c "from getpass import getpass; from src.deployment_access import hash_access_password; print(hash_access_password(getpass('Access password: ')))"
```

Set the result as `BUSHFIRE_ACCESS_PASSWORD_HASH` and leave
`BUSHFIRE_ACCESS_PASSWORD` unset. The administrator equivalents follow the same
rule. Do not configure both plaintext and hash for the same credential. Give
administrators a different password and require their separate sign-in for
global diagnostics. Browser sign-in expires after eight hours and after a
process restart.

## Build and run Docker locally

Start Docker Desktop with its Linux container engine. Create an ignored
`.env.cloud` from the template and fill its two required secrets in a local
editor. Keep that file out of screenshots, logs and Git; the Docker build-context
allowlist also excludes environment files and workstation session data.

Run these commands from the repository root:

```console
docker build -t bushfire-ready:cloud .
docker volume create bushfire-ready-data
docker run --rm --env-file .env.cloud --mount source=bushfire-ready-data,target=/data bushfire-ready:cloud --check-only
docker run --name bushfire-ready-cloud --env-file .env.cloud --mount source=bushfire-ready-data,target=/data -p 127.0.0.1:8501:8501 bushfire-ready:cloud
```

Open [the local application](http://127.0.0.1:8501) once startup checks succeed.
The image defaults to user `bushfire` (UID/GID `10001`). If testing with a
root-owned bind mount, add `--user 0:0` to reproduce Railway's volume initialization;
the entrypoint changes only the runtime directory's ownership and drops groups,
GID and UID before loading the application. Setting `RAILWAY_RUN_UID` inside a
local Docker env file alone does not change Docker's selected user.

The build downloads the pinned CPU embedding assets and declared official
preparedness sources, then builds the index. These network downloads happen at
build time. Runtime inference uses prepared model files under
`/opt/bushfire/models`; it does not require local Ollama or a runtime model download.

The optional national map is included by default. A smaller build can omit it:

```console
docker build --build-arg BUSHFIRE_INCLUDE_NATIONAL_MAP=false -t bushfire-ready:cloud .
```

That build retains the bundled core datasets and their declared geographic
coverage; it does not claim nationwide interactive-map coverage. The flag is a
build argument, so changing a running container's environment does not add or
remove map assets.

## Configure Railway

1. Create a project and connect a service to this repository with the repository
   root as the build context. Railway supports the root
   [`Dockerfile`](../Dockerfile); [`railway.toml`](../railway.toml) selects that
   builder. Leave the service start-command override empty so the image's
   entrypoint runs. [Railway Dockerfile documentation](https://docs.railway.com/builds/dockerfiles)
2. Attach one persistent volume to this service at `/data`. Set
   `BUSHFIRE_RUNTIME_DIR=/data` and `RAILWAY_RUN_UID=0`. Railway mounts volumes as
   root and makes them available at service start, not during builds or
   pre-deploy commands. Initialization therefore belongs in the entrypoint.
   [Railway volume documentation](https://docs.railway.com/volumes)
3. Add the cloud template's non-secret settings in the service Variables tab.
   Add `DEEPSEEK_API_KEY` and the application password there, or store them in
   the project's Shared Variables and explicitly reference them from this
   service as `${{shared.DEEPSEEK_API_KEY}}` and
   `${{shared.BUSHFIRE_ACCESS_PASSWORD}}`. Keep actual values out of the
   repository and Docker build arguments. [Railway variable documentation](https://docs.railway.com/variables)
4. Keep one replica and one application process. The local Qdrant database and
   in-process concurrency gate are designed for this deployment. Do not scale
   replicas without replacing the embedded storage and shared admission design.
5. Let Railway supply `PORT`; the entrypoint listens on `0.0.0.0` at that port.
   Keep `/_stcore/health` and the 300-second startup timeout configured by
   `railway.toml`. [Railway healthcheck documentation](https://docs.railway.com/deployments/healthchecks)
6. Deploy, inspect startup output for `container_ready: true`, and generate a
   domain under Settings > Networking > Public Networking. Railway provides
   HTTPS for that domain. Complete the acceptance checks below before inviting
   reviewers. [Railway public networking documentation](https://docs.railway.com/networking/public-networking)

For a smaller Railway build, set `BUSHFIRE_INCLUDE_NATIONAL_MAP=false` before
rebuilding. The Dockerfile declares this build argument. Resource requirements
and cold-start duration must be measured on the selected Railway plan.

## Persistence and restart behavior

| Location | Purpose |
| --- | --- |
| `/data/audit/` | Append-only governed-report audit records and lock sidecars |
| `/data/traces/` | Privacy-minimised runtime status, duration and count metrics |
| `/data/model-usage.sqlite3` | Shared daily model-call accounting |
| `/data/rag/<manifest_sha256>/raw/` | Official-source bytes bound to that index generation |
| `/data/rag/<manifest_sha256>/index/` | Validated document snapshot and embedded Qdrant index |
| `/data/` | Reports explicitly saved using the server-save action |

At startup, a new image seed is copied into a temporary directory on the
volume, validated, then published under its manifest hash. Existing generations
are preserved and reused; a corrupted existing generation fails validation
instead of being silently overwritten. Build-time locks are excluded from the
copy. Model assets and bundled geographic datasets remain in the image.

Linux audit and RAG operations hold kernel `flock` guards across their critical
sections. The stable `.guard` files must remain in place; do not delete them
while the service is running. The kernel releases the held lock after a process
crash, allowing a new instance to recover its abandoned record even when the
container reuses PID 1. When migrating older PID-only lock records, stop the
old application before moving its data.

Keep `BUSHFIRE_SESSION_STATE_PATH` and `BUSHFIRE_INTERACTION_LOG_PATH` unset in
cloud mode. Browser conversations and current unsaved reports are in memory and
do not survive a restart. Audit persistence does not reconstruct a lost browser
session. Downloaded exports reside on the visitor's device; server-saved reports
remain on the mounted volume and need an operator retention policy. Back up the
volume before upgrades or cleanup, including the usage database so a restore
does not accidentally reset request accounting.

## Privacy and startup readiness

The local CPU embedding model receives the query inside the container. Report
generation sends the disclosed planning fields, relevant evidence and any
revision content to DeepSeek. `BUSHFIRE_ALLOW_EXTERNAL_MODEL=true` records the
operator's choice; each browser session must still acknowledge the external
model disclosure before generation. Use synthetic demonstration inputs and
follow the provider/account's retention terms. Audit and trace defaults minimise
stored content; explicit server saves contain the report itself.

The entrypoint checks cloud access settings, core-data integrity, volume
writability, the CPU model/index binding, and a complete retrieval warmup before
starting Streamlit. This catches missing or unusable RAG instead of allowing
silent cloud degradation. It does not prove that the DeepSeek credential has
available balance or that a real report will pass its quality gate.

After startup, `/_stcore/health` only confirms the web process responds. Railway
uses its configured healthcheck during deployment and does not keep polling it
after a deployment is active. Ongoing uptime/model monitoring requires a
separate monitor; no such monitoring is claimed by this setup.
[Railway healthcheck behavior](https://docs.railway.com/deployments/healthchecks)

## Cloud acceptance record

Record the source commit, image digest, deployment date, model name, CPU model
identity and RAG manifest for this run. Do not replace historical release
artifacts with results from a different model or dirty worktree.

| Check | Current cloud status |
| --- | --- |
| Complete Linux image build and startup | Pending |
| `/data` ownership initialization followed by non-root execution | Pending |
| CPU RAG retrieval evaluation and rejection cases | Pending |
| Real DeepSeek generation, revision and governed quality checks | Pending |
| PDF/DOCX/ZIP exports, including Chinese reviewer names | Pending |
| Two-browser session isolation and separate administrator access | Pending |
| Concurrent-call rejection and persisted daily allowance | Pending |
| Restart with saved audit/trace/quota and reused index generation | Pending |
| Railway HTTPS, deployment health and browser interaction | Pending |
| External user pilot | Not performed |

These entries are a verification record to complete, not a statement that this
deployment or a new release has already succeeded. See the existing
[evaluation guide](evaluation_and_observability.md) and [RAG design](rag.md) for
the distinctions between retrieval metrics, report governance and user evidence.
