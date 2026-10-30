"""Spec compliance for the skill package itself.

These assertions are what make the folder portable: a harness that follows the Agent
Skills specification will read the frontmatter, honour the body length, and load the
references on demand. Nothing here depends on the harness.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True


REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "SKILL.md"
LICENSE = REPO / "LICENSE"
SCRIPTS = REPO / "scripts"
REFERENCES = REPO / "references"

SPEC_FIELDS = {"name", "description", "license", "compatibility"}
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
MAX_BODY_LINES = 500


def parse_frontmatter(text):
    """Return (fields, body). Frontmatter is the block between the first two --- lines."""
    if not text.startswith("---"):
        raise AssertionError("SKILL.md must start with a --- frontmatter block")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise AssertionError("SKILL.md frontmatter is not closed with ---")
    fields = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line:
            continue
        if ": " not in line:
            raise AssertionError("frontmatter line is not 'key: value': %r" % line)
        key, value = line.split(": ", 1)
        fields[key.strip()] = value.strip()
    return fields, parts[2]


class FrontmatterTest(unittest.TestCase):
    def setUp(self):
        self.fields, self.body = parse_frontmatter(SKILL.read_text(encoding="utf-8"))

    def test_name_matches_folder(self):
        self.assertEqual(self.fields["name"], REPO.name)

    def test_required_spec_fields_present(self):
        self.assertTrue(SPEC_FIELDS.issubset(self.fields), "missing: %s" % (SPEC_FIELDS - set(self.fields)))

    def test_description_within_limit(self):
        self.assertTrue(0 < len(self.fields["description"]) <= MAX_DESCRIPTION)

    def test_compatibility_within_limit(self):
        self.assertTrue(0 < len(self.fields["compatibility"]) <= MAX_COMPATIBILITY)

    def test_license_field(self):
        self.assertEqual(self.fields["license"], "AGPL-3.0-only")

    def test_no_harness_specific_frontmatter(self):
        # Claude-Code-only fields hard-fail on other hosts' upload paths.
        for forbidden in ("allowed-tools", "model", "context", "agent", "effort", "when_to_use", "paths", "hooks"):
            self.assertNotIn(forbidden, self.fields, "%r is a harness-specific field" % forbidden)

    def test_body_within_line_limit(self):
        self.assertLess(len(self.body.splitlines()), MAX_BODY_LINES)


class ReferenceTest(unittest.TestCase):
    def setUp(self):
        self.body = SKILL.read_text(encoding="utf-8")

    def test_data_format_reference_is_linked(self):
        self.assertIn("references/data-format.md", self.body)

    def test_every_linked_reference_exists(self):
        for name in sorted(p.name for p in REFERENCES.glob("*.md")):
            self.assertIn("references/" + name, self.body, "%s is not linked from SKILL.md" % name)

    def test_every_referenced_file_exists(self):
        import re

        for match in re.finditer(r"references/([a-z0-9-]+\.md)", self.body):
            target = REFERENCES / match.group(1)
            self.assertTrue(target.is_file(), "SKILL.md links a missing reference: %s" % match.group(1))

    def test_no_absolute_home_paths(self):
        for path in [SKILL, *sorted(REFERENCES.glob("*.md"))]:
            text = path.read_text(encoding="utf-8")
            for marker in ("/Users/", "/home/", "C:\\Users\\"):
                self.assertNotIn(marker, text, "%s contains an absolute home path" % path.name)

    def test_no_app_tool_names_leak_into_the_protocol(self):
        forbidden = [
            "probe_done",
            "plan_init",
            "ask_user_question",
            "send_to_user",
            "list_sessions",
            "list_propositions",
            "pi-agent-core",
            "Electron",
            "Next.js",
        ]
        for path in sorted(REFERENCES.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for word in forbidden:
                self.assertNotIn(word, text, "%s mentions %r, which does not exist in the target harness" % (path.name, word))


class LicenseTest(unittest.TestCase):
    def test_license_is_bundled(self):
        text = LICENSE.read_text(encoding="utf-8")
        self.assertIn("GNU AFFERO GENERAL PUBLIC LICENSE", text)
        self.assertGreater(len(text), 30_000, "LICENSE looks truncated")


class ScriptTest(unittest.TestCase):
    def test_every_script_parses_under_the_declared_floor(self):
        scripts = sorted(SCRIPTS.glob("*.py"))
        self.assertTrue(scripts, "no scripts found")
        for path in scripts:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path), feature_version=(3, 10))

    def test_every_script_disables_bytecode(self):
        for path in sorted(SCRIPTS.glob("*.py")):
            self.assertIn(
                "sys.dont_write_bytecode = True",
                path.read_text(encoding="utf-8"),
                "%s would leave __pycache__ behind" % path.name,
            )

    def test_stdlib_only_helper_passes(self):
        import subprocess

        completed = subprocess.run(
            [sys.executable, "-B", str(REPO / "tests" / "check_stdlib_only.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
