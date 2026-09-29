# Historical cloud deployment record

> Dated deployment and acceptance ledger as at 08f4254; this is not the current status ledger. It retains historical successes, failures and incomplete checks, including later September 27 records.

<a id="cloud-deployment-001"></a>
## Cloud acceptance record

<a id="cloud-deployment-002"></a>
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

<a id="cloud-deployment-003"></a>
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

<a id="cloud-deployment-004"></a>
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

<a id="cloud-deployment-005"></a>
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

<a id="cloud-deployment-006"></a>
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

<a id="cloud-deployment-007"></a>
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
| Real DeepSeek generation, revision and governed quality checks | September 27 on cab29ea: one synthetic generation, targeted wording revision and draft-only review record verified; governance checks are not semantic accuracy |
| PDF/DOCX/ZIP exports, including Chinese reviewer names | September 27: actual cloud package 14 files/13 hashes verified and all 13 PDF pages visually checked; standalone Markdown/DOCX match the package, PDF differs only in creation metadata for this sample; Word visual render and Chinese reviewer acceptance remain pending |
| Authorization on report download requests | Separate-context delivery/anonymous-denial browser CI remains historical evidence; September 27 authenticated live Markdown/PDF/DOCX/ZIP downloads verified; anonymous live denial and relogin were not retested in that run |
| Two-browser session isolation and separate administrator access | Separate-context private-download E2E passed locally; full live isolation and administrator checks pending |
| Concurrent-call rejection and persisted daily allowance | Unit tests and CI passed; September 12 real Railway historical-day allowance remained 2 across different deployments; live contention pending |
| Restart with saved audit/trace/quota and reused index generation | September 11 authorized readback verified saved Markdown, three linked audit events and two Traces; September 12 separately verified historical-day SQLite allowance 2→2 on the same volume; private index reused |
| Railway HTTPS, deployment health and browser interaction | Passed for HTTPS, health 200, authenticated generation and revision |
| External user pilot | Not performed |

The [September 15 and 27 delivery record](LAUNCH_READINESS_2026-09-15.md) binds
the latest synthetic flow to its actual deployment, downloads and audit lineage.
It distinguishes the inspected cloud PDF from the still-unrendered Word file.
The controlled demo is deployed, but the remaining acceptance items are still
open and no new version has been released. See the existing
[evaluation guide](../evaluation_and_observability.md) and [RAG design](../rag.md) for
the distinctions between retrieval metrics, report governance and user evidence.

The [September 11 launch follow-up](LAUNCH_READINESS_2026-09-11.md) supersedes
earlier pending statements about the specific synthetic report/audit/Trace
readback. It also records context-budget warnings, private-download failure
feedback and stronger disposable-container restart checks. Server saving stores
Markdown, not a restorable browser/review workspace. Local re-exports are not
original cloud-downloaded files, and the Word visual check is still open.

The [September 12 maintenance record](LAUNCH_READINESS_2026-09-12.md) covers
sentence-window retrieval, separate SDK-visible evidence diagnostics and bounded
read-only quota observations. `scripts/start_container.py --observe-usage-day
YYYY-MM-DD` optionally logs one explicit historical UTC date in addition to the
current date, allowing an honest cross-midnight restart comparison without
changing counters. It is not a restore command or a public monitoring endpoint.

That historical-day check has now passed on two distinct Railway deployments;
the linked record binds deployment IDs, timestamps, the observed day and volume.
It does not replace authenticated full-download or Word visual acceptance.
After observation, restore `python scripts/start_container.py` and trigger a
fresh deployment from the latest commit. Railway's deployment-level
[Redeploy action](https://docs.railway.com/deployments/deployment-actions) reuses
the selected deployment's code and configuration; do not infer that a changed
service setting took effect just because such a redeploy is healthy. Confirm the
new deployment's startup logs no longer contain the extra historical-day probe.
