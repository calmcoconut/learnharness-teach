#!/usr/bin/env python3
"""Regenerate the committed record fixtures deterministically.

    python3 tests/fixtures/records/build.py

The fixtures are checked in because a test that loads them proves the contract still
reads and audits correctly. They are generated rather than hand-written so the ids stay
consistent with `_data.mint_node_id` and a change to the format has one place to update.
"""

import json
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True

FIXTURES = Path(__file__).resolve().parent
SCRIPTS = FIXTURES.parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _data  # noqa: E402

SESSION = "lh_fixture1"
AT = "2026-01-14T09:30:00Z"


def event(seq, type_, **fields):
    record = {"seq": seq, "at": AT, "type": type_}
    record.update(fields)
    return record

PROPOSITIONS = [
    ("counting", "Entropy is the logarithm of the number of accessible microstates.", []),
    ("multiplicity", "A macrostate is more likely when it has more microstates.", []),
    ("irreversibility", "A process runs one way when the reverse needs an astronomically improbable rearrangement.", []),
    ("second-law", "Entropy of a closed system never decreases.", ["entropy never goes down"]),
    ("equilibrium", "Equilibrium is the macrostate with overwhelmingly the most microstates.", []),
    ("fluctuations", "Small systems can fluctuate away from equilibrium.", []),
]

CHAINS = [
    (["counting", "multiplicity"], "irreversibility"),
    (["irreversibility"], "second-law"),
]

PLAN_NODES = [
    ("counting", "Entropy counts microstates"),
    ("multiplicity", "More microstates, more likely"),
    ("irreversibility", "Why one direction"),
    ("second-law", "The second law"),
    ("equilibrium", "What equilibrium is"),
]

PLAN_EDGES = [
    ("counting", "multiplicity"),
    ("multiplicity", "irreversibility"),
    ("irreversibility", "second-law"),
    ("irreversibility", "equilibrium"),
]


def build_teach_session(root):
    statements = {ref: statement for ref, statement, _aliases in PROPOSITIONS}
    node_ids = {ref: _data.mint_node_id(statement) for ref, statement in statements.items()}

    events = [
        event(1, "session_start", kind="teach", goal="understand why entropy always increases"),
        event(
            2,
            "check_posed",
            node=None,
            question="A coin is flipped 100 times. What is the most likely number of heads, and why?",
            options=["50, because there are more ways to get 50 than any other count", "50, because it is the average", "Any number is equally likely"],
            correct=[0],
            key="50, and the reason is multiplicity: more arrangements give 50 heads than any other total. The average is the same number but is not the reason.",
        ),
        event(
            3,
            "answer",
            check_seq=2,
            selection=[0],
            correct=True,
            confidence=4,
            trace="There are more ways to arrange 50 heads than 60, so it should be more likely.",
        ),
        event(
            4,
            "check_posed",
            node=None,
            question="In one sentence, what does it mean for a process to be irreversible?",
            key="The reverse would require a rearrangement so improbable that it never happens on any timescale we observe.",
        ),
        event(
            5,
            "answer",
            check_seq=4,
            selection=["It means it cannot be undone."],
            correct=False,
            confidence=2,
            trace="I think it means you cannot reverse it, but I am not sure what makes that true.",
        ),
        event(
            6,
            "probe_concluded",
            strands=[
                {"strand": "entropy as counting", "assessment": "holds; can reason about multiplicity without prompting"},
                {"strand": "irreversibility", "assessment": "not held; knows the word, cannot say what makes a direction one-way"},
            ],
            summary="Strong on counting, no working notion of irreversibility. Teach from multiplicity forward.",
        ),
        event(
            7,
            "plan_set",
            revision=1,
            nodes=[{"id": ref, "title": title} for ref, title in PLAN_NODES],
            edges=[{"from": source, "to": target} for source, target in PLAN_EDGES],
        ),
        event(
            8,
            "check_posed",
            node="irreversibility",
            question="A video shows shattered glass reassembling. Why is that the impossible direction rather than the breaking?",
            options=["Reassembling needs the molecules to be in a far smaller number of arrangements", "Breaking releases energy", "Time only runs forwards"],
            correct=[0],
            key="Reassembling needs every fragment to land in one specific arrangement, and there are vastly fewer of those than of broken arrangements.",
        ),
        event(
            9,
            "answer",
            check_seq=8,
            selection=[0],
            correct=True,
            confidence=3,
            trace="Because there are far fewer tidy arrangements, so the reverse is much less likely.",
        ),
        event(10, "step_closed", node="irreversibility", outcome="held"),
        event(11, "session_closed", nodes_written=len(PROPOSITIONS), chains_written=len(CHAINS)),
    ]

    session_dir = root / "sessions" / SESSION
    session_dir.mkdir(parents=True, exist_ok=True)
    with (session_dir / "session.jsonl").open("w", encoding="utf-8") as handle:
        for record in events:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    graph = root / "graph"
    graph.mkdir(parents=True, exist_ok=True)

    with (graph / "nodes.jsonl").open("w", encoding="utf-8") as handle:
        for ref, statement, aliases in PROPOSITIONS:
            handle.write(
                json.dumps(
                    {
                        "id": node_ids[ref],
                        "name": dict(PLAN_NODES).get(ref, ref),
                        "statement": statement,
                        "aliases": aliases,
                        "createdAt": AT,
                        "provenance": [{"chatId": SESSION, "messageId": "11"}],
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )

    with (graph / "chains.jsonl").open("w", encoding="utf-8") as handle:
        for premises, conclusion in CHAINS:
            premise_ids = [node_ids[ref] for ref in premises]
            handle.write(
                json.dumps(
                    {
                        "id": _data.mint_chain_id(premise_ids, node_ids[conclusion]),
                        "premises": premise_ids,
                        "conclusion": node_ids[conclusion],
                        "provenance": [{"chatId": SESSION, "messageId": "11"}],
                        "createdAt": AT,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )

    (graph / "format.json").write_text(
        json.dumps({"version": 1, "writer": "learnharness-teach/0.1"}, indent="\t") + "\n",
        encoding="utf-8",
    )


def build_practice_session(root):
    events = [
        event(1, "session_start", kind="practice", goal="make the second law usable"),
        event(
            2,
            "practice_problem",
            statement="A fridge moves heat from cold to hot. Does this violate the second law?",
            mode="discrimination",
            target=["second-law", "irreversibility"],
            modelSolution="No. The second law applies to the system plus its surroundings; the fridge spends work, so total entropy still rises.",
        ),
        event(
            3,
            "practice_concluded",
            outcome="solvedWithHints",
            verdict="Got there after being asked what the second law applies to.",
            rung="R2",
            missClass="discrimination",
            retest=True,
            work="I said it does not violate it because the fridge uses electricity, so something else must be going up.",
        ),
        event(4, "session_closed"),
    ]
    session_dir = root / "sessions" / "lh_fixture2"
    session_dir.mkdir(parents=True, exist_ok=True)
    with (session_dir / "session.jsonl").open("w", encoding="utf-8") as handle:
        for record in events:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def main():
    for name, builder in (("complete-teach", build_teach_session), ("practice", build_practice_session)):
        target = FIXTURES / name / _data.DATA_DIRNAME
        if target.exists():
            shutil.rmtree(target)
        builder(target)
        print("built %s" % (target.relative_to(FIXTURES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
