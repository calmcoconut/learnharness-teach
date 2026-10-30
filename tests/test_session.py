"""Tests for ``scripts/session.py`` — the record layer.

Stdlib unittest only. Every command runs as a subprocess with ``cwd`` set to a
throwaway project, which is also how the suite proves CWD independence and that
nothing outside ``.learnharness/`` is written.
"""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

import _helpers  # noqa: F401  (puts scripts/ on sys.path and disables bytecode)
from _helpers import TempProject, read_jsonl, run_script, snapshot, write_json_file

import _data

START = "2026-01-14T09:31:07Z"
PLAN_PY = _helpers.SCRIPTS / "plan.py"
HAS_PLAN = PLAN_PY.exists()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def run_session(project, *args):
    return run_script("session.py", list(args), cwd=project.path)


def init(project, goal="understand entropy", kind="teach"):
    code, out, err = run_session(project, "init", "--goal", goal, "--kind", kind)
    if code != 0:
        raise AssertionError("init failed: %s" % err)
    return out.strip()


def nodes(*ids):
    return [{"id": node_id, "title": node_id.capitalize()} for node_id in ids]


def plan_document(ids=("a", "b"), edges=None):
    if edges is None:
        edges = [{"from": ids[index], "to": ids[index + 1]} for index in range(len(ids) - 1)]
    return {"nodes": nodes(*ids), "edges": edges}


def append_events(project, session_id, records):
    """Append hand-written events, continuing the seq of the current log."""
    path = project.root / "sessions" / session_id / "session.jsonl"
    existing = read_jsonl(path)
    seq = existing[-1]["seq"] + 1 if existing else 1
    lines = []
    for record in records:
        payload = {"seq": seq, "at": START}
        payload.update(record)
        seq += 1
        lines.append(json.dumps(payload, separators=(",", ":")))
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")


def pose(project, session_id, question="q", key="k", node=None, options=None,
         correct=None, key_file=None):
    args = ["check", "--session", session_id, "--question", question]
    if key is not None:
        args += ["--key", key]
    if key_file is not None:
        args += ["--key-file", str(key_file)]
    if node is not None:
        args += ["--node", node]
    if options is not None:
        args += ["--options", options]
    if correct is not None:
        args += ["--correct", correct]
    return run_session(project, *args)


def answer(project, session_id, select=None, text=None, correct=None,
           confidence=3, trace="because"):
    args = ["answer", "--session", session_id, "--confidence", str(confidence), "--trace", trace]
    if select is not None:
        args += ["--select", select]
    if text is not None:
        args += ["--text", text]
    if correct is not None:
        args += ["--correct", correct]
    return run_session(project, *args)


def conclude_probe(project, session_id, strands=None, summary=None):
    if strands is None:
        strands = [{"strand": "entropy as counting", "assessment": "holds"}]
    args = ["conclude-probe", "--session", session_id, "--strands-json", json.dumps(strands)]
    if summary is not None:
        args += ["--summary", summary]
    return run_session(project, *args)


def set_plan(project, session_id, document):
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "plan.json"
        write_json_file(path, document)
        return run_session(project, "plan-set", "--session", session_id, "--plan", str(path))


def state_json(project, session_id):
    code, out, err = run_session(project, "state", "--session", session_id, "--format", "json")
    if code != 0:
        raise AssertionError("state failed: %s" % err)
    return json.loads(out)


def state_text(project, session_id):
    code, out, err = run_session(project, "state", "--session", session_id)
    if code != 0:
        raise AssertionError("state failed: %s" % err)
    return out


def events_of(project, session_id, event_type):
    return [event for event in project.events(session_id) if event.get("type") == event_type]


def practice_session(project, goal="practice heat", problem=None, result=None):
    session_id = init(project, goal=goal, kind="practice")
    if problem is not None:
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "problem.json"
            write_json_file(path, problem)
            code, out, err = run_session(
                project, "practice-problem", "--session", session_id, "--problem", str(path)
            )
            if code != 0:
                raise AssertionError("practice-problem failed: %s" % err)
    if result is not None:
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "result.json"
            write_json_file(path, result)
            code, out, err = run_session(
                project, "practice-concluded", "--session", session_id, "--result", str(path)
            )
            if code != 0:
                raise AssertionError("practice-concluded failed: %s" % err)
    return session_id


def run_practice_problem(project, session_id, document):
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "problem.json"
        write_json_file(path, document)
        return run_session(
            project, "practice-problem", "--session", session_id, "--problem", str(path)
        )


def run_practice_concluded(project, session_id, document):
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "result.json"
        write_json_file(path, document)
        return run_session(
            project, "practice-concluded", "--session", session_id, "--result", str(path)
        )


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------


class InitTests(unittest.TestCase):
    def test_init_creates_directory_stamp_and_session_start(self):
        with TempProject() as project:
            code, out, err = run_session(project, "init", "--goal", "understand entropy")
            self.assertEqual(code, 0, err)
            session_id = out.strip()
            self.assertRegex(session_id, _data.SESSION_ID_RE)

            directory = project.root / "sessions" / session_id
            self.assertTrue(directory.is_dir())
            events = read_jsonl(directory / "session.jsonl")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["seq"], 1)
            self.assertEqual(events[0]["type"], "session_start")
            self.assertEqual(events[0]["kind"], "teach")
            self.assertEqual(events[0]["goal"], "understand entropy")

            stamp = project.root / "graph" / "format.json"
            self.assertTrue(stamp.is_file())
            self.assertEqual(json.loads(stamp.read_text(encoding="utf-8"))["version"], 1)

    def test_init_accepts_practice_kind_and_unique_ids(self):
        with TempProject() as project:
            first = init(project, goal="practice heat", kind="practice")
            second = init(project, goal="another")
            self.assertNotEqual(first, second)
            self.assertEqual(project.events(first)[0]["kind"], "practice")
            self.assertEqual(project.events(second)[0]["kind"], "teach")


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------


