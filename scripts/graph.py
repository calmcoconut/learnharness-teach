"""Read, query and export the knowledge graph.

The ledgers are append-only JSONL files under ``graph/``.  This module is the
read side: it applies the app's merge law (later lines with an existing node id
are link-appends; chain lines merge by sorted premises and conclusion), then
renders or filters the merged view.  ``export`` copies the two ledger files into
an existing app data directory and stamps format version 1, after refusing to
overwrite a newer format stamp or a non-empty destination ledger.
"""

import sys

sys.dont_write_bytecode = True

import argparse
import json
import os
import re
import shutil
from pathlib import Path

import _data


# ---------------------------------------------------------------------------
# ledger reading and validation
# ---------------------------------------------------------------------------


def _reject_constant(name):
    raise ValueError("non-finite number in json: %s" % name)


def _is_provenance_point(value):
    return (
        isinstance(value, dict)
        and isinstance(value.get("chatId"), str)
        and isinstance(value.get("messageId"), str)
    )


def _is_string_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def valid_node_line(value):
    """The app's graph-node guard, plus the fields this reader relies on."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and isinstance(value.get("name"), str)
        and isinstance(value.get("statement"), str)
        and _is_string_list(value.get("aliases"))
        and isinstance(value.get("createdAt"), str)
        and isinstance(value.get("provenance"), list)
        and all(_is_provenance_point(point) for point in value.get("provenance", []))
    )


def valid_chain_line(value):
    """The app's graph-chain guard, plus the fields this reader relies on."""
    premises = value.get("premises") if isinstance(value, dict) else None
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and isinstance(premises, list)
        and len(premises) > 0
        and all(isinstance(premise, str) for premise in premises)
        and isinstance(value.get("conclusion"), str)
        and isinstance(value.get("provenance"), list)
        and all(_is_provenance_point(point) for point in value.get("provenance", []))
        and isinstance(value.get("createdAt"), str)
    )


def _read_ledger(path, validator):
    """Return ``(records, warnings)``.  Bad lines are skipped, never fatal."""
    path = Path(path)
    records = []
    warnings = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return records, warnings
    except (OSError, UnicodeError) as exc:
        warnings.append("%s: unreadable (%s); skipped" % (path.name, exc))
        return records, warnings

    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line, parse_constant=_reject_constant)
        except ValueError as exc:
            warnings.append("%s:%d malformed JSON; skipped (%s)" % (path.name, number, exc))
            continue
        if not validator(value):
            warnings.append("%s:%d invalid record shape; skipped" % (path.name, number))
            continue
        records.append(value)
    return records, warnings


def _same_point(left, right):
    return left.get("chatId") == right.get("chatId") and left.get("messageId") == right.get("messageId")


def merge_node_lines(lines):
    """Apply the app's node merge law.

    The first line for an id defines ``name``, ``statement`` and ``createdAt``.
    Later lines union their statement and aliases into ``aliases`` and union
    provenance.  Extra fields from the first line survive.
    """
    merged = []
    by_id = {}
    for line in lines:
        node_id = line["id"]
        existing = by_id.get(node_id)
        if existing is None:
            node = dict(line)
            node["aliases"] = list(line["aliases"])
            node["provenance"] = [dict(point) for point in line["provenance"]]
            by_id[node_id] = node
            merged.append(node)
            continue

        for phrasing in [line["statement"], *line["aliases"]]:
            if phrasing and phrasing not in existing["aliases"]:
                existing["aliases"].append(phrasing)
        for point in line["provenance"]:
            if not any(_same_point(current, point) for current in existing["provenance"]):
                existing["provenance"].append(dict(point))
    return merged


def chain_key(premises, conclusion):
    """The identity a chain assertion merges under: sorted premises + conclusion."""
    return (tuple(sorted(premises)), conclusion)


