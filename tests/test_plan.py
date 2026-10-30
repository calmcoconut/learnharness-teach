"""Tests for ``scripts/plan.py`` — the plan DAG validator.

The CLI tests use ``scripts/plan.py`` as a subprocess through
``tests/_helpers.py`` so they exercise the real exit codes, the real stdout
payload and the real ``Error:`` line on stderr.  The API tests call
``plan.validate`` directly, because that is the contract ``session.py`` codes
against.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

try:  # ``python3 -m unittest tests.test_plan`` imports this file as a package member
    from . import _helpers
except ImportError:  # direct execution, or discovery from inside tests/
    import _helpers

import plan  # noqa: E402  (``tests/_helpers.py`` puts scripts/ on sys.path)


def build(node_ids, edges=()):
    """A plan document with generated titles and ``(from, to)`` edge tuples."""
    nodes = [
        {"id": node_id, "title": node_id.replace("-", " ").replace("_", " ").title()}
        for node_id in node_ids
    ]
    return {"nodes": nodes, "edges": [{"from": source, "to": target} for source, target in edges]}


class PlanCliTest(unittest.TestCase):
    """``plan.py validate --plan FILE|-`` as the agent runs it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="lh-plan-")
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()

    # -- helpers -----------------------------------------------------------

    def write_plan(self, document, name="plan.json"):
        path = self.dir / name
        text = document if isinstance(document, str) else json.dumps(document)
        path.write_text(text, encoding="utf-8")
        return path

    def validate_cli(self, document, cwd=None):
        path = self.write_plan(document)
        return _helpers.run_script("plan.py", ["validate", "--plan", path], cwd=cwd or self.dir)

    def assert_passes(self, result):
        code, out, err = result
        self.assertEqual(code, 0, "expected exit 0; stderr:\n%s" % err)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(set(payload), {"ok", "nodeIds", "warnings"})
        self.assertIs(payload["ok"], True)
        self.assertIsInstance(payload["nodeIds"], list)
        self.assertIsInstance(payload["warnings"], list)
        return payload

    def assert_refused(self, result, *fragments):
        code, out, err = result
        self.assertEqual(code, 1, "expected exit 1; stdout:\n%s" % out)
        payload = json.loads(out)
        self.assertEqual(set(payload), {"ok", "error"})
        self.assertIs(payload["ok"], False)
        error = payload["error"]
        self.assertTrue(error)
        self.assertTrue(err.startswith("Error: "), "stderr:\n%s" % err)
        self.assertIn(error, err)
        for fragment in fragments:
            self.assertIn(fragment, error)
        return error

    # -- success -----------------------------------------------------------

    def test_valid_plan_passes_with_node_ids_in_input_order(self):
        document = {
            "nodes": [
                {
                    "id": "irreversible",
                    "title": "Irreversibility",
                    "summary": "why processes have a direction",
                },
                {"id": "entropy", "title": "Entropy is a count"},
                {"id": "counting", "title": "Counting microstates"},
            ],
            "edges": [
                {"from": "counting", "to": "entropy"},
                {"from": "entropy", "to": "irreversible"},
            ],
        }
        payload = self.assert_passes(self.validate_cli(document))
        self.assertEqual(payload["nodeIds"], ["irreversible", "entropy", "counting"])
        self.assertEqual(payload["warnings"], [])

    def test_diamond_is_not_a_cycle(self):
        document = build(
            ["start", "left", "right", "goal"],
            [("start", "left"), ("start", "right"), ("left", "goal"), ("right", "goal")],
        )
        payload = self.assert_passes(self.validate_cli(document))
        self.assertEqual(payload["nodeIds"], ["start", "left", "right", "goal"])
        self.assertEqual(payload["warnings"], [])

    def test_disconnected_components_are_not_a_cycle(self):
        document = build(["a", "b", "c", "d", "lone"], [("a", "b"), ("c", "d")])
        payload = self.assert_passes(self.validate_cli(document))
        self.assertEqual(payload["nodeIds"], ["a", "b", "c", "d", "lone"])

    def test_plan_without_edges_passes(self):
        payload = self.assert_passes(self.validate_cli(build(["a", "b"])))
        self.assertEqual(payload["nodeIds"], ["a", "b"])

    def test_fifteen_nodes_do_not_warn(self):
        node_ids = ["n%d" % index for index in range(15)]
        payload = self.assert_passes(self.validate_cli(build(node_ids)))
        self.assertEqual(payload["warnings"], [])

    def test_twenty_nodes_warn_but_still_pass(self):
        node_ids = ["n%d" % index for index in range(20)]
        edges = [(node_ids[index], node_ids[index + 1]) for index in range(19)]
        payload = self.assert_passes(self.validate_cli(build(node_ids, edges)))
        self.assertEqual(payload["nodeIds"], node_ids)
        self.assertEqual(len(payload["warnings"]), 1)
        self.assertIn("20", payload["warnings"][0])
        self.assertIn("15", payload["warnings"][0])

    # -- refusals: nodes ---------------------------------------------------

    def test_empty_node_list_is_refused(self):
        self.assert_refused(self.validate_cli({"nodes": [], "edges": []}), "no nodes")

    def test_null_document_members_are_refused_like_absent_ones(self):
        self.assert_refused(self.validate_cli('{"nodes": null, "edges": null}'), "plan has no nodes")

    def test_bad_id_charset_is_refused(self):
        bad_ids = (
            "has space",
            "double__underscore",
            "_leading",
            "trailing_",
            "with.dot",
            "slash/x",
            "dollar$",
        )
        for bad in bad_ids:
            with self.subTest(node_id=bad):
                self.assert_refused(
                    self.validate_cli(build([bad])),
                    "node %r: id does not match" % bad,
                )

    def test_uppercase_id_is_refused(self):
        self.assert_refused(self.validate_cli(build(["Entropy"])), "node 'Entropy': id does not match")

    def test_duplicate_id_is_refused(self):
        document = {
            "nodes": [{"id": "a", "title": "A"}, {"id": "a", "title": "A again"}],
            "edges": [],
        }
        self.assert_refused(self.validate_cli(document), "node 'a': duplicate id")

    def test_blank_title_is_refused(self):
        for title in ("", "   ", "\t\n "):
            with self.subTest(title=title):
                document = {"nodes": [{"id": "a", "title": title}], "edges": []}
                self.assert_refused(self.validate_cli(document), "node 'a': title is empty")

    def test_missing_title_is_refused(self):
        document = {"nodes": [{"id": "a"}], "edges": []}
        self.assert_refused(self.validate_cli(document), "node 'a': title must be a string")

    # -- refusals: edges ---------------------------------------------------

    def test_unknown_edge_endpoints_are_refused(self):
        nodes = [{"id": "a", "title": "A"}]
        for edge, unknown in (
            ({"from": "a", "to": "missing"}, "missing"),
            ({"from": "ghost", "to": "a"}, "ghost"),
        ):
            with self.subTest(edge=edge):
                document = {"nodes": nodes, "edges": [edge]}
                self.assert_refused(self.validate_cli(document), "unknown node %r" % unknown)

    def test_self_loop_is_refused_and_not_reported_as_a_cycle(self):
        document = {"nodes": [{"id": "a", "title": "A"}], "edges": [{"from": "a", "to": "a"}]}
        error = self.assert_refused(self.validate_cli(document), "edge 'a' -> 'a': self-loop")
        self.assertNotIn("cycle", error)

    def test_duplicate_edge_is_refused(self):
        document = build(["a", "b"], [("a", "b"), ("a", "b")])
        self.assert_refused(self.validate_cli(document), "edge 'a' -> 'b': duplicate edge")

    # -- refusals: cycles --------------------------------------------------

    def test_three_node_cycle_is_refused(self):
        document = build(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "a")])
        error = self.assert_refused(self.validate_cli(document), "cycle:")
        self.assertIn("a -> b -> c -> a", error)

    def test_longer_cycle_is_refused(self):
        node_ids = ["s1", "s2", "s3", "s4", "s5", "s6"]
        edges = [(node_ids[index], node_ids[(index + 1) % len(node_ids)]) for index in range(len(node_ids))]
        error = self.assert_refused(self.validate_cli(build(node_ids, edges)), "cycle:")
        for node_id in node_ids:
            self.assertIn(node_id, error)
        self.assertIn("s6 -> s1", error)

    # -- refusals: document shape ------------------------------------------

    def test_malformed_json_is_refused(self):
        for text in ('{"nodes": [{"id": "a",', '{"nodes": [], "edges": []} trailing', "not json at all"):
            with self.subTest(text=text):
                self.assert_refused(self.validate_cli(text), "not valid json")

    def test_empty_input_is_refused(self):
        self.assert_refused(self.validate_cli(""), "plan is empty")

    def test_non_finite_number_is_refused(self):
        text = '{"nodes": [{"id": "a", "title": "A", "weight": NaN}], "edges": []}'
        self.assert_refused(self.validate_cli(text), "non-finite")

    def test_json_array_document_is_refused(self):
        error = self.assert_refused(self.validate_cli([1, 2, 3]), "json object")
        self.assertIn("array", error)

    def test_json_null_document_is_refused(self):
        self.assert_refused(self.validate_cli("null"), "json object")

    # -- several problems, one pass ----------------------------------------

    def test_every_problem_is_reported_at_once(self):
        document = {
            "nodes": [
                {"id": "a", "title": "A"},
                {"id": "a", "title": "   "},
                {"id": "Bad!", "title": "Bad"},
            ],
            "edges": [
                {"from": "a", "to": "ghost"},
                {"from": "a", "to": "a"},
                {"from": "a", "to": "a"},
            ],
        }
        error = self.assert_refused(self.validate_cli(document))
        lines = error.splitlines()
        expected = [
            "node 'a': title is empty",
            "node 'a': duplicate id",
            "node 'Bad!': id does not match",
            "edge 'a' -> 'ghost': unknown node 'ghost'",
            "edge 'a' -> 'a': self-loop",
            "edge 'a' -> 'a': duplicate edge",
        ]
        for fragment in expected:
            self.assertTrue(
                any(fragment in line for line in lines),
                "missing %r in:\n%s" % (fragment, error),
            )
        self.assertGreaterEqual(len(lines), len(expected))

    # -- input plumbing ----------------------------------------------------

    def test_plan_on_stdin_via_dash(self):
        document = build(["a", "b"], [("a", "b")])
        completed = subprocess.run(
            [sys.executable, "-B", str(_helpers.SCRIPTS / "plan.py"), "validate", "--plan", "-"],
            cwd=str(self.dir),
            input=json.dumps(document),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["nodeIds"], ["a", "b"])
        self.assertEqual(payload["warnings"], [])

    def test_refusal_on_stdin_via_dash(self):
        completed = subprocess.run(
            [sys.executable, "-B", str(_helpers.SCRIPTS / "plan.py"), "validate", "--plan", "-"],
            cwd=str(self.dir),
            input=json.dumps(build(["a", "b"], [("a", "b"), ("b", "a")])),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertIs(payload["ok"], False)
        self.assertIn("cycle", payload["error"])
        self.assertTrue(completed.stderr.startswith("Error: "))

    def test_runs_from_any_working_directory(self):
        document = build(["start", "goal"], [("start", "goal")])
        with tempfile.TemporaryDirectory(prefix="lh-plan-cwd-") as other:
            result = self.validate_cli(document, cwd=Path(other).resolve())
        payload = self.assert_passes(result)
        self.assertEqual(payload["nodeIds"], ["start", "goal"])


class PlanApiTest(unittest.TestCase):
    """``plan.validate`` is the contract ``session.py`` codes against."""

    def test_returns_ok_error_warnings_and_node_ids(self):
        result = plan.validate(build(["b", "a"], [("a", "b")]))
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 4)
        ok, error, warnings, node_ids = result
        self.assertIs(ok, True)
        self.assertEqual(error, "")
        self.assertEqual(warnings, [])
        self.assertEqual(node_ids, ["b", "a"])

    def test_absent_or_null_edges_mean_no_edges(self):
        for document in (
            {"nodes": [{"id": "a", "title": "A"}]},
            {"nodes": [{"id": "a", "title": "A"}], "edges": None},
        ):
            with self.subTest(document=document):
                ok, error, warnings, node_ids = plan.validate(document)
                self.assertIs(ok, True)
                self.assertEqual(error, "")
                self.assertEqual(warnings, [])
                self.assertEqual(node_ids, ["a"])

    def test_absent_or_null_nodes_means_no_nodes(self):
        for document in ({}, {"edges": []}, {"nodes": None, "edges": []}):
            with self.subTest(document=document):
                ok, error, warnings, node_ids = plan.validate(document)
                self.assertIs(ok, False)
                self.assertEqual(error, "plan has no nodes")
                self.assertEqual(node_ids, [])

    def test_invalid_documents_return_instead_of_raising(self):
        documents = [
            {},
            {"nodes": []},
            {"nodes": "not a list"},
            {"nodes": [{"id": "a", "title": "A"}], "edges": [{"from": "a", "to": "a"}]},
            build(["a", "b"], [("a", "b"), ("b", "a")]),
            {"nodes": [{"id": "a", "title": "A"}], "edges": [{"from": "a"}]},
        ]
        for document in documents:
            with self.subTest(document=document):
                result = plan.validate(document)
                self.assertEqual(len(result), 4)
                ok, error, warnings, node_ids = result
                self.assertIs(ok, False)
                self.assertTrue(error)
                self.assertIsInstance(node_ids, list)

    def test_non_dict_documents_raise_type_error(self):
        for document in ([], (), "", 0, 1.5, None, True):
            with self.subTest(document=document):
                with self.assertRaises(TypeError):
                    plan.validate(document)

    def test_structurally_bad_nodes_are_named_by_index(self):
        ok, error, warnings, node_ids = plan.validate({"nodes": [{"title": "A"}, 3], "edges": []})
        self.assertIs(ok, False)
        self.assertIn('nodes[0]: "id" must be a string, got null', error)
        self.assertIn("nodes[1]: must be an object, got number", error)
        self.assertEqual(node_ids, [])

    def test_structurally_bad_edges_are_named_by_index(self):
        document = {"nodes": [{"id": "a", "title": "A"}], "edges": [{"from": "a"}, "not an object"]}
        ok, error, warnings, node_ids = plan.validate(document)
        self.assertIs(ok, False)
        self.assertIn('edges[0]: "to" must be a string, got null', error)
        self.assertIn("edges[1]: must be an object, got string", error)

    def test_cycle_detection_does_not_depend_on_recursion_depth(self):
        size = 400
        node_ids = ["n%d" % index for index in range(size)]
        edges = [{"from": node_ids[index], "to": node_ids[(index + 1) % size]} for index in range(size)]
        document = {"nodes": [{"id": node_id, "title": node_id} for node_id in node_ids], "edges": edges}
        ok, error, warnings, node_ids = plan.validate(document)
        self.assertIs(ok, False)
        self.assertIn("cycle:", error)
        self.assertEqual(len(node_ids), size)


if __name__ == "__main__":
    unittest.main()
