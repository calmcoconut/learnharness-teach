"""Audit a record and report anything that breaks the contract.

Read-only. Exit 0 when there are no findings, 1 when a structural violation exists.

    python3 scripts/verify.py [--session ID] [--data-dir PATH] [--format text|json]

Two kinds of message, deliberately kept apart:

* **findings** — the record breaks the contract. They set ``ok`` to false and the exit
  code to 1.
* **warnings** — an advisory limit was exceeded (probe strands, plan nodes, teaching
  steps). They are printed to stderr as ``warning: …`` and carried in the ``warnings``
  list of ``--format json``. They never appear in ``findings`` and never change the exit
  code: ``SKILL.md`` and ``PLAN.md`` §7 make size advisory, so a large but legitimate
  record must still pass the audit and remain exportable.

Checks the things the app would otherwise drop silently: malformed ledger lines,
unresolved chain endpoints, duplicate answers, a check posed without its key, more than
one open check, a check left open by the close, an invalid plan, practice events in the
wrong kind of session or with malformed values, and a graph format stamp this skill does
not understand.
"""

import sys

sys.dont_write_bytecode = True

import argparse

import _data

# Practice sessions measure; they never teach. Teach sessions never run practice.
TEACHING_EVENT_TYPES = ("check_posed", "probe_concluded", "plan_set", "step_closed")
PRACTICE_EVENT_TYPES = ("practice_problem", "practice_concluded")

PROBLEM_MODES = ("recall", "discrimination", "composition")
PRACTICE_OUTCOMES = ("solved", "solvedWithHints", "movedOn", "surrendered", "dismissed")
PRACTICE_RUNGS = ("R0", "R1", "R2", "R3", "R4", "R5")
PRACTICE_MISS_CLASSES = ("cue", "discrimination", "execution", "careless", "structural")

EVENT_TYPES = (
    "session_start",
    "check_posed",
    "answer",
    "probe_concluded",
    "plan_set",
    "step_closed",
    "practice_problem",
    "practice_concluded",
    "session_closed",
)


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


def _is_int(value):
    """A JSON integer: bool is an int in Python and a boolean in JSON, so exclude it."""
    return isinstance(value, int) and not isinstance(value, bool)


def _json_type(value):
    """Name a decoded JSON value the way the data-format reference names it."""
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


def _session_kind(events):
    for event in events:
        if event.get("type") == "session_start":
            return event.get("kind")
    return None


def _check_seq(events, session_id, findings):
    """Seq must start at 1 and increase by one, with no gaps and no repeats."""
    expected = 1
    for event in events:
        seq = event.get("seq")
        if seq != expected:
            findings.append("%s: event seq %r where %d was expected" % (session_id, seq, expected))
            expected = (seq if _is_int(seq) else expected) + 1
        else:
            expected += 1


def _check_check_posed(event, session_id, checks, open_checks, findings):
    seq = event.get("seq")
    checks[seq] = event
    open_checks.append(seq)
    if not _has(event, "key", "str"):
        findings.append("%s: check at seq %s has no committed key" % (session_id, seq))
    if not _has(event, "question", "str"):
        findings.append("%s: check at seq %s has no question text" % (session_id, seq))

    correct = event.get("correct")
    if correct is None:
        return
    options = event.get("options")
    if not isinstance(correct, list):
        findings.append(
            "%s: check at seq %s has correct %r of type %s, not an array of option indices"
            % (session_id, seq, correct, _json_type(correct))
        )
    elif not isinstance(options, list) or not options:
        findings.append("%s: check at seq %s has correct indices but no options" % (session_id, seq))
    else:
        for index in correct:
            if not _is_int(index) or index < 0 or index >= len(options):
                findings.append(
                    "%s: check at seq %s has out-of-range correct index %r" % (session_id, seq, index)
                )