def merge_chain_lines(lines):
    """Apply the app's chain merge law; the first line wins for identity/order."""
    merged = []
    by_key = {}
    for line in lines:
        key = chain_key(line["premises"], line["conclusion"])
        existing = by_key.get(key)
        if existing is None:
            chain = dict(line)
            chain["premises"] = list(line["premises"])
            chain["provenance"] = [dict(point) for point in line["provenance"]]
            by_key[key] = chain
            merged.append(chain)
            continue
        for point in line["provenance"]:
            if not any(_same_point(current, point) for current in existing["provenance"]):
                existing["provenance"].append(dict(point))
    return merged


def _session_recency(node_lines):
    """Remember the last ledger position where each provenance session appeared."""
    recency = {}
    for line_index, line in enumerate(node_lines):
        for point_index, point in enumerate(line["provenance"]):
            recency[point["chatId"]] = (line_index, point_index)
    return recency


def load_graph_details(root):
    """Read and merge the graph plus session recency metadata.

    A newer format stamp raises ``_data.Refusal`` before any ledger is read.
    """
    _data.read_format(root)
    node_lines, node_warnings = _read_ledger(_data.graph_dir(root) / "nodes.jsonl", valid_node_line)
    chain_lines, chain_warnings = _read_ledger(_data.graph_dir(root) / "chains.jsonl", valid_chain_line)
    return (
        merge_node_lines(node_lines),
        merge_chain_lines(chain_lines),
        node_warnings + chain_warnings,
        _session_recency(node_lines),
    )


def load_graph(root):
    """Read and merge the graph.  Returns ``(nodes, chains, warnings)``."""
    nodes, chains, warnings, _recency = load_graph_details(root)
    return nodes, chains, warnings


# ---------------------------------------------------------------------------
# query helpers
# ---------------------------------------------------------------------------


def session_index(nodes, recency=None):
    """Group provenance chat ids with node counts, newest node first."""
    recency = recency or {}
    counts = {}
    newest = {}
    latest_message = {}
    for node in nodes:
        created = node.get("createdAt", "")
        chats = {point["chatId"] for point in node["provenance"]}
        for chat_id in chats:
            counts[chat_id] = counts.get(chat_id, 0) + 1
            if created > newest.get(chat_id, ""):
                newest[chat_id] = created
        for point in node["provenance"]:
            chat_id = point["chatId"]
            message_id = point.get("messageId", "")
            if message_id.isdigit():
                latest_message[chat_id] = max(latest_message.get(chat_id, 0), int(message_id))

    entries = []
    for chat_id, count in counts.items():
        entries.append(
            {
                "chatId": chat_id,
                "id": chat_id,
                "nodes": count,
                "propositions": count,
                "newestAt": newest.get(chat_id, ""),
            }
        )
    # Newest first; timestamps tie on event order and ledger recency, then
    # stable id order for sessions with no datable activity.
    entries.sort(key=lambda entry: entry["chatId"])
    entries.sort(
        key=lambda entry: (
            entry["newestAt"],
            latest_message.get(entry["chatId"], 0),
            *recency.get(entry["chatId"], (-1, -1)),
        ),
        reverse=True,
    )
    return entries


def _query_matcher(query):
    pattern = query if "*" in query else "*" + query + "*"
    expression = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.compile(expression, re.IGNORECASE | re.DOTALL)


def select_nodes(nodes, session=None, query=None):
    selected = nodes
    if session is not None:
        # Birth is the first provenance point, as the app defines it.  A node that a
        # later session merely linked or extended was not born in that session.
        selected = [
            node
            for node in selected
            if node["provenance"] and node["provenance"][0]["chatId"] == session
        ]
    if query is not None:
        matcher = _query_matcher(query)
        selected = [
            node
            for node in selected
            if any(
                matcher.fullmatch(text)
                for text in [node["name"], node["statement"], *node["aliases"]]
            )
        ]
    return selected


def select_chains(chains, node_id=None):
    if node_id is None:
        return chains
    return [
        chain
        for chain in chains
        if chain["conclusion"] == node_id or node_id in chain["premises"]
    ]


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------


def _print_point_list(points):
    if not points:
        print("  Provenance: none recorded")
        return
    print("  Provenance:")
    for point in points:
        print("    - %s / %s" % (point["chatId"], point["messageId"] or "(session-level)"))


