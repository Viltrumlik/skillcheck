"""Har bir tekshiruv uchun ataylab buzilgan loyiha quriladi."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, os.pardir, "skillcheck.py")

spec = importlib.util.spec_from_file_location("skillcheck", SCRIPT)
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

GOOD_SKILL = """---
name: demo
description: Use when you need the demo behaviour in a project that has one.
---

# demo

Body text.
"""

GOOD_PLUGIN = {"name": "demo", "version": "0.1.0", "description": "A demo plugin",
               "keywords": ["demo"]}
GOOD_MARKET = {"name": "demo", "owner": {"name": "A"},
               "plugins": [{"name": "demo", "source": "./", "version": "0.1.0"}]}
GOOD_HOOKS = {"hooks": {"SessionStart": [
    {"matcher": ".*", "hooks": [{"type": "command", "command": "echo hi"}]}]}}


class Project:
    """Vaqtinchalik loyiha. Har bir qismini alohida buzish mumkin."""

    def __init__(self, root):
        self.root = root
        self.write("skills/demo/SKILL.md", GOOD_SKILL)
        self.json(".claude-plugin/plugin.json", GOOD_PLUGIN)
        self.json(".claude-plugin/marketplace.json", GOOD_MARKET)
        self.json("hooks/hooks.json", GOOD_HOOKS)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def json(self, rel, data):
        self.write(rel, json.dumps(data, indent=2))

    def remove(self, rel):
        os.remove(os.path.join(self.root, rel))


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="skillcheck-"))
        self.p = Project(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, self.tmp, *args],
                              capture_output=True, text=True)

    def findings(self):
        out = self.run_cli("--json")
        return json.loads(out.stdout)["findings"]

    def levels(self, substring):
        return [f["level"] for f in self.findings() if substring in f["message"]]

    def assertError(self, substring):
        self.assertIn("error", self.levels(substring),
                      "xato kutilgandi: %r, topilgani: %s" % (substring, self.findings()))

    def assertWarning(self, substring):
        self.assertIn("warning", self.levels(substring),
                      "ogohlantirish kutilgandi: %r" % substring)

    # -- toza loyiha ------------------------------------------------------

    def test_a_correct_project_passes(self):
        out = self.run_cli()
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("toza", out.stdout)

    # -- SKILL.md ---------------------------------------------------------

    def test_missing_frontmatter_is_an_error(self):
        self.p.write("skills/demo/SKILL.md", "# demo\n\nno frontmatter here\n")
        self.assertError("frontmatter yo'q")

    def test_a_name_that_breaks_the_pattern_is_an_error(self):
        self.p.write("skills/demo/SKILL.md",
                     GOOD_SKILL.replace("name: demo", "name: Demo_Skill"))
        self.assertError("qoidaga mos emas")

    def test_a_name_that_differs_from_the_folder_is_a_warning(self):
        self.p.write("skills/demo/SKILL.md",
                     GOOD_SKILL.replace("name: demo", "name: other"))
        self.assertWarning("papka nomi")

    def test_a_missing_description_is_an_error(self):
        self.p.write("skills/demo/SKILL.md", "---\nname: demo\n---\n\nbody\n")
        self.assertError("description yo'q")

    def test_a_description_over_the_limit_is_an_error(self):
        long = "x" * (sc.MAX_DESCRIPTION + 1)
        self.p.write("skills/demo/SKILL.md",
                     "---\nname: demo\ndescription: %s\n---\n\nbody\n" % long)
        self.assertError("juda uzun")

    def test_a_very_short_description_is_a_warning(self):
        self.p.write("skills/demo/SKILL.md",
                     "---\nname: demo\ndescription: does stuff\n---\n\nbody\n")
        self.assertWarning("juda qisqa")

    def test_an_empty_body_is_a_warning(self):
        self.p.write("skills/demo/SKILL.md", GOOD_SKILL.split("# demo")[0])
        self.assertWarning("matn yo'q")

    def test_a_skill_at_the_root_is_also_checked(self):
        shutil.rmtree(os.path.join(self.tmp, "skills"))
        self.p.write("SKILL.md", "# no frontmatter\n")
        self.assertError("frontmatter yo'q")

    # -- plugin.json ------------------------------------------------------

    def test_invalid_json_is_an_error_not_a_crash(self):
        self.p.write(".claude-plugin/plugin.json", "{ name: broken, }")
        out = self.run_cli()
        self.assertEqual(out.returncode, 3)
        self.assertIn("JSON o'qilmadi", out.stdout)

    def test_a_missing_plugin_name_is_an_error(self):
        self.p.json(".claude-plugin/plugin.json", {"version": "0.1.0"})
        self.assertError("name yo'q")

    def test_a_non_semver_version_is_a_warning(self):
        self.p.json(".claude-plugin/plugin.json", dict(GOOD_PLUGIN, version="v1"))
        self.assertWarning("semver")

    def test_missing_keywords_is_a_warning(self):
        plugin = dict(GOOD_PLUGIN)
        del plugin["keywords"]
        self.p.json(".claude-plugin/plugin.json", plugin)
        self.assertWarning("keywords yo'q")

    # -- marketplace.json -------------------------------------------------

    def test_a_source_that_does_not_exist_is_an_error(self):
        self.p.json(".claude-plugin/marketplace.json", dict(
            GOOD_MARKET, plugins=[{"name": "demo", "source": "./nowhere"}]))
        self.assertError("mavjud emas")

    def test_a_version_that_disagrees_with_plugin_json_is_a_warning(self):
        self.p.json(".claude-plugin/marketplace.json", dict(
            GOOD_MARKET, plugins=[{"name": "demo", "source": "./", "version": "9.9.9"}]))
        self.assertWarning("mos emas")

    def test_an_empty_plugins_list_is_an_error(self):
        self.p.json(".claude-plugin/marketplace.json", dict(GOOD_MARKET, plugins=[]))
        self.assertError("plugins bo'sh")

    # -- hooks.json -------------------------------------------------------

    def test_an_unknown_event_name_is_a_warning(self):
        self.p.json("hooks/hooks.json", {"hooks": {"PreToolUze": [
            {"matcher": ".*", "hooks": [{"type": "command", "command": "x"}]}]}})
        self.assertWarning("notanish hodisa")

    def test_a_missing_command_is_an_error(self):
        self.p.json("hooks/hooks.json", {"hooks": {"SessionStart": [
            {"matcher": ".*", "hooks": [{"type": "command"}]}]}})
        self.assertError("command yo'q")

    def test_a_wrong_hook_type_is_an_error(self):
        self.p.json("hooks/hooks.json", {"hooks": {"SessionStart": [
            {"matcher": ".*", "hooks": [{"type": "script", "command": "x"}]}]}})
        self.assertError("command\" bo'lishi kerak")

    def test_a_missing_matcher_is_a_warning(self):
        self.p.json("hooks/hooks.json", {"hooks": {"SessionStart": [
            {"hooks": [{"type": "command", "command": "x"}]}]}})
        self.assertWarning("matcher yo'q")

    def test_a_hook_pointing_at_a_missing_script_is_an_error(self):
        self.p.json("hooks/hooks.json", {"hooks": {"SessionStart": [
            {"matcher": ".*", "hooks": [{"type": "command",
             "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gone.py"'}]}]}})
        self.assertError("mavjud emas")

    def test_a_hook_pointing_at_a_real_script_is_fine(self):
        self.p.write("scripts/here.py", "print(1)\n")
        self.p.json("hooks/hooks.json", {"hooks": {"SessionStart": [
            {"matcher": ".*", "hooks": [{"type": "command",
             "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/here.py"'}]}]}})
        self.assertEqual(self.run_cli().returncode, 0)

    def test_hooks_without_a_plugin_manifest_is_a_warning(self):
        self.p.remove(".claude-plugin/plugin.json")
        self.assertWarning("plugin.json yo'q")

    # -- xatti-harakat ----------------------------------------------------

    def test_warnings_alone_do_not_fail_unless_strict(self):
        self.p.json(".claude-plugin/plugin.json", dict(GOOD_PLUGIN, version="v1"))
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.run_cli("--strict").returncode, 3)

    def test_an_empty_folder_says_there_is_nothing_to_check(self):
        empty = tempfile.mkdtemp(prefix="skillcheck-empty-")
        try:
            out = subprocess.run([sys.executable, SCRIPT, empty, "--json"],
                                 capture_output=True, text=True)
            self.assertIn("topilmadi", out.stdout)
            self.assertEqual(out.returncode, 0)
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_a_path_that_is_not_a_folder_is_a_usage_error(self):
        out = subprocess.run([sys.executable, SCRIPT, os.path.join(self.tmp, "nope")],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)


class UnitTest(unittest.TestCase):
    def test_frontmatter_parsing_takes_only_top_level_keys(self):
        fields = sc.parse_frontmatter("---\nname: a\nmeta:\n  nested: b\n---\nbody\n")
        self.assertEqual(fields.get("name"), "a")
        self.assertNotIn("nested", fields)

    def test_frontmatter_is_none_without_the_fence(self):
        self.assertIsNone(sc.parse_frontmatter("# just markdown\n"))

    def test_quotes_are_stripped_from_values(self):
        fields = sc.parse_frontmatter('---\nname: "quoted"\n---\nbody\n')
        self.assertEqual(fields["name"], "quoted")

    def test_the_name_pattern_matches_the_documented_rule(self):
        for ok in ("a", "demo", "a-b-c", "x9"):
            self.assertTrue(sc.NAME_RE.match(ok), ok)
        for bad in ("-a", "a-", "A", "a_b", "a b", ""):
            self.assertFalse(sc.NAME_RE.match(bad), bad)


if __name__ == "__main__":
    unittest.main()
