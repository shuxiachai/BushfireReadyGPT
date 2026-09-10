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
| `BUSHFIRE_RAG_CORPUS_SHA256` | Verified corpus `manifest_sha256`, printed by the preparation script |
| `BUSHFIRE_RAG_CORPUS_BUNDLE` | `/opt/bushfire/corpus`, used only when that corpus is absent from the volume |
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

First prepare a snapshot of the locally verified catalogue and raw files. This
does not download sources, change their licences or upload anything:

```console
poetry run python scripts/prepare_private_corpus.py --acknowledge-source-terms --output output/private-corpus
```

The script requires the local RAG index to pass full integrity validation. It
records catalogue/source hashes and the observed local file modification times;
those times are **not HTTP retrieval receipts**. Put the printed
`manifest_sha256` in `BUSHFIRE_RAG_CORPUS_SHA256` in `.env.cloud` or Railway.
An existing output directory is rejected, not overwritten.

The acknowledgement records the operator's private, non-commercial research
intent; it grants no copyright permission. Public availability does not mean a
source is copyright-free. Preserve the original catalogue licence fields and
check each source's terms, including third-party exceptions, before external
processing or sharing. The five non-open sources in the current catalogue
remain restricted or require permission/review. A password or private cloud
does not automatically resolve those restrictions. Do not publish original
source bytes, the private deployment archive or its image in a public registry.

For local Docker, mount that verified bundle read-only at `/opt/bushfire/corpus`
as well as the persistent `/data` volume. Replace `/absolute/path/private-corpus`
with its actual host path:

```console
docker build -t bushfire-ready:cloud .
docker volume create bushfire-ready-data
docker run --rm --env-file .env.cloud --mount source=bushfire-ready-data,target=/data --mount type=bind,source=/absolute/path/private-corpus,target=/opt/bushfire/corpus,readonly bushfire-ready:cloud --check-only
docker run --name bushfire-ready-cloud --env-file .env.cloud --mount source=bushfire-ready-data,target=/data --mount type=bind,source=/absolute/path/private-corpus,target=/opt/bushfire/corpus,readonly -p 127.0.0.1:8501:8501 bushfire-ready:cloud
```