def _print_node(node):
    print("## %s (`%s`)" % (node["name"], node["id"]))
    print()
    print(node["statement"])
    print()
    print("- Created: %s" % node["createdAt"])
    if node["aliases"]:
        print("- Aliases:")
        for alias in node["aliases"]:
            print("  - %s" % alias)
    else:
        print("- Aliases: none")
    _print_point_list(node["provenance"])
    print()


def _print_chain(chain, nodes_by_id):
    print("## Chain `%s`" % chain["id"])
    print()
    print("Premises: %s -> Conclusion: %s" % (", ".join(chain["premises"]), chain["conclusion"]))
    print("- Created: %s" % chain["createdAt"])
    _print_point_list(chain["provenance"])
    print()
    for role, node_id in [("Premise", value) for value in chain["premises"]] + [
        ("Conclusion", chain["conclusion"])
    ]:
        node = nodes_by_id.get(node_id)
        if node is None:
            print("- %s `%s`: missing proposition" % (role, node_id))
        else:
            print("- %s `%s`: %s" % (role, node_id, node["statement"]))
    print()


def print_markdown(command, result, root, nodes_by_id):
    print("# %s" % command.capitalize())
    print()
    print("Data directory: %s" % root)
    print()
    if not result:
        if command == "sessions":
            print("No sessions recorded.")
        elif command == "chains":
            print("No chains recorded.")
        else:
            print("No propositions found.")
        return

    if command == "sessions":
        print("| Session | Nodes | Newest node |")
        print("|---|---:|---|")
        for entry in result:
            print("| `%s` | %d | %s |" % (entry["chatId"], entry["nodes"], entry["newestAt"] or "unknown"))
        return

    if command == "chains":
        for chain in result:
            _print_chain(chain, nodes_by_id)
        return

    for node in result:
        _print_node(node)


def print_json(root, records):
    _data.print_json({"data_dir": str(root), "records": records})


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

EXPORT_LEDGERS = ("nodes.jsonl", "chains.jsonl")
MAX_EXPORT_DEFECTS = 5


def _is_graph_directory(path):
    """True when ``path`` is itself a ledger directory rather than a data directory."""
    path = Path(path)
    if path.name == "graph":
        return True
    return any((path / name).exists() for name in EXPORT_LEDGERS)


def _resolve_export_target(destination):
    """Apply the destination rules: a ledger directory stays, anything else is a data dir.

    A destination that already holds ``nodes.jsonl`` or ``chains.jsonl`` -- or is named
    ``graph`` -- is the ledger directory itself.  Every other destination is a data
    directory, so its ledgers belong in ``<destination>/graph``, which is created.
    """
    target = Path(destination).expanduser()
    if target.exists() and not target.is_dir():
        raise _data.Refusal("export target is not a directory: %s" % target)
    if _is_graph_directory(target):
        return target
    return target / "graph"


def _read_destination_format(graph_directory):
    """Read a destination's own format stamp with ``_data.read_format`` semantics.

    ``_data.read_format`` only reads ``root/graph/format.json``, and a destination
    ledger directory is not always named ``graph``, so the numeric comparison and the
    refusal for a newer version are mirrored here rather than skipped.
    """
    path = Path(graph_directory) / "format.json"
    try:
        value = _data.read_json(path, default=None)
    except (ValueError, OSError, UnicodeError):
        return _data.FORMAT_VERSION
    if not isinstance(value, dict):
        return _data.FORMAT_VERSION
    version = value.get("version", _data.FORMAT_VERSION)
    if isinstance(version, bool) or not isinstance(version, (int, float)):
        return _data.FORMAT_VERSION
    if version != version or version in (float("inf"), float("-inf")):
        return _data.FORMAT_VERSION
    if version > _data.FORMAT_VERSION:
        raise _data.Refusal(
            "graph format %s is newer than this skill understands (%s); refusing to touch it"
            % (version, _data.FORMAT_VERSION)
        )
    return version


