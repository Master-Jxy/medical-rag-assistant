"""阶段9跨模块调用边界的轻量静态回归。"""

import ast
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }


def test_auth_module_does_not_depend_on_knowledge_module() -> None:
    imported = set()
    for path in (APP_ROOT / "modules" / "auth").glob("*.py"):
        imported.update(imported_modules(path))
    assert not {
        module for module in imported if module.startswith("app.modules.knowledge")
    }


def test_review_service_uses_job_port_instead_of_job_model() -> None:
    imported = imported_modules(
        APP_ROOT / "modules" / "knowledge" / "review_service.py"
    )
    assert "app.modules.jobs.ports" in imported
    assert "app.modules.jobs.models" not in imported


def test_application_uses_python_310_compatible_str_enum_shim() -> None:
    offenders = []
    for path in APP_ROOT.rglob("*.py"):
        if path == APP_ROOT / "core" / "enums.py":
            continue
        if "from enum import StrEnum" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(APP_ROOT).as_posix())

    assert offenders == []
