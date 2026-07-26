"""任务11.1：Agent与普通RAG的静态架构边界。"""

import ast
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
AGENT_ROOT = APP_ROOT / "modules" / "agent"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return imported


def test_agent_runtime_contracts_do_not_import_forbidden_infrastructure() -> None:
    forbidden_prefixes = (
        "sqlalchemy",
        "app.infrastructure",
        "app.modules.knowledge.repository",
        "app.modules.jobs.models",
        "chromadb",
        "dashscope",
        "redis",
        "subprocess",
    )
    offenders = {}
    protected_files = {
        "contracts.py",
        "policy.py",
        "registry.py",
        "state.py",
    }
    for path in AGENT_ROOT.glob("*.py"):
        if path.name not in protected_files:
            continue
        matches = sorted(
            module
            for module in imported_modules(path)
            if module.startswith(forbidden_prefixes)
        )
        if matches:
            offenders[path.name] = matches

    assert offenders == {}


def test_existing_rag_module_does_not_depend_on_agent() -> None:
    offenders = []
    for path in (APP_ROOT / "modules" / "rag").glob("*.py"):
        if any(
            module.startswith("app.modules.agent")
            for module in imported_modules(path)
        ):
            offenders.append(path.name)

    assert offenders == []


def test_agent_tools_only_depend_on_public_ports() -> None:
    forbidden_prefixes = (
        "sqlalchemy",
        "app.infrastructure",
        "app.modules.knowledge.models",
        "app.modules.knowledge.repository",
        "app.modules.knowledge.public_catalog",
        "chromadb",
        "dashscope",
        "redis",
        "subprocess",
    )
    offenders = {}
    for path in AGENT_ROOT.glob("*tools.py"):
        matches = sorted(
            module
            for module in imported_modules(path)
            if module.startswith(forbidden_prefixes)
        )
        if matches:
            offenders[path.name] = matches

    assert offenders == {}
