"""Safe loading and reference resolution for authored package sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.world.package_spec import PackageDiagnostic

MAX_DOCUMENT_BYTES = 256 * 1024
MAX_DOCUMENT_DEPTH = 24
MAX_STRING_LENGTH = 8_192

def _read_object(path: Path, root: Path, diagnostics: list[PackageDiagnostic]) -> dict[str, Any]:
    value = _read_json(path, root, diagnostics)
    if value is None:
        return {}
    if not isinstance(value, dict):
        diagnostics.append(PackageDiagnostic("INVALID_DOCUMENT", _display(path, root), "document must be an object"))
        return {}
    return value


def _read_array(path: Path, root: Path, diagnostics: list[PackageDiagnostic]) -> list[dict[str, Any]]:
    value = _read_json(path, root, diagnostics)
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        diagnostics.append(PackageDiagnostic("INVALID_DOCUMENT", _display(path, root), "document must be an array of objects"))
        return []
    return value


def _read_json(path: Path, root: Path, diagnostics: list[PackageDiagnostic]) -> Any:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        diagnostics.append(
            PackageDiagnostic(
                "UNSAFE_PACKAGE_PATH",
                _display(path, root),
                "package files and symlink targets must stay inside the package",
            )
        )
        return None
    if not path.is_file():
        diagnostics.append(PackageDiagnostic("MISSING_FILE", _display(path, root), "required package file is missing"))
        return None
    try:
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            diagnostics.append(
                PackageDiagnostic(
                    "DOCUMENT_TOO_LARGE",
                    _display(path, root),
                    f"document exceeds {MAX_DOCUMENT_BYTES} bytes",
                )
            )
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        _validate_value_limits(value, _display(path, root), diagnostics)
        return value
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        diagnostics.append(PackageDiagnostic("INVALID_JSON_YAML", _display(path, root), str(exc)))
        return None


def _safe_ref(root: Path, ref: str, diagnostics: list[PackageDiagnostic], path: str) -> Path | None:
    boundary = "asset" if path.startswith("manifest.yaml.assets.") else "workflow"
    code = "UNSAFE_ASSET_REF" if boundary == "asset" else "UNSAFE_WORKFLOW_REF"
    if not isinstance(ref, str) or not ref or "\0" in ref:
        diagnostics.append(PackageDiagnostic(code, path, f"{boundary} ref is invalid"))
        return None
    candidate = (root / ref).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        diagnostics.append(PackageDiagnostic(code, path, f"{boundary} ref must stay inside the package"))
        return None
    return candidate


def _display(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _validate_value_limits(
    value: Any,
    path: str,
    diagnostics: list[PackageDiagnostic],
) -> None:
    stack = [(value, path, 0)]
    while stack:
        current, current_path, depth = stack.pop()
        if depth > MAX_DOCUMENT_DEPTH:
            diagnostics.append(
                PackageDiagnostic(
                    "DOCUMENT_TOO_DEEP",
                    current_path,
                    f"document depth exceeds {MAX_DOCUMENT_DEPTH}",
                )
            )
            return
        if isinstance(current, str) and len(current) > MAX_STRING_LENGTH:
            diagnostics.append(
                PackageDiagnostic(
                    "TEXT_TOO_LONG",
                    current_path,
                    f"text exceeds {MAX_STRING_LENGTH} characters",
                )
            )
        elif isinstance(current, dict):
            stack.extend(
                (child, f"{current_path}.{key}", depth + 1)
                for key, child in current.items()
            )
        elif isinstance(current, list):
            stack.extend(
                (child, f"{current_path}[{index}]", depth + 1)
                for index, child in enumerate(current)
            )

