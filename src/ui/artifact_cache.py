"""Session-local cache for deterministic derived report files."""

import hashlib
import inspect
from pathlib import Path

import streamlit as st

_CACHE_STATE_KEY = "_derived_report_artifacts"


def _stable_identity_value(value):
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return repr(value).encode("utf-8")
    if isinstance(value, tuple):
        items = [_stable_identity_value(item) for item in value]
        if all(item is not None for item in items):
            return b"(" + b",".join(items) + b")"
    return None


class _RendererFingerprinter:
    def __init__(self, build):
        self.digest = hashlib.sha256()
        self.visited_callables = set()
        self.visited_sources = set()
        self.root_module = str(getattr(build, "__module__", ""))

    def _add_source(self, value):
        try:
            source_path = inspect.getsourcefile(value)
        except TypeError:
            source_path = None
        if not source_path:
            source_path = getattr(value, "__file__", None)
        if not source_path:
            return
        path = Path(source_path).resolve()
        if path in self.visited_sources:
            return
        self.visited_sources.add(path)
        self.digest.update(b"source:")
        self.digest.update(str(path).encode("utf-8"))
        try:
            self.digest.update(path.read_bytes())
        except OSError:
            self.digest.update(b"unreadable")

    def _is_project_dependency(self, value, owner_module):
        dependency_module = str(getattr(value, "__module__", ""))
        return (
            dependency_module == owner_module
            or dependency_module == self.root_module
            or dependency_module.startswith("src.")
        )

    def _add_simple(self, label, value):
        identity = _stable_identity_value(value)
        if identity is None:
            return
        self.digest.update(label.encode("utf-8"))
        self.digest.update(identity)

    def _visit_declared_dependencies(self, value):
        dependencies = getattr(value, "__artifact_cache_dependencies__", ()) or ()
        for dependency in dependencies:
            if callable(dependency):
                self._visit_callable(dependency)
            elif inspect.ismodule(dependency):
                self._add_source(dependency)
            else:
                self._add_simple("declared:", dependency)

    def _visit_global_dependencies(self, value, code, module_name):
        namespace = getattr(value, "__globals__", {})
        for name in sorted(set(code.co_names)):
            dependency = namespace.get(name)
            if callable(dependency) and self._is_project_dependency(dependency, module_name):
                self._visit_callable(dependency)
            elif inspect.ismodule(dependency) and str(getattr(dependency, "__name__", "")).startswith("src."):
                self._add_source(dependency)
            else:
                self._add_simple(f"global:{name}:", dependency)

    def _visit_closure_dependencies(self, value, code, module_name):
        closure = getattr(value, "__closure__", None) or ()
        for name, cell in zip(code.co_freevars, closure):
            try:
                dependency = cell.cell_contents
            except ValueError:
                continue
            if callable(dependency) and self._is_project_dependency(dependency, module_name):
                self._visit_callable(dependency)
            else:
                self._add_simple(f"closure:{name}:", dependency)

    def _visit_callable(self, value):
        object_id = id(value)
        if object_id in self.visited_callables:
            return
        self.visited_callables.add(object_id)

        module_name = str(getattr(value, "__module__", ""))
        self.digest.update(b"callable:")
        self.digest.update(module_name.encode("utf-8"))
        self.digest.update(str(getattr(value, "__qualname__", "")).encode("utf-8"))
        self._add_source(value)

        code = getattr(value, "__code__", None)
        if code is not None:
            self.digest.update(code.co_code)
            self.digest.update(repr(code.co_consts).encode("utf-8"))
            self.digest.update(repr(code.co_names).encode("utf-8"))
            self.digest.update(str(code.co_firstlineno).encode("ascii"))

        self._add_simple("version:", getattr(value, "__artifact_cache_version__", None))
        self._visit_declared_dependencies(value)

        if code is None:
            return
        self._visit_global_dependencies(value, code, module_name)
        self._visit_closure_dependencies(value, code, module_name)

    def fingerprint(self, build):
        self._visit_callable(build)
        return self.digest.hexdigest()


def _renderer_identity(build):
    """Fingerprint a renderer and reachable project-owned code dependencies.

    Reading a few small source modules is cheap compared with producing a PDF
    or DOCX and prevents a session cache from surviving a hot code update. The
    bounded callable walk also reaches imported helpers such as
    ``markdown_tables`` and ``export_content`` without traversing third-party
    libraries. Dynamically dispatched renderers can declare extra dependencies
    through ``__artifact_cache_dependencies__`` and an explicit
    ``__artifact_cache_version__`` attribute.
    """

    return _RendererFingerprinter(build).fingerprint(build)


def get_report_artifact(report_text, artifact_type, build, *, cache=None):
    """Build a derived artifact once per exact report text and session.

    The cache is deliberately kept in Streamlit session state rather than a
    process-wide decorator so private reports are not shared across users.
    """

    text = str(report_text or "")
    kind = str(artifact_type or "").strip().lower()
    if not text:
        raise ValueError("A report is required to build a derived artifact.")
    if not kind:
        raise ValueError("An artifact type is required.")
    if not callable(build):
        raise TypeError("build must be callable.")

    active_cache = cache if cache is not None else st.session_state.setdefault(_CACHE_STATE_KEY, {})
    if not isinstance(active_cache, dict):
        active_cache = {}
        if cache is None:
            st.session_state[_CACHE_STATE_KEY] = active_cache
    identity = hashlib.sha256(text.encode("utf-8")).hexdigest()
    renderer_identity = _renderer_identity(build)
    entry = active_cache.get(kind)
    if (
        isinstance(entry, dict)
        and entry.get("identity") == identity
        and entry.get("renderer_identity") == renderer_identity
        and isinstance(entry.get("content"), bytes)
    ):
        return entry["content"]

    content = build(text)
    if not isinstance(content, bytes):
        raise TypeError("Derived report builders must return bytes.")
    active_cache[kind] = {
        "identity": identity,
        "renderer_identity": renderer_identity,
        "content": content,
    }
    return content
