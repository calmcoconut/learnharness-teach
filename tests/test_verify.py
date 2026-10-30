"""`verify.py` must audit a record without crashing, and must not refuse a legitimate one.

`PLAN.md` §5.5 and §7 make probe/plan/step size advisory: a large but legitimate record
passes `conclude-probe` with a warning, so it must also pass the audit and stay exportable.
The rest of these tests are about malformed input — the auditor reports it as a finding and
never raises, and practice records get checked at all.
"""

import json
import sys
import unittest

sys.dont_write_bytecode = True

import _helpers

AT = "2026-01-14T09:30:00Z"
SESSION = "lh_testsess"

NODE_ID = "n_a1b2c3d4e5f6"
SECOND_NODE_ID = "n_0f1e2d3c4b5a"
CHAIN_ID = "arg_001122334455"

TEACH_NODES = [
    {"id": "counting", "title": "Entropy counts"},
    {"id": "irreversibility", "title": "Why one direction"},
    {"id": "second-law", "title": "The second law"},
]
TEACH_EDGES = [
    {"from": "counting", "to": "irreversibility"},
    {"from": "irreversibility", "to": "second-law"},
]


# --------------------------------------------------------------------------
# record builders
# --------------------------------------------------------------------------


def event(seq, event_type, **fields):
    record = {"seq": seq, "at": AT, "type": event_type}
    record.update(fields)
    return record


def session_start(kind="teach", seq=1, goal="understand entropy"):
    return event(seq, "session_start", kind=kind, goal=goal)


def check_posed(seq, node=None, key="Because multiplicity.", **extra):
    fields = {"node": node, "question": "Why is 50 heads the likely count?", "key": key}
    fields.update(extra)
    return event(seq, "check_posed", **fields)


def answer(seq, check_seq, confidence=4, **extra):
    fields = {
        "check_seq": check_seq,
        "selection": ["because there are more ways to arrange it"],
        "correct": True,
        "confidence": confidence,
        "trace": "more arrangements give that total",
    }
    fields.update(extra)
    return event(seq, "answer", **fields)


def probe_concluded(seq, strands=None, summary="measured"):
    strands = (
        strands
        if strands is not None
        else [
            {"strand": "entropy as counting", "assessment": "holds"},
            {"strand": "irreversibility", "assessment": "not held"},
        ]
    )
    return event(seq, "probe_concluded", strands=strands, summary=summary)


def plan_set(seq, nodes=None, edges=None, revision=1):
    return event(
        seq,
        "plan_set",
        revision=revision,
        nodes=TEACH_NODES if nodes is None else nodes,
        edges=TEACH_EDGES if edges is None else edges,
    )


def step_closed(seq, node="irreversibility", outcome="held"):
    return event(seq, "step_closed", node=node, outcome=outcome)


def node_line(node_id=NODE_ID, statement="Entropy is a count", **over):
    record = {
        "id": node_id,
        "name": "Entropy is a count",
        "statement": statement,
        "aliases": [],
        "createdAt": AT,
        "provenance": [{"chatId": SESSION, "messageId": "2"}],
    }
    record.update(over)
    return record


def chain_line(premises=None, conclusion=SECOND_NODE_ID, chain_id=CHAIN_ID, **over):
    record = {
        "id": chain_id,
        "premises": [NODE_ID] if premises is None else premises,
        "conclusion": conclusion,
        "provenance": [{"chatId": SESSION, "messageId": "2"}],
        "createdAt": AT,
    }
    record.update(over)
    return record


def clean_graph():
    nodes = [
        node_line(),
        node_line(node_id=SECOND_NODE_ID, statement="Entropy is the logarithm of the microstate count."),
    ]
    return (nodes, [chain_line()])


def clean_teach_events():
    return [
        session_start(),
        check_posed(2),
        answer(3, 2),
        probe_concluded(4),
        plan_set(5),
        check_posed(6, node="irreversibility"),
        answer(7, 6),
        step_closed(8),
        event(9, "session_closed", nodes_written=2, chains_written=1),
    ]


def clean_practice_events():
    return [
        session_start(kind="practice", goal="make the second law usable"),
        event(
            2,
            "practice_problem",
            statement="A fridge moves heat from cold to hot. Does it violate the second law?",
            mode="discrimination",
            target=["second-law"],
            modelSolution="No; the fridge spends work, so total entropy still rises.",
        ),
        event(
            3,
            "practice_concluded",
            outcome="solvedWithHints",
            verdict="got there after being asked what the second law applies to",
            rung="R2",
            missClass="discrimination",
            retest=True,
        ),
        event(4, "session_closed"),
    ]


