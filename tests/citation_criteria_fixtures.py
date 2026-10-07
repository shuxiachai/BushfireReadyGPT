"""Test-only source-guard filesystem, not a complete historical runtime.

Fixed builders execute their pinned source. Shared imports still execute from
the real checkout: their exact dependency bytes and loaded origins are checked
separately. No sys.path, sys.modules or production admission guard is replaced.
"""

import ast
import copy
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from scripts import citation_criteria_comparison as comparison

REAL_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ROOT_DEPENDENCIES = {
    "src/agents/report_agent.py",
    "src/report_template.py",
    "src/model_evidence.py",
    "src/rag/context.py",
    "src/agents/planner_agent.py",
}
_TEMPLATE_FUNCTIONS = {"extract_narrative_body", "_remove_governance_notice", "_remove_section"}
_TEMPLATE_VALUES = {"GOVERNANCE_NOTICE_MARKDOWN", "REPORT_NARRATIVE_WORD_BUDGET"}


@dataclass(frozen=True)
class SourceGuardFixture:
    """Temporary admission inputs with separately verified current shared code."""

    root: Path
    real_project_root: Path


def _shared_dependency_paths(candidate, *, roots=None):
    pending, seen = list(_ROOT_DEPENDENCIES if roots is None else roots), set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        assert path in candidate, f"Unbound fixed-builder dependency: {path}"
        for node in ast.walk(ast.parse(candidate[path])):
            modules = []
            if isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert not node.level, f"Unreviewed relative builder import in {path}"
                if node.module == "src":
                    modules = ["src." + item.name for item in node.names]
                elif node.module:
                    modules = [node.module]
            for module in modules:
                if not module.startswith("src."):
                    continue
                target = module.replace(".", "/") + ".py"
                if target not in candidate:
                    target = module.replace(".", "/") + "/__init__.py"
                assert target in candidate, f"Unbound shared import: {module}"
                pending.append(target)
    return seen


def _template_extraction_contract(source):
    selected = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in _TEMPLATE_FUNCTIONS:
            selected[node.name] = ast.dump(node, include_attributes=False)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in _TEMPLATE_VALUES:
                    selected[target.id] = ast.literal_eval(node.value)
    assert set(selected) == _TEMPLATE_FUNCTIONS | _TEMPLATE_VALUES
    return selected


def verify_actual_shared_dependencies(candidate):
    for relative in _shared_dependency_paths(candidate):
        path = REAL_PROJECT_ROOT / relative
        actual = path.read_bytes()
        if relative == "src/report_template.py":
            # Fixed prompt builders have their own pinned module namespace. The
            # current template is used only by shared narrative extraction.
            assert _template_extraction_contract(actual) == _template_extraction_contract(candidate[relative])
        else:
            assert comparison._normal(actual) == comparison._normal(candidate[relative]), relative
        module_name = relative.removesuffix(".py").removesuffix("/__init__").replace("/", ".")
        module = sys.modules.get(module_name)
        if module is not None:
            assert Path(module.__file__).resolve() == path.resolve(), f"Shared module origin changed: {module_name}"


@contextmanager
def historical_source_guard_checkout(monkeypatch, tmp_path, references):
    candidate = references[comparison.CANDIDATE]
    verify_actual_shared_dependencies(candidate)
    helper_blobs = {
        relative: comparison._git("show", f"{comparison.CANDIDATE}:{relative}") for relative in comparison.HELPER_FILES
    }
    # The production prepare function calls the real _build_arm helper.
    for relative, expected in helper_blobs.items():
        assert comparison._normal((REAL_PROJECT_ROOT / relative).read_bytes()) == comparison._normal(expected)
        module = sys.modules.get(relative.removesuffix(".py").replace("/", "."))
        if module is not None:
            assert Path(module.__file__).resolve() == (REAL_PROJECT_ROOT / relative).resolve()
    root = tmp_path / "citation-source-guard-reference"
    files = {
        **candidate,
        **helper_blobs,
        **{relative: (REAL_PROJECT_ROOT / relative).read_bytes() for relative in comparison.EXPERIMENT_FILES},
    }
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def fixed_git(*args, input_data=None):
        assert input_data is None and len(args) == 2 and args[0] == "show"
        prefix = comparison.CANDIDATE + ":"
        assert args[1].startswith(prefix)
        return helper_blobs[args[1][len(prefix) :]]

    monkeypatch.setattr(comparison, "PROJECT_ROOT", root)
    monkeypatch.setattr(comparison, "_git_sources", lambda commit: copy.deepcopy(references[commit]))
    monkeypatch.setattr(comparison, "_git", fixed_git)
    yield SourceGuardFixture(root=root, real_project_root=REAL_PROJECT_ROOT)
    verify_actual_shared_dependencies(candidate)
