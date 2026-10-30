"""Writer-specific tests for graph_write.py.

These cover the session-kind guard, provenance message selection and dedupe,
chain link-appends, and the global ``--data-dir`` option.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import _helpers

import graph

DATA = _helpers._data

AT = "2026-01-01T00:00:00Z"


def point(session, message="1"):
    return {"chatId": session, "messageId": message}


def start_event(kind="teach", goal="understand entropy"):
    return {"seq": 1, "at": AT, "type": "session_start", "kind": kind, "goal": goal}


class GraphWriteTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = _helpers.TempProject()
        self.project = self.temp.__enter__()
        self.addCleanup(self.temp.__exit__, None, None, None)
        self.session = self.project.make_session()

    def write_proposals(self, proposals, name="proposals.json"):
        path = self.project.path / name
        _helpers.write_json_file(path, proposals)
        return path

    def merge(self, proposals, session=None, message=None, data_dir=None, cwd=None):
        path = self.write_proposals(proposals)
        args = []
        if data_dir is not None:
            args.extend(["--data-dir", str(data_dir)])
        args.extend(["merge", "--session", session or self.session, "--proposals", str(path)])
        if message is not None:
            args.extend(["--message", str(message)])
        return _helpers.run_script("graph_write.py", args, cwd=cwd or self.project.path)

    def merge_ok(self, proposals, **kwargs):
        code, out, err = self.merge(proposals, **kwargs)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def assert_refused(self, proposals, **kwargs):
        code, out, err = self.merge(proposals, **kwargs)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertTrue(err.strip())
        return err

    def node_proposal(self, **extra):
        proposal = {"ref": "a", "statement": "Entropy counts microstates.", "name": "Entropy"}
        proposal.update(extra)
        return proposal

    def chain_proposals(self, **chain_extra):
        chain = {"premises": ["a"], "conclusion": "b"}
        chain.update(chain_extra)
        return {
            "nodes": [
                {"ref": "a", "statement": "Entropy counts microstates.", "name": "Entropy"},
                {"ref": "b", "statement": "Irreversibility follows from counting.", "name": "Irreversibility"},
            ],
            "chains": [chain],
        }


class PracticeGuardTests(GraphWriteTestCase):
    def test_practice_session_refuses_to_write_propositions(self):
        practice = self.project.make_session(kind="practice", session_id="lh_practice")
        error = self.assert_refused(self.chain_proposals(), session=practice)
        self.assertIn("practice", error.lower())
        self.assertIn("records no propositions", error)
        self.assertEqual(self.project.nodes(), [])
        self.assertEqual(self.project.chains(), [])


class ChainProvenanceTests(GraphWriteTestCase):
    def test_second_session_reassertion_appends_a_link_not_a_duplicate_chain(self):
        proposals = self.chain_proposals()
        self.merge_ok(proposals)
        original = self.project.chains()[0]

        other = self.project.make_session(session_id="lh_sess0002")
        result = self.merge_ok(proposals, session=other)
        self.assertEqual(result, {"ok": True, "nodes": 2, "chains": 1, "reused": 2})

        raw = self.project.chains()
        self.assertEqual(len(raw), 2)
        link = raw[1]
        self.assertEqual(link["id"], original["id"])
        self.assertEqual(link["premises"], original["premises"])
        self.assertEqual(link["conclusion"], original["conclusion"])
        self.assertEqual(link["createdAt"], original["createdAt"])
        self.assertEqual(link["provenance"], [point(other)])

        merged = graph.merge_chain_lines(raw)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len({chain["id"] for chain in merged}), 1)
        self.assertEqual(
            merged[0]["provenance"],
            [point(self.session), point(other)],
        )

    def test_same_session_reassertion_writes_nothing(self):
        proposals = self.chain_proposals()
        self.merge_ok(proposals)
        chain_lines = len(self.project.chains())
        result = self.merge_ok(proposals)
        self.assertEqual(result, {"ok": True, "nodes": 0, "chains": 0, "reused": 2})
        self.assertEqual(len(self.project.chains()), chain_lines)


class MessageSelectionTests(GraphWriteTestCase):
    def write_log(self, events):
        self.project.write_events(self.session, events)

    def test_message_option_sets_the_point(self):
        self.write_log(
            [
                start_event(),
                {"seq": 2, "at": AT, "type": "step_closed", "node": "plan-a", "outcome": "held"},
            ]
        )
        self.merge_ok({"nodes": [self.node_proposal()]}, message=1)
        self.assertEqual(self.project.nodes()[0]["provenance"], [point(self.session, "1")])

    def test_per_proposal_message_id_sets_each_point(self):
        self.write_log(
            [
                start_event(),
                {"seq": 2, "at": AT, "type": "step_closed", "node": "plan-a", "outcome": "held"},
                {"seq": 3, "at": AT, "type": "step_closed", "node": "plan-b", "outcome": "held"},
            ]
        )
        proposals = self.chain_proposals()
        proposals["nodes"][0]["messageId"] = 2
        proposals["nodes"][1]["messageId"] = "3"
        proposals["chains"][0]["messageId"] = 1
        self.merge_ok(proposals)

        nodes = self.project.nodes()
        self.assertEqual(nodes[0]["provenance"], [point(self.session, "2")])
        self.assertEqual(nodes[1]["provenance"], [point(self.session, "3")])
        self.assertEqual(self.project.chains()[0]["provenance"], [point(self.session, "1")])

    def test_target_node_uses_the_last_matching_answer_and_chains_fall_back(self):
        self.write_log(
            [
                start_event(),
                {"seq": 2, "at": AT, "type": "check_posed", "node": "plan-a", "question": "A?"},
                {"seq": 3, "at": AT, "type": "answer", "check_seq": 2, "correct": True},
                {"seq": 4, "at": AT, "type": "check_posed", "node": "plan-b", "question": "B?"},
                {"seq": 5, "at": AT, "type": "answer", "check_seq": 4, "correct": True},
                {"seq": 6, "at": AT, "type": "step_closed", "node": "plan-b", "outcome": "held"},
            ]
        )
        proposals = self.chain_proposals()
        proposals["nodes"][0]["targetNode"] = "plan-a"
        proposals["nodes"][1]["targetNode"] = "plan-b"
        self.merge_ok(proposals)

        nodes = self.project.nodes()
        self.assertEqual(nodes[0]["provenance"], [point(self.session, "3")])
        self.assertEqual(nodes[1]["provenance"], [point(self.session, "5")])
        self.assertEqual(self.project.chains()[0]["provenance"], [point(self.session, "6")])

    def test_invalid_message_ids_are_refused_without_writing(self):
        cases = [
            {"nodes": [self.node_proposal(messageId=99)]},
            {"nodes": [self.node_proposal(messageId="not-a-seq")]},
            {"nodes": [self.node_proposal(messageId=True)]},
            self.chain_proposals(messageId=99),
        ]
        for proposals in cases:
            with self.subTest(proposals=proposals):
                self.assert_refused(proposals)
                self.assertEqual(self.project.nodes(), [])
                self.assertEqual(self.project.chains(), [])

        self.assert_refused({"nodes": [self.node_proposal()]}, message=99)
        self.assertEqual(self.project.nodes(), [])

    def test_two_messages_create_two_points_and_remerging_dedupes(self):
        self.write_log(
            [
                start_event(),
                {"seq": 2, "at": AT, "type": "step_closed", "node": "plan-a", "outcome": "held"},
                {"seq": 3, "at": AT, "type": "step_closed", "node": "plan-a", "outcome": "held"},
            ]
        )
        proposals = {"nodes": [self.node_proposal()]}
        self.merge_ok(proposals, message=2)
        self.merge_ok(proposals, message=3)

        raw = self.project.nodes()
        self.assertEqual(len(raw), 2)
        merged = graph.merge_node_lines(raw)
        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["provenance"],
            [point(self.session, "2"), point(self.session, "3")],
        )

        result = self.merge_ok(proposals, message=3)
        self.assertEqual(result, {"ok": True, "nodes": 0, "chains": 0, "reused": 1})
        self.assertEqual(len(self.project.nodes()), 2)


class DataDirTests(GraphWriteTestCase):
    def test_data_dir_works_from_an_unrelated_cwd(self):
        path = self.write_proposals({"nodes": [self.node_proposal()]})
        with tempfile.TemporaryDirectory() as elsewhere:
            code, out, err = _helpers.run_script(
                "graph_write.py",
                [
                    "--data-dir",
                    str(self.project.root),
                    "merge",
                    "--session",
                    self.session,
                    "--proposals",
                    str(path),
                ],
                cwd=elsewhere,
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["nodes"], 1)
            self.assertFalse((Path(elsewhere) / ".learnharness").exists())
        self.assertEqual(len(self.project.nodes()), 1)
        self.assertEqual(self.project.nodes()[0]["provenance"], [point(self.session)])


if __name__ == "__main__":
    unittest.main()
