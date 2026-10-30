"""Merge extracted propositions and reasoning chains into the graph ledgers.

This is the only writer to ``graph/nodes.jsonl`` and ``graph/chains.jsonl``.
Proposals use local refs; this script resolves them against the existing merged
graph (or mints deterministic ids), validates every record and every chain
endpoint, and appends app-compatible lines only.  A refusal writes nothing.
Practice sessions are refused: practice records no propositions.

Optional provenance fields (explicit values win over derivation):

``merge --message SEQ``
    A default event seq for every record that does not name its own.  ``SEQ``
    must be an existing event in the session log.
``messageId`` on a node or chain
    A per-record event seq, likewise required to exist.  It overrides
    ``--message``.
``targetNode`` on a node
    The plan node whose check establishes the proposition.  When no explicit
    seq is given, the record uses the last ``answer`` to a ``check_posed`` for
    that node; without a matching answer it falls back like any other record
    to the last ``answer`` or ``step_closed`` event (and finally to the last
    event in the session).

Provenance points already present on that node or chain are never appended
again, including when the only change is a new alias.
"""

import sys

sys.dont_write_bytecode = True

import argparse
import json
from pathlib import Path

import _data
import graph


# ---------------------------------------------------------------------------
# proposal parsing and validation
# ---------------------------------------------------------------------------


def _reject_constant(name):
    raise ValueError("non-finite number in json: %s" % name)