class CheckTests(unittest.TestCase):
    def test_check_refuses_when_a_check_is_open(self):
        with TempProject() as project:
            session_id = project.make_session()
            self.assertEqual(pose(project, session_id, question="one")[0], 0)
            code, out, err = pose(project, session_id, question="two")
            self.assertEqual(code, 1)
            self.assertIn("already open", err)
            self.assertEqual(len(events_of(project, session_id, "check_posed")), 1)

    def test_check_refuses_without_a_key(self):
        with TempProject() as project:
            session_id = project.make_session()
            code, out, err = pose(project, session_id, key=None)
            self.assertEqual(code, 1)
            self.assertIn("key", err)
            self.assertEqual(events_of(project, session_id, "check_posed"), [])

    def test_check_refuses_unknown_node_after_the_probe(self):
        with TempProject() as project:
            session_id = project.make_session()
            append_events(
                project,
                session_id,
                [{"type": "probe_concluded", "strands": [{"strand": "s", "assessment": "a"}]}],
            )
            code, out, err = pose(project, session_id, node="nope")
            self.assertEqual(code, 1)
            self.assertIn("current plan", err)
            self.assertEqual(events_of(project, session_id, "check_posed"), [])

    def test_check_refuses_a_node_tag_before_the_probe_concludes(self):
        with TempProject() as project:
            session_id = project.make_session()
            code, out, err = pose(project, session_id, node="a")
            self.assertEqual(code, 1)
            self.assertIn("probe", err)
            self.assertEqual(events_of(project, session_id, "check_posed"), [])

    def test_probe_phase_checks_still_work_before_the_conclusion(self):
        with TempProject() as project:
            session_id = project.make_session()
            self.assertEqual(pose(project, session_id, key="the key")[0], 0)
            self.assertEqual(answer(project, session_id, text="x", correct="true")[0], 0)
            self.assertEqual(len(events_of(project, session_id, "check_posed")), 1)
            self.assertEqual(len(events_of(project, session_id, "answer")), 1)
            self.assertEqual(state_json(project, session_id)["phase"], "probe")

    def test_check_writes_the_key_into_the_event_without_showing_it(self):
        with TempProject() as project:
            session_id = project.make_session()
            code, out, err = pose(
                project,
                session_id,
                question="What does reversible mean?",
                key="No net change in the universe.",
                options="run backwards,slow,isothermal",
                correct="0,2",
            )
            self.assertEqual(code, 0, err)
            self.assertNotIn("No net change in the universe.", out)
            check = events_of(project, session_id, "check_posed")[0]
            self.assertEqual(check["key"], "No net change in the universe.")
            self.assertEqual(check["options"], ["run backwards", "slow", "isothermal"])
            self.assertEqual(check["correct"], [0, 2])
            self.assertIsNone(check["node"])

    def test_check_free_recall_has_no_options_or_correct(self):
        with TempProject() as project:
            session_id = project.make_session()
            self.assertEqual(pose(project, session_id, key="the key")[0], 0)
            check = events_of(project, session_id, "check_posed")[0]
            self.assertNotIn("options", check)
            self.assertNotIn("correct", check)
            self.assertEqual(check["key"], "the key")

    def test_check_refuses_correct_without_options(self):
        with TempProject() as project:
            session_id = project.make_session()
            code, out, err = pose(project, session_id, correct="0")
            self.assertEqual(code, 1)
            self.assertIn("free-recall", err)

    def test_check_refuses_options_without_correct(self):
        with TempProject() as project:
            session_id = project.make_session()
            code, out, err = pose(project, session_id, options="a,b")
            self.assertEqual(code, 1)
            self.assertIn("--correct", err)

    def test_check_accepts_key_file(self):
        with TempProject() as project:
            session_id = project.make_session()
            key_path = project.path / "key.txt"
            key_path.write_text("from a file\n", encoding="utf-8")
            code, out, err = pose(project, session_id, key=None, key_file=key_path)
            self.assertEqual(code, 0, err)
            self.assertEqual(events_of(project, session_id, "check_posed")[0]["key"], "from a file")


class ConcurrentCheckTests(unittest.TestCase):
    def test_parallel_checks_get_unique_seqs_and_leave_exactly_one_open(self):
        with TempProject() as project:
            session_id = project.make_session()
            results = []
            lock = threading.Lock()
            barrier = threading.Barrier(6)

            def worker(index):
                barrier.wait()
                result = pose(project, session_id, question="parallel %d" % index)
                with lock:
                    results.append(result)

            threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
                self.assertFalse(thread.is_alive(), "a check subprocess did not finish")

            events = project.events(session_id)
            seqs = [event["seq"] for event in events]
            self.assertEqual(seqs, list(range(1, len(events) + 1)))
            self.assertEqual(len(set(seqs)), len(seqs))

            checks = events_of(project, session_id, "check_posed")
            self.assertEqual(len(checks), 1)
            self.assertEqual([result[0] for result in results].count(0), 1)
            self.assertEqual(state_json(project, session_id)["open"]["seq"], checks[0]["seq"])


# --------------------------------------------------------------------------
# answer
# --------------------------------------------------------------------------


class AnswerTests(unittest.TestCase):
    def test_answer_refuses_with_no_open_check(self):
        with TempProject() as project:
            session_id = project.make_session()
            code, out, err = answer(project, session_id, select="0")
            self.assertEqual(code, 1)
            self.assertIn("no check is open", err)

    def test_answer_grades_an_option_check(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id, options="a,b,c", correct="0,2")
            code, out, err = answer(
                project, session_id, select="0,2", confidence=4, trace="no net change"
            )
            self.assertEqual(code, 0, err)
            answer_event = events_of(project, session_id, "answer")[0]
            self.assertEqual(answer_event["check_seq"], 2)
            self.assertEqual(answer_event["selection"], [0, 2])
            self.assertTrue(answer_event["correct"])
            self.assertEqual(answer_event["confidence"], 4)
            self.assertEqual(answer_event["trace"], "no net change")

            pose(project, session_id, options="a,b", correct="1")
            self.assertEqual(answer(project, session_id, select="0")[0], 0)
            self.assertFalse(events_of(project, session_id, "answer")[-1]["correct"])

    def test_answer_grades_a_free_recall_check_with_the_judgement(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id, key="the key")
            code, out, err = answer(
                project, session_id, text="my explanation", correct="true", confidence=4
            )
            self.assertEqual(code, 0, err)
            answer_event = events_of(project, session_id, "answer")[0]
            self.assertEqual(answer_event["selection"], ["my explanation"])
            self.assertTrue(answer_event["correct"])

            pose(project, session_id, key="the key")
            self.assertEqual(
                answer(project, session_id, text="other", correct="false")[0], 0
            )
            self.assertFalse(events_of(project, session_id, "answer")[-1]["correct"])

    def test_answer_refuses_free_recall_without_a_judgement(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id)
            code, out, err = answer(project, session_id, text="my explanation")
            self.assertEqual(code, 1)
            self.assertIn("--correct", err)
            self.assertEqual(events_of(project, session_id, "answer"), [])

    def test_answer_refuses_empty_free_recall_text(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id)
            code, out, err = answer(project, session_id, text="   ", correct="true")
            self.assertEqual(code, 1)
            self.assertIn("--text", err)
            self.assertEqual(events_of(project, session_id, "answer"), [])

    def test_answer_refuses_out_of_range_confidence(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id)
            code, out, err = answer(project, session_id, text="x", correct="true", confidence=9)
            self.assertEqual(code, 1)
            self.assertIn("confidence", err)
            self.assertEqual(events_of(project, session_id, "answer"), [])

    def test_answer_refuses_select_out_of_range(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id, options="a,b", correct="0")
            code, out, err = answer(project, session_id, select="5")
            self.assertEqual(code, 1)
            self.assertIn("out of range", err)