def matching(findings, *needles):
    return [finding for finding in findings if all(needle in finding for needle in needles)]


def assert_finding(case, findings, *needles):
    if not matching(findings, *needles):
        case.fail("no finding mentions %r; got:\n  %s" % (needles, "\n  ".join(findings)))


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------


class VerifyTestCase(unittest.TestCase):
    def setUp(self):
        self.project = _helpers.TempProject()
        self.project.__enter__()
        self.addCleanup(self.project.__exit__, None, None, None)
        self.root = self.project.root

    # -- builders --------------------------------------------------------

    def write_session(self, events, session_id=SESSION):
        self.project.write_events(session_id, events)

    def write_graph(self, nodes=(), chains=(), version=None):
        if nodes:
            _helpers.write_jsonl(self.root / "graph" / "nodes.jsonl", list(nodes))
        if chains:
            _helpers.write_jsonl(self.root / "graph" / "chains.jsonl", list(chains))
        if version is not None:
            _helpers.write_json_file(
                self.root / "graph" / "format.json", {"version": version, "writer": "test"}
            )

    # -- audits ----------------------------------------------------------

    def audit(self, *args):
        return _helpers.run_script("verify.py", ["--data-dir", self.root, *args])

    def audit_json(self, *args):
        code, out, err = self.audit("--format", "json", *args)
        self.assertNotIn("Traceback", err, "verify.py crashed:\n%s" % err)
        try:
            payload = json.loads(out)
        except ValueError:
            self.fail("verify.py printed no json\nstdout: %r\nstderr: %r" % (out, err))
        return code, payload, err

    def findings(self, *args):
        """Audit, require a refusal, and return the findings."""
        code, payload, err = self.audit_json(*args)
        self.assertEqual(code, 1, "expected findings, got %r" % (payload,))
        self.assertFalse(payload["ok"], payload)
        self.assertTrue(payload["findings"], payload)
        self.assertNotIn("Traceback", err)
        return payload["findings"]


# --------------------------------------------------------------------------
# clean records
# --------------------------------------------------------------------------


class CleanRecordTest(VerifyTestCase):
    def test_clean_teach_record_exits_zero_with_no_findings(self):
        self.write_session(clean_teach_events())
        nodes, chains = clean_graph()
        self.write_graph(nodes, chains)

        code, out, err = self.audit()
        self.assertEqual(code, 0, out + err)
        self.assertIn("consistent", out)

        code, payload, _err = self.audit_json()
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["findings"], [])
        self.assertEqual(payload["warnings"], [])

    def test_clean_practice_record_exits_zero_with_no_findings(self):
        self.write_session(clean_practice_events())
        code, payload, err = self.audit_json()
        self.assertEqual(code, 0, err)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["findings"], [])

    def test_auditing_writes_nothing(self):
        self.write_session(clean_teach_events())
        nodes, chains = clean_graph()
        self.write_graph(nodes, chains)
        before = _helpers.snapshot(self.root)
        self.audit()
        self.audit_json()
        self.assertEqual(_helpers.snapshot(self.root), before)


# --------------------------------------------------------------------------
# advisories are not findings (H3)
# --------------------------------------------------------------------------


class AdvisoryTest(VerifyTestCase):
    def test_nine_strands_and_sixteen_nodes_warn_but_pass(self):
        strands = [{"strand": "strand %d" % number, "assessment": "holds"} for number in range(9)]
        nodes = [{"id": "node-%02d" % number, "title": "Node %d" % number} for number in range(1, 17)]
        events = [session_start(), probe_concluded(2, strands=strands), plan_set(3, nodes=nodes, edges=[])]
        self.write_session(events)

        code, out, err = self.audit()
        self.assertEqual(code, 0, out + err)
        self.assertIn("consistent", out)
        self.assertNotIn("strand", out, "an advisory must not be printed as a finding")
        self.assertIn("warning:", err)
        self.assertIn("strand", err)

        code, payload, _err = self.audit_json()
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["findings"], [])
        self.assertEqual(len(payload["warnings"]), 2, payload)
        assert_finding(self, payload["warnings"], "9 strands")
        assert_finding(self, payload["warnings"], "16 plan nodes")

    def test_twenty_one_steps_warn_but_pass(self):
        events = [session_start(), plan_set(2, nodes=[{"id": "counting", "title": "Counting"}], edges=[])]
        seq = 3
        for _ in range(21):
            events.append(step_closed(seq, node="counting"))
            seq += 1
        events.append(event(seq, "session_closed"))
        self.write_session(events)

        code, payload, err = self.audit_json()
        self.assertEqual(code, 0, err)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["findings"], [])
        assert_finding(self, payload["warnings"], "21 teaching steps")


