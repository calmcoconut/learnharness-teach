"""Audit a record and report anything that breaks the contract.

Read-only. Exit 0 when clean, 1 when findings exist.

    python3 scripts/verify.py [--session ID] [--data-dir PATH] [--format text|json]

Checks the things the app would otherwise drop silently: malformed ledger lines,
unresolved chain endpoints, duplicate answers, a check posed without its key, more than
one open check, an invalid plan, and a graph format stamp this skill does not understand.
"""

import sys

sys.dont_write_bytecode = True

import argparse

import _data


def _load_plan_module():
    try:
        import plan  # noqa: WPS433  (local module beside this file)
    except Exception:
        return None
    return plan


def _has(record, key, kind):
    value = record.get(key)
    if kind == "str":
        return isinstance(value, str) and value.strip() != ""
    if kind == "list":
        return isinstance(value, list)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    return value is not None


def check_session(root, session_id):
    """Return a list of finding strings for one session."""
    findings = []
    events = _data.load_events(root, session_id)

    if not events:
        return ["%s: empty session log" % session_id]
    if events[0].get("type") != "session_start":
        findings.append("%s: first event is %r, not session_start" % (session_id, events[0].get("type")))

    # seq integrity
    expected = 1
    for event in events:
        seq = event.get("seq")
        if seq != expected:
            findings.append("%s: event seq %r where %d was expected" % (session_id, seq, expected))
            expected = (seq if isinstance(seq, int) else expected) + 1
        else:
            expected += 1

    checks = {}
    answered = {}
    open_checks = []
    probe_conclusions = 0
    plans = {}

    for event in events:
        kind = event.get("type")
        seq = event.get("seq")

        if kind == "check_posed":
            checks[seq] = event
            open_checks.append(seq)
            if not _has(event, "key", "str"):
                findings.append("%s: check at seq %s has no committed key" % (session_id, seq))
            if not _has(event, "question", "str"):
                findings.append("%s: check at seq %s has no question text" % (session_id, seq))
            correct = event.get("correct")
            if correct is not None:
                options = event.get("options")
                if not isinstance(options, list) or not options:
                    findings.append("%s: check at seq %s has correct indices but no options" % (session_id, seq))
                else:
                    for index in correct if isinstance(correct, list) else []:
                        if not isinstance(index, int) or index < 0 or index >= len(options):
                            findings.append(
                                "%s: check at seq %s has out-of-range correct index %r" % (session_id, seq, index)
                            )

        elif kind == "answer":
            target = event.get("check_seq")
            if target not in checks:
                findings.append("%s: answer at seq %s references unknown check %r" % (session_id, seq, target))
            elif target in answered:
                findings.append(
                    "%s: check %s answered twice (seq %s and %s)" % (session_id, target, answered[target], seq)
                )
            else:
                answered[target] = seq
                if target in open_checks:
                    open_checks.remove(target)
            confidence = event.get("confidence")
            if not isinstance(confidence, int) or not 1 <= confidence <= 5:
                findings.append("%s: answer at seq %s has confidence %r outside 1-5" % (session_id, seq, confidence))
            if not _has(event, "trace", "str"):
                findings.append("%s: answer at seq %s has no reasoning trace" % (session_id, seq))

        elif kind == "probe_concluded":
            probe_conclusions += 1
            if probe_conclusions > 1:
                findings.append("%s: probe concluded more than once" % session_id)
            if open_checks:
                findings.append(
                    "%s: probe concluded at seq %s while check %s was still open" % (session_id, seq, open_checks[-1])
                )
            strands = event.get("strands")
            if not isinstance(strands, list) or not strands:
                findings.append("%s: probe conclusion at seq %s has no strands" % (session_id, seq))
            else:
                if len(strands) > _data.WARN_STRANDS:
                    findings.append(
                        "%s: probe has %d strands (advisory limit %d)" % (session_id, len(strands), _data.WARN_STRANDS)
                    )
                for strand in strands:
                    if not isinstance(strand, dict) or not strand.get("strand") or not strand.get("assessment"):
                        findings.append("%s: probe strand at seq %s is missing strand or assessment" % (session_id, seq))

        elif kind == "plan_set":
            revision = event.get("revision")
            if revision in plans:
                findings.append("%s: plan revision %r recorded twice" % (session_id, revision))
            plans[revision] = event
            validator = _load_plan_module()
            document = {"nodes": event.get("nodes"), "edges": event.get("edges")}
            if validator is not None:
                ok, error, warnings, _ids = validator.validate(document)
                if not ok:
                    findings.append("%s: plan revision %r is invalid: %s" % (session_id, revision, error))
                for warning in warnings:
                    findings.append("%s: plan revision %r: %s" % (session_id, revision, warning))
            elif not isinstance(document["nodes"], list) or not document["nodes"]:
                findings.append("%s: plan revision %r has no nodes" % (session_id, revision))

        elif kind == "step_closed":
            node = event.get("node")
            current = plans[max(plans)] if plans else None
            known = {n.get("id") for n in (current or {}).get("nodes", []) if isinstance(n, dict)}
            if node not in known:
                findings.append("%s: step closed for %r which is not in the current plan" % (session_id, node))

        elif kind == "session_closed":
            if seq != events[-1].get("seq"):
                findings.append("%s: session_closed is not the last event" % session_id)

        elif kind not in (
            "session_start",
            "check_posed",
            "answer",
            "probe_concluded",
            "plan_set",
            "step_closed",
            "practice_problem",
            "practice_concluded",
            "session_closed",
        ):
            findings.append("%s: unknown event type %r at seq %s" % (session_id, kind, seq))

    if len(open_checks) > 1:
        findings.append("%s: %d checks are open at once: %s" % (session_id, len(open_checks), open_checks))

    steps_closed = [e for e in events if e.get("type") == "step_closed"]
    if len(steps_closed) > _data.WARN_STEPS:
        findings.append(
            "%s: %d teaching steps (advisory limit %d)" % (session_id, len(steps_closed), _data.WARN_STEPS)
        )

    return findings


