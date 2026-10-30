"""Read, query and export the knowledge graph.

The ledgers are append-only JSONL files under ``graph/``.  This module is the
read side: it applies the app's merge law (later lines with an existing node id
are link-appends; chain lines merge by sorted premises and conclusion), then
renders or filters the merged view.  ``export`` copies the two ledger files
verbatim into the app's data directory and stamps format version 1.
"""

import sys

sys.dont_write_bytecode = True

import argparse
import json
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
        selected = [
            node
            for node in selected
            if any(point["chatId"] == session for point in node["provenance"])
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

def export_ledgers(root, destination):
    """Copy exactly the two ledgers and stamp format version 1 in ``destination``.

    ``destination`` may be either the directory the ledgers belong in, or the app's
    data directory — the one that holds ``graph/`` and ``chats/``. Pointing at a data
    directory is the common case and silently writing the ledgers one level too high
    would produce a graph the app never shows, so an existing ``graph/`` or ``chats/``
    subdirectory is treated as a data root.
    """
    target = Path(destination).expanduser()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _data.Refusal("cannot create export directory %s: %s" % (target, exc))

    if not target.is_dir():
        raise _data.Refusal("export target is not a directory: %s" % target)

    for marker in ("graph", "chats"):
        candidate = target / marker
        if candidate.is_dir():
            target = candidate
            break

    if not target.is_dir():
        raise _data.Refusal("export target is not a directory: %s" % target)

    counts = {}
    for name in ("nodes.jsonl", "chains.jsonl"):
        source = _data.graph_dir(root) / name
        destination_file = target / name
        try:
            if source.exists() and source.resolve() != destination_file.resolve():
                shutil.copyfile(source, destination_file)
            elif not source.exists() and not destination_file.exists():
                destination_file.write_text("", encoding="utf-8")
        except OSError as exc:
            raise _data.Refusal("cannot export %s: %s" % (name, exc))
        records, _problems = _data.read_jsonl(source)
        counts[name] = len(records)

    # Direct write: export must not touch any other file already in the target.
    try:
        (target / "format.json").write_text(
            json.dumps({"version": _data.FORMAT_VERSION}, indent="\t") + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise _data.Refusal("cannot write export format stamp: %s" % exc)

    return {
        "to": str(target),
        "nodes": counts["nodes.jsonl"],
        "chains": counts["chains.jsonl"],
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
            "Copy nodes.jsonl and chains.jsonl into DEST and stamp format version 1. DEST may "
            "be the graph directory itself, or the app's data directory: if DEST already "
            "contains a graph/ or chats/ subdirectory, the ledgers are written into DEST/graph. "
            "No other file in DEST is read, rewritten or removed."
        ),
    )
    export.add_argument("--to", metavar="PATH", required=True)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    root = _data.find_root(args.data_dir)

    if args.command == "export":
        _data.read_format(root)
        result = export_ledgers(root, args.to)
        if args.format == "json":
            _data.print_json({"ok": True, "data_dir": str(root), "records": [result]})
        else:
            print("# Export")
            print()
            print("Data directory: %s" % root)
            print("Exported to: %s" % result["to"])
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
