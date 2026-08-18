import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERIC_PATHS = (
    PROJECT_ROOT / "app" / "core",
    PROJECT_ROOT / "app" / "services",
    PROJECT_ROOT / "app" / "tools",
    PROJECT_ROOT / "app" / "api",
    PROJECT_ROOT / "app" / "agents",
)


def test_generic_framework_does_not_import_business_plugins() -> None:
    violations: list[str] = []
    for directory in GENERIC_PATHS:
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                if any(module.startswith("app.integrations.inspection") for module in modules):
                    violations.append(str(path.relative_to(PROJECT_ROOT)))

    assert violations == []