def check_graph(root):
    findings = []

    try:
        _data.read_format(root)
    except _data.Refusal as exc:
        return [str(exc)]

    node_records, node_problems = _data.read_jsonl(_data.graph_dir(root) / "nodes.jsonl")
    for problem in node_problems:
        findings.append("nodes.jsonl: %s" % problem)

    chain_records, chain_problems = _data.read_jsonl(_data.graph_dir(root) / "chains.jsonl")
    for problem in chain_problems:
        findings.append("chains.jsonl: %s" % problem)

    node_ids = set()
    for index, record in enumerate(node_records, start=1):
        node_id = record.get("id")
        if not isinstance(node_id, str) or not _data.NODE_ID_RE.match(node_id):
            findings.append("nodes.jsonl line %d: bad id %r" % (index, node_id))
            continue
        node_ids.add(node_id)
        if not _has(record, "statement", "str"):
            findings.append("nodes.jsonl line %d (%s): empty statement" % (index, node_id))
        if not _has(record, "aliases", "list"):
            findings.append("nodes.jsonl line %d (%s): missing aliases array (the app drops this line)" % (index, node_id))
        if not _has(record, "provenance", "list"):
            findings.append(
                "nodes.jsonl line %d (%s): missing provenance array (the app drops this line)" % (index, node_id)
            )
        for point in record.get("provenance") or []:
            if not isinstance(point, dict) or not isinstance(point.get("chatId"), str) or not isinstance(
                point.get("messageId"), str
            ):
                findings.append("nodes.jsonl line %d (%s): malformed provenance point" % (index, node_id))

    for index, record in enumerate(chain_records, start=1):
        chain_id = record.get("id")
        if not isinstance(chain_id, str) or not _data.CHAIN_ID_RE.match(chain_id):
            findings.append("chains.jsonl line %d: bad id %r" % (index, chain_id))
        premises = record.get("premises")
        if not isinstance(premises, list) or not premises:
            findings.append("chains.jsonl line %d: empty premises" % index)
            continue
        conclusion = record.get("conclusion")
        for endpoint in [*premises, conclusion]:
            if endpoint not in node_ids:
                findings.append(
                    "chains.jsonl line %d (%s): endpoint %r does not resolve (the app drops this chain)"
                    % (index, chain_id, endpoint)
                )
        if len(premises) == 1 and premises[0] == conclusion:
            findings.append("chains.jsonl line %d: conclusion equals its sole premise" % index)

    return findings


def main():
    parser = argparse.ArgumentParser(description="Audit a learnharness record.")
    parser.add_argument("--session", help="limit session checks to one id")
    parser.add_argument("--data-dir", help="path to the .learnharness directory")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    root = _data.find_root(args.data_dir)

    if args.session:
        session_ids = [_data.validate_session_id(args.session)]
    else:
        session_ids = _data.list_session_ids(root)

    findings = []
    for session_id in session_ids:
        findings.extend(check_session(root, session_id))
    findings.extend(check_graph(root))

    if args.format == "json":
        _data.print_json({"ok": not findings, "sessions": session_ids, "findings": findings})
    else:
        if not session_ids and not findings:
            print("no sessions and no graph under %s" % root)
        for finding in findings:
            print("- %s" % finding)
        if findings:
            print("\n%d finding(s)" % len(findings))
        else:
            print("ok: %d session(s) and the graph are consistent" % len(session_ids))

    raise SystemExit(1 if findings else 0)


if __name__ == "__main__":
    _data.run(main)
