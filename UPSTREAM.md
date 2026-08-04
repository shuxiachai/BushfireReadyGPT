# Upstream Provenance

BushfireReadyGPT is an independently modified derivative of the open-source
[project-araia/WildfireGPT](https://github.com/project-araia/WildfireGPT) project,
also described upstream as MARSHA.

## Licence

The upstream repository is distributed under the Apache License 2.0. This
repository retains an Apache-2.0 `LICENSE` file. No government agency, emergency
service, data provider or upstream maintainer endorses this derivative project.

## Revision Boundary

The exact upstream commit used for the original local download was not recorded.
That provenance gap is disclosed here rather than assigning an unverified commit.
Before commercial redistribution, compare the retained legacy-derived files with
the upstream repository and record the confirmed upstream revision.

## Major Modifications

- Repositioned the application from United States wildfire analysis to Australian
  bushfire preparedness planning.
- Replaced the generic chatbot-first workflow with a structured Streamlit report
  workflow and governed report revisions.
- Added deterministic Australian profile, official-source, community,
  risk-context, planning, evidence-confidence and quality-check stages.
- Added local Ollama support, Australian ABS/ASGS-derived context, report exports,
  audit records and human-review controls.
- Removed inactive United States datasets and legacy analysis routes from the
  active product workflow.

Australian government and ABS/ASGS data licences are tracked separately in
`data_australia/licence_register.yml`; those entries remain subject to
source-specific legal review before commercial deployment.
