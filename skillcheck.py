#!/usr/bin/env python3
"""skillcheck - lint Agent Skills and Claude Code plugin manifests.

A skill or plugin that is subtly malformed does not fail loudly. It just
never loads, or loads and is ignored, and you find out when someone tells
you it does not work. This checks the parts that have to be right.

    skillcheck            # check the project in the current folder
    skillcheck path/to/plugin --json

Exit codes: 0 clean, 1 error reading files, 2 usage, 3 problems found.

Errors are things that are definitely wrong: invalid JSON, a missing
required field, a name that breaks the documented pattern. Everything
judgemental is a warning, because this tool is not the spec.

Zero dependencies. Python 3.9+.
"""

import argparse
import json
import os
import re
import sys

VERSION = "0.1.0"
EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_FOUND = 0, 1, 2, 3

NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+")
MAX_DESCRIPTION = 1024

# Hujjatlashtirilgan hodisalar. Ro'yxat o'sib boradi, shuning uchun
# notanish nom xato emas, ogohlantirish.
KNOWN_EVENTS = {
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "UserPromptSubmit",
    "Notification", "Stop", "SubagentStop", "PreCompact", "SessionStart",
    "SessionEnd",
}


def relative(path, start=None):
    """Ko'rsatish uchun qisqartirilgan yo'l.

    Windows'da turli disklardagi yo'llar uchun os.path.relpath ValueError
    tashlaydi (C: va D:). Bunda qisqartirishdan voz kechamiz -- to'liq yo'l
    xunukroq, lekin yiqilishdan yaxshiroq.
    """
    try:
        return os.path.relpath(path, start)
    except ValueError:
        return path


