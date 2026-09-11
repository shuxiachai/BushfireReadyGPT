# Docker and Railway deployment

This guide describes the unreleased cloud deployment work: a single Streamlit
instance, DeepSeek report generation, and local CPU embeddings with embedded
Qdrant and BM25 retrieval. It is a password-protected demonstration, with
browser sessions isolated in memory. Shared credentials do not establish
individual user identity, role-based access control or production multitenancy.

The existing `v0.6.0` release artifacts are historical local-model evidence.
They do not validate the new CPU embedding model, DeepSeek reports or Railway
deployment. The cloud acceptance record at the end of this document distinguishes
completed synthetic checks from remaining verification. No external user pilot has
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

Credential independence is checked across plaintext/hash configurations. Two
independently salted hashes cannot be compared for password equality at startup;
administrator sign-in therefore also rejects a candidate that matches the access
credential. Different stored hashes are not proof of different passwords.

### Windows with CPU embeddings

The default double-click path still uses Ollama. If deliberately configuring
`BUSHFIRE_RAG_EMBED_PROVIDER=fastembed` on Windows, install the optional CPU
dependencies explicitly:

```powershell
poetry install --with dev,cloud --no-root
```

Configure the pinned FastEmbed model/revision/cache settings from
`.env.cloud.example` for your local paths. If model assets have not been prepared,
temporarily set `BUSHFIRE_RAG_EMBED_LOCAL_FILES_ONLY=false` and run:

```powershell
poetry run python scripts/build_rag_index.py --prepare-embedding-only
```

This explicit step can download model assets. Restore
`BUSHFIRE_RAG_EMBED_LOCAL_FILES_ONLY=true` before normal startup. The launcher
checks the existing model files, `identity.json` and dependency versions without
loading the inference model or downloading anything. A failed CPU preflight stops
before any Ollama/model or RAG source downloads. Ollama is only needed if it is
also the selected report provider. A model identity change requires a controlled
index rebuild and retrieval reevaluation; do not overwrite a frozen release index.

### Private export delivery

Cloud mode and password-protected local mode use authenticated-session delivery
for Markdown, PDF, DOCX, ZIP, JSON and text/CSV exports. Before sending export
bytes, the server revalidates the current session. An inline `srcdoc` iframe
receives bounded, encoded bytes over that session; its button creates a
browser-local Blob download. Private exports are not registered with Streamlit's
unauthenticated `/media/` store. This requires Streamlit 1.62 or later.

Individual private downloads are limited to 8 MiB before Base64 encoding. The
default local mode without a password retains native Streamlit downloads.
Already-delivered bytes cannot be revoked by logout, expiry or password changes,
just as a previously displayed report cannot be recalled. This is not a signed
download-link service, individual identity system or role-based authorization.
Restart the existing service when deploying the fix to clear any old public
media registrations; do not distribute URLs created by the previous deployment.

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

### 2026-09-11 follow-up — synthetic lifecycle checked, file/restart checks incomplete

The [September 11 follow-up](AUDIT_FOLLOWUP_2026-09-11.md) records one real
DeepSeek generation and one wording revision on deployed `d847dbd`, a clearly
synthetic `Reviewed draft` sign-off with Chinese text, a 19/19 deterministic
quality check, parent lineage in the manifest, explicit server save, and a new
unauthenticated session restricted to the sign-in page. The corrected unknown
community indicators were visible in the generated report. This is not an
external user pilot, a full file-content/visual verification, or a test of the
subsequent maintenance deployment. The in-app browser did not return a completed
download; PDF/DOCX visual checks and saved audit/trace/quota readback after restart
remain incomplete. The dated records below are historical and are not rewritten
as evidence for this new run.

### 2026-09-10 deployment checks — controlled demo running