# --------------------------------------------------------------------------
# malformed ledgers (M10)
# --------------------------------------------------------------------------


class MalformedGraphTest(VerifyTestCase):
    def test_malformed_chain_endpoint_is_a_finding_not_a_crash(self):
        for bad in ({"id": NODE_ID}, [NODE_ID], None):
            for position in ("premise", "conclusion"):
                with self.subTest(endpoint=bad, position=position):
                    nodes = [
                        node_line(),
                        node_line(node_id=SECOND_NODE_ID, statement="Entropy is a logarithm."),
                    ]
                    chains = (
                        [chain_line(premises=[bad])] if position == "premise" else [chain_line(conclusion=bad)]
                    )
                    self.write_graph(nodes, chains)
                    assert_finding(self, self.findings(), "chains.jsonl line 1", "malformed endpoint")

    def test_premises_that_are_not_an_array(self):
        for premises in ({"a": NODE_ID}, NODE_ID, 3, None):
            with self.subTest(premises=premises):
                chain = chain_line()
                chain["premises"] = premises
                self.write_graph([node_line()], [chain])
                assert_finding(self, self.findings(), "chains.jsonl line 1", "not an array")

    def test_dangling_chain_endpoint(self):
        self.write_graph([node_line()], [chain_line(premises=["n_ffffffffffff"])])
        assert_finding(self, self.findings(), "chains.jsonl line 1", "does not resolve")

    def test_node_line_missing_aliases(self):
        record = node_line()
        del record["aliases"]
        self.write_graph([record])
        assert_finding(self, self.findings(), "nodes.jsonl line 1", "aliases")

    def test_node_line_missing_provenance(self):
        record = node_line()
        del record["provenance"]
        self.write_graph([record])
        assert_finding(self, self.findings(), "nodes.jsonl line 1", "provenance")

    def test_malformed_provenance_is_a_finding_not_a_crash(self):
        for provenance in (5, "lh_testsess", {"chatId": SESSION}, ["lh_testsess"]):
            with self.subTest(provenance=provenance):
                self.write_graph([node_line(provenance=provenance)])
                assert_finding(self, self.findings(), "nodes.jsonl line 1", "provenance")

    def test_malformed_node_id_is_a_finding_not_a_crash(self):
        for bad in ({"id": NODE_ID}, [NODE_ID], None):
            with self.subTest(node_id=bad):
                self.write_graph([node_line(id=bad)])
                assert_finding(self, self.findings(), "nodes.jsonl line 1", "bad id")

    def test_format_version_two_is_refused(self):
        for version in (2, 2.0):
            with self.subTest(version=version):
                self.write_graph(version=version)
                assert_finding(self, self.findings(), "format")


# --------------------------------------------------------------------------
# malformed session logs
# --------------------------------------------------------------------------


class MalformedSessionTest(VerifyTestCase):
    def test_duplicate_seq(self):
        self.write_session([session_start(), plan_set(2), plan_set(2, revision=2)])
        assert_finding(self, self.findings(), "event seq 2 where 3 was expected")

    def test_two_open_checks(self):
        self.write_session([session_start(), check_posed(2), check_posed(3)])
        assert_finding(self, self.findings(), "2 checks are open at once")

    def test_answer_to_an_unknown_check(self):
        for target in (99, {"seq": 2}, [2], None):
            with self.subTest(check_seq=target):
                self.write_session([session_start(), check_posed(2), answer(3, target)])
                assert_finding(self, self.findings(), "answer at seq 3", "unknown check")

    def test_probe_concluded_twice(self):
        self.write_session([session_start(), probe_concluded(2), probe_concluded(3)])
        assert_finding(self, self.findings(), "probe concluded more than once")

    def test_invalid_plan(self):
        self.write_session([session_start(), plan_set(2, nodes=[])])
        assert_finding(self, self.findings(), "is invalid")

    def test_plan_revision_that_is_not_an_integer(self):
        for revision in ({"revision": 1}, [1], "one"):
            with self.subTest(revision=revision):
                self.write_session([session_start(), plan_set(2, revision=revision)])
                assert_finding(self, self.findings(), "revision", "integer")

    def test_step_closed_for_an_absent_node(self):
        self.write_session([session_start(), plan_set(2), step_closed(3, node="ghost")])
        assert_finding(self, self.findings(), "step closed for 'ghost'", "current plan")

    def test_step_closed_with_a_malformed_node(self):
        for node in ({"id": "ghost"}, ["ghost"], None):
            with self.subTest(node=node):
                self.write_session([session_start(), plan_set(2), step_closed(3, node=node)])
                assert_finding(self, self.findings(), "step_closed at seq 3", "plan node id")

    def test_closed_session_with_an_open_check(self):
        self.write_session([session_start(), check_posed(2), event(3, "session_closed")])
        assert_finding(self, self.findings(), "session_closed at seq 3", "still open")

    def test_damaged_session_log_is_a_finding(self):
        path = self.root / "sessions" / SESSION / "session.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        good = '{"seq":1,"at":"%s","type":"session_start","kind":"teach","goal":"g"}\n' % AT
        path.write_text(good + "not json\n", encoding="utf-8")
        assert_finding(self, self.findings(), "damaged")