class Finding:
    def __init__(self, level, where, message, hint=None):
        self.level, self.where, self.message, self.hint = level, where, message, hint

    def as_dict(self):
        d = {"level": self.level, "where": self.where, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        return d


def error(where, message, hint=None):
    return Finding("error", where, message, hint)


def warn(where, message, hint=None):
    return Finding("warning", where, message, hint)


def read_json(path):
    """(data, finding) qaytaradi. Faqat bittasi bo'ladi."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except ValueError as e:
        return None, error(relative(path), "invalid JSON: %s" % e,
                           "a missing comma or bracket is the usual cause")
    except OSError as e:
        return None, error(relative(path), "could not open the file: %s" % e)


# ---------------------------------------------------------------- SKILL.md


FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


def parse_frontmatter(text):
    """Faqat kerakli kalitlarni oladi. To'liq YAML emas -- SKILL.md
    frontmatter'i sayoz va bog'liqlik qo'shishga arzimaydi."""
    m = FRONTMATTER.match(text)
    if not m:
        return None
    fields = {}
    for line in m.group(1).splitlines():
        if line.strip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key == key.strip():  # ichki kalitlarni o'tkazib yuboramiz
            fields[key.strip()] = value.strip().strip('"\'')
    return fields


def check_skill(path, findings, root=None):
    where = relative(path, root)
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        findings.append(error(where, "could not be read: %s" % e))
        return

    fields = parse_frontmatter(text)
    if fields is None:
        findings.append(error(
            where, "no frontmatter",
            "the file must open with a --- line and carry name and description"))
        return

    name = fields.get("name")
    if not name:
        findings.append(error(where, "frontmatter has no name"))
    elif not NAME_RE.match(name):
        findings.append(error(
            where, "name %r breaks the pattern" % name,
            "lowercase letters, digits and hyphens; cannot start or end with a hyphen"))
    else:
        folder = os.path.basename(os.path.dirname(path))
        if folder != name:
            findings.append(warn(
                where, "name %r does not match its folder %r" % (name, folder),
                "most loaders find a skill by its folder name"))

    desc = fields.get("description")
    if not desc:
        findings.append(error(
            where, "frontmatter has no description",
            "an agent picks the skill by reading this"))
    elif len(desc) > MAX_DESCRIPTION:
        findings.append(error(
            where, "description is too long (%d > %d)" % (len(desc), MAX_DESCRIPTION)))
    elif len(desc) < 20:
        findings.append(warn(
            where, "description is very short (%d characters)" % len(desc),
            "say when to use it, so the agent reaches for it at the right moment"))

    body = text[FRONTMATTER.match(text).end():].strip()
    if not body:
        findings.append(warn(where, "nothing after the frontmatter"))


# ---------------------------------------------------------------- manifests


def check_plugin_json(path, findings, root=None):
    where = relative(path, root)
    data, bad = read_json(path)
    if bad:
        findings.append(bad)
        return None
    if not isinstance(data, dict):
        findings.append(error(where, "expected an object at the top level"))
        return None

    name = data.get("name")
    if not name:
        findings.append(error(where, "no name"))
    elif not NAME_RE.match(str(name)):
        findings.append(error(where, "name %r breaks the pattern" % name))

    version = data.get("version")
    if not version:
        findings.append(warn(where, "no version",
                             "loaders decide what to update by this"))
    elif not VERSION_RE.match(str(version)):
        findings.append(warn(where, "version %r is not semver-shaped" % version))

    if not data.get("description"):
        findings.append(warn(where, "no description",
                             "catalogues and listings show this"))
    if not data.get("keywords"):
        findings.append(warn(where, "no keywords", "it will not turn up in search"))
    return data


def check_marketplace_json(path, plugin, findings, root=None):
    where = relative(path, root)
    data, bad = read_json(path)
    if bad:
        findings.append(bad)
        return
    if not isinstance(data, dict):
        findings.append(error(where, "yuqori darajada obyekt kutilgan"))
        return
    if not data.get("name"):
        findings.append(error(where, "no name"))
    if not isinstance(data.get("owner"), dict):
        findings.append(warn(where, "owner missing or not an object"))

    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        findings.append(error(where, "plugins is empty or not a list"))
        return
    root = os.path.dirname(os.path.dirname(path))
    for i, entry in enumerate(plugins):
        tag = "%s plugins[%d]" % (where, i)
        if not isinstance(entry, dict):
            findings.append(error(tag, "not an object"))
            continue
        if not entry.get("name"):
            findings.append(error(tag, "no name"))
        source = entry.get("source")
        if not source:
            findings.append(error(tag, "no source"))
        elif isinstance(source, str) and source.startswith("."):
            if not os.path.isdir(os.path.join(root, source)):
                findings.append(error(tag, "source %r does not exist" % source))
        if plugin and entry.get("version") and plugin.get("version") \
                and entry["version"] != plugin["version"]:
            findings.append(warn(
                tag, "version %r disagrees with plugin.json %r"
                % (entry["version"], plugin["version"])))


def check_hooks_json(path, findings, root=None):
    where = relative(path, root)
    data, bad = read_json(path)
    if bad:
        findings.append(bad)
        return
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict) or not hooks:
        findings.append(error(where, "hooks object is missing or empty"))
        return

    root = os.path.dirname(os.path.dirname(path))
    for event, entries in hooks.items():
        if event not in KNOWN_EVENTS:
            findings.append(warn(
                where, "unknown event %r" % event,
                "a typo here means the hook never runs, and says nothing"))
        if not isinstance(entries, list):
            findings.append(error(where, "%s is not a list" % event))
            continue
        for i, entry in enumerate(entries):
            tag = "%s %s[%d]" % (where, event, i)
            if not isinstance(entry, dict):
                findings.append(error(tag, "not an object"))
                continue
            if "matcher" not in entry:
                findings.append(warn(tag, "no matcher",
                                     "use \".*\" to match everything"))
            inner = entry.get("hooks")
            if not isinstance(inner, list) or not inner:
                findings.append(error(tag, "inner hooks is empty or not a list"))
                continue
            for j, hook in enumerate(inner):
                htag = "%s.hooks[%d]" % (tag, j)
                if not isinstance(hook, dict):
                    findings.append(error(htag, "not an object"))
                    continue
                if hook.get("type") != "command":
                    findings.append(error(htag, 'type must be "command"'))
                command = hook.get("command")
                if not command:
                    findings.append(error(htag, "no command"))
                elif isinstance(command, str):
                    check_hook_path(command, root, htag, findings)


