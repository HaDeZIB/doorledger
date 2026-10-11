#!/usr/bin/env python3
"""Vendor the DoorLedger core modules the CareAgent needs into the AgentCore app folder.

AgentCore CodeZip packages only ``app/CareAgent/``. The agent imports ``doorledger.agent`` and
``doorledger.aws.snapshot``; this copies exactly those modules and their dependencies (no
OpenCV / presence-code reader, no API, no watcher) into ``app/CareAgent/doorledger/``.

Run before ``agentcore dev`` / ``agentcore package`` / ``agentcore deploy``:

    python deploy/agentcore/sync_core.py
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "core" / "src" / "doorledger"
DST = HERE / "app" / "CareAgent" / "doorledger"
ROOTS = ["agent.py", "aws/snapshot.py"]
# Never vendor these, even if something imports them lazily.
DENY = {"api.py", "watcher.py", "vision.py", "presence.py", "presence_reader.py", "live.py",
        "aws/dynamo.py", "aws/agentcore.py"}


def _local_imports(path: Path) -> set[str]:
    """Relative ``from .x import y`` / ``from ..x import y`` targets of one module (top level)."""
    out: set[str] = set()
    tree = ast.parse(path.read_text())
    pkg = path.parent.relative_to(SRC)
    for node in tree.body:  # top-level only: lazy imports inside functions are optional
        if isinstance(node, ast.ImportFrom) and node.level:
            base = pkg
            for _ in range(node.level - 1):
                base = base.parent
            if node.module:
                target = base / (node.module.replace(".", "/") + ".py")
                out.add(str(target))
            else:
                for alias in node.names:
                    out.add(str(base / f"{alias.name}.py"))
    return {p for p in out if (SRC / p).is_file()}


def closure() -> list[str]:
    todo, seen = list(ROOTS), set()
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        if rel in DENY:
            raise SystemExit(f"{rel} is on the deny list but is imported by the agent closure")
        seen.add(rel)
        todo.extend(_local_imports(SRC / rel) - seen)
    return sorted(seen)


def main() -> None:
    files = closure()
    if DST.exists():
        shutil.rmtree(DST)
    for rel in files:
        target = DST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SRC / rel, target)
    (DST / "__init__.py").write_text(
        '"""Vendored subset of doorledger for the AgentCore CareAgent (read-only)."""\n')
    (DST / "aws" / "__init__.py").write_text('"""Vendored subset."""\n')
    print(f"vendored {len(files)} modules into {DST.relative_to(HERE.parents[1])}:")
    for rel in files:
        print("  ", rel)


if __name__ == "__main__":
    main()