# --------------------------------------------------------------------------
# practice records (M6)
# --------------------------------------------------------------------------


class PracticeTest(VerifyTestCase):
    def practice_session(self, *after_start):
        return [session_start(kind="practice", goal="make the second law usable"), *after_start]

    def practice_problem(self, **over):
        fields = {
            "statement": "Does a fridge violate the second law?",
            "mode": "recall",
            "target": ["second-law"],
            "modelSolution": "No; it spends work.",
        }
        fields.update(over)
        return event(2, "practice_problem", **fields)

    def practice_concluded(self, **over):
        fields = {"outcome": "solved", "rung": None, "missClass": None, "retest": False}
        fields.update(over)
        return event(2, "practice_concluded", **fields)

    def test_practice_session_cannot_teach(self):
        teaching = {
            "check_posed": check_posed(2),
            "probe_concluded": probe_concluded(2),
            "plan_set": plan_set(2),
            "step_closed": step_closed(2),
        }
        for event_type, record in teaching.items():
            with self.subTest(event_type=event_type):
                self.write_session(self.practice_session(record))
                assert_finding(self, self.findings(), "practice does not teach", event_type)

    def test_teach_session_cannot_practice(self):
        self.write_session(
            [session_start(), self.practice_problem(), self.practice_concluded()]
        )
        findings = self.findings()
        assert_finding(self, findings, "teach session has a practice_problem")
        assert_finding(self, findings, "teach session has a practice_concluded")

    def test_practice_problem_missing_fields_and_target(self):
        self.write_session(self.practice_session(event(2, "practice_problem", target=[])))
        findings = self.findings()
        assert_finding(self, findings, "practice_problem at seq 2", "no statement")
        assert_finding(self, findings, "practice_problem at seq 2", "no mode")
        assert_finding(self, findings, "practice_problem at seq 2", "no modelSolution")
        assert_finding(self, findings, "practice_problem at seq 2", "empty target")

    def test_practice_problem_with_wrong_types(self):
        self.write_session(
            self.practice_session(
                event(
                    2,
                    "practice_problem",
                    statement=7,
                    mode=["recall"],
                    target={"counting": True},
                    modelSolution=None,
                )
            )
        )
        findings = self.findings()
        assert_finding(self, findings, "no statement")
        assert_finding(self, findings, "no mode")
        assert_finding(self, findings, "no modelSolution")
        assert_finding(self, findings, "empty target")

    def test_practice_problem_unknown_mode(self):
        self.write_session(self.practice_session(self.practice_problem(mode="quiz")))
        assert_finding(self, self.findings(), "unknown mode 'quiz'")

    def test_practice_problem_malformed_target_entry(self):
        self.write_session(self.practice_session(self.practice_problem(target=[7])))
        assert_finding(self, self.findings(), "target entry")

    def test_practice_concluded_without_outcome(self):
        self.write_session(self.practice_session(event(2, "practice_concluded", retest=False)))
        assert_finding(self, self.findings(), "practice_concluded at seq 2", "no outcome")

    def test_practice_concluded_unknown_values(self):
        for key, value in (("outcome", "nailedIt"), ("rung", "R9"), ("missClass", "mood")):
            with self.subTest(field=key):
                self.write_session(self.practice_session(self.practice_concluded(**{key: value})))
                assert_finding(self, self.findings(), "unknown %s %r" % (key, value))

    def test_practice_concluded_retest_must_be_a_boolean(self):
        for retest in ("yes", 1, 0, "true"):
            with self.subTest(retest=retest):
                self.write_session(self.practice_session(self.practice_concluded(retest=retest)))
                assert_finding(self, self.findings(), "practice_concluded at seq 2", "retest")

    def test_practice_concluded_missing_retest_is_a_finding(self):
        # `references/data-format.md` marks retest required and `references/practice.md`
        # says to supply all five fields, so a practice result without it is incomplete.
        self.write_session(self.practice_session(self.practice_concluded(retest=None)))
        assert_finding(self, self.findings(), "practice_concluded at seq 2", "retest")


if __name__ == "__main__":
    unittest.main()