SCRIPT_IN_COMMAND = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"'\s]+)")


def check_hook_path(command, root, tag, findings):
    for rel in SCRIPT_IN_COMMAND.findall(command):
        if not os.path.exists(os.path.join(root, rel)):
            findings.append(error(
                tag, "command points at %r, which does not exist" % rel,
                "the path is relative to the plugin root"))


# ---------------------------------------------------------------- walk


def collect(root):
    """Tekshiriladigan fayllarni topadi."""
    found = {"skills": [], "plugin": None, "marketplace": None, "hooks": None}
    skills_dir = os.path.join(root, "skills")
    if os.path.isdir(skills_dir):
        for entry in sorted(os.listdir(skills_dir)):
            candidate = os.path.join(skills_dir, entry, "SKILL.md")
            if os.path.isfile(candidate):
                found["skills"].append(candidate)
    direct = os.path.join(root, "SKILL.md")
    if os.path.isfile(direct):
        found["skills"].append(direct)
    for key, rel in (("plugin", ".claude-plugin/plugin.json"),
                     ("marketplace", ".claude-plugin/marketplace.json"),
                     ("hooks", "hooks/hooks.json")):
        path = os.path.join(root, rel)
        if os.path.isfile(path):
            found[key] = path
    return found


def check(root):
    findings = []
    found = collect(root)
    if not any([found["skills"], found["plugin"], found["marketplace"], found["hooks"]]):
        findings.append(warn(
            relative(root), "nothing here to check",
            "expected skills/<name>/SKILL.md, .claude-plugin/ or hooks/hooks.json"))
        return findings, found
    for path in found["skills"]:
        check_skill(path, findings, root)
    plugin = check_plugin_json(found["plugin"], findings, root) if found["plugin"] else None
    if found["marketplace"]:
        check_marketplace_json(found["marketplace"], plugin, findings, root)
    if found["hooks"]:
        check_hooks_json(found["hooks"], findings, root)
    if found["hooks"] and not found["plugin"]:
        findings.append(warn(
            relative(found["hooks"], root), "no .claude-plugin/plugin.json",
            "hooks are only registered when installed as a plugin"))
    return findings, found


# ---------------------------------------------------------------- cli


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def report(findings, found, root):
    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]
    for f in errors + warnings:
        mark = "ERROR " if f.level == "error" else "warn  "
        print("%s%s: %s" % (mark, f.where, f.message))
        if f.hint:
            print("       %s" % f.hint)
    checked = len(found["skills"]) + sum(
        1 for k in ("plugin", "marketplace", "hooks") if found[k])
    if not findings:
        print("clean: %s checked" % plural(checked, "file"))
    else:
        print("\n%s, %s (%s)" % (plural(len(errors), "error"),
                                  plural(len(warnings), "warning"),
                                  plural(checked, "file")))


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="skillcheck",
        description="Lint Agent Skills and Claude Code plugin manifests.")
    p.add_argument("path", nargs="?", default=".", metavar="PATH")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--strict", action="store_true",
                   help="treat warnings as failures too")
    p.add_argument("--version", action="version", version="skillcheck " + VERSION)
    args = p.parse_args(argv)

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        print("error: not a folder: %s" % args.path, file=sys.stderr)
        return EXIT_USAGE

    try:
        findings, found = check(root)
    except OSError as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps({
            "ok": not findings,
            "findings": [f.as_dict() for f in findings],
        }, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        report(findings, found, root)

    bad = [f for f in findings if f.level == "error" or args.strict]
    return EXIT_FOUND if bad else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
