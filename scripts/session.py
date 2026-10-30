"""``session.py`` — the append-only teaching record.

The log is canonical; everything else in this module is derived from it.  There
is no done-ledger: phase, current node, visited nodes and the open check are all
computed by replaying ``session.jsonl``.

Usage::

    python3 scripts/session.py [--data-dir PATH] [--format text|json] COMMAND [opts]

Commands: init, check, answer, conclude-probe, plan-set, step-close,
practice-problem, practice-concluded, close, state, render, list.

Hard rules, enforced here because they are the product:

* one open check at a time;
* the answer key is committed inside ``check_posed`` before the question is
  asked;
* the probe is concluded at most once, and never with a check open;
* ``plan-set`` refuses a plan that ``plan.py`` rejects;
* ``session_closed`` is terminal and recorded at most once.

Size limits are advisory only: they warn on stderr and never refuse.
"""

import sys

sys.dont_write_bytecode = True

import argparse
import json
from pathlib import Path

import _data
from _data import (
    KINDS,
    Refusal,
    WARN_PLAN_NODES,
    WARN_STEPS,
    WARN_STRANDS,
    append_event,
    ensure_format,
    find_root,
    list_session_ids,
    load_events,
    mint_session_id,
    print_json,
    print_warnings,
    require_session,
    run,
    session_dir,
    session_markdown,
    sessions_dir,
)


# --------------------------------------------------------------------------
# derivations (PLAN.md 4.3) — never stored, always replayed
# --------------------------------------------------------------------------


def _typed(events, event_type):
    return [event for event in events if event.get("type") == event_type]


def _start_event(events):
    for event in events:
        if event.get("type") == "session_start":
            return event
    raise Refusal("session log has no session_start event")


def _last_of(events, event_type):
    found = None
    for event in events:
        if event.get("type") == event_type:
            found = event
    return found


def _closed_event(events):
    return _last_of(events, "session_closed")


def _probe_event(events):
    return _last_of(events, "probe_concluded")


def _plan_event(events):
    best = None
    for event in events:
        if event.get("type") != "plan_set":
            continue
        if best is None or event.get("revision", 0) > best.get("revision", 0):
            best = event
    return best


def _checks(events):
    return _typed(events, "check_posed")


def _answers(events):
    return _typed(events, "answer")


def _kind(events):
    return _start_event(events).get("kind") or "teach"


def _goal(events):
    return _start_event(events).get("goal") or ""


def _phase(events):
    if _closed_event(events) is not None:
        return "closed"
    if _kind(events) == "practice":
        return "practice"
    if _probe_event(events) is None:
        return "probe"
    if not _node_checks(events):
        return "plan"
    return "teach"


def _node_checks(events):
    return [check for check in _checks(events) if check.get("node")]


def _current_node(events):
    tagged = _node_checks(events)
    if not tagged:
        return None
    return tagged[-1].get("node")


def _visited_nodes(events):
    tagged = _node_checks(events)
    if not tagged:
        return []
    current_seq = tagged[-1].get("seq") or 0
    visited = []
    for check in _node_checks(events):
        if (check.get("seq") or 0) >= current_seq:
            continue
        node = check.get("node")
        if node and node not in visited:
            visited.append(node)
    return visited


def _open_check(events):
    answered = set()
    for answer in _answers(events):
        target = answer.get("check_seq")
        if isinstance(target, int):
            answered.add(target)
    found = None
    for check in _checks(events):
        if check.get("seq") not in answered:
            found = check
    return found


def _check_by_seq(events, seq):
    for check in _checks(events):
        if check.get("seq") == seq:
            return check
    return None


def _answers_by_check(events):
    mapping = {}
    for answer in _answers(events):
        mapping[answer.get("check_seq")] = answer
    return mapping


def _plan_node_ids(events):
    plan = _plan_event(events)
    if plan is None:
        return []
    identifiers = []
    for node in plan.get("nodes") or []:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            identifiers.append(node.get("id"))
    return identifiers


# --------------------------------------------------------------------------
# small text helpers
# --------------------------------------------------------------------------


def _one_line(value):
    if value is None:
        return ""
    return " ".join(str(value).split())