# --------------------------------------------------------------------------
# conclude-probe
# --------------------------------------------------------------------------


class ConcludeProbeTests(unittest.TestCase):
    def test_refuses_while_a_check_is_open(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id)
            code, out, err = conclude_probe(project, session_id)
            self.assertEqual(code, 1)
            self.assertIn("open", err)
            self.assertEqual(events_of(project, session_id, "probe_concluded"), [])

    def test_refuses_before_any_check_has_been_answered(self):
        with TempProject() as project:
            session_id = project.make_session()
            code, out, err = conclude_probe(project, session_id)
            self.assertEqual(code, 1)
            self.assertIn("answered", err)
            self.assertEqual(events_of(project, session_id, "probe_concluded"), [])

            # An answer that names no real check is not a measurement either.
            append_events(
                project,
                session_id,
                [
                    {
                        "type": "answer",
                        "check_seq": 99,
                        "selection": ["x"],
                        "correct": True,
                        "confidence": 3,
                        "trace": "t",
                    }
                ],
            )
            code, out, err = conclude_probe(project, session_id)
            self.assertEqual(code, 1)
            self.assertIn("answered", err)
            self.assertEqual(events_of(project, session_id, "probe_concluded"), [])

            # A posed-but-unanswered check is still not a measurement.
            pose(project, session_id)
            code, out, err = conclude_probe(project, session_id)
            self.assertEqual(code, 1)
            self.assertIn("open", err)
            self.assertEqual(events_of(project, session_id, "probe_concluded"), [])

    def test_succeeds_once_and_then_refuses(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id)
            answer(project, session_id, text="x", correct="true")
            code, out, err = conclude_probe(project, session_id, summary="strong on counting")
            self.assertEqual(code, 0, err)
            probe = events_of(project, session_id, "probe_concluded")[0]
            self.assertEqual(probe["summary"], "strong on counting")
            self.assertEqual(probe["strands"], [{"strand": "entropy as counting", "assessment": "holds"}])

            code, out, err = conclude_probe(project, session_id)
            self.assertEqual(code, 1)
            self.assertIn("already concluded", err)
            self.assertEqual(len(events_of(project, session_id, "probe_concluded")), 1)

    def test_reads_strands_from_a_file_and_accepts_a_summary_in_the_document(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id)
            answer(project, session_id, text="x", correct="true")
            strands = [{"strand": "counting", "assessment": "holds"}]
            path = project.path / "strands.json"
            write_json_file(path, {"strands": strands, "summary": "from the file"})
            code, out, err = run_session(
                project, "conclude-probe", "--session", session_id, "--strands", str(path)
            )
            self.assertEqual(code, 0, err)
            probe = events_of(project, session_id, "probe_concluded")[0]
            self.assertEqual(probe["strands"], strands)
            self.assertEqual(probe["summary"], "from the file")

    def test_strand_count_is_advisory_only(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id)
            answer(project, session_id, text="x", correct="true")
            strands = [
                {"strand": "strand %d" % index, "assessment": "assessment"}
                for index in range(_data.WARN_STRANDS + 1)
            ]
            code, out, err = conclude_probe(project, session_id, strands=strands)
            self.assertEqual(code, 0, err)
            self.assertIn("advisory", err)
            self.assertEqual(len(events_of(project, session_id, "probe_concluded")), 1)

    def test_refuses_empty_strands(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id)
            answer(project, session_id, text="x", correct="true")
            code, out, err = conclude_probe(project, session_id, strands=[])
            self.assertEqual(code, 1)
            self.assertIn("strand", err)


# --------------------------------------------------------------------------
# phase derivation
# --------------------------------------------------------------------------


class PhaseTests(unittest.TestCase):
    def test_probe_plan_teach_closed_transitions(self):
        with TempProject() as project:
            session_id = project.make_session()
            self.assertEqual(state_json(project, session_id)["phase"], "probe")

            # A probe check is untagged, so it does not leave the probe phase.
            pose(project, session_id)
            answer(project, session_id, text="x", correct="true")
            self.assertEqual(state_json(project, session_id)["phase"], "probe")

            self.assertEqual(conclude_probe(project, session_id)[0], 0)
            self.assertEqual(state_json(project, session_id)["phase"], "plan")

            # Authoring a plan does not by itself leave the plan phase.
            append_events(
                project,
                session_id,
                [{"type": "plan_set", "revision": 1, "nodes": nodes("a", "b"), "edges": [{"from": "a", "to": "b"}]}],
            )
            self.assertEqual(state_json(project, session_id)["phase"], "plan")

            # The first node-tagged check ends it.
            self.assertEqual(pose(project, session_id, node="a")[0], 0)
            self.assertEqual(state_json(project, session_id)["phase"], "teach")
            self.assertEqual(answer(project, session_id, text="x", correct="true")[0], 0)

            self.assertEqual(run_session(project, "close", "--session", session_id)[0], 0)
            self.assertEqual(state_json(project, session_id)["phase"], "closed")

    def test_practice_kind_is_practice_and_closed_wins(self):
        with TempProject() as project:
            session_id = init(project, goal="practice", kind="practice")
            self.assertEqual(state_json(project, session_id)["phase"], "practice")
            self.assertEqual(run_session(project, "close", "--session", session_id)[0], 0)
            self.assertEqual(state_json(project, session_id)["phase"], "closed")


# --------------------------------------------------------------------------
# current / visited
# --------------------------------------------------------------------------


