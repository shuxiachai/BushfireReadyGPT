# BushfireReadyGPT: local-first governed AI for Australian bushfire preparedness

[![Tests](https://github.com/shuxiachai/BushfireReadyGPT/actions/workflows/tests.yml/badge.svg)](https://github.com/shuxiachai/BushfireReadyGPT/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/shuxiachai/BushfireReadyGPT)](https://github.com/shuxiachai/BushfireReadyGPT/releases/latest)
[![License](https://img.shields.io/github/license/shuxiachai/BushfireReadyGPT)](LICENSE)

BushfireReadyGPT turns an Australian location, audience, scenario and planning focus into a structured **draft** bushfire-preparedness report. It is for learning, demonstrations and controlled stakeholder discussion: the application combines declared Australian context, traceable evidence and a required human review rather than acting as a generic emergency chatbot.

The standard installation is local-first: it uses [Ollama](https://ollama.com/) on the operator's machine, with no OpenAI API key required. A separate, password-protected Docker/Railway demonstration can use private DeepSeek narrative generation and a local CPU RAG index in its container; it is optional and has distinct deployment limits.

> **Safety boundary:** this is not a live incident, evacuation, route, fire-ban, safe-place or life-safety decision system. In an emergency, use official emergency services information and call `000` if life is at risk.

**中文简介：** 本项目是面向澳洲山火应急准备场景的本地优先报告生成原型。它把地点、受众、场景和规划重点组织为可审阅的准备报告草稿；仅适用于学习展示、作品集和受控讨论，不用于实时火情判断、撤离命令或生命安全决策。

This Australian adaptation is based on the Apache-2.0-licensed [project-araia/WildfireGPT](https://github.com/project-araia/WildfireGPT) / MARSHA project. The original United States material remains local legacy reference only. See [UPSTREAM.md](UPSTREAM.md) for attribution and modifications, and [LICENSE](LICENSE) for licence terms.

## See it

- [Watch the 89-second local demo](docs/assets/bushfire-ready-gpt-demo.webm).
- [Follow the live demonstration walkthrough](docs/demo_walkthrough.md).
- Open the [v0.6.0 governed Markdown sample](examples/v0.6.0/cairns-council-report.md), [PDF](examples/v0.6.0/cairns-council-report.pdf), [DOCX](examples/v0.6.0/cairns-council-report.docx), or [pilot package](examples/v0.6.0/cairns-council-pilot-package.zip).

| Create a draft | Inspect evidence and status |
| --- | --- |
| ![Create Report workflow](docs/assets/create-report.png) | ![Data and map status](docs/assets/data-map.png) |

| Review before export |
| --- |
| ![Generated report preview](docs/assets/report-preview.png) |

All examples are demonstration drafts, not emergency plans or operational instructions.

## Engineering in three points

1. **Eight deterministic components, not autonomous agents.** Profile, Australian data, official knowledge/RAG, vulnerability, risk, planning, report and quality functions are named Python component boundaries. Only narrative generation and bounded revision call the configured model. See the [architecture](docs/architecture.md).
2. **Evidence and review stay visible.** Outputs distinguish official references, processed data, rule inferences, model prose and unverified input; governed drafts carry quality checks, evidence tables, version/audit records and human-review sign-off. These controls support review; they do not prove factual accuracy or create legal approval.
3. **Local by default, explicit cloud boundary.** Ollama supports offline-friendly single-user demonstrations. The optional private DeepSeek/Railway path has its own access, persistence and quota constraints; see [deployment and acceptance status](docs/DEPLOYMENT.md).

## Current status and limits

The current tagged release is **v0.6.0**. Its release-specific, historical validation evidence belongs to clean-source commit [`44d0c3f`](https://github.com/shuxiachai/BushfireReadyGPT/commit/44d0c3f1f8c78af4291f79b090eb3fc53da95ea7), not to every later maintenance change. The release record and immutable benchmark artifacts are linked below.

Maintenance after v0.6.0 is documented separately. It includes ongoing hardening and controlled-demo acceptance work, but does **not** declare a newer release, complete production acceptance, or new historical benchmark results. Read the [September 15 content and delivery review](docs/LAUNCH_READINESS_2026-09-15.md) and [September 12 implementation record](docs/LAUNCH_READINESS_2026-09-12.md) before relying on current cloud claims.

This is a governed portfolio MVP / controlled-pilot prototype. It is not ready for operational emergency management, public life-safety decisions, government procurement or commercial deployment without independent legal, security, privacy, data/licence and domain review. There are no completed external pilot claims: [the pilot evidence register](docs/pilot_results.md) records the current status.

Important governance qualifications:

- Local audit records are application-level, tamper-evident evidence, not immutable government records. The local profile has no authenticated user identity, verified reviewer identity, digital signature, trusted timestamp, WORM retention or external transparency log.
- The optional shared cloud demo adds controls described in its deployment documentation, but it is not a multi-tenant production emergency service and still needs privacy, security, retention and licence review.
- Australian data is planning context only. It is not live incident status, fire danger ratings, evacuation information, safe routes or confirmed assembly points.

## Run locally

### Windows launcher

Install [Python 3.11-3.13](https://www.python.org/downloads/windows/) and [Ollama](https://ollama.com/download/windows), then from the project folder double-click:

```text
Start BushfireReadyGPT.bat
```

The launcher checks the local environment, reuses valid local dependencies/models/indexes where possible, prepares the dedicated report model, starts Ollama when needed and opens the app. It is the local Ollama path; it does not install Docker or cloud-only dependencies.

### Essential CLI path

From Windows PowerShell at the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install poetry==2.3.4
poetry install --with dev --no-root

ollama pull qwen2.5:7b
ollama pull embeddinggemma
ollama create bushfire-ready-qwen -f .\Modelfile

poetry run streamlit run src\wildfireChat.py
```

Local RAG is optional. To build it from its declared static official sources:

```powershell
poetry run python scripts\build_rag_index.py --download
```

For Docker/Railway, CPU embeddings, private-corpus handling and the controlled-demo limitations, follow [DEPLOYMENT.md](docs/DEPLOYMENT.md) rather than mixing those steps into the local launcher flow.

## Troubleshooting and verification

- **Launcher or model issue:** confirm Python and Ollama are installed, then rerun `Start BushfireReadyGPT.bat`. See [local setup and deployment troubleshooting](docs/DEPLOYMENT.md).
- **No local RAG results:** build the index with the command above; RAG remains optional, and the application must not turn missing retrieval into invented evidence. Read the [RAG design and trust boundary](docs/rag.md).
- **Data/map warning:** do not treat unavailable or unverified context as confirmed. Use the application's Evidence Trail and [data/architecture documentation](docs/architecture.md) to understand the boundary.
- **Test the working tree:**

  ```powershell
  poetry run pytest -m "not e2e" -q --cov=src --cov-report=term-missing --cov-fail-under=85
  powershell -ExecutionPolicy Bypass -File .\scripts\run_quality_checks.ps1
  ```

  The maintained CI coverage threshold is 85% for the non-E2E suite. A local result is evidence for that run only; GitHub Actions is authoritative for remote CI.

## Documentation and history

Start with the [documentation index](docs/README.md), [plain-language project overview](docs/project_overview.md), [architecture](docs/architecture.md), [RAG guide](docs/rag.md), and [demo walkthrough](docs/demo_walkthrough.md).

For governance, readiness and commercial positioning, use the [September 12 readiness record](docs/LAUNCH_READINESS_2026-09-12.md), [deployment status](docs/DEPLOYMENT.md), [commercial gap assessment](docs/commercial_gap_assessment.md), [commercial-readiness checklist](docs/commercial_readiness_checklist.md), and [pilot evidence register](docs/pilot_results.md).

Historical release scope, validation and limitations are retained in [v0.3.0](docs/releases/v0.3.0.md), [v0.4.0](docs/releases/v0.4.0.md), [v0.5.0](docs/releases/v0.5.0.md), and [v0.6.0](docs/releases/v0.6.0.md). The v0.6.0 [report-generation](docs/benchmarks/report-generation-v0.6.0.json), [red-team](docs/benchmarks/report-red-team-v0.6.0.json), and [RAG-retrieval](docs/benchmarks/rag-retrieval-v0.6.0.json) artifacts are historical release evidence, not a guarantee for maintained or cloud deployments.

Earlier samples remain available under [examples/](examples/); they are preserved for comparison and do not become current operational claims.