def _check_answer(event, session_id, checks, answered, open_checks, findings):
    seq = event.get("seq")
    target = event.get("check_seq")
    # Type-check before the set lookup: a dict or list check_seq is unhashable and would
    # otherwise raise TypeError out of the auditor.
    if not _is_int(target) or target not in checks:
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
    if not _is_int(confidence) or not 1 <= confidence <= 5:
        findings.append("%s: answer at seq %s has confidence %r outside 1-5" % (session_id, seq, confidence))
    if not _has(event, "trace", "str"):
        findings.append("%s: answer at seq %s has no reasoning trace" % (session_id, seq))


def _check_probe_concluded(event, session_id, open_checks, conclusions, findings, warnings):
    seq = event.get("seq")
    if conclusions > 1:
        findings.append("%s: probe concluded more than once" % session_id)
    if open_checks:
        findings.append(
            "%s: probe concluded at seq %s while check %s was still open" % (session_id, seq, open_checks[-1])
        )

    strands = event.get("strands")
    if not isinstance(strands, list) or not strands:
        findings.append("%s: probe conclusion at seq %s has no strands" % (session_id, seq))
        return

    if len(strands) > _data.WARN_STRANDS:
        # Advisory only: exceeding the limit never fails the audit.
        warnings.append(
            "%s: probe has %d strands, above the advisory limit of %d; the probe is not refused"
            % (session_id, len(strands), _data.WARN_STRANDS)
        )
    for strand in strands:
        if not isinstance(strand, dict) or not _has(strand, "strand", "str") or not _has(
            strand, "assessment", "str"
        ):
            findings.append("%s: probe strand at seq %s is missing strand or assessment" % (session_id, seq))


def _check_plan_set(event, session_id, plans, findings, warnings):
    seq = event.get("seq")
    revision = event.get("revision")
    if not _is_int(revision):
        findings.append(
            "%s: plan at seq %s has revision %r of type %s, not an integer"
            % (session_id, seq, revision, _json_type(revision))
        )
    else:
        if revision in plans:
            findings.append("%s: plan revision %r recorded twice" % (session_id, revision))
        plans[revision] = event

    validator = _load_plan_module()
    document = {"nodes": event.get("nodes"), "edges": event.get("edges")}
    if validator is None:
        if not isinstance(document["nodes"], list) or not document["nodes"]:
            findings.append("%s: plan revision %r has no nodes" % (session_id, revision))
        return
    try:
        ok, error, plan_warnings, _ids = validator.validate(document)
    except (TypeError, ValueError) as exc:
        findings.append("%s: plan revision %r could not be validated: %s" % (session_id, revision, exc))
        return
    if not ok:
        findings.append("%s: plan revision %r is invalid: %s" % (session_id, revision, error))
    for warning in plan_warnings:
        # plan.py already treats these as advisory; the auditor must not upgrade them.
        warnings.append("%s: plan revision %r: %s" % (session_id, revision, warning))


def _check_step_closed(event, session_id, plans, findings):
    node = event.get("node")
    if not isinstance(node, str) or not node.strip():
        findings.append(
            "%s: step_closed at seq %s has node %r of type %s, not a plan node id"
            % (session_id, event.get("seq"), node, _json_type(node))
        )
        return
    current = plans[max(plans)] if plans else None
    nodes = (current or {}).get("nodes")
    # Only a real array can be walked; a malformed plan node list must not raise here.
    known = {n.get("id") for n in nodes if isinstance(n, dict)} if isinstance(nodes, list) else set()
    if node not in known:
        findings.append("%s: step closed for %r which is not in the current plan" % (session_id, node))