def _clip(value, limit):
    text = _one_line(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _cell(value):
    return _one_line(value).replace("|", "\\|")


def _quote(value):
    text = _one_line(value)
    if not text:
        return "\u2014"
    return '"%s"' % text


def _selection_numbers(selection):
    if not isinstance(selection, list) or not selection:
        return "\u2014"
    parts = []
    for value in selection:
        if isinstance(value, int) and not isinstance(value, bool):
            # Options render 1-based; the record stays 0-based.
            parts.append(str(value + 1))
        else:
            parts.append(_one_line(value))
    return ", ".join(parts) or "\u2014"


# --------------------------------------------------------------------------
# state (PLAN.md 6)
# --------------------------------------------------------------------------


def _practice_summary(events):
    problems = _typed(events, "practice_problem")
    if not problems:
        return None
    problem = problems[-1]
    targets = problem.get("target")
    return {
        "mode": problem.get("mode"),
        "targets": targets if isinstance(targets, list) else [],
        "statement": _clip(problem.get("statement"), 120),
        "concluded": bool(_typed(events, "practice_concluded")),
    }


def _state_fields(session_id, events):
    plan = _plan_event(events)
    nodes = plan.get("nodes") if plan is not None else None
    edges = plan.get("edges") if plan is not None else None
    node_count = len(nodes) if isinstance(nodes, list) else 0
    edge_count = len(edges) if isinstance(edges, list) else 0
    visited = _visited_nodes(events)
    open_check = _open_check(events)
    practice = _practice_summary(events)

    last_answer = None
    for answer in _answers(events):
        last_answer = answer
    last = None
    if last_answer is not None:
        check = _check_by_seq(events, last_answer.get("check_seq"))
        last = {
            "check_seq": last_answer.get("check_seq"),
            "node": (check or {}).get("node"),
            "correct": bool(last_answer.get("correct")),
            "confidence": last_answer.get("confidence"),
            "trace": _clip(last_answer.get("trace"), 200),
        }

    plan_summary = None
    if plan is not None:
        plan_summary = {
            "revision": plan.get("revision", 1),
            "nodes": node_count,
            "edges": edge_count,
            "warn": ("above %d nodes" % WARN_PLAN_NODES) if node_count > WARN_PLAN_NODES else None,
        }

    return {
        "session": session_id,
        "kind": _kind(events),
        "phase": _phase(events),
        "closed": _closed_event(events) is not None,
        "goal": _clip(_goal(events), 240),
        "practice": practice,
        "plan": plan_summary,
        "current": _current_node(events),
        "visited": visited,
        "open": None
        if open_check is None
        else {
            "seq": open_check.get("seq"),
            "question": _clip(open_check.get("question"), 120),
        },
        "last": last,
        "next": None
        if plan is None
        else
        {
            # A node is untouched when it is neither behind us nor the one in progress.
            "untouched": max(node_count - len(visited) - (1 if _current_node(events) else 0), 0),
            "total": node_count,
        },
    }


def _state_text(fields):
    lines = [
        "session  %s   kind %s   phase %s   closed %s"
        % (fields["session"], fields["kind"], fields["phase"], "yes" if fields["closed"] else "no"),
        "goal     %s" % (fields["goal"] or "-"),
    ]

    plan = fields["plan"]
    if plan is None:
        lines.append("plan     none")
    else:
        line = "plan     revision %s, %d nodes, %d edges" % (
            plan["revision"],
            plan["nodes"],
            plan["edges"],
        )
        if plan["warn"]:
            line += "   (warn: %s)" % plan["warn"]
        lines.append(line)

    lines.append("current  %s" % (fields["current"] or "none"))
    lines.append("visited  %s" % (", ".join(fields["visited"]) if fields["visited"] else "none"))

    open_check = fields["open"]
    if open_check is None:
        lines.append("open     none")
    else:
        lines.append(
            "open     %s \u2014 %s" % (open_check["seq"], open_check["question"] or "(no question)")
        )

    last = fields["last"]
    if last is None:
        lines.append("last     none")
    else:
        verdict = "correct" if last["correct"] else "incorrect"
        lines.append(
            "last     %s \u2014 %s (confidence %s)"
            % (last["node"] or "probe", verdict, last["confidence"])
        )
        if last["trace"]:
            lines.append('         "%s"' % last["trace"])

    practice = fields.get("practice")
    if practice is not None:
        lines.append(
            "practice %s, %d target(s), %s \u2014 %s"
            % (
                practice["mode"] or "-",
                len(practice["targets"]),
                "concluded" if practice["concluded"] else "open",
                practice["statement"] or "(no statement)",
            )
        )

    nxt = fields["next"]
    if nxt is None:
        lines.append("next     none")
    else:
        lines.append("next     %d of %d nodes untouched" % (nxt["untouched"], nxt["total"]))

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# render (session.md)
# --------------------------------------------------------------------------


def _outline_lines(plan, visited, current):
    """Indented outline derived from edges: roots first, children nested."""
    nodes = plan.get("nodes") or []
    edges = plan.get("edges") or []

    by_id = {}
    order = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or node_id in by_id:
            continue
        by_id[node_id] = node
        order.append(node_id)

    children = {node_id: [] for node_id in order}
    has_parent = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = edge.get("from")
        target = edge.get("to")
        if source in children and target in children:
            children[source].append(target)
            has_parent.add(target)

    visited_set = set(visited)
    lines = []
    emitted = set()

    def walk(node_id, depth):
        if node_id in emitted:
            return
        emitted.add(node_id)
        node = by_id[node_id]
        if node_id == current:
            mark = "[>]"
        elif node_id in visited_set:
            mark = "[x]"
        else:
            mark = "[ ]"
        title = _one_line(node.get("title")) or node_id
        lines.append("%s- %s **%s** (%s)" % ("  " * depth, mark, title, node_id))
        for child in children[node_id]:
            walk(child, depth + 1)

    for node_id in order:
        if node_id not in has_parent:
            walk(node_id, 0)
    # Defensive: a plan that failed to mention a root still renders every node.
    for node_id in order:
        if node_id not in emitted:
            walk(node_id, 0)
    return lines


def _join_markdown(lines):
    out = []
    for line in lines:
        if line == "" and out and out[-1] == "":
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def _render_markdown(session_id, events):
    start = _start_event(events)
    kind = _kind(events)
    goal = _one_line(start.get("goal")) or session_id
    created = start.get("at") or "-"

    lines = ["# %s" % goal, ""]
    lines.append(
        "session %s | kind %s | phase %s | created %s"
        % (session_id, kind, _phase(events), created)
    )
    lines.append("")

    # -- Probe ------------------------------------------------------------
    lines += ["## Probe", ""]
    probe = _probe_event(events)
    if probe is None:
        lines.append("_No probe conclusion recorded._")
    else:
        strands = [entry for entry in (probe.get("strands") or []) if isinstance(entry, dict)]
        if strands:
            lines.append("| Strand | Assessment |")
            lines.append("| --- | --- |")
            for entry in strands:
                lines.append("| %s | %s |" % (_cell(entry.get("strand")), _cell(entry.get("assessment"))))
        else:
            lines.append("_No strands recorded._")
        if probe.get("summary"):
            lines += ["", _one_line(probe.get("summary"))]
    lines.append("")

    # -- Plan -------------------------------------------------------------
    lines += ["## Plan", ""]
    plan = _plan_event(events)
    if plan is None:
        lines.append("_No plan set._")
    else:
        nodes = plan.get("nodes") or []
        edges = plan.get("edges") or []
        lines.append(
            "Revision %s \u2014 %d nodes, %d edges."
            % (plan.get("revision", 1), len(nodes), len(edges))
        )
        lines.append("")
        outline = _outline_lines(plan, _visited_nodes(events), _current_node(events))
        if outline:
            lines.extend(outline)
        else:
            lines.append("_The plan has no nodes._")
    lines.append("")

    # -- Steps ------------------------------------------------------------
    lines += ["## Steps", ""]
    checks = _checks(events)
    answers = _answers_by_check(events)
    if not checks:
        lines.append("_No checks recorded._")
    else:
        for check in checks:
            heading = "### Check %s" % check.get("seq")
            if check.get("node"):
                heading += " \u2014 %s" % check.get("node")
            lines += [heading, ""]
            lines += [_one_line(check.get("question")) or "(no question)", ""]

            options = check.get("options")
            if isinstance(options, list) and options:
                for index, option in enumerate(options, 1):
                    lines.append("%d. %s" % (index, _one_line(option)))
                lines.append("")

            answer = answers.get(check.get("seq"))
            if answer is None:
                lines.append("- **Answered:** no")
            else:
                if isinstance(options, list) and options:
                    lines.append("- **Selected:** %s" % _selection_numbers(answer.get("selection")))
                else:
                    selection = answer.get("selection")
                    text = ""
                    if isinstance(selection, list):
                        text = ", ".join(_one_line(item) for item in selection if _one_line(item))
                    elif selection is not None:
                        text = _one_line(selection)
                    lines.append("- **Answer:** %s" % _quote(text))
                lines.append("- **Correct:** %s" % ("yes" if answer.get("correct") else "no"))
                lines.append("- **Confidence:** %s" % (answer.get("confidence"),))
                lines.append("- **Trace:** %s" % (_one_line(answer.get("trace")) or "\u2014"))

            if check.get("key"):
                lines += ["", "**Key:** %s" % _one_line(check.get("key"))]
            lines.append("")
    lines.append("")

    # -- Practice ---------------------------------------------------------
    problems = _typed(events, "practice_problem")
    conclusions = _typed(events, "practice_concluded")
    if kind == "practice" or problems or conclusions:
        lines += ["## Practice", ""]
        if not problems and not conclusions:
            lines.append("_No practice record yet._")
        for problem in problems:
            lines.append("**Statement:** %s" % (_one_line(problem.get("statement")) or "\u2014"))
            lines.append("")
            lines.append("- **Mode:** %s" % (_one_line(problem.get("mode")) or "\u2014"))
            targets = problem.get("target")
            if isinstance(targets, list) and targets:
                lines.append("- **Targets:** %s" % ", ".join(_one_line(item) for item in targets))
            else:
                lines.append("- **Targets:** \u2014")
            lines.append("")
            if problem.get("modelSolution"):
                lines.append("")
                lines.append("**Model solution:** %s" % _one_line(problem.get("modelSolution")))
        for conclusion in conclusions:
            lines.append("- **Outcome:** %s" % (_one_line(conclusion.get("outcome")) or "\u2014"))
            lines.append("- **Verdict:** %s" % (_one_line(conclusion.get("verdict")) or "\u2014"))
            lines.append("- **Rung:** %s" % (_one_line(conclusion.get("rung")) or "\u2014"))
            lines.append("- **Miss class:** %s" % (_one_line(conclusion.get("missClass")) or "\u2014"))
            if conclusion.get("work"):
                lines.append("- **Work:** %s" % _one_line(conclusion.get("work")))
            if isinstance(conclusion.get("retest"), bool):
                lines.append("- **Retest:** %s" % ("yes" if conclusion.get("retest") else "no"))
            lines.append("")
        lines.append("")

    # -- Session ----------------------------------------------------------
    lines += ["## Session", ""]
    closed = _closed_event(events)
    if closed is None:
        lines.append("- **Closed:** no")
    else:
        lines.append("- **Closed:** yes \u2014 %s" % (closed.get("at") or "-"))
        if isinstance(closed.get("nodes_written"), int):
            lines.append("- **Nodes written:** %d" % closed.get("nodes_written"))
        if isinstance(closed.get("chains_written"), int):
            lines.append("- **Chains written:** %d" % closed.get("chains_written"))

    return _join_markdown(lines)


# --------------------------------------------------------------------------
# input helpers
# --------------------------------------------------------------------------


def _read_text_file(path, label):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise Refusal("cannot read %s %s: %s" % (label, path, exc.strerror or exc))
    except UnicodeDecodeError as exc:
        raise Refusal("%s %s is not valid utf-8: %s" % (label, path, exc))


def _reject_constant(name):
    raise ValueError("non-finite number (%s) is not allowed" % name)


def _read_json_source(source, label):
    if source == "-":
        text = sys.stdin.read()
        origin = "stdin"
    else:
        text = _read_text_file(source, label)
        origin = source
    if not text.strip():
        raise Refusal("%s %s is empty" % (label, origin))
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        raise Refusal("%s %s is not valid json: %s" % (label, origin, exc))


def _read_json_text(text, label):
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        raise Refusal("%s is not valid json: %s" % (label, exc))

def _parse_options_json(text):
    try:
        value = json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        raise Refusal("--options-file is not valid json: %s" % exc)
    if not isinstance(value, list) or not value:
        raise Refusal("--options-file must contain a non-empty json array of strings")
    parts = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise Refusal("--options-file entries must be non-empty strings")
        parts.append(item.strip())
    return parts



def _parse_options(raw):
    if raw is None:
        return None
    parts = [part.strip() for part in str(raw).split(",")]
    if not parts or any(part == "" for part in parts):
        raise Refusal("--options must be a comma-separated list of non-empty options")
    return parts


def _parse_index_list(raw, label):
    if raw is None:
        return None
    parts = [part.strip() for part in str(raw).split(",") if part.strip() != ""]
    if not parts:
        raise Refusal("%s needs at least one 0-based index" % label)
    indices = []
    for part in parts:
        try:
            value = int(part)
        except ValueError:
            raise Refusal("%s must be comma-separated 0-based indices, got %r" % (label, part))
        if value < 0:
            raise Refusal("%s must not contain negative indices, got %d" % (label, value))
        if value in indices:
            raise Refusal("%s lists index %d twice" % (label, value))
        indices.append(value)
    return indices


def _parse_judgement(raw):
    text = str(raw).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    raise Refusal("--correct must be true or false for a free-recall check, got %r" % raw)


def _required_text(document, key, label):
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Refusal("%s needs a non-empty %r string" % (label, key))
    return value.strip()


def _string_list(value, label):
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise Refusal("%s must be a list of non-empty strings" % label)
    return [item.strip() for item in value]


def _load_plan_module():
    try:
        import plan as plan_module
    except ImportError as exc:
        raise Refusal("plan.py is not available beside session.py (%s); a plan cannot be validated" % exc)
    if not hasattr(plan_module, "validate"):
        raise Refusal("plan.py does not expose validate(document)")
    return plan_module


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def _mutable_events(root, session_id):
    events = require_session(root, session_id)
    if _closed_event(events) is not None:
        raise Refusal("session %s is already closed; the log is terminal" % session_id)
    return events


def cmd_init(root, args):
    goal = (args.goal or "").strip()
    if not goal:
        raise Refusal("init needs a non-empty --goal")
    if args.kind not in KINDS:
        raise Refusal("unknown --kind %r (expected one of: %s)" % (args.kind, ", ".join(KINDS)))
    ensure_format(root)
    sessions_dir(root).mkdir(parents=True, exist_ok=True)
    session_id = mint_session_id(set(list_session_ids(root)))
    session_dir(root, session_id).mkdir(parents=True)
    append_event(root, session_id, {"type": "session_start", "kind": args.kind, "goal": goal})
    sys.stdout.write(session_id + "\n")


def cmd_check(root, args):
    events = _mutable_events(root, args.session)

    open_check = _open_check(events)
    if open_check is not None:
        raise Refusal(
            "a check is already open (seq %s); answer it before posing another"
            % open_check.get("seq")
        )

    if args.key is not None and args.key_file is not None:
        raise Refusal("give either --key or --key-file, not both")
    if args.key is not None:
        key = args.key.strip()
    elif args.key_file is not None:
        key = _read_text_file(args.key_file, "--key-file").strip()
    else:
        raise Refusal("check needs the answer key before the question is asked (--key or --key-file)")
    if not key:
        raise Refusal("the answer key is empty")

    question = (args.question or "").strip()
    if not question:
        raise Refusal("check needs a non-empty --question")

    node = args.node
    if node is not None and node not in _plan_node_ids(events):
        raise Refusal("--node %r is not in the current plan" % node)

    if args.options is not None and args.options_file is not None:
        raise Refusal("give either --options or --options-file, not both")
    if args.options_file is not None:
        options = _parse_options_json(_read_text_file(args.options_file, "--options-file"))
    else:
        options = _parse_options(args.options)
    correct = _parse_index_list(args.correct, "--correct")
    if options is None and correct is not None:
        raise Refusal(
            "free-recall checks (no --options) take no --correct; correctness is recorded on answer"
        )
    if options is not None:
        if correct is None:
            raise Refusal("a check with --options needs --correct indices (0-based)")
        out_of_range = [index for index in correct if index >= len(options)]
        if out_of_range:
            raise Refusal(
                "--correct index %d is out of range for %d options"
                % (out_of_range[0], len(options))
            )

    event = {"type": "check_posed", "node": node, "question": question, "key": key}
    if options is not None:
        event["options"] = options
        event["correct"] = correct
    written = append_event(root, args.session, event)

    sys.stdout.write("posed check %s\n" % written.get("seq"))
    sys.stdout.write("question: %s\n" % question)
    if options is not None:
        for index, option in enumerate(options, 1):
            sys.stdout.write("%d. %s\n" % (index, option))


def cmd_answer(root, args):
    events = _mutable_events(root, args.session)

    open_check = _open_check(events)
    if open_check is None:
        raise Refusal("no check is open; pose one with check before answering")

    if args.select is not None and args.text is not None:
        raise Refusal("give either --select or --text, not both")

    keyed = isinstance(open_check.get("correct"), list)
    options = open_check.get("options")
    option_count = len(options) if isinstance(options, list) else 0

    if keyed:
        if args.correct is not None:
            raise Refusal(
                "this check has committed --correct indices; give --select and let the record grade it"
            )
        if args.select is None:
            raise Refusal("this check has keyed options; answer with --select 0,2")
        selection = _parse_index_list(args.select, "--select")
        out_of_range = [index for index in selection if index >= option_count]
        if out_of_range:
            raise Refusal(
                "selection index %d is out of range for %d options"
                % (out_of_range[0], option_count)
            )
        correct = sorted(selection) == sorted(open_check.get("correct") or [])
    else:
        if args.select is not None:
            raise Refusal("this check is free recall; answer with --text")
        if args.text is None or not args.text.strip():
            raise Refusal("this check is free recall; answer with a non-empty --text")
        if args.correct is None:
            raise Refusal("free-recall checks need the agent's judgement: --correct true|false")
        selection = [args.text.strip()]
        correct = _parse_judgement(args.correct)

    if args.confidence is None or not 1 <= args.confidence <= 5:
        raise Refusal("--confidence must be an integer from 1 to 5")

    trace = (args.trace or "").strip()
    if not trace:
        raise Refusal("answer needs a non-empty --trace")

    written = append_event(
        root,
        args.session,
        {
            "type": "answer",
            "check_seq": open_check.get("seq"),
            "selection": selection,
            "correct": correct,
            "confidence": args.confidence,
            "trace": trace,
        },
    )

    sys.stdout.write(
        "answered check %s: %s (confidence %s)\n"
        % (written.get("check_seq"), "correct" if correct else "incorrect", args.confidence)
    )


def _normalise_strands(document, summary_holder):
    if isinstance(document, list):
        entries = document
    elif isinstance(document, dict):
        entries = document.get("strands")
        if not summary_holder.get("summary") and isinstance(document.get("summary"), str):
            summary_holder["summary"] = document.get("summary")
    else:
        raise Refusal("strands must be a json list, or an object with a 'strands' list")

    if not isinstance(entries, list) or not entries:
        raise Refusal("the probe needs at least one strand")

    strands = []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise Refusal("strand %d must be a json object with 'strand' and 'assessment'" % index)
        name = entry.get("strand")
        assessment = entry.get("assessment")
        if not isinstance(name, str) or not name.strip():
            raise Refusal("strand %d needs a non-empty 'strand' string" % index)
        if not isinstance(assessment, str) or not assessment.strip():
            raise Refusal("strand %d needs a non-empty 'assessment' string" % index)
        strands.append({"strand": name.strip(), "assessment": assessment.strip()})
    return strands


def cmd_conclude_probe(root, args):
    events = _mutable_events(root, args.session)

    open_check = _open_check(events)
    if open_check is not None:
        raise Refusal(
            "cannot conclude the probe while check %s is open; answer it first"
            % open_check.get("seq")
        )
    if _probe_event(events) is not None:
        raise Refusal("the probe is already concluded; it is recorded at most once")

    if args.strands is not None and args.strands_json is not None:
        raise Refusal("give either --strands or --strands-json, not both")
    if args.strands is None and args.strands_json is None:
        raise Refusal("conclude-probe needs --strands FILE or --strands-json JSON")

    summary_holder = {"summary": args.summary}
    if args.strands is not None:
        document = _read_json_source(args.strands, "--strands")
    else:
        document = _read_json_text(args.strands_json, "--strands-json")

    strands = _normalise_strands(document, summary_holder)
    summary = (summary_holder.get("summary") or "").strip()

    event = {"type": "probe_concluded", "strands": strands}
    if summary:
        event["summary"] = summary
    written = append_event(root, args.session, event)

    if len(strands) > WARN_STRANDS:
        print_warnings(
            [
                "%d probe strands is above the advisory limit of %d"
                % (len(strands), WARN_STRANDS)
            ]
        )
    sys.stdout.write("probe concluded with %d strand(s)\n" % len(strands))


def cmd_plan_set(root, args):
    events = _mutable_events(root, args.session)

    document = _read_json_source(args.plan, "--plan")
    if not isinstance(document, dict):
        raise Refusal("--plan must contain a json object with 'nodes' and 'edges'")

    plan_module = _load_plan_module()
    try:
        result = plan_module.validate(document)
    except TypeError as exc:
        raise Refusal(str(exc))
    if not isinstance(result, tuple) or len(result) != 4:
        raise Refusal("plan.py validate() did not return (ok, error, warnings, node_ids)")
    ok, error, warnings, node_ids = result
    warnings = [str(item) for item in (warnings or [])]
    if not ok:
        raise Refusal(str(error) or "the plan is invalid")

    nodes = document.get("nodes") or []
    edges = document.get("edges") or []
    revisions = [event.get("revision", 0) for event in _typed(events, "plan_set")]
    revision = max(revisions) + 1 if revisions else 1

    append_event(
        root,
        args.session,
        {"type": "plan_set", "revision": revision, "nodes": nodes, "edges": edges},
    )

    if len(nodes) > WARN_PLAN_NODES and not any(
        "plan nodes" in warning.lower() for warning in warnings
    ):
        warnings.append(
            "%d plan nodes is above the advisory limit of %d"
            % (len(nodes), WARN_PLAN_NODES)
        )
    print_warnings(warnings)

    sys.stdout.write(
        "plan revision %s set: %d nodes, %d edges\n" % (revision, len(nodes), len(edges))
    )


def cmd_step_close(root, args):
    events = _mutable_events(root, args.session)

    if args.node not in _plan_node_ids(events):
        raise Refusal("--node %r is not in the current plan" % args.node)

    outcome = args.outcome or "held"
    append_event(
        root, args.session, {"type": "step_closed", "node": args.node, "outcome": outcome}
    )

    closed_steps = len(_typed(events, "step_closed")) + 1
    if closed_steps > WARN_STEPS:
        print_warnings(
            [
                "%d teaching steps is above the advisory limit of %d"
                % (closed_steps, WARN_STEPS)
            ]
        )
    sys.stdout.write("closed step %s: %s\n" % (args.node, outcome))


def cmd_practice_problem(root, args):
    events = _mutable_events(root, args.session)
    if _kind(events) != "practice":
        raise Refusal("practice-problem only applies to a practice session")

    document = _read_json_source(args.problem, "--problem")
    if not isinstance(document, dict):
        raise Refusal("--problem must contain a json object")

    statement = _required_text(document, "statement", "practice-problem")
    mode = _required_text(document, "mode", "practice-problem")
    model_solution = _required_text(document, "modelSolution", "practice-problem")
    targets = _string_list(document.get("target"), "practice-problem target")

    append_event(
        root,
        args.session,
        {
            "type": "practice_problem",
            "statement": statement,
            "mode": mode,
            "target": targets,
            "modelSolution": model_solution,
        },
    )
    sys.stdout.write("practice problem set: mode %s, %d target(s)\n" % (mode, len(targets)))


def cmd_practice_concluded(root, args):
    events = _mutable_events(root, args.session)
    if _kind(events) != "practice":
        raise Refusal("practice-concluded only applies to a practice session")

    document = _read_json_source(args.result, "--result")
    if not isinstance(document, dict):
        raise Refusal("--result must contain a json object")

    outcome = _required_text(document, "outcome", "practice-concluded")
    event = {"type": "practice_concluded", "outcome": outcome}
    for key in ("verdict", "rung", "missClass"):
        value = document.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise Refusal("practice-concluded: %r must be a non-empty string" % key)
        event[key] = value.strip()
    retest = document.get("retest")
    if retest is not None:
        if not isinstance(retest, bool):
            raise Refusal("practice-concluded: 'retest' must be true or false")
        event["retest"] = retest

    work = document.get("work")
    if work is not None:
        if not isinstance(work, str) or not work.strip():
            raise Refusal("practice-concluded: 'work' must be a non-empty string when given")
        event["work"] = work.strip()

    append_event(root, args.session, event)
    sys.stdout.write("practice concluded: %s\n" % outcome)


def cmd_close(root, args):
    events = require_session(root, args.session)
    if _closed_event(events) is not None:
        raise Refusal("session %s is already closed" % args.session)

    event = {"type": "session_closed"}
    for name in ("nodes_written", "chains_written"):
        value = getattr(args, name, None)
        if value is None:
            continue
        if value < 0:
            raise Refusal("--%s must not be negative" % name.replace("_", "-"))
        event[name] = value

    append_event(root, args.session, event)
    counts = ""
    if "nodes_written" in event or "chains_written" in event:
        counts = " (nodes %s, chains %s)" % (
            event.get("nodes_written", "-"),
            event.get("chains_written", "-"),
        )
    sys.stdout.write("closed session %s%s\n" % (args.session, counts))


def cmd_state(root, args):
    events = require_session(root, args.session)
    fields = _state_fields(args.session, events)
    if args.format == "json":
        print_json(fields)
    else:
        sys.stdout.write(_state_text(fields))


def cmd_render(root, args):
    events = require_session(root, args.session)
    text = _render_markdown(args.session, events)
    if args.write:
        session_markdown(root, args.session).write_text(text, encoding="utf-8")
    sys.stdout.write(text)


def cmd_list(root, args):
    rows = []
    for session_id in list_session_ids(root):
        try:
            events = load_events(root, session_id)
            start = _start_event(events)
        except Refusal as exc:
            sys.stderr.write("warning: skipping %s: %s\n" % (session_id, exc))
            continue
        plan = _plan_event(events)
        nodes = plan.get("nodes") if plan is not None else None
        node_count = len(nodes) if isinstance(nodes, list) else 0
        rows.append(
            (
                session_id,
                start.get("kind") or "-",
                _phase(events),
                node_count,
                _clip(start.get("goal"), 120),
            )
        )

    if not rows:
        sys.stdout.write("no sessions\n")
        return

    lines = ["%-14s %-9s %-9s %5s  %s" % ("ID", "KIND", "PHASE", "NODES", "GOAL")]
    for row in rows:
        lines.append("%-14s %-9s %-9s %5d  %s" % row)
    sys.stdout.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="session.py",
        description="The append-only learnharness session record.",
    )
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        default=None,
        help="record root (default: discover .learnharness upward from the cwd)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format for state (default: text)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    init_parser = subparsers.add_parser("init", help="start a session and print its id")
    init_parser.add_argument("--goal", required=True, metavar="TEXT")
    init_parser.add_argument("--kind", choices=KINDS, default="teach")
    init_parser.set_defaults(func=cmd_init)

    check_parser = subparsers.add_parser(
        "check", help="pose a check; the key is committed with the question"
    )
    check_parser.add_argument("--session", required=True, metavar="ID")
    check_parser.add_argument("--question", required=True, metavar="TEXT")
    check_parser.add_argument("--key", default=None, metavar="TEXT")
    check_parser.add_argument("--key-file", default=None, metavar="PATH")
    check_parser.add_argument("--node", default=None, metavar="ID")
    check_parser.add_argument("--options", default=None, metavar="a,b,c")
    check_parser.add_argument("--options-file", default=None, metavar="PATH")
    check_parser.add_argument("--correct", default=None, metavar="0,2")
    check_parser.set_defaults(func=cmd_check)

    answer_parser = subparsers.add_parser("answer", help="answer the open check")
    answer_parser.add_argument("--session", required=True, metavar="ID")
    answer_parser.add_argument("--select", default=None, metavar="0,2")
    answer_parser.add_argument("--text", default=None, metavar="TEXT")
    answer_parser.add_argument("--correct", default=None, metavar="true|false")
    answer_parser.add_argument("--confidence", type=int, required=True, metavar="1-5")
    answer_parser.add_argument("--trace", required=True, metavar="TEXT")
    answer_parser.set_defaults(func=cmd_answer)

    probe_parser = subparsers.add_parser(
        "conclude-probe", help="record the probe conclusion; allowed once"
    )
    probe_parser.add_argument("--session", required=True, metavar="ID")
    probe_parser.add_argument("--strands", default=None, metavar="FILE")
    probe_parser.add_argument("--strands-json", default=None, metavar="JSON")
    probe_parser.add_argument("--summary", default=None, metavar="TEXT")
    probe_parser.set_defaults(func=cmd_conclude_probe)

    plan_parser = subparsers.add_parser(
        "plan-set", help="validate a plan with plan.py and record a revision"
    )
    plan_parser.add_argument("--session", required=True, metavar="ID")
    plan_parser.add_argument("--plan", required=True, metavar="FILE|-")
    plan_parser.set_defaults(func=cmd_plan_set)

    step_parser = subparsers.add_parser("step-close", help="record that a teaching step finished")
    step_parser.add_argument("--session", required=True, metavar="ID")
    step_parser.add_argument("--node", required=True, metavar="ID")
    step_parser.add_argument("--outcome", choices=("held", "partial", "missed"), default=None)
    step_parser.set_defaults(func=cmd_step_close)

    problem_parser = subparsers.add_parser(
        "practice-problem", help="record a practice problem and its model solution up front"
    )
    problem_parser.add_argument("--session", required=True, metavar="ID")
    problem_parser.add_argument("--problem", required=True, metavar="FILE|-")
    problem_parser.set_defaults(func=cmd_practice_problem)

    practice_parser = subparsers.add_parser(
        "practice-concluded", help="record the practice outcome"
    )
    practice_parser.add_argument("--session", required=True, metavar="ID")
    practice_parser.add_argument("--result", required=True, metavar="FILE|-")
    practice_parser.set_defaults(func=cmd_practice_concluded)

    close_parser = subparsers.add_parser("close", help="append the terminal event")
    close_parser.add_argument("--session", required=True, metavar="ID")
    close_parser.add_argument("--nodes-written", type=int, default=None, metavar="N")
    close_parser.add_argument("--chains-written", type=int, default=None, metavar="M")
    close_parser.set_defaults(func=cmd_close)

    state_parser = subparsers.add_parser("state", help="print the bounded derived summary")
    state_parser.add_argument("--session", required=True, metavar="ID")
    state_parser.add_argument(
        "--format", choices=("text", "json"), default=argparse.SUPPRESS
    )
    state_parser.set_defaults(func=cmd_state)

    render_parser = subparsers.add_parser("render", help="emit session.md")
    render_parser.add_argument("--session", required=True, metavar="ID")
    render_parser.add_argument("--write", action="store_true", help="also write session.md")
    render_parser.set_defaults(func=cmd_render)

    list_parser = subparsers.add_parser("list", help="list sessions")
    list_parser.set_defaults(func=cmd_list)

    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    root = find_root(args.data_dir)
    args.func(root, args)


if __name__ == "__main__":
    run(main)
