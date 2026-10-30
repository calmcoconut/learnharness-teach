"""Graph writer and reader tests.

The ledgers are app-compatible JSONL: every write must be valid even when the
app would silently drop a malformed line, and the reader must apply the app's
merge law without ever modifying the record.
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

DATA = _helpers._data


def point(session, message="1"):
    return {"chatId": session, "messageId": message}


def node_line(node_id, statement, name=None, aliases=None, created="2026-01-01T00:00:00Z", provenance=None):
    return {
        "id": node_id,
        "name": name or statement,
        "statement": statement,
        "aliases": list(aliases or []),
        "createdAt": created,
        "provenance": list(provenance or []),
    }


def chain_line(chain_id, premises, conclusion, created="2026-01-02T00:00:00Z", provenance=None):
    return {
        "id": chain_id,
        "premises": list(premises),
        "conclusion": conclusion,
        "provenance": list(provenance or []),
        "createdAt": created,
    }


class GraphTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = _helpers.TempProject()
        self.project = self.temp.__enter__()
        self.addCleanup(self.temp.__exit__, None, None, None)
        self.session = self.project.make_session()

    def write_proposals(self, proposals, name="proposals.json"):
        path = self.project.path / name
        _helpers.write_json_file(path, proposals)
        return path

    def merge(self, proposals, session=None, cwd=None):
        path = self.write_proposals(proposals)
        return _helpers.run_script(
            "graph_write.py",
            ["merge", "--session", session or self.session, "--proposals", path],
            cwd=cwd or self.project.path,
        )

    def graph(self, *arguments, format="json", cwd=None, data_dir=None):
        args = ["--data-dir", data_dir or self.project.root, "--format", format, *arguments]
        return _helpers.run_script("graph.py", args, cwd=cwd or self.project.path)

    def export(self, destination, *extra, format="json"):
        return self.graph("export", "--to", destination, *extra, format=format)

    def records(self, *arguments, **kwargs):
        code, out, err = self.graph(*arguments, **kwargs)
        self.assertEqual(code, 0, err)
        return json.loads(out)["records"]

    def merge_ok(self, proposals, session=None, cwd=None):
        code, out, err = self.merge(proposals, session=session, cwd=cwd)
        self.assertEqual(code, 0, err)
        return json.loads(out)


class WriteTests(GraphTestCase):
    def test_write_new_nodes_and_chain(self):
        proposals = {
            "nodes": [
                {
                    "ref": "a",
                    "statement": "Entropy counts microstates.",
                    "name": "Entropy count",
                    "aliases": ["Entropy is counting"],
                },
                {"ref": "b", "statement": "Irreversibility follows from counting.", "name": "Irreversibility"},
            ],
            "chains": [{"premises": ["a"], "conclusion": "b"}],
        }
        result = self.merge_ok(proposals)
        self.assertEqual(result, {"ok": True, "nodes": 2, "chains": 1, "reused": 0})

        node_a = DATA.mint_node_id("Entropy counts microstates.")
        node_b = DATA.mint_node_id("Irreversibility follows from counting.")
        nodes = self.project.nodes()
        self.assertEqual([record["id"] for record in nodes], [node_a, node_b])
        self.assertEqual(nodes[0]["name"], "Entropy count")
        self.assertEqual(nodes[0]["aliases"], ["Entropy is counting"])
        self.assertEqual(nodes[0]["provenance"], [point(self.session)])
        self.assertEqual(nodes[1]["aliases"], [])
        self.assertEqual(nodes[1]["provenance"], [point(self.session)])

        chains = self.project.chains()
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["id"], DATA.mint_chain_id([node_a], node_b))
        self.assertEqual(chains[0]["premises"], [node_a])
        self.assertEqual(chains[0]["conclusion"], node_b)
        self.assertEqual(chains[0]["provenance"], [point(self.session)])

        stamp = json.loads((self.project.root / "graph" / "format.json").read_text(encoding="utf-8"))
        self.assertEqual(stamp["version"], 1)

        propositions = self.records("propositions")
        self.assertEqual([record["id"] for record in propositions], [node_a, node_b])
        self.assertEqual(len(self.records("chains")), 1)

    def test_remerge_is_idempotent(self):
        proposals = {
            "nodes": [
                {"ref": "a", "statement": "A first proposition.", "name": "First"},
                {"ref": "b", "statement": "A second proposition.", "name": "Second"},
            ],
            "chains": [{"premises": ["a"], "conclusion": "b"}],
        }
        self.merge_ok(proposals)
        result = self.merge_ok(proposals)
        self.assertEqual(result, {"ok": True, "nodes": 0, "chains": 0, "reused": 2})
        self.assertEqual(len(self.project.nodes()), 2)
        self.assertEqual(len(self.project.chains()), 1)
        self.assertEqual(len(self.records("propositions")), 2)

    def test_alias_matching_reuses_existing_node(self):
        first = {
            "nodes": [
                {
                    "ref": "a",
                    "statement": "Entropy is a count of microstates.",
                    "name": "Entropy",
                    "aliases": ["Counting microstates."],
                }
            ]
        }
        self.merge_ok(first)
        second = {
            "nodes": [
                {
                    "ref": "again",
                    "statement": "Counting microstates.",
                    "name": "A different label for the same thing",
                }
            ]
        }
        result = self.merge_ok(second)
        self.assertEqual(result, {"ok": True, "nodes": 0, "chains": 0, "reused": 1})
        self.assertEqual(len(self.project.nodes()), 1)
        self.assertEqual(len(self.records("propositions")), 1)

    def test_link_lines_accumulate_aliases_and_provenance(self):
        first = {
            "nodes": [
                {
                    "ref": "a",
                    "statement": "Entropy is a count of microstates.",
                    "name": "Entropy",
                    "aliases": ["First phrasing"],
                }
            ]
        }
        self.merge_ok(first)
        other = self.project.make_session(session_id="lh_sess0002")
        second = {
            "nodes": [
                {
                    "ref": "a",
                    "statement": "Entropy is a count of microstates.",
                    "aliases": ["Second phrasing"],
                }
            ]
        }
        result = self.merge_ok(second, session=other)
        self.assertEqual(result, {"ok": True, "nodes": 1, "chains": 0, "reused": 1})

        raw = self.project.nodes()
        self.assertEqual(len(raw), 2)
        self.assertEqual(raw[1]["id"], raw[0]["id"])
        self.assertEqual(raw[1]["statement"], "Entropy is a count of microstates.")
        self.assertIsInstance(raw[1]["aliases"], list)
        self.assertIsInstance(raw[1]["provenance"], list)

        nodes = self.records("propositions")
        self.assertEqual(len(nodes), 1)
        self.assertIn("First phrasing", nodes[0]["aliases"])
        self.assertIn("Second phrasing", nodes[0]["aliases"])
        self.assertEqual(
            nodes[0]["provenance"],
            [point(self.session), point(other)],
        )

    def test_every_emitted_line_has_both_arrays(self):
        self.merge_ok(
            {
                "nodes": [
                    {"ref": "a", "statement": "One proposition.", "name": "One"},
                    {"ref": "b", "statement": "Another proposition.", "name": "Two"},
                ],
                "chains": [{"premises": ["a"], "conclusion": "b"}],
            }
        )
        other = self.project.make_session(session_id="lh_sess0002")
        self.merge_ok(
            {"nodes": [{"ref": "a", "statement": "One proposition.", "aliases": ["Another wording"]}]},
            session=other,
        )
        for record in self.project.nodes():
            self.assertIsInstance(record.get("aliases"), list)
            self.assertIsInstance(record.get("provenance"), list)
            self.assertTrue(record["aliases"] is not None)
            self.assertTrue(record["provenance"] is not None)
        for record in self.project.chains():
            self.assertIsInstance(record.get("provenance"), list)


class RefusalTests(GraphTestCase):
    def assert_refused(self, proposals):
        code, out, err = self.merge(proposals)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertTrue(err.strip())
        return err

    def test_unknown_ref_refused_without_partial_write(self):
        self.merge_ok({"nodes": [{"ref": "a", "statement": "An existing proposition.", "name": "Existing"}]})
        before = len(self.project.nodes())
        self.assert_refused(
            {
                "nodes": [{"ref": "b", "statement": "A brand new proposition.", "name": "New"}],
                "chains": [{"premises": ["b"], "conclusion": "ghost"}],
            }
        )
        self.assertEqual(len(self.project.nodes()), before)
        self.assertEqual(self.project.chains(), [])

    def test_empty_premises_refused(self):
        self.assert_refused(
            {"nodes": [{"ref": "a", "statement": "A proposition.", "name": "A"}], "chains": [{"premises": [], "conclusion": "a"}]}
        )
        self.assertEqual(self.project.nodes(), [])

    def test_chain_to_non_existent_node_refused(self):
        self.assert_refused(
            {
                "nodes": [{"ref": "a", "statement": "A proposition.", "name": "A"}],
                "chains": [{"premises": ["a"], "conclusion": "b"}],
            }
        )
        self.assertEqual(self.project.nodes(), [])

    def test_duplicate_ref_and_empty_statement_refused(self):
        self.assert_refused(
            {
                "nodes": [
                    {"ref": "a", "statement": "First.", "name": "First"},
                    {"ref": "a", "statement": "Second.", "name": "Second"},
                ]
            }
        )
        self.assert_refused({"nodes": [{"ref": "a", "statement": "   ", "name": "Blank"}]})
        self.assertEqual(self.project.nodes(), [])

    def test_chain_conclusion_equal_to_sole_premise_refused(self):
        self.assert_refused(
            {
                "nodes": [{"ref": "a", "statement": "A proposition.", "name": "A"}],
                "chains": [{"premises": ["a"], "conclusion": "a"}],
            }
        )
        self.assertEqual(self.project.nodes(), [])


class ReadMergeLawTests(GraphTestCase):
    def test_three_node_lines_merge_to_one_node(self):
        node_id = "n_0123456789ab"
        first = node_line(
            node_id,
            "Base statement.",
            name="Original name",
            aliases=["First alias"],
            created="2026-01-01T00:00:00Z",
            provenance=[point("lh_aaaaaaa1", "1")],
        )
        link_one = node_line(
            node_id,
            "Second statement.",
            name="Later name",
            aliases=["Second alias"],
            created="2026-02-02T00:00:00Z",
            provenance=[point("lh_aaaaaaa1", "1"), point("lh_bbbbbbb2", "2")],
        )
        link_two = node_line(
            node_id,
            "Third statement.",
            aliases=["Third alias"],
            created="2026-03-03T00:00:00Z",
            provenance=[point("lh_ccccccc3", "3")],
        )
        _helpers.write_jsonl(self.project.root / "graph" / "nodes.jsonl", [first, link_one, link_two])

        nodes = self.records("propositions")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["name"], "Original name")
        self.assertEqual(nodes[0]["statement"], "Base statement.")
        self.assertEqual(nodes[0]["createdAt"], "2026-01-01T00:00:00Z")
        self.assertEqual(
            nodes[0]["aliases"],
            ["First alias", "Second statement.", "Second alias", "Third statement.", "Third alias"],
        )
        self.assertEqual(
            nodes[0]["provenance"],
            [
                point("lh_aaaaaaa1", "1"),
                point("lh_bbbbbbb2", "2"),
                point("lh_ccccccc3", "3"),
            ],
        )

    def test_chain_lines_merge_by_sorted_premises_and_conclusion(self):
        first = chain_line(
            "arg_0123456789ab",
            ["n_000000000002", "n_000000000001"],
            "n_000000000003",
            created="2026-01-01T00:00:00Z",
            provenance=[point("lh_aaaaaaa1", "1")],
        )
        second = chain_line(
            "arg_other00000",
            ["n_000000000001", "n_000000000002"],
            "n_000000000003",
            created="2026-09-09T00:00:00Z",
            provenance=[point("lh_bbbbbbb2", "2")],
        )
        _helpers.write_jsonl(self.project.root / "graph" / "chains.jsonl", [first, second])
        chains = self.records("chains")
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["id"], "arg_0123456789ab")
        self.assertEqual(chains[0]["premises"], ["n_000000000002", "n_000000000001"])
        self.assertEqual(chains[0]["createdAt"], "2026-01-01T00:00:00Z")
        self.assertEqual(chains[0]["provenance"], [point("lh_aaaaaaa1", "1"), point("lh_bbbbbbb2", "2")])


class QueryTests(GraphTestCase):
    def seed_nodes(self):
        _helpers.write_jsonl(
            self.project.root / "graph" / "nodes.jsonl",
            [
                node_line(
                    "n_000000000001",
                    "Entropy is a count of microstates.",
                    name="Entropy",
                    aliases=["Microstates"],
                    created="2026-01-01T00:00:00Z",
                    provenance=[point("lh_aaaaaaa1", "1")],
                ),
                node_line(
                    "n_000000000002",
                    "Irreversibility follows from counting.",
                    name="Irreversibility",
                    created="2026-02-01T00:00:00Z",
                    provenance=[point("lh_aaaaaaa1", "2"), point("lh_bbbbbbb2", "3")],
                ),
                node_line(
                    "n_000000000003",
                    "A reversible process leaves no net change.",
                    name="Reversibility",
                    created="2026-01-15T00:00:00Z",
                    provenance=[point("lh_bbbbbbb2", "4")],
                ),
            ],
        )

    def test_find_wildcard_and_case_insensitivity(self):
        self.seed_nodes()
        self.assertEqual([item["id"] for item in self.records("find", "ENTROPY")], ["n_000000000001"])
        self.assertEqual([item["id"] for item in self.records("find", "*count*")], ["n_000000000001", "n_000000000002"])
        self.assertEqual([item["id"] for item in self.records("find", "micro*")], ["n_000000000001"])
        self.assertEqual(self.records("find", "no such proposition"), [])

    def test_sessions_and_provenance_filter(self):
        self.seed_nodes()
        sessions = self.records("sessions")
        self.assertEqual([entry["chatId"] for entry in sessions], ["lh_bbbbbbb2", "lh_aaaaaaa1"])
        self.assertEqual([entry["nodes"] for entry in sessions], [2, 2])

        # Birth is the merged node's first provenance point. n_000000000002 was born
        # in aaaaaaa1 and only link-appended in bbbbbbb2, so it must not appear there.
        second = self.records("propositions", "--session", "lh_bbbbbbb2")
        self.assertEqual([item["id"] for item in second], ["n_000000000003"])
        first = self.records("propositions", "--session", "lh_aaaaaaa1")
        self.assertEqual([item["id"] for item in first], ["n_000000000001", "n_000000000002"])

    def test_propositions_session_filters_on_birth_not_later_appends(self):
        _helpers.write_jsonl(
            self.project.root / "graph" / "nodes.jsonl",
            [
                node_line(
                    "n_000000000001",
                    "Born in the first session.",
                    name="First",
                    provenance=[point("lh_aaaaaaa1", "1")],
                ),
                node_line(
                    "n_000000000001",
                    "Born in the first session.",
                    provenance=[point("lh_aaaaaaa1", "1"), point("lh_bbbbbbb2", "2")],
                ),
                node_line(
                    "n_000000000002",
                    "Born in the second session.",
                    name="Second",
                    provenance=[point("lh_bbbbbbb2", "3"), point("lh_aaaaaaa1", "4")],
                ),
            ],
        )
        self.assertEqual(
            [item["id"] for item in self.records("propositions", "--session", "lh_aaaaaaa1")],
            ["n_000000000001"],
        )
        self.assertEqual(
            [item["id"] for item in self.records("propositions", "--session", "lh_bbbbbbb2")],
            ["n_000000000002"],
        )

    def test_chains_by_node_and_unknown_node_are_nonempty_output(self):
        self.merge_ok(
            {
                "nodes": [
                    {"ref": "a", "statement": "Premise proposition.", "name": "Premise"},
                    {"ref": "b", "statement": "Conclusion proposition.", "name": "Conclusion"},
                ],
                "chains": [{"premises": ["a"], "conclusion": "b"}],
            }
        )
        self.assertEqual(len(self.records("chains", "--node", DATA.mint_node_id("Premise proposition."))), 1)
        for format in ("json", "markdown"):
            code, out, err = self.graph("chains", "--node", "n_ffffffffffff", format=format)
            self.assertEqual(code, 0, err)
            self.assertTrue(out.strip())
            if format == "json":
                self.assertEqual(json.loads(out)["records"], [])

    def test_malformed_lines_warn_and_are_skipped(self):
        _helpers.write_jsonl(
            self.project.root / "graph" / "nodes.jsonl",
            [node_line("n_000000000001", "A valid proposition.", provenance=[point("lh_aaaaaaa1")])],
        )
        with (self.project.root / "graph" / "nodes.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"torn":\n{"id":"n_bad"}\n')
        code, out, err = self.graph("propositions")
        self.assertEqual(code, 0, err)
        self.assertEqual([item["id"] for item in json.loads(out)["records"]], ["n_000000000001"])
        self.assertIn("warning", err.lower())
        self.assertIn("nodes.jsonl", err)


class FormatAndExportTests(GraphTestCase):
    def test_format_version_two_refused_by_both_scripts(self):
        path = self.project.root / "graph" / "format.json"
        _helpers.write_json_file(path, {"version": 2})
        error = self.merge(
            {"nodes": [{"ref": "a", "statement": "A proposition.", "name": "A"}]}
        )[2]
        self.assertIn("newer", error)
        code, out, err = self.graph("propositions")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("newer", err)
        self.assertFalse((self.project.root / "graph" / "nodes.jsonl").exists())

    def test_export_copies_only_ledgers_and_leaves_other_files_alone(self):
        self.merge_ok(
            {
                "nodes": [
                    {"ref": "a", "statement": "Premise proposition.", "name": "Premise"},
                    {"ref": "b", "statement": "Conclusion proposition.", "name": "Conclusion"},
                ],
                "chains": [{"premises": ["a"], "conclusion": "b"}],
            }
        )
        target = self.project.path / "app-data"
        target.mkdir()
        sessions = target / "sessions.jsonl"
        coverage = target / "coverage.jsonl"
        sessions.write_text('{"chatId":"keep-me"}\n', encoding="utf-8")
        coverage.write_text('{"keep":true}\n', encoding="utf-8")
        before = _helpers.snapshot(target)

        code, out, err = self.graph("export", "--to", target)
        self.assertEqual(code, 0, err)
        self.assertTrue(out.strip())

        after = _helpers.snapshot(target)
        for name in ("sessions.jsonl", "coverage.jsonl"):
            self.assertEqual(after[name], before[name], "%s was touched" % name)
        self.assertEqual(sessions.read_text(encoding="utf-8"), '{"chatId":"keep-me"}\n')
        self.assertEqual(coverage.read_text(encoding="utf-8"), '{"keep":true}\n')

        source = self.project.root / "graph"
        self.assertEqual(
            (target / "graph" / "nodes.jsonl").read_bytes(), (source / "nodes.jsonl").read_bytes()
        )
        self.assertEqual(
            (target / "graph" / "chains.jsonl").read_bytes(), (source / "chains.jsonl").read_bytes()
        )
        self.assertEqual(
            set(path.name for path in target.iterdir()),
            {"graph", "sessions.jsonl", "coverage.jsonl"},
        )
        stamp = json.loads((target / "graph" / "format.json").read_text(encoding="utf-8"))
        self.assertEqual(stamp, {"version": 1})


class ExportSafetyTests(GraphTestCase):
    """Export is the only writer that touches data it did not create."""

    def seed_graph(self):
        return self.merge_ok(
            {
                "nodes": [
                    {"ref": "a", "statement": "Premise proposition.", "name": "Premise"},
                    {"ref": "b", "statement": "Conclusion proposition.", "name": "Conclusion"},
                ],
                "chains": [{"premises": ["a"], "conclusion": "b"}],
            }
        )

    def source_bytes(self, name):
        return (self.project.root / "graph" / name).read_bytes()

    def test_export_refuses_newer_destination_format_and_writes_nothing(self):
        self.seed_graph()
        target = self.project.path / "app"
        target.mkdir()
        app_nodes = target / "nodes.jsonl"
        app_nodes.write_text('{"id":"n_aaaaaaaaaaa1"}\n', encoding="utf-8")
        _helpers.write_json_file(target / "format.json", {"version": 9})
        before = _helpers.snapshot(target)

        code, out, err = self.export(target)

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("newer", err)
        self.assertEqual(_helpers.snapshot(target), before)
        self.assertEqual(app_nodes.read_text(encoding="utf-8"), '{"id":"n_aaaaaaaaaaa1"}\n')

    def test_export_refuses_non_empty_destination_without_replace(self):
        self.seed_graph()
        target = self.project.path / "app"
        (target / "graph").mkdir(parents=True)
        (target / "graph" / "nodes.jsonl").write_text('{"id":"n_aaaaaaaaaaa1"}\n', encoding="utf-8")
        (target / "graph" / "chains.jsonl").write_text("", encoding="utf-8")
        _helpers.write_json_file(target / "graph" / "format.json", {"version": 1})
        before = _helpers.snapshot(target)

        code, out, err = self.export(target)

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("--replace", err)
        self.assertIn("nodes.jsonl", err)
        self.assertEqual(_helpers.snapshot(target), before)

    def test_export_replace_overwrites_existing_ledgers(self):
        self.seed_graph()
        target = self.project.path / "app"
        (target / "graph").mkdir(parents=True)
        (target / "graph" / "nodes.jsonl").write_text('{"id":"n_aaaaaaaaaaa1"}\n', encoding="utf-8")
        (target / "graph" / "chains.jsonl").write_text('{"id":"arg_aaaaaaaaaaa1"}\n', encoding="utf-8")
        _helpers.write_json_file(target / "graph" / "format.json", {"version": 1})
        other = target / "sessions.jsonl"
        other.write_text('{"chatId":"keep-me"}\n', encoding="utf-8")

        code, out, err = self.export(target, "--replace")
        self.assertEqual(code, 0, err)
        result = json.loads(out)["records"][0]
        self.assertEqual(result["action"], "replaced")
        self.assertEqual(result["nodes"], 2)
        self.assertEqual(result["chains"], 1)
        self.assertEqual(result["to"], str(target / "graph"))

        self.assertEqual((target / "graph" / "nodes.jsonl").read_bytes(), self.source_bytes("nodes.jsonl"))
        self.assertEqual((target / "graph" / "chains.jsonl").read_bytes(), self.source_bytes("chains.jsonl"))
        self.assertEqual(other.read_text(encoding="utf-8"), '{"chatId":"keep-me"}\n')
        self.assertEqual(
            sorted(path.name for path in (target / "graph").iterdir()),
            ["chains.jsonl", "format.json", "nodes.jsonl"],
        )

        code, out, err = self.export(target, "--replace", format="markdown")
        self.assertEqual(code, 0, err)
        self.assertIn("replaced", out.lower())

    def test_export_refuses_when_source_record_is_absent(self):
        target = self.project.path / "app"

        code, out, err = self.export(target)

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("no graph to export", err)
        self.assertFalse(target.exists())
        self.assertFalse((self.project.root / "graph").exists())

        target.mkdir()
        code, out, err = self.export(target)
        self.assertEqual(code, 1)
        self.assertEqual(list(target.iterdir()), [])

    def test_export_into_fresh_data_dir_creates_graph_subdirectory(self):
        self.seed_graph()
        target = self.project.path / "fresh-data"

        code, out, err = self.export(target)

        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["records"][0]["action"], "created")
        graph = target / "graph"
        self.assertEqual((graph / "nodes.jsonl").read_bytes(), self.source_bytes("nodes.jsonl"))
        self.assertEqual((graph / "chains.jsonl").read_bytes(), self.source_bytes("chains.jsonl"))
        self.assertEqual(json.loads((graph / "format.json").read_text(encoding="utf-8")), {"version": 1})
        self.assertFalse((target / "nodes.jsonl").exists())
        self.assertEqual(sorted(path.name for path in target.iterdir()), ["graph"])

        code, out, err = self.export(self.project.path / "second-fresh", format="markdown")
        self.assertEqual(code, 0, err)
        self.assertIn("created", out.lower())
        self.assertIn("Nodes: 2", out)
        self.assertIn("Chains: 1", out)

    def test_export_into_data_dir_with_only_chats_creates_graph_subdirectory(self):
        self.seed_graph()
        target = self.project.path / "app"
        (target / "chats").mkdir(parents=True)
        chats = target / "chats" / "chats.jsonl"
        chats.write_text('{"keep":true}\n', encoding="utf-8")

        code, out, err = self.export(target)

        self.assertEqual(code, 0, err)
        self.assertTrue((target / "graph" / "nodes.jsonl").is_file())
        self.assertTrue((target / "graph" / "format.json").is_file())
        self.assertFalse((target / "chats" / "nodes.jsonl").exists())
        self.assertFalse((target / "nodes.jsonl").exists())
        self.assertEqual(chats.read_text(encoding="utf-8"), '{"keep":true}\n')

    def test_export_into_directory_with_ledgers_writes_in_place(self):
        self.seed_graph()
        target = self.project.path / "existing-ledgers"
        target.mkdir()
        (target / "nodes.jsonl").write_text("", encoding="utf-8")

        code, out, err = self.export(target)

        self.assertEqual(code, 0, err)
        self.assertEqual((target / "nodes.jsonl").read_bytes(), self.source_bytes("nodes.jsonl"))
        self.assertTrue((target / "chains.jsonl").is_file())
        self.assertFalse((target / "graph").exists())

    def test_export_into_empty_directory_named_graph_writes_in_place(self):
        self.seed_graph()
        target = self.project.path / "elsewhere" / "graph"

        code, out, err = self.export(target)

        self.assertEqual(code, 0, err)
        self.assertTrue((target / "nodes.jsonl").is_file())
        self.assertFalse((target / "graph").exists())

    def test_export_refuses_malformed_source_node_line(self):
        self.seed_graph()
        with (self.project.root / "graph" / "nodes.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"id":"n_000000000001","statement":"","aliases":[],"provenance":[]}\n')
        target = self.project.path / "app"

        code, out, err = self.export(target)

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("nodes.jsonl:3", err)
        self.assertIn("empty statement", err)
        self.assertFalse(target.exists())

    def test_export_refuses_chain_with_unresolved_endpoint(self):
        self.seed_graph()
        with (self.project.root / "graph" / "chains.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                '{"id":"arg_000000000001","premises":["n_0000000000ff"],"conclusion":"n_0000000000ff",'
                '"provenance":[],"createdAt":"2026-01-01T00:00:00Z"}\n'
            )
        target = self.project.path / "app"

        code, out, err = self.export(target)

        self.assertEqual(code, 1)
        self.assertIn("chains.jsonl:2", err)
        self.assertIn("does not resolve", err)
        self.assertFalse(target.exists())

    def test_export_refuses_torn_source_line(self):
        self.seed_graph()
        with (self.project.root / "graph" / "nodes.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"id":\n')
        target = self.project.path / "app"

        code, out, err = self.export(target)

        self.assertEqual(code, 1)
        self.assertIn("nodes.jsonl:3", err)
        self.assertIn("malformed json", err)
        self.assertFalse(target.exists())


class CwdIndependenceTests(GraphTestCase):
    def test_scripts_do_not_depend_on_the_current_directory(self):
        self.merge_ok({"nodes": [{"ref": "a", "statement": "A proposition.", "name": "A"}]})
        with tempfile.TemporaryDirectory() as elsewhere:
            code, out, err = self.graph("propositions", cwd=elsewhere)
            self.assertEqual(code, 0, err)
            self.assertEqual(len(json.loads(out)["records"]), 1)

            # With no --data-dir, the record root is found by walking up from CWD.
            code, out, err = _helpers.run_script(
                "graph.py", ["--format", "json", "propositions"], cwd=self.project.path
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(len(json.loads(out)["records"]), 1)


if __name__ == "__main__":
    unittest.main()