def _parse_message_id(value, where):
    """Parse an optional event sequence.  Existence is checked against the log."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise _data.Refusal("%s: messageId must be an integer event seq" % where)
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise _data.Refusal("%s: messageId must be an integer event seq" % where)
        number = int(text)
    else:
        raise _data.Refusal("%s: messageId must be an integer event seq" % where)
    if number < 1:
        raise _data.Refusal("%s: messageId must be a positive event seq" % where)
    return number


def _parse_target_node(value, where):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _data.Refusal("%s: targetNode must be a non-empty string" % where)
    return value.strip()


def _read_proposals(source):
    try:
        if source == "-":
            text = sys.stdin.read()
        else:
            text = Path(source).expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise _data.Refusal("cannot read proposals: %s" % exc)
    if not text.strip():
        raise _data.Refusal("proposal document is empty")
    try:
        document = json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        raise _data.Refusal("proposal document is not valid JSON: %s" % exc)
    if not isinstance(document, dict):
        raise _data.Refusal("proposal document must be a JSON object")
    return document


def _optional_aliases(value, where):
    if value is None:
        return []
    if not isinstance(value, list):
        raise _data.Refusal("%s: aliases must be an array of strings" % where)
    aliases = []
    for alias in value:
        if not isinstance(alias, str):
            raise _data.Refusal("%s: aliases must be an array of strings" % where)
        alias = alias.strip()
        if alias and alias not in aliases:
            aliases.append(alias)
    return aliases


def _parse_nodes(document):
    raw_nodes = document.get("nodes", [])
    if raw_nodes is None:
        raw_nodes = []
    if not isinstance(raw_nodes, list):
        raise _data.Refusal("nodes must be an array")

    nodes = []
    refs = set()
    for index, item in enumerate(raw_nodes, start=1):
        where = "node %d" % index
        if not isinstance(item, dict):
            raise _data.Refusal("%s: must be an object" % where)
        ref = item.get("ref")
        if not isinstance(ref, str) or not ref.strip():
            raise _data.Refusal("%s: ref must be a non-empty string" % where)
        ref = ref.strip()
        if ref in refs:
            raise _data.Refusal("duplicate node ref: %r" % ref)
        refs.add(ref)

        statement = item.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            raise _data.Refusal("node %r: statement must be a non-empty string" % ref)
        statement = statement.strip()

        name = item.get("name")
        if name is None:
            name = ""
        if not isinstance(name, str):
            raise _data.Refusal("node %r: name must be a string" % ref)
        name = name.strip() or statement

        aliases = _optional_aliases(item.get("aliases"), "node %r" % ref)
        message_id = _parse_message_id(item.get("messageId"), "node %r" % ref)
        target_node = _parse_target_node(item.get("targetNode"), "node %r" % ref)
        nodes.append(
            {
                "ref": ref,
                "statement": statement,
                "name": name,
                "aliases": aliases,
                "messageId": message_id,
                "targetNode": target_node,
            }
        )
    return nodes


def _parse_chains(document):
    raw_chains = document.get("chains", [])
    if raw_chains is None:
        raw_chains = []
    if not isinstance(raw_chains, list):
        raise _data.Refusal("chains must be an array")

    chains = []
    for index, item in enumerate(raw_chains, start=1):
        where = "chain %d" % index
        if not isinstance(item, dict):
            raise _data.Refusal("%s: must be an object" % where)
        premises = item.get("premises")
        if not isinstance(premises, list) or not premises:
            raise _data.Refusal("%s: premises must be a non-empty array" % where)
        parsed_premises = []
        for premise in premises:
            if not isinstance(premise, str) or not premise.strip():
                raise _data.Refusal("%s: every premise must be a non-empty string" % where)
            parsed_premises.append(premise.strip())
        conclusion = item.get("conclusion")
        if not isinstance(conclusion, str) or not conclusion.strip():
            raise _data.Refusal("%s: conclusion must be a non-empty string" % where)
        message_id = _parse_message_id(item.get("messageId"), where)
        chains.append(
            {
                "premises": parsed_premises,
                "conclusion": conclusion.strip(),
                "messageId": message_id,
            }
        )
    return chains


# ---------------------------------------------------------------------------
# resolution and merge
# ---------------------------------------------------------------------------


def _same_point(left, right):
    return left.get("chatId") == right.get("chatId") and left.get("messageId") == right.get("messageId")


def _find_existing(statement, by_id, order):
    for node_id in order:
        node = by_id[node_id]
        if node["statement"].strip() == statement:
            return node
        for alias in node["aliases"]:
            if alias.strip() == statement:
                return node
    return None


def _mint_disambiguated_node_id(statement, by_id):
    base = _data.mint_node_id(statement)
    if base not in by_id:
        return base
    counter = 0
    while True:
        counter += 1
        candidate = "n_" + _data.sha256_hex("node\x00" + statement + "\x00collision\x00" + str(counter))[:12]
        if candidate not in by_id:
            return candidate


def _provenance_point(session_id, sequence):
    return {"chatId": session_id, "messageId": str(sequence)}


def _check_nodes(events):
    return {
        event.get("seq"): event.get("node")
        for event in events
        if event.get("type") == "check_posed"
    }


def _default_sequence(events, target_node=None):
    """The seq of the event that establishes a record when none was supplied."""
    check_nodes = _check_nodes(events)
    matched = None
    fallback = None
    for event in events:
        kind = event.get("type")
        if kind == "answer":
            fallback = event.get("seq")
            if target_node is not None and check_nodes.get(event.get("check_seq")) == target_node:
                matched = event.get("seq")
        elif kind == "step_closed":
            fallback = event.get("seq")
    if matched is not None:
        return matched
    if fallback is not None:
        return fallback
    return events[-1].get("seq")


def _record_sequence(proposal, message, events, target_node=None):
    if proposal.get("messageId") is not None:
        return proposal["messageId"]
    if message is not None:
        return message
    return _default_sequence(events, target_node)


def _require_event_sequence(sequence, available, session_id, where):
    if sequence not in available:
        raise _data.Refusal(
            "%s: messageId %s is not an event seq in session %s"
            % (where, sequence, session_id)
        )
    return sequence


def merge_proposals(root, session_id, document, message=None):
    """Resolve, validate and append one proposal document.  Returns the summary."""
    nodes = _parse_nodes(document)
    chains = _parse_chains(document)

    events = _data.require_session(root, session_id)
    if not events:
        raise _data.Refusal("session %s has no events" % session_id)
    start = next((event for event in events if event.get("type") == "session_start"), None)
    if start is not None and start.get("kind") == "practice":
        raise _data.Refusal(
            "session %s is a practice session; practice records no propositions" % session_id
        )
    available = {event["seq"] for event in events}
    message = _parse_message_id(message, "--message")
    if message is not None:
        _require_event_sequence(message, available, session_id, "--message")

    # Reads refuse a newer format stamp before any merge decision is made.
    existing_nodes, existing_chains, warnings = graph.load_graph(root)
    _data.print_warnings(warnings)

    by_id = {node["id"]: node for node in existing_nodes}
    order = [node["id"] for node in existing_nodes]
    chains_by_key = {
        graph.chain_key(chain["premises"], chain["conclusion"]): chain
        for chain in existing_chains
    }
    chains_by_id = {chain["id"]: chain for chain in existing_chains}

    now = _data.now_iso()
    node_lines = []
    chain_lines = []
    ref_map = {}
    reused = 0

    for proposal in nodes:
        statement = proposal["statement"]
        existing = _find_existing(statement, by_id, order)
        sequence = _record_sequence(proposal, message, events, proposal.get("targetNode"))
        _require_event_sequence(sequence, available, session_id, "node %r" % proposal["ref"])
        point = _provenance_point(session_id, sequence)

        if existing is not None:
            node_id = existing["id"]
            reused += 1
            ref_map[proposal["ref"]] = node_id

            has_point = any(_same_point(current, point) for current in existing["provenance"])
            new_alias = any(
                alias not in existing["aliases"] and alias != existing["statement"]
                for alias in proposal["aliases"]
            )
            if has_point and not new_alias:
                continue

            line = {
                "id": node_id,
                "name": existing["name"],
                "statement": statement,
                "aliases": list(proposal["aliases"]),
                "createdAt": existing["createdAt"],
                "provenance": [] if has_point else [dict(point)],
            }
            node_lines.append(line)

            # Keep the in-memory view in sync so later refs in this proposal
            # see exactly what a reader will see after the append.
            for phrasing in [statement, *proposal["aliases"]]:
                if phrasing and phrasing not in existing["aliases"]:
                    existing["aliases"].append(phrasing)
            if not has_point:
                existing["provenance"].append(dict(point))
            continue

        node_id = _mint_disambiguated_node_id(statement, by_id)
        node = {
            "id": node_id,
            "name": proposal["name"],
            "statement": statement,
            "aliases": list(proposal["aliases"]),
            "createdAt": now,
            "provenance": [dict(point)],
        }
        by_id[node_id] = node
        order.append(node_id)
        ref_map[proposal["ref"]] = node_id
        node_lines.append(
            {
                "id": node_id,
                "name": node["name"],
                "statement": node["statement"],
                "aliases": list(node["aliases"]),
                "createdAt": node["createdAt"],
                "provenance": [dict(point)],
            }
        )

    proposal_chain_keys = set()

    def resolve_endpoint(value):
        if value in ref_map:
            return ref_map[value]
        if value in by_id:
            return value
        match = _find_existing(value, by_id, order)
        if match is not None:
            return match["id"]
        raise _data.Refusal("chain references a ref that was not defined and does not match a node: %r" % value)

    for proposal in chains:
        premises = [resolve_endpoint(value) for value in proposal["premises"]]
        conclusion = resolve_endpoint(proposal["conclusion"])

        if len(premises) == 1 and premises[0] == conclusion:
            raise _data.Refusal("a chain's conclusion cannot equal its sole premise")

        key = graph.chain_key(premises, conclusion)
        if key in proposal_chain_keys:
            raise _data.Refusal("duplicate chain key in proposal: %s -> %s" % (sorted(premises), conclusion))
        proposal_chain_keys.add(key)

        chain_id = _data.mint_chain_id(premises, conclusion)
        existing = chains_by_key.get(key)
        if existing is None:
            existing = chains_by_id.get(chain_id)

        sequence = _record_sequence(proposal, message, events)
        _require_event_sequence(
            sequence,
            available,
            session_id,
            "chain %s -> %s" % (sorted(premises), conclusion),
        )
        point = _provenance_point(session_id, sequence)

        if existing is not None:
            if any(_same_point(current, point) for current in existing["provenance"]):
                continue
            line = {
                "id": existing["id"],
                "premises": list(existing["premises"]),
                "conclusion": existing["conclusion"],
                "provenance": [dict(point)],
                "createdAt": existing["createdAt"],
            }
            chain_lines.append(line)
            existing["provenance"].append(dict(point))
            continue

        chain = {
            "id": chain_id,
            "premises": list(premises),
            "conclusion": conclusion,
            "provenance": [dict(point)],
            "createdAt": now,
        }
        chain_lines.append(chain)
        chains_by_key[key] = chain
        chains_by_id[chain_id] = chain

    # Everything validated; now touch the record.  ensure_format also refuses
    # a newer stamp if one appeared after the read.
    _data.ensure_format(root)
    for line in node_lines:
        _data.append_jsonl(_data.graph_dir(root) / "nodes.jsonl", line)
    for line in chain_lines:
        _data.append_jsonl(_data.graph_dir(root) / "chains.jsonl", line)

    # ``nodes`` reports node LINES written (new definitions and link-appends);
    # ``reused`` reports how many proposals matched an existing node instead of
    # minting one.  Session close copies these counts into the event log.
    return {"ok": True, "nodes": len(node_lines), "chains": len(chain_lines), "reused": reused}


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(description="Merge graph proposals into the ledgers.")
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        help="path to the .learnharness directory",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    merge = commands.add_parser("merge", help="merge a proposal document")
    merge.add_argument("--session", required=True, metavar="ID", help="session id supplying provenance")
    merge.add_argument("--proposals", required=True, metavar="FILE|-", help="proposal JSON file, or - for stdin")
    merge.add_argument(
        "--message",
        metavar="SEQ",
        default=None,
        help="default provenance event seq for records without their own messageId",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    document = _read_proposals(args.proposals)
    root = _data.find_root(args.data_dir)
    result = merge_proposals(root, args.session, document, message=args.message)
    _data.print_json(result)
    return 0


if __name__ == "__main__":
    _data.run(main)