def _check_practice_problem(event, session_id, findings):
    seq = event.get("seq")
    for key in ("statement", "mode", "modelSolution"):
        if not _has(event, key, "str"):
            findings.append("%s: practice_problem at seq %s has no %s" % (session_id, seq, key))

    mode = event.get("mode")
    if isinstance(mode, str) and mode.strip() and mode not in PROBLEM_MODES:
        findings.append(
            "%s: practice_problem at seq %s has unknown mode %r (expected one of %s)"
            % (session_id, seq, mode, ", ".join(PROBLEM_MODES))
        )

    target = event.get("target")
    if not isinstance(target, list) or not target:
        findings.append("%s: practice_problem at seq %s has an empty target" % (session_id, seq))
        return
    for entry in target:
        if not isinstance(entry, str) or not entry.strip():
            findings.append(
                "%s: practice_problem at seq %s has target entry %r, which is not a node id string"
                % (session_id, seq, entry)
            )


def _check_practice_concluded(event, session_id, findings):
    seq = event.get("seq")

    outcome = event.get("outcome")
    if outcome is None:
        findings.append("%s: practice_concluded at seq %s has no outcome" % (session_id, seq))
    elif not isinstance(outcome, str) or outcome not in PRACTICE_OUTCOMES:
        findings.append(
            "%s: practice_concluded at seq %s has unknown outcome %r (expected one of %s)"
            % (session_id, seq, outcome, ", ".join(PRACTICE_OUTCOMES))
        )

    rung = event.get("rung")
    if rung is not None and (not isinstance(rung, str) or rung not in PRACTICE_RUNGS):
        findings.append(
            "%s: practice_concluded at seq %s has unknown rung %r (expected null or one of %s)"
            % (session_id, seq, rung, ", ".join(PRACTICE_RUNGS))
        )

    miss_class = event.get("missClass")
    if miss_class is not None and (
        not isinstance(miss_class, str) or miss_class not in PRACTICE_MISS_CLASSES
    ):
        findings.append(
            "%s: practice_concluded at seq %s has unknown missClass %r (expected null or one of %s)"
            % (session_id, seq, miss_class, ", ".join(PRACTICE_MISS_CLASSES))
        )

    retest = event.get("retest")
    if not isinstance(retest, bool):
        findings.append(
            "%s: practice_concluded at seq %s has retest %r of type %s, not true or false"
            % (session_id, seq, retest, _json_type(retest))
        )


