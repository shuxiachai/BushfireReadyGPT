# Legacy Cleanup Plan

## Current Status

BushfireReadyGPT now uses a streamlined application path:

- `src/wildfireChat.py` for the Streamlit UI.
- `src/agents/` for the Australia-focused deterministic multi-agent analysis pipeline.
- `src/assistants/profile/` plus `src/assistants/assistant.py` and `src/assistants/assistant_router.py` for the current Ollama-backed conversation layer.
- `data_australia/` for current Australian official source metadata, risk rules, ABS-derived community data and geography files.

The legacy OpenAI-style planning and analyst flow has been removed from the active router and archived.

## Archived Modules

The following directories have been moved to `legacy/archived_unused_modules/`:

| Archived path | Original path | Reason |
| --- | --- | --- |
| `legacy/archived_unused_modules/src_assistants_plan/` | `src/assistants/plan/` | Old planning assistant route; no longer used by the current Streamlit workflow. |
| `legacy/archived_unused_modules/src_assistants_analyst/` | `src/assistants/analyst/` | Old analyst assistant and literature-search tools; no longer loaded by the active router. |
| `legacy/archived_unused_modules/src_literature/` | `src/literature/` | Original literature indexing utilities; not used by the current report-generation flow. |
| `legacy/archived_unused_modules/data_literature/` | `data/literature/` | Original local literature index and embeddings; not used by the current report-generation flow. |

## What Remains Active

The active app still uses:

- `src/assistants/assistant.py`
- `src/assistants/assistant_router.py`
- `src/assistants/profile/`
- `src/agents/`
- `src/report_template.py`
- `src/coverage_map.py`
- `src/data_status.py`
- `src/data_register.py`
- `src/audit.py`
- `src/pdf_export.py`
- `src/docx_export.py`
- `data_australia/`
- `scripts/`

## Why The Archived Code Was Not Deleted

The archived modules may still be useful as local reference material if the project later adds a new `Research Evidence Agent`. The `legacy/` directory is ignored by Git, so it should not be treated as part of the current deliverable unless you deliberately decide to version it.

Before reusing them, the project should:

- Replace the old wildfire literature corpus with Australia-focused bushfire preparedness, disaster resilience and public health evidence.
- Review data and document licences.
- Add source metadata such as title, author, year, publication venue and URL.
- Clearly separate academic evidence from official emergency instructions.
- Ensure generated reports do not overstate research findings as operational advice.

## Future Decision

After the current MVP is stable, decide whether to:

1. Permanently delete these archived modules, or
2. Rebuild them as a new Australia-focused `Research Evidence Agent`.

Recommended path: keep the archive during the internship/project phase, then rebuild only the parts needed for a properly cited research-evidence module.
