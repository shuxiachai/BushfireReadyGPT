"""Explicit test-only f69 checkout; never validates or rewrites a closed campaign.

The real prepare/validate guards run against temporary reference files. Shared
helpers still import from the real checkout, so their actual origins and bytes
are checked separately. No production module or sys.modules entry is replaced.
"""

import ast
import copy
import importlib
import sys
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from scripts import scoped_basis_comparison as comparison
from tests.citation_criteria_fixtures import _shared_dependency_paths

REAL_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_NAMESPACE_BUILDERS = {"src/agents/report_agent.py", "src/report_basis.py"}
_SHARED_DEPENDENCY_ROOTS = {
    "src/agents/report_agent.py",
    "src/report_template.py",
    "src/report_basis.py",
    "src/model_evidence.py",
    "src/model_response.py",
    "src/rag/context.py",
    "src/agents/planner_agent.py",
}
_STABLE_TEMPLATE_DEFS = {"extract_narrative_body", "_remove_governance_notice", "_remove_section"}
_STABLE_TEMPLATE_VALUES = {"GOVERNANCE_NOTICE_MARKDOWN", "REPORT_NARRATIVE_WORD_BUDGET"}


@lru_cache(maxsize=1)
def fixed_git_sources():
    """Cache immutable raw Git blobs, independently of current-source admission."""
    assert comparison.PROJECT_ROOT.resolve() == REAL_PROJECT_ROOT.resolve()
    return MappingProxyType(
        {
            commit: MappingProxyType(comparison._git_sources(commit))
            for commit in (comparison.BASELINE, comparison.CANDIDATE)
        }
    )


def _template_dependencies(source):
    selected = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in _STABLE_TEMPLATE_DEFS:
            selected[node.name] = ast.dump(node, include_attributes=False)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in _STABLE_TEMPLATE_VALUES:
                    selected[target.id] = ast.literal_eval(node.value)
    assert set(selected) == _STABLE_TEMPLATE_DEFS | _STABLE_TEMPLATE_VALUES, "Stable template dependency set changed"
    return selected


def _normalise_source(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def verify_real_shared_helpers(candidate):
    # This is an initial-builder source-guard fixture, not a historical runtime.
    # Load the safe extraction chain, never credential-bearing configuration.
    # Only the pinned import closure executes in this fixture; unrelated modules
    # imported by other pytest files are not historical builder dependencies.
    for name in ("src.report_template", "src.model_evidence", "src.model_response", "src.rag.context"):
        importlib.import_module(name)
    for relative in _shared_dependency_paths(candidate, roots=_SHARED_DEPENDENCY_ROOTS):
        name = relative.removesuffix(".py").removesuffix("/__init__").replace("/", ".")
        module = sys.modules.get(name)
        actual = REAL_PROJECT_ROOT / relative
        assert actual.resolve().is_relative_to(REAL_PROJECT_ROOT.resolve()), f"Shared module outside checkout: {name}"
        if module is not None:
            assert Path(module.__file__).resolve() == actual.resolve(), f"Shared module origin changed: {name}"
        if relative == "src/report_template.py":
            # These exact definitions and values are the current-template
            # dependency of model_response/model_evidence narrative extraction.
            assert _template_dependencies(actual.read_text(encoding="utf-8")) == _template_dependencies(
                candidate[relative]
            ), "Stable template dependency changed"
            for function in _STABLE_TEMPLATE_DEFS:
                assert Path(getattr(module, function).__code__.co_filename).resolve() == actual.resolve()
        elif relative not in _NAMESPACE_BUILDERS:
            assert _normalise_source(actual.read_text(encoding="utf-8")) == _normalise_source(
                candidate[relative].decode("utf-8")
            ), f"Shared helper changed: {relative}"


@contextmanager
def historical_checkout(monkeypatch, tmp_path):
    references = fixed_git_sources()
    candidate = references[comparison.CANDIDATE]
    verify_real_shared_helpers(candidate)
    root = tmp_path / "reference-f69-checkout"
    for relative, content in candidate.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for relative in (comparison.SCRIPT_PATH, comparison.TEST_PATH):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((REAL_PROJECT_ROOT / relative).read_bytes())
    monkeypatch.setattr(comparison, "PROJECT_ROOT", root)
    monkeypatch.setattr(comparison, "_git_sources", lambda commit: copy.deepcopy(dict(references[commit])))
    yield comparison._source_snapshot()
    verify_real_shared_helpers(candidate)
