"""阶段8架构边界：具体Telemetry适配器只能在应用装配层出现。"""

import ast
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
BUSINESS_DIRS = (
    APP_DIR / "api",
    APP_DIR / "modules",
    APP_DIR / "services",
)


def test_business_modules_do_not_import_concrete_telemetry_adapter() -> None:
    violations: list[str] = []
    for directory in BUSINESS_DIRS:
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "app.infrastructure.telemetry"
                ):
                    violations.append(str(path.relative_to(APP_DIR)))
                elif isinstance(node, ast.Import):
                    if any(
                        alias.name == "app.infrastructure.telemetry"
                        for alias in node.names
                    ):
                        violations.append(str(path.relative_to(APP_DIR)))

    assert violations == []


def test_telemetry_service_does_not_depend_on_fastapi_request() -> None:
    service_path = APP_DIR / "services" / "telemetry_service.py"
    tree = ast.parse(
        service_path.read_text(encoding="utf-8"),
        filename=str(service_path),
    )

    fastapi_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
            fastapi_imports.append(node.lineno)
        elif isinstance(node, ast.Import):
            if any(alias.name == "fastapi" for alias in node.names):
                fastapi_imports.append(node.lineno)

    assert fastapi_imports == []