class PositionTests(unittest.TestCase):
    def test_current_and_visited_across_three_checks(self):
        with TempProject() as project:
            session_id = project.make_session()
            append_events(
                project,
                session_id,
                [
                    {"type": "probe_concluded", "strands": [{"strand": "s", "assessment": "a"}]},
                    {
                        "type": "plan_set",
                        "revision": 1,
                        "nodes": nodes("a", "b", "c", "d"),
                        "edges": [
                            {"from": "a", "to": "b"},
                            {"from": "b", "to": "c"},
                            {"from": "c", "to": "d"},
                        ],
                    },
                ],
            )

            for node_id in ("a", "b", "c"):
                self.assertEqual(pose(project, session_id, node=node_id, options="x,y", correct="0")[0], 0)
                self.assertEqual(answer(project, session_id, select="0")[0], 0)

            fields = state_json(project, session_id)
            self.assertEqual(fields["current"], "c")
            self.assertEqual(fields["visited"], ["a", "b"])
            # 4 nodes, two visited, one in progress -> exactly one untouched.
            self.assertEqual(fields["next"], {"untouched": 1, "total": 4})
            self.assertIsNone(fields["open"])
            self.assertEqual(fields["last"]["node"], "c")

            # An open check shows up but does not move position.
            self.assertEqual(pose(project, session_id, node="d", options="x,y", correct="0")[0], 0)
            fields = state_json(project, session_id)
            self.assertEqual(fields["current"], "d")
            self.assertEqual(fields["visited"], ["a", "b", "c"])
            self.assertEqual(fields["open"]["seq"], 10)

    def test_untouched_does_not_double_count_a_current_node_that_was_visited(self):
        with TempProject() as project:
            session_id = project.make_session()
            append_events(
                project,
                session_id,
                [
                    {"type": "probe_concluded", "strands": [{"strand": "s", "assessment": "a"}]},
                    {
                        "type": "plan_set",
                        "revision": 1,
                        "nodes": nodes("a", "b", "c"),
                        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
                    },
                ],
            )
            for node_id in ("a", "b", "a"):
                self.assertEqual(
                    pose(project, session_id, node=node_id, options="x,y", correct="0")[0], 0
                )
                self.assertEqual(answer(project, session_id, select="0")[0], 0)

            fields = state_json(project, session_id)
            self.assertEqual(fields["current"], "a")
            self.assertEqual(fields["visited"], ["a", "b"])
            # Three nodes, a and b seen, a is also current; c is the only untouched node.
            self.assertEqual(fields["next"], {"untouched": 1, "total": 3})


# --------------------------------------------------------------------------
# step-close
# --------------------------------------------------------------------------


class StepCloseTests(unittest.TestCase):
    def setUp(self):
        self.project = TempProject()
        self.session_id = self.project.make_session()
        append_events(
            self.project,
            self.session_id,
            [
                {"type": "probe_concluded", "strands": [{"strand": "s", "assessment": "a"}]},
                {"type": "plan_set", "revision": 1, "nodes": nodes("a", "b"), "edges": [{"from": "a", "to": "b"}]},
            ],
        )

    def tearDown(self):
        self.project.__exit__(None, None, None)

    def test_refuses_unknown_node(self):
        code, out, err = run_session(
            self.project, "step-close", "--session", self.session_id, "--node", "zzz"
        )
        self.assertEqual(code, 1)
        self.assertIn("current plan", err)
        self.assertEqual(events_of(self.project, self.session_id, "step_closed"), [])

    def test_refuses_before_the_probe_concludes(self):
        with TempProject() as project:
            session_id = project.make_session()
            append_events(
                project,
                session_id,
                [{"type": "plan_set", "revision": 1, "nodes": nodes("a"), "edges": []}],
            )
            code, out, err = run_session(
                project, "step-close", "--session", session_id, "--node", "a"
            )
            self.assertEqual(code, 1)
            self.assertIn("probe", err)
            self.assertEqual(events_of(project, session_id, "step_closed"), [])

    def test_records_outcome_and_defaults_to_held(self):
        code, out, err = run_session(
            self.project, "step-close", "--session", self.session_id, "--node", "a"
        )
        self.assertEqual(code, 0, err)
        code, out, err = run_session(
            self.project,
            "step-close",
            "--session",
            self.session_id,
            "--node",
            "b",
            "--outcome",
            "missed",
        )
        self.assertEqual(code, 0, err)
        steps = events_of(self.project, self.session_id, "step_closed")
        self.assertEqual([step["node"] for step in steps], ["a", "b"])
        self.assertEqual([step["outcome"] for step in steps], ["held", "missed"])

    def test_step_count_is_advisory_only(self):
        append_events(
            self.project,
            self.session_id,
            [{"type": "step_closed", "node": "a", "outcome": "held"} for _ in range(_data.WARN_STEPS)],
        )
        code, out, err = run_session(
            self.project, "step-close", "--session", self.session_id, "--node", "a"
        )
        self.assertEqual(code, 0, err)
        self.assertIn("advisory", err)
        self.assertEqual(
            len(events_of(self.project, self.session_id, "step_closed")), _data.WARN_STEPS + 1
        )


# --------------------------------------------------------------------------
# close
# --------------------------------------------------------------------------


class CloseTests(unittest.TestCase):
    def test_close_succeeds_once_then_refuses(self):
        with TempProject() as project:
            session_id = project.make_session()
            code, out, err = run_session(project, "close", "--session", session_id)
            self.assertEqual(code, 0, err)
            closed = events_of(project, session_id, "session_closed")
            self.assertEqual(len(closed), 1)
            self.assertEqual(closed[0]["seq"], 2)

            code, out, err = run_session(project, "close", "--session", session_id)
            self.assertEqual(code, 1)
            self.assertIn("already closed", err)
            self.assertEqual(len(events_of(project, session_id, "session_closed")), 1)

    def test_close_refuses_while_a_check_is_open_and_names_its_seq(self):
        with TempProject() as project:
            session_id = project.make_session()
            self.assertEqual(pose(project, session_id)[0], 0)
            code, out, err = run_session(project, "close", "--session", session_id)
            self.assertEqual(code, 1)
            self.assertIn("check 2", err)
            self.assertIn("open", err)
            self.assertEqual(events_of(project, session_id, "session_closed"), [])

            self.assertEqual(answer(project, session_id, text="x", correct="true")[0], 0)
            self.assertEqual(run_session(project, "close", "--session", session_id)[0], 0)

    def test_mutations_refuse_after_close(self):
        with TempProject() as project:
            session_id = project.make_session()
            run_session(project, "close", "--session", session_id)
            code, out, err = pose(project, session_id)
            self.assertEqual(code, 1)
            self.assertIn("closed", err)

            # Reading the record still works.
            self.assertEqual(state_json(project, session_id)["closed"], True)
            self.assertEqual(run_session(project, "render", "--session", session_id)[0], 0)


