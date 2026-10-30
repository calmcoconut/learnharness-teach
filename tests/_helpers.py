"""Shared helpers for the test suite.

Standard library only. Every test module imports this first so that ``scripts``
is importable regardless of the current working directory.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _data  # noqa: E402  (path set up above)


def run_script(name, args, cwd=None, timeout=30):
    """Run ``scripts/<name>`` as a subprocess.

    Returns ``(returncode, stdout, stderr)``. The working directory is always an
    explicit argument so tests can prove CWD independence.
    """
    command = [sys.executable, "-B", str(SCRIPTS / name)] + [str(a) for a in args]
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_clean_env(),
    )
    return completed.returncode, completed.stdout, completed.stderr


def _clean_env():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    return env


class TempProject:
    """A throwaway project directory that can host a ``.learnharness`` record."""

    def __init__(self, prefix="lh-test-"):
        self._dir = tempfile.TemporaryDirectory(prefix=prefix)
        self.path = Path(self._dir.name).resolve()
        self.root = self.path / _data.DATA_DIRNAME

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._dir.cleanup()
        return False

    # -- record helpers ----------------------------------------------------

    def make_session(self, kind="teach", goal="understand entropy", session_id=None):
        """Create a session directory and a session_start event without a subprocess."""
        session_id = session_id or "lh_testsess"
        directory = self.root / "sessions" / session_id
        directory.mkdir(parents=True, exist_ok=True)
        events = [{"seq": 1, "at": _data.now_iso(), "type": "session_start", "kind": kind, "goal": goal}]
        write_jsonl(directory / "session.jsonl", events)
        return session_id

    def write_events(self, session_id, events):
        directory = self.root / "sessions" / session_id
        directory.mkdir(parents=True, exist_ok=True)
        write_jsonl(directory / "session.jsonl", events)

    def events(self, session_id):
        return read_jsonl(self.root / "sessions" / session_id / "session.jsonl")

    def nodes(self):
        return read_jsonl(self.root / "graph" / "nodes.jsonl")

    def chains(self):
        return read_jsonl(self.root / "graph" / "chains.jsonl")


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json_file(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent="\t") + "\n", encoding="utf-8")


def snapshot(directory):
    """Map every path under ``directory`` to ``(size, mtime_ns)``."""
    result = {}
    directory = Path(directory)
    if not directory.exists():
        return result
    for entry in sorted(directory.rglob("*")):
        stat = entry.stat()
        result[str(entry.relative_to(directory))] = (stat.st_size, stat.st_mtime_ns)
    return result