The password-protected [Railway demo](https://bushfire-ready-production.up.railway.app)
is running on a single service with a 1 GB `/data` volume. Deployment
`2c20b4c0-f527-4c87-9a88-e0eeab140118`, built from source `1570b7d`, reached
Railway `SUCCESS`; the public health endpoint returned HTTP 200 (`ok`).
The complete image includes 2,473 national SA2 map rows.

The earlier missing-password startup blocker is resolved. The operator set a
valid password and the verified private nine-source context was deployed again.
No access-control bypass or password-policy relaxation was used. The original
NSW HTTP 403 build blocker is also removed: builds no longer request the source
websites. An earlier private upload had been superseded before startup; the
successful deployment above is the one used for the browser checks below.

Deployment identity:

- Source: `1570b7d2137b7a630bb4f2781f57adb83de60a1d`.
- Image: `sha256:d72c398a2f216568d972340323e4d699bb680e139567fd3eb0eb2cecec058163`.
- Private corpus manifest: `c947360236f993d2984fafed0bb46b8e7020335ee4ef4bd65dc4375e8d23fcc2` (nine sources).
- Report model: `deepseek-v4-flash`; retrieval uses the fixed-revision, 384-dimensional
  BGE-small FastEmbed CPU profile described in [CPU RAG validation](CLOUD_RAG_VALIDATION.md).
- The browser evidence trail and independently verified export bind index
  `f1d4587e0a0f3648190febac62be8ef358961a27701ab2efb292c6b79b677c45`
  and retrieval method `dense_bm25_rrf_v1`.

A separate synthetic DeepSeek API connectivity request succeeded (18 total
tokens; configured `deepseek-v4-flash`, response model alias `deepseek-flash`).
This checks the credential and provider connection only; it is not a governed
report-generation or revision acceptance test. No reference documents were sent
by that connectivity request.

In an authenticated Chrome session, the application generated a **synthetic
technical acceptance** report for Cairns Council preparedness. The form used
`Synthetic deployment acceptance` as the organisation, not a real Council
request. The user-facing external-model acknowledgement was enabled before
generation; planning context and retrieved references were sent to DeepSeek.

- Version 1: `02e8913aacee4197a6a1444a0e7a7715`; four local RAG passages were
  retrieved and the governed quality gate passed.
- Version 2: `3509d4a7aa97405392412481702fcdab`; one request to clarify roles and
  communication responsibilities completed and the governed quality gate passed.
  The visible export manifest binds its parent lineage to version 1 above.
- Both versions remain `Draft - human review required`; no human approval or
  reviewer identity was supplied.
- A new tab in the same Chrome browser required sign-in while the original
  authenticated session retained its report. This is a new-session login check,
  **not** independent-browser, multi-tenant or administrator-access validation.
- The version 2 ZIP was retrieved locally from the current download request after
  a rerun; an earlier observed temporary media URL had expired. Its SHA256 is
  `90bfaa737b1fc37a97f8bcbe4a69e006dd3cf08b006f0eaca05791405bb94f5e`.
  `verify_sample_package` verified 12 entries, all 11 artifact hashes, readable
  Markdown/PDF/DOCX, the current quality-policy binding and the parent audit chain.
  The PDF has 14 pages and the DOCX has 136 paragraphs. Additional comparison with
  the included version 1 audit confirmed unchanged `inputs_hash`,
  `area_selection_hash`, `analysis` and `export_register_hashes`.
- All 14 PDF pages were visually inspected: page 13 contains only a two-line
  source note and is otherwise nearly empty. No clipping, overlapping text or
  broken tables was observed on the other pages. DOCX structure checks passed,
  but its visual render could not run because the bundled environment lacks
  LibreOffice; Word layout is not certified.
- The existing report was also saved through the application's **Save report on
  server** action, which reported success. Saving and downloading did not make
  another model request or change the report's content/approval. This does not
  establish that the saved file survives a deployment restart.

#### Original issues found during this acceptance

1. **Download authorization gap in the original deployment.** An HTTP request
   without the application login or cookies retrieved the current synthetic ZIP
   with status 200. Streamlit's media route does not apply the application's
   shared-password gate. The login page protects UI execution, not possession of
   a media URL. Do not publish these links or place sensitive reports in this
   demo. Private export delivery must require authorization; an opaque file ID
   is not access control. No third-party data was
   accessed or links enumerated during this check.
2. **The governed gate missed an incomplete narrative ending.** In the downloaded
   Markdown, section 15 ends mid-sentence with `pending current`, immediately
   before the deterministic Evidence Tables. The same ending appears in the
   PDF, so this is not a PDF or transfer truncation. That application version
   discarded the provider's `finish_reason`; the export cannot establish whether
   this particular response hit its token limit. Preserve this synthetic bad
   case, record completion status and reject/repair incomplete model responses.
   Passing the current 19/19 checks does not establish narrative completeness.
3. **PDF pagination needs refinement.** Avoid stranding a two-line source note
   on page 13 before the separate sign-off page. Keep this original downloaded
   package unchanged as evidence and retest a separately generated export after
   an exporter fix.

#### Follow-up fixes and local verification

The original ZIP, PDF and narrative remain unchanged as failure evidence. These
fixes do not retrospectively approve that report or change the historical
`governed-report-v6` policy fingerprint:

- **Private exports:** all application download entry points now use the shared
  delivery component described above. Seventy focused tests cover access expiry,
  password rotation, malformed configuration, forged sessions, content escaping,
  size limits and native local fallback. A real Chromium test uses two separate
  browser contexts, checks all six report/data formats byte for byte, and confirms
  anonymous requests to the corresponding synthetic media URLs return 404.
  No protected bytes are registered in the public media store.
- **New-response admission:** both streaming and non-streaming model responses
  require an explicit normal `stop`. Length truncation, filtering, tools, missing
  termination and inconsistent protocols cannot become a report. Length failures
  and obvious unfinished Safety Disclaimer prose can request a concise complete
  rewrite, sharing the existing maximum of three total attempts with structural
  repair; there is no token-budget increase or reuse of partial text. Trace
  records allowlisted completion reasons, not provider response text. This is an
  admission check for new generation/revision, not proof of semantic completeness
  or a rewrite of historical export policy.
- **PDF:** normal-sized Human Review Sign-off content stays together when space
  permits without an unconditional page break. Table titles stay with the header
  and first row, while long tables still paginate. A separate local Windows-font
  re-export of the original narrative has 14 pages, all visually reviewed, with
  all 311 source text units retained, the near-empty page removed, and the entire
  final sign-off together. Original incomplete prose was deliberately preserved.
  Font metrics can change page counts in Linux. DOCX visual review remains pending.

Local final regression: `1289` non-E2E tests passed with `9` platform/permission
skips and `87.84%` measured `src` coverage. Two Windows launcher tests passed
separately in a normal-permission run because the sandbox cannot reliably
inspect occupied ports. Both Chromium E2E tests passed: the existing report
workflow and the new private-download regression (`1293` passes in total across
these runs). Ruff/format, Bandit, Poetry lock/package checks and the dependency
vulnerability audit also passed. Historical release verification passed in
explicit dirty-tree diagnostic mode and subsequently passed again on the clean
committed tree, without a dirty override.

#### Verified follow-up deployment

Repair source `063968c9ee3165bbffd0dd8b2dc8fd1b38779ab9` was pushed to `main`.
Railway deployment `3c20b8f1-e11e-46a1-8e95-3e3437717935` reached `SUCCESS` on
2026-09-10, using image
`sha256:4bb81ed612e858b5954cfe47c1caf8dc48aad79004992f172aa4ec50fbbcd8f1`.
The health check returned HTTP 200 (`ok`), and an unauthenticated request to the
previously observed synthetic ZIP URL now returns 404. Startup recorded
`container_ready=true`, provider `deepseek`, model `deepseek-v4-flash`, RAG
`ready`, and the same corpus/index manifest identities recorded above. This
GitHub-source image does not include the official source bundle: startup reused
and verified the previously populated `/data` private corpus and index.

Both [cross-platform regression](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/34447658197)
and [Linux Docker smoke](https://github.com/shuxiachai/BushfireReadyGPT/actions/runs/34447658122)
passed for that source. Python 3.11, Python 3.13 and Windows each passed `1297`
non-E2E tests (`3` skips); Linux measured `88.19%` `src` coverage. The separate
Chromium job passed two E2E tests. Static checks, dependency auditing and clean
historical release verification also passed. These maintained-source numbers
do not replace the `v0.6.0` release measurements.

This verifies the running repair image, removal of the old media registration,
and live private-index reuse. It does not establish a new post-fix DeepSeek
report, authenticated live Blob-download acceptance, or persistence of every
saved report/audit/trace/quota record; those checks remain separate.

#### Subsequent whole-project audit

The [2026-09-10 project audit](PROJECT_AUDIT_2026-09-10.md) records later fixes
to review/download synchronization, cloud error redaction, credential
independence, revision evidence binding, map verification, missing indicators,
RAG chunk sizing, bounded lock reads and CPU startup preflight. The earlier
deployment and CI identifiers above certify their named source only, not this
later audit. Consult the audit record for its own validation and rollout status.
The frozen private RAG index is deliberately reused; corrected chunk sizing
requires a separately reviewed build and evaluation before replacing it.

Audit repair source `efe8c843a85b415ebabb4565cb040197a0ac0210` subsequently
deployed successfully as `d82e415d-76bd-4f4d-a99a-16e8f442e4b2` on 2026-09-10.
Its health endpoint returned 200 (`ok`) and startup confirmed the unchanged
private corpus/index identities. See the audit record for image identity and
source-specific regression results. This adds no post-audit real-model acceptance.

These checks establish real cloud generation and revision for one synthetic
scenario, not external-user outcomes, all-scenario regression or production
readiness. The follow-up deployment establishes private-index reuse only; do not
infer saved-report, audit, trace or quota recovery from a healthy web endpoint.

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

Keep the source commit, image digest, deployment date, model name, CPU model
identity and RAG manifest bound to each acceptance run. Do not replace historical release
artifacts with results from a different model or dirty worktree.

| Check | Current cloud status |
| --- | --- |
| Complete Linux image build and startup | CI passed with synthetic corpus; full private Railway deployment SUCCESS and application started |
| `/data` ownership initialization followed by non-root execution | CI passed, including actual PID 1 UID/GID; live Railway still pending |
| CPU RAG retrieval evaluation and rejection cases | Local CPU diagnostics recorded separately; CI offline warmup passed |
| Real DeepSeek generation, revision and governed quality checks | September 11 synthetic generation plus wording revision on d847dbd passed the 19/19 deterministic check; file/visual/restart boundaries are recorded in the follow-up above |
| PDF/DOCX/ZIP exports, including Chinese reviewer names | Original package integrity passed; local fixed PDF visually checked and exporter deployed; live fixed export, Word visual render and Chinese reviewer acceptance pending |
| Authorization on report download requests | Fix deployed; old public ZIP returns 404; authenticated delivery and anonymous denial pass separate-context browser CI; authenticated live export acceptance pending |
| Two-browser session isolation and separate administrator access | Separate-context private-download E2E passed locally; full live isolation and administrator checks pending |
| Concurrent-call rejection and persisted daily allowance | Unit tests passed; CI persisted quota passed; live contention pending |
| Restart with saved audit/trace/quota and reused index generation | September 11 authorized readback verified saved Markdown, three linked audit events and two Traces after deployment; original private index reused; live SQLite quota readback remains unverified |
| Railway HTTPS, deployment health and browser interaction | Passed for HTTPS, health 200, authenticated generation and revision |
| External user pilot | Not performed |

The controlled demo is deployed, but the remaining acceptance items are still
open and no new version has been released. See the existing
[evaluation guide](evaluation_and_observability.md) and [RAG design](rag.md) for
the distinctions between retrieval metrics, report governance and user evidence.

The [September 11 launch follow-up](LAUNCH_READINESS_2026-09-11.md) supersedes
earlier pending statements about the specific synthetic report/audit/Trace
readback. It also records context-budget warnings, private-download failure
feedback and stronger disposable-container restart checks. Server saving stores
Markdown, not a restorable browser/review workspace. Local re-exports are not
original cloud-downloaded files, and the Word visual check is still open.
