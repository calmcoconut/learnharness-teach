"""Shared plumbing for learnharness-teach.

Standard library only. Imported by every script in this directory.

Conventions enforced here so the command scripts stay thin:

* every path is derived from a record root, never from the current directory
  of an individual script;
* JSONL files are append-only, one compact object per line, newline-terminated;
* the graph format stamp is read and refused centrally, never per script;
* ids are minted deterministically so a re-run of the same proposal is
  idempotent rather than duplicative.
"""

import sys

sys.dont_write_bytecode = True

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

DATA_DIRNAME = ".learnharness"
FORMAT_VERSION = 1
WRITER = "learnharness-teach/0.1"

SESSION_ID_RE = re.compile(r"^lh_[a-z0-9]{8}$")
NODE_ID_RE = re.compile(r"^n_[0-9a-f]{12}$")
CHAIN_ID_RE = re.compile(r"^arg_[0-9a-f]{12}$")

PHASES = ("probe", "plan", "teach", "practice", "closed")
KINDS = ("teach", "practice")

# Advisory only. Exceeding these warns; it never refuses.
WARN_STRANDS = 8
WARN_PLAN_NODES = 15
WARN_STEPS = 20


class Refusal(Exception):
    """A command declined to do something. Printed as ``Error: <message>``."""


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mint_node_id(statement):
    return "n_" + sha256_hex("node\x00" + statement.strip())[:12]


def mint_chain_id(premises, conclusion):
    key = "\x00".join(sorted(premises)) + "\x01" + conclusion
    return "arg_" + sha256_hex("chain\x00" + key)[:12]


def mint_session_id(existing=None):
    existing = existing or set()
    for _ in range(64):
        candidate = "lh_" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(8))
        if candidate not in existing:
            return candidate
    raise Refusal("could not mint a unique session id")


# --------------------------------------------------------------------------
# record root resolution
# --------------------------------------------------------------------------


def find_root(explicit=None, start=None):
    """Resolve the record root.

    ``explicit`` wins and is used as-is. Otherwise walk up from ``start``
    (default: cwd) looking for a ``.learnharness`` directory. If none exists,
    fall back to ``start/.learnharness`` so ``init`` can create it in place.

    The record root is the ``.learnharness`` directory itself, not its parent.
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    here = Path(start or os.getcwd()).resolve()
    for candidate in (here, *here.parents):
        probe = candidate / DATA_DIRNAME
        if probe.is_dir():
            return probe
    return here / DATA_DIRNAME


def sessions_dir(root):
    return Path(root) / "sessions"


def session_dir(root, session_id):
    validate_session_id(session_id)
    return sessions_dir(root) / session_id


def session_log(root, session_id):
    return session_dir(root, session_id) / "session.jsonl"


def session_markdown(root, session_id):
    return session_dir(root, session_id) / "session.md"


def graph_dir(root):
    return Path(root) / "graph"


def validate_session_id(session_id):
    if not SESSION_ID_RE.match(session_id or ""):
        raise Refusal("not a session id: %r (expected lh_ plus 8 lowercase characters)" % (session_id,))
    return session_id


def list_session_ids(root):
    directory = sessions_dir(root)
    if not directory.is_dir():
        return []
    return sorted(
        entry.name
        for entry in directory.iterdir()
        if entry.is_dir() and SESSION_ID_RE.match(entry.name)
    )


# --------------------------------------------------------------------------
# json / jsonl io
# --------------------------------------------------------------------------


def _reject_constant(name):
    raise ValueError("non-finite number in json: %s" % name)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return default
    return json.loads(text, parse_constant=_reject_constant)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent="\t") + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_jsonl(path):
    """Return ``(records, problems)``.

    Unparsable lines are reported rather than silently dropped, because the app
    drops them silently and we would rather know before exporting.
    """
    path = Path(path)
    records = []
    problems = []
    if not path.exists():
        return records, problems
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line, parse_constant=_reject_constant)
        except ValueError as exc:
            problems.append("%s:%d %s" % (path.name, number, exc))
            continue
        if not isinstance(value, dict):
            problems.append("%s:%d not a json object" % (path.name, number))
            continue
        records.append(value)
    return records, problems


def append_jsonl(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":"), sort_keys=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


# --------------------------------------------------------------------------
# graph format stamp
# --------------------------------------------------------------------------


def read_format(root):
    """Read the graph format stamp. An absent or unreadable stamp reads as v1."""
    path = graph_dir(root) / "format.json"
    try:
        value = read_json(path, default=None)
    except ValueError:
        return FORMAT_VERSION
    if not isinstance(value, dict):
        return FORMAT_VERSION
    version = value.get("version", FORMAT_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        return FORMAT_VERSION
    if version > FORMAT_VERSION:
        raise Refusal(
            "graph format %s is newer than this skill understands (%s); refusing to touch it"
            % (version, FORMAT_VERSION)
        )
    return version


def ensure_format(root):
    """Create the stamp if absent. Never rewrites an existing stamp."""
    path = graph_dir(root) / "format.json"
    if path.exists():
        read_format(root)
        return
    write_json(path, {"version": FORMAT_VERSION, "writer": WRITER})


# --------------------------------------------------------------------------
# session events
# --------------------------------------------------------------------------


def load_events(root, session_id):
    records, problems = read_jsonl(session_log(root, session_id))
    if problems:
        raise Refusal("session log is damaged: " + "; ".join(problems[:3]))
    return records


def append_event(root, session_id, event):
    events = load_events(root, session_id)
    event = dict(event)
    event["seq"] = (events[-1]["seq"] + 1) if events else 1
    event["at"] = now_iso()
    ordered = {"seq": event.pop("seq"), "at": event.pop("at")}
    ordered.update(event)
    append_jsonl(session_log(root, session_id), ordered)
    return ordered


def require_session(root, session_id):
    if not session_dir(root, session_id).is_dir():
        raise Refusal("no such session: %s" % session_id)
    return load_events(root, session_id)


# --------------------------------------------------------------------------
# output helpers
# --------------------------------------------------------------------------


def print_json(value):
    sys.stdout.write(json.dumps(value, indent="\t", sort_keys=False) + "\n")


def print_warnings(warnings, stream=None):
    stream = stream or sys.stderr
    for warning in warnings:
        stream.write("warning: %s\n" % warning)


def run(main):
    """Entrypoint wrapper: turn Refusal into a clean exit 1."""
    try:
        main()
    except Refusal as exc:
        sys.stderr.write("Error: %s\n" % exc)
        raise SystemExit(1)
    except BrokenPipeError:
        raise SystemExit(0)
