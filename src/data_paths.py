import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_path(value, *, base):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _environment_path(name, default, *, base):
    configured = os.environ.get(name, "").strip()
    return _resolve_path(configured or default, base=base)


@dataclass(frozen=True)
class DataPaths:
    """Resolved paths for every local dataset used by the application.

    Use :meth:`from_env` at runtime so environment changes are observed without
    reloading modules. Relative configuration values are anchored to the project
    root instead of the process working directory.
    """

    project_root: Path
    data_dir: Path
    manifest: Path
    community_profile: Path
    community_sample: Path
    sa2_coverage: Path
    all_sa2_profile: Path
    all_sa2_boundary: Path
    all_sa2_boundary_by_state_dir: Path
    abs_raw: Path
    asgs_metadata: Path
    asgs_sa2_allocation: Path
    asgs_lga_summary: Path
    official_sources: Path
    risk_context_rules: Path
    region_mappings: Path
    licence_register: Path
    rag_dir: Path
    rag_sources: Path
    rag_raw_dir: Path
    rag_index_dir: Path

    @classmethod
    def from_env(cls, project_root=None):
        root = _resolve_path(project_root or PROJECT_ROOT, base=PROJECT_ROOT)
        data_dir = _environment_path(
            "BUSHFIRE_DATA_DIR",
            root / "data_australia",
            base=root,
        )

        def data_path(environment_name, relative_path):
            return _environment_path(
                environment_name,
                data_dir / relative_path,
                base=root,
            )

        rag_dir = data_path("BUSHFIRE_RAG_DIR", "rag")

        def rag_path(environment_name, relative_path):
            return _environment_path(
                environment_name,
                rag_dir / relative_path,
                base=root,
            )

        return cls(
            project_root=root,
            data_dir=data_dir,
            manifest=data_path(
                "BUSHFIRE_DATA_MANIFEST_PATH",
                "manifest.json",
            ),
            community_profile=data_path(
                "BUSHFIRE_COMMUNITY_PROFILE_PATH",
                "processed/community_profiles.csv",
            ),
            community_sample=data_path(
                "BUSHFIRE_COMMUNITY_SAMPLE_PATH",
                "community_profile_sample.csv",
            ),
            sa2_coverage=data_path(
                "BUSHFIRE_SA2_COVERAGE_PATH",
                "processed/sa2_coverage.geojson",
            ),
            all_sa2_profile=data_path(
                "BUSHFIRE_ALL_SA2_PROFILE_PATH",
                "processed/sa2_profiles_all.csv",
            ),
            all_sa2_boundary=data_path(
                "BUSHFIRE_ALL_SA2_BOUNDARY_PATH",
                "processed/sa2_boundaries_all.geojson",
            ),
            all_sa2_boundary_by_state_dir=data_path(
                "BUSHFIRE_ALL_SA2_BOUNDARY_BY_STATE_DIR",
                "processed/sa2_boundaries_by_state",
            ),
            abs_raw=data_path(
                "BUSHFIRE_ABS_RAW_PATH",
                "raw/abs_population_people_sa2_qld_subset.json",
            ),
            asgs_metadata=data_path(
                "BUSHFIRE_ASGS_METADATA_PATH",
                "processed/asgs_allocations/metadata.json",
            ),
            asgs_sa2_allocation=data_path(
                "BUSHFIRE_ASGS_SA2_ALLOCATION_PATH",
                "processed/asgs_allocations/sa2_to_sa3_sa4_state_2021.csv",
            ),
            asgs_lga_summary=data_path(
                "BUSHFIRE_ASGS_LGA_SUMMARY_PATH",
                "processed/asgs_allocations/lga_2025_summary.csv",
            ),
            official_sources=data_path(
                "BUSHFIRE_OFFICIAL_SOURCES_PATH",
                "official_sources.yml",
            ),
            risk_context_rules=data_path(
                "BUSHFIRE_RISK_CONTEXT_RULES_PATH",
                "risk_context_rules.yml",
            ),
            region_mappings=data_path(
                "BUSHFIRE_REGION_MAPPINGS_PATH",
                "region_mappings.yml",
            ),
            licence_register=data_path(
                "BUSHFIRE_LICENCE_REGISTER_PATH",
                "licence_register.yml",
            ),
            rag_dir=rag_dir,
            rag_sources=rag_path(
                "BUSHFIRE_RAG_SOURCES_PATH",
                "sources.yml",
            ),
            rag_raw_dir=rag_path(
                "BUSHFIRE_RAG_RAW_DIR",
                "raw",
            ),
            rag_index_dir=rag_path(
                "BUSHFIRE_RAG_INDEX_DIR",
                "index",
            ),
        )


def get_data_paths(project_root=None):
    """Resolve the current data configuration without import-time caching."""

    return DataPaths.from_env(project_root=project_root)


def safe_data_path_label(path, data_paths=None):
    """Describe a configured path without exposing an external absolute directory."""

    paths = data_paths or get_data_paths()
    resolved = Path(path).expanduser().resolve()
    try:
        relative = resolved.relative_to(paths.project_root.resolve())
    except ValueError:
        return f"<external-data>/{resolved.name}"
    label = relative.as_posix()
    return label or "."
