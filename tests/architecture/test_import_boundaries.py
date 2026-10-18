"""Static checks for dependency direction between engine packages."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ImportedName:
    module: str
    name: str | None
    path: Path
    line: int

    @property
    def target(self) -> str:
        return self.module if self.name is None else f"{self.module}.{self.name}"

    def describe(self) -> str:
        return f"{self.path.relative_to(ROOT)}:{self.line} imports {self.target}"


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def _imports(path: Path) -> tuple[ImportedName, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    importer = _module_name(path)
    package = (
        importer if path.name == "__init__.py" else importer.rpartition(".")[0]
    )
    found: list[ImportedName] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                ImportedName(alias.name, None, path, node.lineno)
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            found.extend(
                ImportedName(module, alias.name, path, node.lineno)
                for alias in node.names
            )
    return tuple(found)


def _python_files(package: str) -> tuple[Path, ...]:
    package_path = ROOT.joinpath(*package.split("."))
    module_path = package_path.with_suffix(".py")
    if package_path.is_file():
        return (package_path,)
    if module_path.is_file():
        return (module_path,)
    return tuple(sorted(package_path.rglob("*.py")))


def _violations(
    package: str,
    forbidden_prefixes: tuple[str, ...],
) -> list[ImportedName]:
    return [
        imported
        for path in _python_files(package)
        for imported in _imports(path)
        if any(
            imported.module == prefix
            or imported.module.startswith(f"{prefix}.")
            or imported.target == prefix
            or imported.target.startswith(f"{prefix}.")
            for prefix in forbidden_prefixes
        )
    ]


def _assert_no_violations(violations: list[ImportedName]) -> None:
    assert not violations, "forbidden dependencies:\n" + "\n".join(
        imported.describe() for imported in violations
    )


def test_world_is_independent_of_runtime_and_outer_layers() -> None:
    _assert_no_violations(
        _violations(
            "engine.world",
            (
                "engine.runtime",
                "engine.narrative",
                "engine.application",
                "engine.participation",
            ),
        )
    )


def test_narrative_is_independent_of_runtime_and_application() -> None:
    _assert_no_violations(
        _violations(
            "engine.narrative",
            ("engine.runtime", "engine.application"),
        )
    )


def test_runtime_does_not_depend_on_narrative_or_application() -> None:
    _assert_no_violations(
        _violations(
            "engine.runtime",
            ("engine.narrative", "engine.application"),
        )
    )


def test_participation_does_not_depend_on_runtime_or_adapters() -> None:
    _assert_no_violations(
        _violations(
            "engine.participation",
            ("engine.runtime", "engine.adapters"),
        )
    )


def test_contracts_are_independent_of_engine_implementations() -> None:
    _assert_no_violations(
        _violations(
            "engine.contracts",
            (
                "engine.world",
                "engine.runtime",
                "engine.narrative",
                "engine.application",
                "engine.participation",
                "engine.adapters",
                "engine.bootstrap",
            ),
        )
    )


def test_inner_and_application_layers_do_not_import_adapters() -> None:
    for package in (
        "engine.world",
        "engine.runtime",
        "engine.narrative",
        "engine.application",
    ):
        _assert_no_violations(_violations(package, ("engine.adapters",)))


def test_only_bootstrap_imports_concrete_adapters() -> None:
    offenders = [
        imported
        for path in _python_files("engine")
        if "adapters" not in path.parts and "bootstrap" not in path.parts
        for imported in _imports(path)
        if imported.module == "engine.adapters"
        or imported.module.startswith("engine.adapters.")
    ]
    _assert_no_violations(offenders)


def test_engine_modules_stay_within_size_budget() -> None:
    oversized = []
    for path in sorted((ROOT / "engine").rglob("*.py")):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > 500:
            oversized.append(f"{path.relative_to(ROOT)}: {line_count} lines")
    assert not oversized, "engine modules over 500 lines:\n" + "\n".join(oversized)


def test_removed_runtime_facade_is_not_reintroduced() -> None:
    removed = ROOT / "engine/runtime/simulation/runtime.py"
    assert not removed.exists()
    offenders = [
        imported.describe()
        for path in ROOT.rglob("*.py")
        if "tests" not in path.parts
        for imported in _imports(path)
        if imported.module == "engine.runtime.simulation.runtime"
    ]
    assert not offenders, "imports removed runtime facade:\n" + "\n".join(offenders)
