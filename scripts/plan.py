"""``plan.py`` — decide whether a teaching plan is an acceptable DAG.

The plan is the phase-2 artefact: a dependency map from the measured starting
points to the session goal.  ``session.py plan-set`` calls :func:`validate`
before it appends a ``plan_set`` event, so this module is the only thing that
decides whether a plan may be recorded at all.

Document shape::

    {"nodes": [{"id": "counting", "title": "Entropy is a count", "summary": "..."}],
     "edges": [{"from": "counting", "to": "irreversible"}]}

A missing or ``null`` ``nodes``/``edges`` value counts as empty, so a plan
logged without edges (``session.py``) validates the same way as the file it was
authored from.

A plan is refused when it has no nodes, when a node id does not match
``^[a-z0-9]+([_-][a-z0-9]+)*$``, when an id repeats, when a title is empty or
whitespace-only, when the plan, a node, or an edge carries an unknown key, when
a node summary is present but not a string, when an edge names an unknown node,
when an edge is a self-loop, when two edges are identical, or when the edges
contain a cycle. Every problem is reported, newline-joined, so one pass is
enough to fix them.

Size is advisory: more than ``_data.WARN_PLAN_NODES`` nodes adds a warning to
the success payload and never refuses.

Usage::

    python3 scripts/plan.py validate --plan FILE|-
"""

import sys

sys.dont_write_bytecode = True

import argparse
import json
import re
from collections import deque
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _data

NODE_ID_RULE = "^[a-z0-9]+([_-][a-z0-9]+)*$"
NODE_ID_RE = re.compile(NODE_ID_RULE)

_PLAN_KEYS = frozenset(("nodes", "edges"))
_NODE_KEYS = frozenset(("id", "title", "summary"))
_EDGE_KEYS = frozenset(("from", "to"))

# Cycles are diagnostic text, not the verdict; report enough to start fixing.
MAX_REPORTED_CYCLES = 20

_WHITE, _GRAY, _BLACK = 0, 1, 2


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def validate(document):
    """Return ``(ok, error, warnings, node_ids)`` for a plan document.

    ``error`` is ``""`` when ``ok`` is True and a newline-joined list of problems
    otherwise, each naming the offending node or edge.  ``warnings`` holds
    advisory notes; it never affects ``ok``.  ``node_ids`` is the input order of
    the ids.  A merely invalid document is returned, never raised; only a
    non-dict document raises ``TypeError``.
    """
    if not isinstance(document, dict):
        raise TypeError("plan document must be a json object, got %s" % _json_type(document))

    errors = []
    node_ids = []

    for key in document:
        if key not in _PLAN_KEYS:
            errors.append("unknown top-level key %r" % (key,))

    node_entries = document.get("nodes")
    if node_entries is None:
        errors.append("plan has no nodes")
        node_entries = []
    elif not isinstance(node_entries, list):
        errors.append('"nodes" must be a list, got %s' % _json_type(node_entries))
        node_entries = []
    elif not node_entries:
        errors.append("plan has no nodes")

    known = _collect_nodes(node_entries, errors, node_ids)

    edge_entries = document.get("edges")
    if edge_entries is None:
        edge_entries = []
    elif not isinstance(edge_entries, list):
        errors.append('"edges" must be a list, got %s' % _json_type(edge_entries))
        edge_entries = []

    graph = _collect_edges(edge_entries, set(known), errors)

    if _has_cycle(graph, known):
        cycles, truncated = _find_cycles(graph, known)
        for cycle in cycles:
            errors.append("cycle: " + " -> ".join(cycle + (cycle[0],)))
        if truncated:
            errors.append(
                "cycle: more than %d distinct cycles; fix the listed cycles first" % len(cycles)
            )

    warnings = []
    if len(known) > _data.WARN_PLAN_NODES:
        warnings.append(
            "%d plan nodes is above the advisory limit of %d"
            % (len(known), _data.WARN_PLAN_NODES)
        )

    return (not errors, "\n".join(errors), warnings, node_ids)


def _collect_nodes(entries, errors, node_ids):
    """Validate node entries. Append every string id to ``node_ids`` in input order.

    Returns the distinct known ids, in input order, for endpoint resolution.
    """
    known = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append("nodes[%d]: must be an object, got %s" % (index, _json_type(entry)))
            continue

        node_id = entry.get("id")
        if not isinstance(node_id, str):
            errors.append(
                'nodes[%d]: "id" must be a string, got %s' % (index, _json_type(node_id))
            )
            node_id = None
        else:
            node_ids.append(node_id)
            if not NODE_ID_RE.fullmatch(node_id):
                errors.append("node %r: id does not match %s" % (node_id, NODE_ID_RULE))
            if node_id in known:
                errors.append("node %r: duplicate id" % (node_id,))
            known[node_id] = True

        label = "node %r" % (node_id,) if node_id is not None else "nodes[%d]" % index
        for key in entry:
            if key not in _NODE_KEYS:
                errors.append("%s: unknown key %r" % (label, key))

        summary = entry.get("summary")
        if "summary" in entry and not isinstance(summary, str):
            errors.append("%s: summary must be a string, got %s" % (label, _json_type(summary)))

        title = entry.get("title")
        if not isinstance(title, str):
            errors.append("%s: title must be a string, got %s" % (label, _json_type(title)))
        elif not title.strip():
            errors.append("%s: title is empty" % label)

    return list(known)


