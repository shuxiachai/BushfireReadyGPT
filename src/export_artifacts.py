"""Bound governed export bytes to their verified report and source clock."""

import hashlib
import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

EXPORT_ARTIFACT_POLICY = "governed-export-artifacts-v1"
_CACHE_ENTRY_KEY = "bound_report_artifacts"


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


def normalize_export_timestamp(value):
    """Use an explicit source timestamp; never infer a timezone or a new clock."""
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str) and value.strip():
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Export source timestamp must be an ISO datetime.") from None
    else:
        raise ValueError("Export source timestamp is required.")
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Export source timestamp must include its timezone.")
    return timestamp.astimezone(timezone.utc)


@dataclass(frozen=True)
class _ArtifactBundle:
    binding: tuple
    pdf: bytes
    docx: bytes
    pdf_sha256: str
    docx_sha256: str


def _verified_export_binding(report_text, audit_chain):
    from src.audit import AuditIntegrityError

    if not isinstance(report_text, str) or not report_text:
        raise AuditIntegrityError("An exact report is required for governed artifacts.")
    if not isinstance(audit_chain, (list, tuple)) or not audit_chain:
        raise AuditIntegrityError("Governed artifacts require the verified current audit chain.")
    try:
        root = audit_chain[0]["record"]
        latest = audit_chain[-1]["record"]
        report_hash = hashlib.sha256(report_text.encode("utf-8")).hexdigest()
        if (
            root["event_type"] != "report.created"
            or root["report_id"] != latest["report_id"]
            or root["report_version"] != latest["report_version"]
            or latest["report_content"]["sha256"] != report_hash
        ):
            raise AuditIntegrityError("Artifact report does not match the captured audit binding.")
        generated_at = normalize_export_timestamp(root["recorded_at"]).isoformat()
        for record in (root, latest):
            if not isinstance(record["audit_id"], str) or not record["audit_id"]:
                raise AuditIntegrityError("Artifact audit identity is missing.")
            digest = record["record_hash"]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise AuditIntegrityError("Artifact audit digest is invalid.")
        binding = (
            EXPORT_ARTIFACT_POLICY,
            report_hash,
            root["report_id"],
            root["report_version"],
            root["audit_id"],
            root["record_hash"],
            generated_at,
            latest["audit_id"],
            latest["record_hash"],
            latest["report_content"]["sha256"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AuditIntegrityError("Governed artifact context is incomplete or invalid.") from error
    return binding, generated_at


def _bundle_is_valid(entry, binding):
    return (
        isinstance(entry, _ArtifactBundle)
        and entry.binding == binding
        and isinstance(entry.pdf, bytes)
        and isinstance(entry.docx, bytes)
        and entry.pdf_sha256 == hashlib.sha256(entry.pdf).hexdigest()
        and entry.docx_sha256 == hashlib.sha256(entry.docx).hexdigest()
    )


def _artifacts_for_captured_chain(report_text, audit_chain, *, cache=None, pdf_builder=None, docx_builder=None):
    """Internal resolver for a chain already captured by the governed caller.

    The package calls this only after all its audit/analysis/review checks.
    Cache dictionaries are internal memoization, never an external byte-input API.
    """
    if pdf_builder is None:
        from src.pdf_export import create_report_pdf

        pdf_builder = create_report_pdf
    if docx_builder is None:
        from src.docx_export import create_report_docx

        docx_builder = create_report_docx
    if cache is not None and not isinstance(cache, dict):
        raise TypeError("Artifact cache must be a session-local dictionary.")
    binding, generated_at = _verified_export_binding(report_text, audit_chain)
    binding += (_renderer_identity(pdf_builder), _renderer_identity(docx_builder))
    cached = cache.get(_CACHE_ENTRY_KEY) if cache is not None else None
    if not _bundle_is_valid(cached, binding):
        pdf = pdf_builder(report_text, generated_at=generated_at)
        docx = docx_builder(report_text, generated_at=generated_at)
        if not isinstance(pdf, bytes) or not isinstance(docx, bytes):
            raise TypeError("Derived report builders must return bytes.")
        cached = _ArtifactBundle(binding, pdf, docx, hashlib.sha256(pdf).hexdigest(), hashlib.sha256(docx).hexdigest())
        if cache is not None:
            cache[_CACHE_ENTRY_KEY] = cached
    # Return a new container; consumers cannot mutate the frozen cached bundle.
    return {"pdf": cached.pdf, "docx": cached.docx}


def get_report_artifacts(report_text, *, audit_path, cache=None):
    """Resolve standalone artifacts only from a freshly verified current head."""
    from src.audit import AuditIntegrityError, capture_current_audit_chain

    if not audit_path:
        raise AuditIntegrityError("Governed downloads require a current audit path.")
    chain = capture_current_audit_chain(audit_path)
    return _artifacts_for_captured_chain(report_text, chain, cache=cache)