def _is_non_empty_file(path):
    path = Path(path)
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return True


def _scan_source_ledger(path):
    """Read one source ledger, keeping each record's line number.

    Unlike the read side, export cannot skip bad lines: copying them hands the app lines
    it drops silently.  Every defect is collected with the line that carries it.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], []
    except (OSError, UnicodeError) as exc:
        return [], ["%s: unreadable (%s)" % (path.name, exc)]

    records = []
    defects = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line, parse_constant=_reject_constant)
        except ValueError as exc:
            defects.append("%s:%d malformed json (%s)" % (path.name, number, exc))
            continue
        if not isinstance(value, dict):
            defects.append("%s:%d not a json object" % (path.name, number))
            continue
        records.append((number, value))
    return records, defects


def _inspect_source_ledgers(graph_directory):
    """Return ``(defects, node_count, chain_count)`` for the source ledgers.

    The shapes are the ones ``verify.py`` checks, plus exact line numbers: a bad id, an
    empty statement, a missing ``aliases``/``provenance`` array, empty premises, or a
    chain endpoint that does not resolve in the merged node id set.
    """
    graph_directory = Path(graph_directory)
    node_records, defects = _scan_source_ledger(graph_directory / "nodes.jsonl")
    node_ids = set()
    for number, record in node_records:
        node_id = record.get("id")
        if not isinstance(node_id, str) or not _data.NODE_ID_RE.match(node_id):
            defects.append("nodes.jsonl:%d bad node id %r" % (number, node_id))
            continue
        node_ids.add(node_id)
        statement = record.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            defects.append("nodes.jsonl:%d (%s) empty statement" % (number, node_id))
        if not isinstance(record.get("aliases"), list):
            defects.append("nodes.jsonl:%d (%s) missing aliases array" % (number, node_id))
        if not isinstance(record.get("provenance"), list):
            defects.append("nodes.jsonl:%d (%s) missing provenance array" % (number, node_id))

    chain_records, chain_defects = _scan_source_ledger(graph_directory / "chains.jsonl")
    defects.extend(chain_defects)
    for number, record in chain_records:
        chain_id = record.get("id")
        if not isinstance(chain_id, str) or not _data.CHAIN_ID_RE.match(chain_id):
            defects.append("chains.jsonl:%d bad chain id %r" % (number, chain_id))
        premises = record.get("premises")
        if not isinstance(premises, list) or not premises:
            defects.append("chains.jsonl:%d empty premises" % number)
            continue
        for endpoint in [*premises, record.get("conclusion")]:
            if endpoint not in node_ids:
                defects.append(
                    "chains.jsonl:%d (%s) endpoint %r does not resolve" % (number, chain_id, endpoint)
                )
    return defects, len(node_records), len(chain_records)


def _copy_ledger(source, destination_file):
    """Copy one ledger into place atomically, or create an empty one when absent."""
    source = Path(source)
    destination_file = Path(destination_file)
    if source.exists():
        if destination_file.exists() and destination_file.resolve() == source.resolve():
            return
        temporary = destination_file.with_name(destination_file.name + ".tmp")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination_file)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise _data.Refusal("cannot export %s: %s" % (source.name, exc))
        return
    try:
        destination_file.write_text("", encoding="utf-8")
    except OSError as exc:
        raise _data.Refusal("cannot export %s: %s" % (source.name, exc))


def export_ledgers(root, destination, replace=False):
    """Copy the two ledgers into a destination, refusing to destroy what is already there.

    Every refusal happens before anything is written: the source graph must exist and
    contain only lines the app would keep, and a destination holding a newer format
    stamp or a non-empty ledger is refused unless ``replace`` is set.
    """
    target = _resolve_export_target(destination)

    source_graph = _data.graph_dir(root)
    if not source_graph.is_dir():
        raise _data.Refusal("no graph to export: %s does not exist; check --data-dir" % source_graph)

    _read_destination_format(target)

    conflicts = [name for name in EXPORT_LEDGERS if _is_non_empty_file(target / name)]
    if conflicts and not replace:
        raise _data.Refusal(
            "destination %s already has non-empty %s; pass --replace to overwrite"
            % (target, " and ".join(conflicts))
        )

    defects, node_count, chain_count = _inspect_source_ledgers(source_graph)
    if defects:
        shown = defects[:MAX_EXPORT_DEFECTS]
        if len(defects) > len(shown):
            shown.append("... and %d more" % (len(defects) - len(shown)))
        raise _data.Refusal(
            "refusing to export source lines the app would drop: %s" % "; ".join(shown)
        )

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _data.Refusal("cannot create export directory %s: %s" % (target, exc))
    if not target.is_dir():
        raise _data.Refusal("export target is not a directory: %s" % target)

    for name in EXPORT_LEDGERS:
        _copy_ledger(source_graph / name, target / name)

    # Only the stamp is added beside the ledgers; every other file is left untouched.
    try:
        _data.write_json(target / "format.json", {"version": _data.FORMAT_VERSION})
    except OSError as exc:
        raise _data.Refusal("cannot write export format stamp: %s" % exc)

    return {
        "to": str(target),
        "action": "replaced" if conflicts else "created",
        "nodes": node_count,
        "chains": chain_count,
    }


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(description="Read, query and export the learnharness graph.")
    parser.add_argument("--data-dir", metavar="PATH", help="path to the .learnharness directory")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="output format (default: markdown)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("sessions", help="list provenance sessions and node counts")

    propositions = commands.add_parser("propositions", help="list propositions, optionally by session")
    propositions.add_argument("--session", metavar="ID")

    find = commands.add_parser("find", help="search propositions; '*' is the only wildcard")
    find.add_argument("query", metavar="QUERY")

    chains = commands.add_parser("chains", help="list chains, optionally containing one node")
    chains.add_argument("--node", metavar="ID")

    export = commands.add_parser(
        "export",
        help="copy the two ledgers and a format stamp into a destination directory",
        description=(
            "Copy nodes.jsonl and chains.jsonl into DEST and stamp format version 1. If DEST "
            "already contains nodes.jsonl or chains.jsonl, or DEST is named 'graph', the "
            "ledgers are written into DEST itself; any other DEST is treated as the app's "
            "data directory and its ledgers belong in DEST/graph, which is created. Export "
            "refuses when DEST holds a newer format stamp or non-empty ledgers (pass "
            "--replace to overwrite) and when the source ledgers hold lines the app would "
            "drop. No other file in DEST is read, rewritten or removed."
        ),
    )
    export.add_argument("--to", metavar="PATH", required=True)
    export.add_argument(
        "--replace",
        action="store_true",
        help="overwrite destination ledgers that already contain records",
    )

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    root = _data.find_root(args.data_dir)

    if args.command == "export":
        _data.read_format(root)
        result = export_ledgers(root, args.to, replace=args.replace)
        if args.format == "json":
            _data.print_json({"ok": True, "data_dir": str(root), "records": [result]})
        else:
            print("# Export")
            print()
            print("Data directory: %s" % root)
            print("Exported to: %s" % result["to"])
            print(
                "Action: %s"
                % (
                    "replaced existing ledger files"
                    if result["action"] == "replaced"
                    else "created new ledger files"
                )
            )
            print("Nodes: %d" % result["nodes"])
            print("Chains: %d" % result["chains"])
        return 0

    nodes, chains, warnings, recency = load_graph_details(root)
    _data.print_warnings(warnings)
    nodes_by_id = {node["id"]: node for node in nodes}

    if args.command == "sessions":
        result = session_index(nodes, recency)
    elif args.command == "propositions":
        result = select_nodes(nodes, session=args.session)
    elif args.command == "find":
        result = select_nodes(nodes, query=args.query)
    else:
        result = select_chains(chains, node_id=args.node)

    if args.format == "json":
        print_json(root, result)
    else:
        print_markdown(args.command, result, root, nodes_by_id)
    return 0


if __name__ == "__main__":
    _data.run(main)