def _collect_edges(entries, known, errors):
    """Validate edge entries and return the adjacency map of usable edges."""
    graph = {}
    seen = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append("edges[%d]: must be an object, got %s" % (index, _json_type(entry)))
            continue

        for key in entry:
            if key not in _EDGE_KEYS:
                errors.append("edges[%d]: unknown key %r" % (index, key))

        source = entry.get("from")
        target = entry.get("to")
        source_ok = isinstance(source, str)
        target_ok = isinstance(target, str)
        if not source_ok:
            errors.append(
                'edges[%d]: "from" must be a string, got %s' % (index, _json_type(source))
            )
        if not target_ok:
            errors.append(
                'edges[%d]: "to" must be a string, got %s' % (index, _json_type(target))
            )
        if not (source_ok and target_ok):
            continue

        label = "edge %r -> %r" % (source, target)
        unknown = [node for node in (source, target) if node not in known]
        if unknown:
            for node in unknown:
                errors.append("%s: unknown node %r" % (label, node))
            continue

        key = (source, target)
        if key in seen:
            errors.append("%s: duplicate edge" % label)
            continue
        seen.add(key)

        if source == target:
            errors.append("%s: self-loop" % label)
            continue

        graph.setdefault(source, []).append(target)

    return graph


def _has_cycle(graph, order):
    """Kahn's algorithm: a graph is acyclic exactly when every node is settled."""
    indegree = {node: 0 for node in order}
    for source in order:
        for target in graph.get(source, ()):
            if target in indegree:
                indegree[target] += 1

    ready = deque(node for node in order if indegree[node] == 0)
    settled = 0
    while ready:
        node = ready.popleft()
        settled += 1
        for target in graph.get(node, ()):
            if target not in indegree:
                continue
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    return settled != len(order)


def _find_cycles(graph, order, limit=MAX_REPORTED_CYCLES):
    """Name representative cycles with an iterative DFS (no recursion depth risk).

    Returns ``(cycles, truncated)``; each cycle is a tuple of distinct node ids
    in traversal order, and ``truncated`` says more distinct cycles exist.
    """
    color = {node: _WHITE for node in order}
    cycles = []
    seen = set()

    for root in order:
        if color[root] != _WHITE:
            continue
        color[root] = _GRAY
        path = [root]
        stack = [(root, iter(graph.get(root, ())))]
        while stack:
            node, children = stack[-1]
            descended = False
            for child in children:
                if child not in color:
                    continue
                if color[child] == _WHITE:
                    color[child] = _GRAY
                    path.append(child)
                    stack.append((child, iter(graph.get(child, ()))))
                    descended = True
                    break
                if color[child] == _GRAY:
                    cycle = tuple(path[path.index(child):])
                    key = _cycle_key(cycle)
                    if key in seen:
                        continue
                    seen.add(key)
                    if len(cycles) >= limit:
                        return cycles, True
                    cycles.append(cycle)
            if descended:
                continue
            stack.pop()
            color[node] = _BLACK
            path.pop()

    return cycles, False


def _cycle_key(cycle):
    """Canonical rotation of a cycle, so the same loop is not reported twice."""
    return min(cycle[index:] + cycle[:index] for index in range(len(cycle)))


def _json_type(value):
    """Name a decoded JSON value in the same vocabulary a plan author writes."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------


def _refusal(message):
    """Print the refusal payload to stdout and return the exception to raise."""
    _data.print_json({"ok": False, "error": message})
    return _data.Refusal(message)


def _reject_constant(name):
    raise ValueError("non-finite number (%s) is not allowed" % name)


def _read_text(spec):
    """Read the plan document as UTF-8 text from ``spec``, or stdin for ``-``."""
    if spec == "-":
        stream = getattr(sys.stdin, "buffer", None)
        data = stream.read() if stream is not None else sys.stdin.read().encode("utf-8")
    else:
        path = Path(spec)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise _refusal("cannot read plan file %s: %s" % (path, exc.strerror or exc))

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _refusal("plan is not valid utf-8: %s" % (exc,))


def _load_document(spec):
    text = _read_text(spec)
    if not text.strip():
        raise _refusal("plan is empty")
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        raise _refusal("plan is not valid json: %s" % (exc,))


def _cmd_validate(spec):
    document = _load_document(spec)
    try:
        ok, error, warnings, node_ids = validate(document)
    except TypeError as exc:
        raise _refusal(str(exc))
    if not ok:
        raise _refusal(error)
    _data.print_json({"ok": True, "nodeIds": node_ids, "warnings": warnings})


def main(argv=None):
    parser = argparse.ArgumentParser(prog="plan.py", description="Validate a teaching plan DAG.")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    validate_parser = subparsers.add_parser(
        "validate",
        help="read a plan document and refuse it if it is not a valid DAG",
    )
    validate_parser.add_argument(
        "--plan",
        required=True,
        metavar="FILE|-",
        help="plan document to read, or - for stdin",
    )

    args = parser.parse_args(argv)
    if args.command == "validate":
        _cmd_validate(args.plan)


if __name__ == "__main__":
    _data.run(main)