Open [the local application](http://127.0.0.1:8501) once startup checks succeed.
The image defaults to user `bushfire` (UID/GID `10001`). If testing with a
root-owned bind mount, add `--user 0:0` to reproduce Railway's volume initialization;
the entrypoint changes only the runtime directory's ownership and drops groups,
GID and UID before loading the application. Setting `RAILWAY_RUN_UID` inside a
local Docker env file alone does not change Docker's selected user.

The build downloads the pinned CPU embedding assets, but never requests the
preparedness source websites. First startup validates the supplied private
bundle, builds its index offline on the volume, validates the result and
publishes the completed generation atomically. Subsequent startup validates and
reuses it. Runtime inference uses prepared model files under
`/opt/bushfire/models`; it does not require Ollama or a runtime model download.
The public repository/image contains only a corpus placeholder. Without an
imported generation or a valid private bundle it cannot start the cloud app.

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
   root as the build context. Explicitly select the Dockerfile builder and root
   [`Dockerfile`](../Dockerfile) in the service settings or through the Railway
   API. Leave the service start-command override empty so the image's
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
   Set sleeping/serverless to disabled and the restart policy to `ON_FAILURE`
   with a maximum of `3` retries in the service settings or API.
5. Let Railway supply `PORT`; the entrypoint listens on `0.0.0.0` at that port.
   Explicitly set the service healthcheck path to `/_stcore/health` and its
   startup timeout to `300` seconds in the service settings or API.
   [Railway healthcheck documentation](https://docs.railway.com/deployments/healthchecks)
6. Bootstrap the private corpus using the isolated CLI context described below.
   Inspect startup output for `container_ready: true`, and generate a
   domain under Settings > Networking > Public Networking. Railway provides
   HTTPS for that domain. Complete the acceptance checks below before inviting
   reviewers. [Railway public networking documentation](https://docs.railway.com/networking/public-networking)

### First private deployment

Commit the code intended for deployment before preparing the upload. The
context script reads only allowlisted **HEAD blobs**, not arbitrary working-tree
files. It adds only the verified corpus and writes an explicit deployment
manifest; `.env`, Git metadata, personal documents, local reports and untracked
files are not copied.

```console
poetry run python scripts/prepare_railway_context.py --corpus output/private-corpus --output output/railway-private-context
railway up output/railway-private-context --path-as-root --no-gitignore --project YOUR_PROJECT_ID --environment YOUR_ENVIRONMENT_ID --service YOUR_SERVICE_ID --detach
```

Use `--no-gitignore` **only with this inspected isolated context**, never with
the repository root. It is necessary because the private bundle is intentionally
Git-ignored. This upload goes to the selected private Railway project, not to
GitHub. Keep Railway project access restricted. The initial private build image
contains the original source bytes; do not export or publish it.

The Railway CLI volume-file commands require an active deployment, so they
cannot seed a never-started service. The private first image solves that
bootstrap dependency. Once the verified corpus/index is on `/data`, later
GitHub deployments can use the public placeholder image with the same expected
corpus hash. A changed corpus or CPU model requires an explicitly reviewed new
generation; the service never silently downloads or overwrites it. Keep a
protected backup of the bundle for disaster recovery.

For a smaller Railway build, set `BUSHFIRE_INCLUDE_NATIONAL_MAP=false` before
rebuilding. The Dockerfile declares this build argument. Resource requirements
and cold-start duration must be measured on the selected Railway plan.

These settings are managed directly on the Railway service. Legacy
`railway.toml`/`railway.json` Config as Code is deprecated: new services cannot
opt in, and existing legacy files stop being read on 2026-12-01. This project
does not claim an applied Infrastructure as Code definition. If adopting the
replacement later, import the actual linked environment with
`railway config pull`, retain `preserve()` for existing secret values, and
review `railway config plan` before applying any changes. Do not use
`--include-variables` when exporting a public configuration because it can
inline non-sealed secrets. [Railway IaC migration documentation](https://docs.railway.com/infrastructure-as-code)

## Persistence and restart behavior

| Location | Purpose |
| --- | --- |
| `/data/audit/` | Append-only governed-report audit records and lock sidecars |
| `/data/traces/` | Privacy-minimised runtime status, duration and count metrics |
| `/data/model-usage.sqlite3` | Shared daily model-call accounting |
| `/data/private-rag/<corpus_manifest_sha256>/sources.yml` | Original catalogue, including licence restrictions |
| `/data/private-rag/<corpus_manifest_sha256>/raw/` | Source bytes bound to the verified private bundle |
| `/data/private-rag/<corpus_manifest_sha256>/index/` | Validated document snapshot and embedded Qdrant index |
| `/data/` | Reports explicitly saved using the server-save action |

At startup, the private bundle is installed and indexed in a temporary directory
on the volume, validated, then published under its canonical bundle manifest
hash. Existing generations are preserved and reused; a corrupted existing
generation fails validation instead of being silently overwritten. Bundle
validation alone does not validate vectors: startup separately checks the full
index and CPU model binding. Model assets and bundled geographic datasets remain
in the image. The older baked-seed helper remains supported for explicit legacy
configurations, but the default Docker build no longer creates a web-fetched seed.

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

### 2026-09-10 deployment checks — missing access password, not live

Implementation commits through `ed0b80b` were pushed. Railway has a single
service, a 1 GB `/data` volume and a generated HTTPS domain, but the application
is **not running**. The original NSW HTTP 403 build blocker is removed: the
builder no longer requests those pages. Railway successfully built the complete
image including 2,473 national SA2 map rows. A private nine-source context was
uploaded for bootstrap; it was superseded by the subsequent GitHub CI-fix
deployment before initializing the volume. No access-control bypass was attempted.

The current startup blocker is an empty rendered `BUSHFIRE_ACCESS_PASSWORD`.
The service stops before starting Streamlit, as intended. The operator must
set a valid access password in the service Variables, then the verified private
bootstrap image must be deployed again. The raw bundle is not yet confirmed
installed on `/data`; a build/upload is not an active service.

A separate synthetic DeepSeek API connectivity request succeeded (18 total
tokens; configured `deepseek-v4-flash`, response model alias `deepseek-flash`).
This checks the credential and provider connection only; it is not a governed
report-generation or revision acceptance test. No reference documents were sent
by that connectivity request.

The operator subsequently requested retaining all nine local sources for the
private, non-commercial demonstration. A bounded private snapshot/import path
now replaces build-time source website requests; source licences are unchanged,
and the public CI uses original synthetic text instead of the official corpus.
The private deployment still requires the checks below; this implementation is
not a finding that all sources permit every cloud use.

Local private-import checks: `1145` non-E2E tests passed, `9` platform/link
permission skips, `87.56%` measured coverage. The nine-source bundle also passed
real offline CPU index construction and reuse without the image bundle; the
index manifest timestamp was unchanged. Ruff/format and Bandit checks passed.
The Windows CPU-default fixture now clears both model and semantic-threshold
values left by the launcher. The
[Linux Docker smoke workflow](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/34439156457)
and [Linux 3.11/3.13, Windows and Chromium regression workflow](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/34439156441)
passed on `ed0b80b`. The image smoke proves synthetic-corpus startup, actual
PID 1 UID/GID 10001 after a root-owned mount, offline retrieval, Chinese PDF text,
and quota/index persistence across a restart. It deliberately makes no model
API calls and does not substitute for private production-corpus evaluation.
That committed regression run passed `1154` non-E2E tests on each Linux and
Windows job (`3` skips), with `87.92%` Linux `src` coverage, plus one Chromium
E2E. Counts differ from the earlier local snapshot because the last three
container regressions and Linux-capable link tests were included.

Record the source commit, image digest, deployment date, model name, CPU model
identity and RAG manifest for this run. Do not replace historical release
artifacts with results from a different model or dirty worktree.

| Check | Current cloud status |
| --- | --- |
| Complete Linux image build and startup | CI passed with synthetic corpus; full Railway build passed, app blocked on password |
| `/data` ownership initialization followed by non-root execution | CI passed, including actual PID 1 UID/GID; live Railway still pending |
| CPU RAG retrieval evaluation and rejection cases | Local CPU diagnostics recorded separately; CI offline warmup passed |
| Real DeepSeek generation, revision and governed quality checks | Pending |
| PDF/DOCX/ZIP exports, including Chinese reviewer names | Chinese PDF CI passed; live multi-format acceptance pending |
| Two-browser session isolation and separate administrator access | Pending |
| Concurrent-call rejection and persisted daily allowance | Unit tests passed; CI persisted quota passed; live contention pending |
| Restart with saved audit/trace/quota and reused index generation | CI index/quota/sentinel passed; live audit/trace/restart pending |
| Railway HTTPS, deployment health and browser interaction | Pending |
| External user pilot | Not performed |

These entries are a verification record to complete, not a statement that this
deployment or a new release has already succeeded. See the existing
[evaluation guide](evaluation_and_observability.md) and [RAG design](rag.md) for
the distinctions between retrieval metrics, report governance and user evidence.
