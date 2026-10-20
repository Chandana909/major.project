"""Every third-party package the code imports is declared in pyproject.toml, so that a fresh install runs
everything: the application, the datasets, the evaluation, the dashboard and the tests."""
from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ["auditiq", "auditiq_bench", "evaluation", "app", "scripts", "tests"]
# The import name of each package whose distribution is named differently.
DISTRIBUTION = {"dotenv": "python-dotenv", "faker": "faker", "pymupdf": "pymupdf", "fitz": "pymupdf",
                "sklearn": "scikit-learn", "yaml": "pyyaml"}


def declared() -> set[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = project["dependencies"] + [r for extra in project.get("optional-dependencies", {}).values()
                                               for r in extra]
    return {re.split(r"[<>=!~\[; ]", r, maxsplit=1)[0].strip().lower() for r in requirements}


def imported() -> dict[str, set[str]]:
    local = {p.name for p in ROOT.iterdir() if p.is_dir()} | {p.stem for p in (ROOT / "tests").glob("*.py")}
    found: dict[str, set[str]] = {}
    for folder in FOLDERS:
        for path in (ROOT / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    top = name.split(".")[0]
                    if top not in local and top not in sys.stdlib_module_names:
                        found.setdefault(top, set()).add(path.relative_to(ROOT).as_posix())
    return found


def test_every_imported_package_is_declared():
    have = declared()
    missing = {name: sorted(files) for name, files in imported().items()
               if DISTRIBUTION.get(name, name).lower() not in have}
    assert missing == {}, f"imported but not declared in pyproject.toml: {missing}"