class StartedLogTests(unittest.TestCase):
    def test_every_mutating_command_refuses_an_empty_log(self):
        with TempProject() as project, tempfile.TemporaryDirectory() as scratch:
            session_id = project.make_session()
            project.write_events(session_id, [])
            plan_path = Path(scratch) / "plan.json"
            write_json_file(plan_path, plan_document(("a", "b")))
            problem_path = Path(scratch) / "problem.json"
            write_json_file(
                problem_path,
                {"statement": "s", "mode": "recall", "target": ["a"], "modelSolution": "m"},
            )
            result_path = Path(scratch) / "result.json"
            write_json_file(
                result_path,
                {"outcome": "solved", "verdict": "v", "rung": None, "missClass": None, "retest": False},
            )
            commands = [
                ("check", ["--question", "q", "--key", "k"]),
                ("answer", ["--text", "x", "--correct", "true", "--confidence", "3", "--trace", "t"]),
                (
                    "conclude-probe",
                    ["--strands-json", json.dumps([{"strand": "s", "assessment": "a"}])],
                ),
                ("plan-set", ["--plan", str(plan_path)]),
                ("step-close", ["--node", "a"]),
                ("practice-problem", ["--problem", str(problem_path)]),
                ("practice-concluded", ["--result", str(result_path)]),
                ("close", []),
            ]
            for command, extra in commands:
                with self.subTest(command=command):
                    code, out, err = run_session(
                        project, command, "--session", session_id, *extra
                    )
                    self.assertEqual(code, 1)
                    self.assertIn("session_start", err)
                    self.assertEqual(project.events(session_id), [])

    def test_refuses_a_log_whose_first_event_is_not_session_start(self):
        with TempProject() as project:
            session_id = project.make_session()
            project.write_events(
                session_id,
                [
                    {
                        "seq": 1,
                        "at": START,
                        "type": "answer",
                        "check_seq": 1,
                        "selection": ["x"],
                        "correct": True,
                        "confidence": 3,
                        "trace": "t",
                    }
                ],
            )
            code, out, err = run_session(project, "close", "--session", session_id)
            self.assertEqual(code, 1)
            self.assertIn("session_start", err)
            self.assertEqual(events_of(project, session_id, "session_closed"), [])


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------


class StateTests(unittest.TestCase):
    def test_text_layout_matches_the_plan(self):
        with TempProject() as project:
            session_id = project.make_session(goal="understand entropy")
            append_events(
                project,
                session_id,
                [
                    {"type": "probe_concluded", "strands": [{"strand": "s", "assessment": "a"}]},
                    {
                        "type": "plan_set",
                        "revision": 1,
                        "nodes": nodes("a", "b", "c", "d"),
                        "edges": [
                            {"from": "a", "to": "b"},
                            {"from": "b", "to": "c"},
                            {"from": "c", "to": "d"},
                        ],
                    },
                ],
            )
            for node_id in ("a", "b", "c"):
                pose(project, session_id, node=node_id, options="x,y", correct="0")
                answer(project, session_id, select="0", confidence=4, trace="because")

            expected = "\n".join(
                [
                    "session  lh_testsess   kind teach   phase teach   closed no",
                    "goal     understand entropy",
                    "plan     revision 1, 4 nodes, 3 edges",
                    "current  c",
                    "visited  a, b",
                    "open     none",
                    "last     c \u2014 correct (confidence 4)",
                    '         "because"',
                    "next     1 of 4 nodes untouched",
                ]
            ) + "\n"
            self.assertEqual(state_text(project, session_id), expected)

    def test_json_carries_the_same_fields(self):
        with TempProject() as project:
            session_id = project.make_session()
            fields = state_json(project, session_id)
            self.assertEqual(
                set(fields),
                {
                    "session",
                    "kind",
                    "phase",
                    "closed",
                    "goal",
                    "plan",
                    "current",
                    "visited",
                    "open",
                    "last",
                    "next",
                    "practice",
                },
            )
            self.assertEqual(fields["session"], session_id)
            self.assertEqual(fields["kind"], "teach")
            self.assertEqual(fields["phase"], "probe")
            self.assertFalse(fields["closed"])
            self.assertIsNone(fields["plan"])
            self.assertIsNone(fields["current"])
            self.assertEqual(fields["visited"], [])
            self.assertIsNone(fields["open"])
            self.assertIsNone(fields["last"])
            self.assertIsNone(fields["next"])

    def test_open_check_and_missing_plan_render_deterministically(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id, question="What is entropy?", key="a count")
            text = state_text(project, session_id)
            self.assertIn("open     %d \u2014 What is entropy?" % 2, text)
            self.assertIn("plan     none", text)
            self.assertIn("next     none", text)
            self.assertIn("last     none", text)

    def test_plan_warning_appears_above_the_advisory_limit(self):
        with TempProject() as project:
            session_id = project.make_session()
            many = ["n%d" % index for index in range(_data.WARN_PLAN_NODES + 1)]
            append_events(
                project,
                session_id,
                [{"type": "plan_set", "revision": 1, "nodes": nodes(*many), "edges": []}],
            )
            text = state_text(project, session_id)
            self.assertIn("(warn: above %d nodes)" % _data.WARN_PLAN_NODES, text)
            self.assertEqual(
                state_json(project, session_id)["plan"]["warn"],
                "above %d nodes" % _data.WARN_PLAN_NODES,
            )

    def test_state_stays_bounded(self):
        with TempProject() as project:
            session_id = project.make_session()
            append_events(
                project,
                session_id,
                [
                    {"type": "plan_set", "revision": 1, "nodes": nodes("a", "b"), "edges": []},
                    {"type": "check_posed", "node": "a", "question": "q", "options": ["x", "y"], "correct": [0], "key": "k"},
                    {"type": "answer", "check_seq": 2, "selection": [0], "correct": True, "confidence": 3, "trace": "t" * 5000},
                ],
            )
            text = state_text(project, session_id)
            self.assertLess(len(text), 2000)
            self.assertIn("...", text)


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------


