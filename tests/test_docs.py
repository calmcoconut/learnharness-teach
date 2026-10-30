"""Documentation must not cite commands or flags that do not exist.

Every `python3 scripts/<name>.py ...` invocation in the shipped docs and in the golden
transcript is extracted and checked against that script's own `--help` output. This is the
guard for the class of drift that is invisible to every other test: prose that reads
correctly but would fail if an agent followed it literally.
"""

import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import _helpers

REPO = Path(__file__).resolve().parent.parent

DOCS = [
    REPO / "SKILL.md",
    REPO / "README.md",
    *sorted((REPO / "references").glob("*.md")),
    *sorted((REPO / "tests" / "fixtures" / "golden").glob("*.md")),
]

# Subcommands per script. `verify.py` has none.
SUBCOMMANDS = {
    "session.py": [
        "init",
        "check",
        "answer",
        "conclude-probe",
        "plan-set",
        "step-close",
        "practice-problem",
        "practice-concluded",
        "close",
        "state",
        "render",
        "list",
    ],
    "plan.py": ["validate"],
    "graph.py": ["sessions", "propositions", "find", "chains", "export"],
    "graph_write.py": ["merge"],
    "verify.py": [],
}

COMMAND_RE = re.compile(r"python3\s+(?:<skill>/)?scripts/([a-z_]+\.py)(.*)")


def _join_continuations(text):
    """Collapse backslash line continuations so a command is one string."""
    return text.replace("\\\n", " ")


def _tokens(remainder):
    """Split a command remainder into clean tokens.

    Prose often wraps a command in backticks and trails a comma, so both are stripped
    before a token is compared with anything.
    """
    cleaned = remainder.replace("`", " ")
    return [token.strip(".,;:()'\"") for token in cleaned.split() if token.strip(".,;:()'\"")]


def _flags_in(remainder):
    """Every long option appearing in a command's arguments."""
    return [token.split("=", 1)[0] for token in _tokens(remainder) if token.startswith("--")]

def _help_text(script, subcommand=None):
    args = [subcommand, "--help"] if subcommand else ["--help"]
    code, out, err = _helpers.run_script(script, args)
    return out + err


class DocumentedCommandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.known = {}
        for script, subcommands in SUBCOMMANDS.items():
            text = _help_text(script)
            for subcommand in subcommands:
                text += _help_text(script, subcommand)
            cls.known[script] = text

        cls.commands = []
        for path in DOCS:
            if not path.is_file():
                continue
            joined = _join_continuations(path.read_text(encoding="utf-8"))
            for line in joined.splitlines():
                match = COMMAND_RE.search(line)
                if match:
                    cls.commands.append((path.name, match.group(1), match.group(2)))

    def test_docs_contain_commands(self):
        self.assertGreater(len(self.commands), 10, "expected the docs to show real invocations")

    def test_every_script_name_exists(self):
        for source, script, _remainder in self.commands:
            self.assertTrue(
                (REPO / "scripts" / script).is_file(),
                "%s cites %s, which does not exist" % (source, script),
            )

    def test_every_flag_exists(self):
        missing = []
        for source, script, remainder in self.commands:
            if script not in self.known:
                continue
            for flag in _flags_in(remainder):
                if flag not in self.known[script]:
                    missing.append("%s: %s does not accept %s" % (source, script, flag))
        self.assertEqual(missing, [], "\n".join(missing))

    def test_every_cited_subcommand_exists(self):
        missing = []
        for source, script, remainder in self.commands:
            subcommands = SUBCOMMANDS.get(script)
            if not subcommands:
                continue
            tokens = [t for t in _tokens(remainder) if not t.startswith("-")]
            if not tokens:
                continue
            # `graph.py` and `session.py` accept global options before the command, so a
            # value token can precede it. Prose may also name a command inline; only
            # complain when no known subcommand appears anywhere near the front.
            if not any(token in subcommands for token in tokens[:3]):
                missing.append("%s: %s has no subcommand among %r" % (source, script, tokens[:3]))
        self.assertEqual(missing, [], "\n".join(missing))


class ReferenceLinkTest(unittest.TestCase):
    def test_every_reference_is_linked_from_skill(self):
        skill = (REPO / "SKILL.md").read_text(encoding="utf-8")
        for path in sorted((REPO / "references").glob("*.md")):
            self.assertIn("references/" + path.name, skill)

    def test_golden_transcript_links_its_rubric(self):
        transcript = (REPO / "tests" / "fixtures" / "golden" / "teach-session.md").read_text(encoding="utf-8")
        self.assertIn("rubric.md", transcript)


if __name__ == "__main__":
    unittest.main()
