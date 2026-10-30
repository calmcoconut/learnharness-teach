"""The committed record fixtures must stay readable and auditable.

`tests/fixtures/records/build.py` regenerates them. If the format changes and the builder
is not re-run, or if a reader regresses, these tests fail.
"""

import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import _helpers

REPO = Path(__file__).resolve().parent.parent
RECORDS = REPO / "tests" / "fixtures" / "records"
TEACH = RECORDS / "complete-teach" / ".learnharness"
PRACTICE = RECORDS / "practice" / ".learnharness"


def state(root, session_id):
    code, out, err = _helpers.run_script(
        "session.py", ["--data-dir", root, "--format", "json", "state", "--session", session_id]
    )
    assert code == 0, err
    return json.loads(out)


class FixturePresenceTest(unittest.TestCase):
    def test_both_fixtures_are_committed(self):
        self.assertTrue((TEACH / "sessions" / "lh_fixture1" / "session.jsonl").is_file())
        self.assertTrue((PRACTICE / "sessions" / "lh_fixture2" / "session.jsonl").is_file())
        self.assertTrue((TEACH / "graph" / "nodes.jsonl").is_file())
        self.assertTrue((TEACH / "graph" / "chains.jsonl").is_file())
        self.assertTrue((TEACH / "graph" / "format.json").is_file())


class VerifyTest(unittest.TestCase):
    def test_teach_fixture_audits_clean(self):
        code, out, err = _helpers.run_script("verify.py", ["--data-dir", TEACH])
        self.assertEqual(code, 0, out + err)
        self.assertIn("consistent", out)

    def test_practice_fixture_audits_clean(self):
        code, out, err = _helpers.run_script("verify.py", ["--data-dir", PRACTICE])
        self.assertEqual(code, 0, out + err)

    def test_both_fixtures_audit_together(self):
        # --data-dir points at one record, so audit them separately but assert both ran.
        for root in (TEACH, PRACTICE):
            code, _out, err = _helpers.run_script("verify.py", ["--data-dir", root])
            self.assertEqual(code, 0, err)


class TeachDerivationTest(unittest.TestCase):
    def setUp(self):
        self.fields = state(TEACH, "lh_fixture1")

    def test_phase_is_closed(self):
        self.assertEqual(self.fields["phase"], "closed")
        self.assertTrue(self.fields["closed"])

    def test_plan_revision_and_shape(self):
        self.assertEqual(self.fields["plan"]["revision"], 1)
        self.assertEqual(self.fields["plan"]["nodes"], 5)
        self.assertEqual(self.fields["plan"]["edges"], 4)

    def test_position_comes_from_tagged_checks_only(self):
        # Exactly one teaching check exists, so it is current and nothing is behind it.
        self.assertEqual(self.fields["current"], "irreversibility")
        self.assertEqual(self.fields["visited"], [])

    def test_untouched_excludes_the_node_in_progress(self):
        self.assertEqual(self.fields["next"], {"untouched": 4, "total": 5})

    def test_last_answer_carries_confidence_and_trace(self):
        self.assertEqual(self.fields["last"]["node"], "irreversibility")
        self.assertTrue(self.fields["last"]["correct"])
        self.assertEqual(self.fields["last"]["confidence"], 3)
        self.assertTrue(self.fields["last"]["trace"])

    def test_nothing_is_open(self):
        self.assertIsNone(self.fields["open"])


class PracticeDerivationTest(unittest.TestCase):
    def test_practice_session_reports_its_problem(self):
        fields = state(PRACTICE, "lh_fixture2")
        self.assertEqual(fields["kind"], "practice")
        self.assertEqual(fields["phase"], "closed")
        self.assertIsNone(fields["plan"])
        self.assertIsNotNone(fields["practice"])
        self.assertEqual(fields["practice"]["mode"], "discrimination")
        self.assertEqual(len(fields["practice"]["targets"]), 2)
        self.assertTrue(fields["practice"]["concluded"])


class GraphFixtureTest(unittest.TestCase):
    def test_every_node_line_carries_the_arrays_the_app_requires(self):
        records = _helpers.read_jsonl(TEACH / "graph" / "nodes.jsonl")
        self.assertEqual(len(records), 6)
        for record in records:
            self.assertIsInstance(record.get("aliases"), list, record.get("id"))
            self.assertIsInstance(record.get("provenance"), list, record.get("id"))
            self.assertTrue(record.get("statement"))

    def test_every_chain_endpoint_resolves(self):
        nodes = {r["id"] for r in _helpers.read_jsonl(TEACH / "graph" / "nodes.jsonl")}
        chains = _helpers.read_jsonl(TEACH / "graph" / "chains.jsonl")
        self.assertEqual(len(chains), 2)
        for chain in chains:
            self.assertTrue(chain["premises"])
            for endpoint in [*chain["premises"], chain["conclusion"]]:
                self.assertIn(endpoint, nodes)

    def test_provenance_points_at_the_session(self):
        for record in _helpers.read_jsonl(TEACH / "graph" / "nodes.jsonl"):
            for point in record["provenance"]:
                self.assertEqual(point["chatId"], "lh_fixture1")
                self.assertTrue(point["messageId"])

    def test_format_stamp_is_version_one(self):
        stamp = json.loads((TEACH / "graph" / "format.json").read_text(encoding="utf-8"))
        self.assertEqual(stamp["version"], 1)

    def test_practice_wrote_no_propositions(self):
        self.assertFalse((PRACTICE / "graph" / "nodes.jsonl").exists())

    def test_graph_queries_see_the_fixture(self):
        code, out, err = _helpers.run_script("graph.py", ["--data-dir", TEACH, "propositions"])
        self.assertEqual(code, 0, err)
        self.assertIn("Entropy", out)
        code, out, err = _helpers.run_script("graph.py", ["--data-dir", TEACH, "chains"])
        self.assertEqual(code, 0, err)
        self.assertIn("Premises:", out)


if __name__ == "__main__":
    unittest.main()