class RenderTests(unittest.TestCase):
    def _teach_session(self, project):
        session_id = project.make_session(goal="understand entropy")
        append_events(
            project,
            session_id,
            [
                {
                    "type": "probe_concluded",
                    "strands": [{"strand": "counting", "assessment": "holds"}],
                    "summary": "Strong on counting.",
                },
                {"type": "plan_set", "revision": 1, "nodes": nodes("a", "b", "c", "d"),
                 "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "c", "to": "d"}]},
            ],
        )
        for node_id in ("a", "b", "c"):
            pose(project, session_id, node=node_id, options="x,y", correct="0", key="key for %s" % node_id)
            answer(project, session_id, select="0", confidence=4, trace="reason")
        return session_id

    def test_renders_the_expected_structure(self):
        with TempProject() as project:
            session_id = self._teach_session(project)
            code, text, err = run_session(project, "render", "--session", session_id)
            self.assertEqual(code, 0, err)
            for heading in ("# understand entropy", "## Probe", "## Plan", "## Steps", "## Session"):
                self.assertIn(heading, text)
            self.assertIn("| Strand | Assessment |", text)
            self.assertIn("Strong on counting.", text)
            self.assertIn("Revision 1 \u2014 4 nodes, 3 edges.", text)
            self.assertIn("- [x] **A** (a)", text)
            self.assertIn("  - [x] **B** (b)", text)
            self.assertIn("    - [>] **C** (c)", text)
            self.assertIn("      - [ ] **D** (d)", text)
            self.assertIn("### Check 4 \u2014 a", text)
            self.assertIn("1. x", text)
            self.assertIn("- **Selected:** 1", text)
            self.assertIn("- **Correct:** yes", text)
            self.assertIn("- **Confidence:** 4", text)
            self.assertIn("- **Trace:** reason", text)
            self.assertIn("**Key:** key for a", text)
            self.assertIn("- **Closed:** no", text)
            self.assertNotIn("## Practice", text)

    def test_no_plan_omits_the_whole_plan_section(self):
        with TempProject() as project:
            session_id = self._teach_session(project)
            code, text, err = run_session(
                project, "render", "--session", session_id, "--no-plan"
            )
            self.assertEqual(code, 0, err)
            self.assertNotIn("## Plan", text)
            self.assertNotIn("Revision 1", text)
            self.assertNotIn("**A** (a)", text)
            self.assertNotIn("- [x]", text)
            for heading in ("## Probe", "## Steps", "## Session"):
                self.assertIn(heading, text)

            code, written, err = run_session(
                project, "render", "--session", session_id, "--no-plan", "--write"
            )
            self.assertEqual(code, 0, err)
            path = project.root / "sessions" / session_id / "session.md"
            self.assertEqual(path.read_text(encoding="utf-8"), written)
            self.assertNotIn("## Plan", path.read_text(encoding="utf-8"))

    def test_write_puts_session_md_beside_the_log(self):
        with TempProject() as project:
            session_id = self._teach_session(project)
            code, text, err = run_session(project, "render", "--session", session_id, "--write")
            self.assertEqual(code, 0, err)
            path = project.root / "sessions" / session_id / "session.md"
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_unanswered_check_and_free_recall_shapes(self):
        with TempProject() as project:
            session_id = project.make_session()
            pose(project, session_id, question="Explain it", key="because")
            code, text, err = run_session(project, "render", "--session", session_id)
            self.assertEqual(code, 0, err)
            self.assertIn("- **Answered:** no", text)
            self.assertIn("**Key:** because", text)
            self.assertIn("_No plan set._", text)
            self.assertIn("_No probe conclusion recorded._", text)

    def test_practice_section(self):
        with TempProject() as project:
            session_id = practice_session(
                project,
                problem={
                    "statement": "Explain heat death",
                    "mode": "recall",
                    "target": ["a", "b"],
                    "modelSolution": "Entropy maxes out.",
                },
                result={
                    "outcome": "solvedWithHints",
                    "verdict": "got there",
                    "rung": "R2",
                    "missClass": "cue",
                    "retest": True,
                },
            )
            code, text, err = run_session(project, "render", "--session", session_id)
            self.assertEqual(code, 0, err)
            self.assertIn("## Practice", text)
            self.assertIn("**Statement:** Explain heat death", text)
            self.assertIn("- **Mode:** recall", text)
            self.assertIn("- **Targets:** a, b", text)
            self.assertIn("- **Outcome:** solvedWithHints", text)
            self.assertIn("- **Verdict:** got there", text)
            self.assertIn("- **Rung:** R2", text)
            self.assertIn("- **Miss class:** cue", text)
            self.assertIn("- **Retest:** yes", text)


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------


class ListTests(unittest.TestCase):
    def test_lists_id_kind_phase_goal_and_node_count(self):
        with TempProject() as project:
            teach = init(project, goal="understand entropy")
            append_events(
                project,
                teach,
                [{"type": "plan_set", "revision": 1, "nodes": nodes("a", "b"), "edges": [{"from": "a", "to": "b"}]}],
            )
            practice = init(project, goal="practice heat", kind="practice")
            code, out, err = run_session(project, "list")
            self.assertEqual(code, 0, err)
            lines = out.splitlines()
            self.assertIn("ID", lines[0])
            self.assertIn("NODES", lines[0])
            self.assertEqual(len(lines), 3)
            self.assertIn(teach, out)
            self.assertIn(practice, out)
            self.assertIn("teach", out)
            self.assertIn("practice", out)
            self.assertIn("understand entropy", out)
            self.assertIn("practice heat", out)
            self.assertRegex(out, r"%s\s+teach\s+probe\s+2" % teach)
            self.assertRegex(out, r"%s\s+practice\s+practice\s+0" % practice)
            self.assertIn("START", lines[0])
            self.assertIn(project.events(teach)[0]["at"], out)
            self.assertIn(project.events(practice)[0]["at"], out)

    def test_most_recent_first_and_json_matches(self):
        with TempProject() as project:
            older = project.make_session(session_id="lh_older001")
            newer = project.make_session(session_id="lh_newer002")
            for session_id, at in (
                (older, "2026-01-01T00:00:00Z"),
                (newer, "2026-02-01T00:00:00Z"),
            ):
                events = project.events(session_id)
                events[0]["at"] = at
                project.write_events(session_id, events)

            code, out, err = run_session(project, "list")
            self.assertEqual(code, 0, err)
            self.assertLess(out.index(newer), out.index(older))
            self.assertIn("2026-02-01T00:00:00Z", out)
            self.assertIn("2026-01-01T00:00:00Z", out)

            code, out, err = run_session(project, "list", "--format", "json")
            self.assertEqual(code, 0, err)
            rows = json.loads(out)
            self.assertEqual([row["id"] for row in rows], [newer, older])
            self.assertEqual(rows[0]["start"], "2026-02-01T00:00:00Z")
            self.assertEqual(rows[1]["start"], "2026-01-01T00:00:00Z")

    def test_empty_record(self):
        with TempProject() as project:
            code, out, err = run_session(project, "list")
            self.assertEqual(code, 0, err)
            self.assertIn("no sessions", out)


# --------------------------------------------------------------------------
# practice
# --------------------------------------------------------------------------


class PracticeTests(unittest.TestCase):
    def test_practice_flow(self):
        with TempProject() as project:
            session_id = practice_session(
                project,
                problem={
                    "statement": "Explain heat death",
                    "mode": "recall",
                    "target": ["a"],
                    "modelSolution": "Entropy maxes out.",
                },
                result={"outcome": "solvedWithHints", "verdict": "v", "rung": "R2",
                        "missClass": "cue", "retest": True},
            )
            problem = events_of(project, session_id, "practice_problem")[0]
            self.assertEqual(problem["statement"], "Explain heat death")
            self.assertEqual(problem["mode"], "recall")
            self.assertEqual(problem["target"], ["a"])
            self.assertEqual(problem["modelSolution"], "Entropy maxes out.")
            conclusion = events_of(project, session_id, "practice_concluded")[0]
            self.assertEqual(conclusion["outcome"], "solvedWithHints")
            self.assertEqual(conclusion["rung"], "R2")
            self.assertTrue(conclusion["retest"])
            self.assertEqual(state_json(project, session_id)["phase"], "practice")

    def test_practice_problem_requires_a_known_mode_and_a_nonempty_target(self):
        with TempProject() as project:
            session_id = init(project, goal="practice", kind="practice")
            good = {
                "statement": "s",
                "mode": "recall",
                "target": ["a"],
                "modelSolution": "m",
            }
            cases = [
                (dict(good, mode="essay"), "mode"),
                ({key: value for key, value in good.items() if key != "target"}, "target"),
                (dict(good, target=[]), "target"),
            ]
            for document, needle in cases:
                with self.subTest(document=document):
                    code, out, err = run_practice_problem(project, session_id, document)
                    self.assertEqual(code, 1)
                    self.assertIn(needle, err)
                    self.assertEqual(events_of(project, session_id, "practice_problem"), [])

            for mode in ("recall", "discrimination", "composition"):
                with self.subTest(mode=mode):
                    code, out, err = run_practice_problem(
                        project, session_id, dict(good, mode=mode)
                    )
                    self.assertEqual(code, 0, err)
            self.assertEqual(len(events_of(project, session_id, "practice_problem")), 3)

    def test_practice_concluded_requires_the_full_documented_shape(self):
        with TempProject() as project:
            session_id = init(project, goal="practice", kind="practice")
            good = {
                "outcome": "solved",
                "verdict": "clean retrieve",
                "rung": None,
                "missClass": None,
                "retest": False,
            }
            cases = [
                (dict(good, outcome="won"), "outcome"),
                ({key: value for key, value in good.items() if key != "verdict"}, "verdict"),
                ({key: value for key, value in good.items() if key != "rung"}, "rung"),
                ({key: value for key, value in good.items() if key != "missClass"}, "missClass"),
                ({key: value for key, value in good.items() if key != "retest"}, "retest"),
                (dict(good, rung="R9"), "rung"),
                (dict(good, missClass="none"), "missClass"),
                (dict(good, retest="yes"), "retest"),
            ]
            for document, needle in cases:
                with self.subTest(document=document):
                    code, out, err = run_practice_concluded(project, session_id, document)
                    self.assertEqual(code, 1)
                    self.assertIn(needle, err)
                    self.assertEqual(events_of(project, session_id, "practice_concluded"), [])

            code, out, err = run_practice_concluded(project, session_id, good)
            self.assertEqual(code, 0, err)
            conclusion = events_of(project, session_id, "practice_concluded")[0]
            self.assertEqual(conclusion["outcome"], "solved")
            self.assertEqual(conclusion["verdict"], "clean retrieve")
            self.assertIsNone(conclusion["rung"])
            self.assertIsNone(conclusion["missClass"])
            self.assertIs(conclusion["retest"], False)

    def test_practice_commands_refuse_a_teach_session(self):
        with TempProject() as project:
            session_id = project.make_session()
            with tempfile.TemporaryDirectory() as scratch:
                problem = Path(scratch) / "problem.json"
                write_json_file(problem, {"statement": "s", "mode": "recall", "modelSolution": "m"})
                code, out, err = run_session(
                    project, "practice-problem", "--session", session_id, "--problem", str(problem)
                )
                self.assertEqual(code, 1)
                self.assertIn("practice", err)
                result = Path(scratch) / "result.json"
                write_json_file(result, {"outcome": "solved"})
                code, out, err = run_session(
                    project, "practice-concluded", "--session", session_id, "--result", str(result)
                )
                self.assertEqual(code, 1)
                self.assertIn("practice", err)

    def test_practice_problem_requires_a_committed_model_solution(self):
        with TempProject() as project:
            session_id = init(project, goal="practice", kind="practice")
            with tempfile.TemporaryDirectory() as scratch:
                path = Path(scratch) / "problem.json"
                write_json_file(path, {"statement": "s", "mode": "recall"})
                code, out, err = run_session(
                    project, "practice-problem", "--session", session_id, "--problem", str(path)
                )
            self.assertEqual(code, 1)
            self.assertIn("modelSolution", err)
            self.assertEqual(events_of(project, session_id, "practice_problem"), [])

    def test_non_finite_numbers_are_refused_before_they_reach_the_log(self):
        with TempProject() as project:
            session_id = init(project, goal="practice", kind="practice")
            with tempfile.TemporaryDirectory() as scratch:
                path = Path(scratch) / "problem.json"
                write_json_file(
                    path,
                    {"statement": "s", "mode": "recall", "modelSolution": float("nan")},
                )
                code, out, err = run_session(
                    project, "practice-problem", "--session", session_id, "--problem", str(path)
                )
            self.assertEqual(code, 1)
            self.assertIn("non-finite", err)
            self.assertEqual(events_of(project, session_id, "practice_problem"), [])
            # The log is still readable, not poisoned with NaN.
            self.assertEqual(read_jsonl(project.root / "sessions" / session_id / "session.jsonl")[0]["type"], "session_start")


# --------------------------------------------------------------------------
# plan-set (needs plan.py)
# --------------------------------------------------------------------------


@unittest.skipUnless(HAS_PLAN, "scripts/plan.py is not present")
class PlanSetTests(unittest.TestCase):
    def test_refuses_before_the_probe_concludes(self):
        with TempProject() as project:
            session_id = project.make_session()
            code, out, err = set_plan(project, session_id, plan_document(("a", "b")))
            self.assertEqual(code, 1)
            self.assertIn("probe", err)
            self.assertEqual(events_of(project, session_id, "plan_set"), [])

    def test_valid_plan_is_recorded_and_unlocks_nodes(self):
        with TempProject() as project:
            session_id = project.make_session()
            append_events(
                project,
                session_id,
                [{"type": "probe_concluded", "strands": [{"strand": "s", "assessment": "a"}]}],
            )
            document = plan_document(("counting", "irreversible"))
            code, out, err = set_plan(project, session_id, document)
            self.assertEqual(code, 0, err)
            plan = events_of(project, session_id, "plan_set")[0]
            self.assertEqual(plan["revision"], 1)
            self.assertEqual(plan["nodes"], document["nodes"])
            self.assertEqual(plan["edges"], document["edges"])
            self.assertEqual(pose(project, session_id, node="irreversible")[0], 0)

    def test_invalid_plan_is_refused_and_not_recorded(self):
        with TempProject() as project:
            session_id = project.make_session()
            append_events(
                project,
                session_id,
                [{"type": "probe_concluded", "strands": [{"strand": "s", "assessment": "a"}]}],
            )
            document = {"nodes": nodes("a", "b"), "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]}
            code, out, err = set_plan(project, session_id, document)
            self.assertEqual(code, 1)
            self.assertIn("cycle", err)
            self.assertEqual(events_of(project, session_id, "plan_set"), [])

    def test_revision_increments(self):
        with TempProject() as project:
            session_id = project.make_session()
            append_events(
                project,
                session_id,
                [{"type": "probe_concluded", "strands": [{"strand": "s", "assessment": "a"}]}],
            )
            self.assertEqual(set_plan(project, session_id, plan_document(("a", "b")))[0], 0)
            self.assertEqual(set_plan(project, session_id, plan_document(("a", "b", "c")))[0], 0)
            plans = events_of(project, session_id, "plan_set")
            self.assertEqual([plan["revision"] for plan in plans], [1, 2])
            self.assertEqual(state_json(project, session_id)["plan"]["revision"], 2)

    def test_plan_node_count_is_advisory_only(self):
        with TempProject() as project:
            session_id = project.make_session()
            append_events(
                project,
                session_id,
                [{"type": "probe_concluded", "strands": [{"strand": "s", "assessment": "a"}]}],
            )
            many = ["n%d" % index for index in range(_data.WARN_PLAN_NODES + 1)]
            code, out, err = set_plan(project, session_id, plan_document(tuple(many), edges=[]))
            self.assertEqual(code, 0, err)
            self.assertIn("advisory", err)
            self.assertEqual(len(events_of(project, session_id, "plan_set")), 1)
            self.assertEqual(state_json(project, session_id)["plan"]["nodes"], len(many))


# --------------------------------------------------------------------------
# CWD independence
# --------------------------------------------------------------------------


class CwdTests(unittest.TestCase):
    def _drive_every_command(self, project):
        with tempfile.TemporaryDirectory() as scratch:
            teach = init(project)
            self.assertEqual(pose(project, teach)[0], 0)
            self.assertEqual(answer(project, teach, text="x", correct="true")[0], 0)
            self.assertEqual(conclude_probe(project, teach)[0], 0)
            if HAS_PLAN:
                self.assertEqual(set_plan(project, teach, plan_document(("a", "b")))[0], 0)
            else:
                append_events(
                    project,
                    teach,
                    [{"type": "plan_set", "revision": 1, "nodes": nodes("a", "b"), "edges": [{"from": "a", "to": "b"}]}],
                )
            self.assertEqual(pose(project, teach, node="b", options="x,y", correct="1")[0], 0)
            self.assertEqual(answer(project, teach, select="1")[0], 0)
            self.assertEqual(
                run_session(project, "step-close", "--session", teach, "--node", "b")[0], 0
            )

            practice = init(project, goal="practice heat", kind="practice")
            problem = Path(scratch) / "problem.json"
            write_json_file(problem, {"statement": "s", "mode": "recall", "target": ["a"], "modelSolution": "m"})
            self.assertEqual(
                run_session(project, "practice-problem", "--session", practice, "--problem", str(problem))[0], 0
            )
            result = Path(scratch) / "result.json"
            write_json_file(
                result,
                {"outcome": "solved", "verdict": "v", "rung": None, "missClass": None, "retest": False},
            )
            self.assertEqual(
                run_session(project, "practice-concluded", "--session", practice, "--result", str(result))[0], 0
            )

            self.assertEqual(state_text(project, teach)[:9], "session  ")
            self.assertEqual(run_session(project, "render", "--session", teach, "--write")[0], 0)
            self.assertEqual(run_session(project, "list")[0], 0)
            self.assertEqual(run_session(project, "close", "--session", teach)[0], 0)
            self.assertEqual(run_session(project, "close", "--session", practice)[0], 0)

    def test_every_command_is_cwd_independent_and_confined(self):
        with TempProject() as project:
            before = set(snapshot(project.path))
            self._drive_every_command(project)
            created = set(snapshot(project.path)) - before
            self.assertTrue(created)
            for path in created:
                parts = Path(path).parts
                self.assertEqual(parts[0], ".learnharness", "stray path: %s" % path)
                self.assertNotIn("__pycache__", parts)
                self.assertFalse(path.endswith(".pyc"), "bytecode written: %s" % path)

    def test_discovery_walks_up_from_a_nested_cwd(self):
        with TempProject() as project:
            session_id = init(project)
            nested = project.path / "nested" / "deeper"
            nested.mkdir(parents=True)
            code, out, err = run_script("session.py", ["state", "--session", session_id], cwd=nested)
            self.assertEqual(code, 0, err)
            self.assertIn(session_id, out)

    def test_data_dir_lets_an_unrelated_cwd_read_the_record(self):
        with TempProject() as project:
            session_id = init(project)
            with tempfile.TemporaryDirectory() as elsewhere:
                code, out, err = run_script(
                    "session.py",
                    ["--data-dir", str(project.root), "state", "--session", session_id],
                    cwd=elsewhere,
                )
                self.assertEqual(code, 0, err)
                self.assertIn(session_id, out)
                self.assertEqual(os.listdir(elsewhere), [])


if __name__ == "__main__":
    unittest.main()