def check_session(root, session_id):
    """Return ``(findings, warnings)`` for one session."""
    try:
        events = _data.load_events(root, session_id)
    except _data.Refusal as exc:
        # A damaged log is a finding, not a traceback out of the auditor.
        return (["%s: %s" % (session_id, exc)], [])

    if not events:
        return (["%s: empty session log" % session_id], [])

    findings = []
    warnings = []

    if events[0].get("type") != "session_start":
        findings.append("%s: first event is %r, not session_start" % (session_id, events[0].get("type")))

    kind = _session_kind(events)
    if kind not in _data.KINDS:
        findings.append(
            "%s: session_start kind is %r, not one of %s" % (session_id, kind, ", ".join(_data.KINDS))
        )

    _check_seq(events, session_id, findings)

    checks = {}
    answered = {}
    open_checks = []
    probe_conclusions = 0
    plans = {}
    steps_closed = 0

    for event in events:
        event_type = event.get("type")
        seq = event.get("seq")

        if kind == "practice" and event_type in TEACHING_EVENT_TYPES:
            findings.append(
                "%s: practice session has a %s at seq %s; practice does not teach"
                % (session_id, event_type, seq)
            )
        if kind == "teach" and event_type in PRACTICE_EVENT_TYPES:
            findings.append(
                "%s: teach session has a %s at seq %s; practice events belong to practice sessions"
                % (session_id, event_type, seq)
            )

        if event_type == "check_posed":
            _check_check_posed(event, session_id, checks, open_checks, findings)
        elif event_type == "answer":
            _check_answer(event, session_id, checks, answered, open_checks, findings)
        elif event_type == "probe_concluded":
            probe_conclusions += 1
            _check_probe_concluded(event, session_id, open_checks, probe_conclusions, findings, warnings)
        elif event_type == "plan_set":
            _check_plan_set(event, session_id, plans, findings, warnings)
        elif event_type == "step_closed":
            steps_closed += 1
            _check_step_closed(event, session_id, plans, findings)
        elif event_type == "practice_problem":
            _check_practice_problem(event, session_id, findings)
        elif event_type == "practice_concluded":
            _check_practice_concluded(event, session_id, findings)
        elif event_type == "session_closed":
            if seq != events[-1].get("seq"):
                findings.append("%s: session_closed is not the last event" % session_id)
            if open_checks:
                findings.append(
                    "%s: session_closed at seq %s while check %s is still open; the close strands the check"
                    % (session_id, seq, open_checks[-1])
                )
        elif event_type not in EVENT_TYPES:
            findings.append("%s: unknown event type %r at seq %s" % (session_id, event_type, seq))

    if len(open_checks) > 1:
        findings.append("%s: %d checks are open at once: %s" % (session_id, len(open_checks), open_checks))

    if steps_closed > _data.WARN_STEPS:
        # Advisory only: a long session is still a valid record.
        warnings.append(
            "%s: %d teaching steps, above the advisory limit of %d; no step is refused"
            % (session_id, steps_closed, _data.WARN_STEPS)
        )

    return (findings, warnings)


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
            findings.append(
                "nodes.jsonl line %d (%s): aliases is missing or not an array (the app drops this line)"
                % (index, node_id)
            )
        provenance = record.get("provenance")
        if not isinstance(provenance, list):
            findings.append(
                "nodes.jsonl line %d (%s): provenance is missing or not an array (the app drops this line)"
                % (index, node_id)
            )
            continue
        for point in provenance:
            if (
                not isinstance(point, dict)
                or not isinstance(point.get("chatId"), str)
                or not isinstance(point.get("messageId"), str)
            ):
                findings.append(
                    "nodes.jsonl line %d (%s): malformed provenance point %r" % (index, node_id, point)
                )

    for index, record in enumerate(chain_records, start=1):
        chain_id = record.get("id")
        if not isinstance(chain_id, str) or not _data.CHAIN_ID_RE.match(chain_id):
            findings.append("chains.jsonl line %d: bad id %r" % (index, chain_id))

        premises = record.get("premises")
        if not isinstance(premises, list):
            findings.append(
                "chains.jsonl line %d (%s): premises is of type %s, not an array"
                % (index, chain_id, _json_type(premises))
            )
            continue
        if not premises:
            findings.append("chains.jsonl line %d: empty premises" % index)
            continue

        conclusion = record.get("conclusion")
        endpoints = [*premises, conclusion]

        # Type-check every endpoint before the set lookup. A dict or list endpoint is
        # unhashable, so `endpoint in node_ids` would raise TypeError instead of reporting.
        for endpoint in endpoints:
            if not isinstance(endpoint, str):
                findings.append(
                    "chains.jsonl line %d (%s): malformed endpoint %r of type %s, not a node id"
                    % (index, chain_id, endpoint, _json_type(endpoint))
                )
        for endpoint in endpoints:
            if isinstance(endpoint, str) and endpoint not in node_ids:
                findings.append(
                    "chains.jsonl line %d (%s): endpoint %r does not resolve (the app drops this chain)"
                    % (index, chain_id, endpoint)
                )

        if len(premises) == 1 and isinstance(premises[0], str) and premises[0] == conclusion:
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
    warnings = []
    for session_id in session_ids:
        session_findings, session_warnings = check_session(root, session_id)
        findings.extend(session_findings)
        warnings.extend(session_warnings)
    findings.extend(check_graph(root))

    if args.format == "json":
        _data.print_json(
            {
                "ok": not findings,
                "sessions": session_ids,
                "findings": findings,
                "warnings": warnings,
            }
        )
    else:
        # Advisories go to stderr and are never counted as findings.
        _data.print_warnings(warnings)
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
