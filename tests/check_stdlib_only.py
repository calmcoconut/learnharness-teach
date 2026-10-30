#!/usr/bin/env python3
"""Assert that every shipped script imports only the standard library.

Runs standalone so CI can call it without a test framework:

    python tests/check_stdlib_only.py

The skill's whole install story is "copy the folder and run python3", so a single
third-party import would silently break every user. This is the guard.
"""

import ast
import sys
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"

STDLIB = set(sys.stdlib_module_names)
ALLOWED_LOCAL = {"_data", "plan", "session", "graph", "graph_write", "verify"}


def top_level_imports(tree):
    """Yield every module name imported at any depth in the module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, resolves locally
                continue
            if node.module:
                yield node.module.split(".")[0]


def main():
    if not SCRIPTS.is_dir():
        sys.stderr.write("no scripts directory at %s\n" % SCRIPTS)
        return 1

    problems = []
    checked = 0

    for path in sorted(SCRIPTS.glob("*.py")):
        checked += 1
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        for module in sorted(set(top_level_imports(tree))):
            if module in ALLOWED_LOCAL:
                continue
            if module not in STDLIB:
                problems.append("%s imports non-stdlib module %r" % (path.name, module))

        if "sys.dont_write_bytecode = True" not in source:
            problems.append("%s does not set sys.dont_write_bytecode before importing" % path.name)

        # Guard against network use, which the compatibility claim forbids.
        for forbidden in ("socket", "urllib", "http", "ftplib", "smtplib", "telnetlib", "requests"):
            if forbidden in set(top_level_imports(tree)):
                problems.append("%s imports %r; the skill must not touch the network" % (path.name, forbidden))

    if checked == 0:
        problems.append("no scripts found; expected at least _data.py")

    for problem in problems:
        sys.stderr.write("FAIL %s\n" % problem)

    if problems:
        return 1

    print("ok: %d scripts, standard library only, bytecode disabled" % checked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
