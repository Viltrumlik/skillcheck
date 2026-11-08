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
        return None, error(path, "JSON o'qilmadi: %s" % e,
                           "vergul yoki qavs tushib qolgan bo'lishi mumkin")
    except OSError as e:
        return None, error(path, "fayl ochilmadi: %s" % e)


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


def check_skill(path, findings):
    where = os.path.relpath(path)
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        findings.append(error(where, "o'qilmadi: %s" % e))
        return

    fields = parse_frontmatter(text)
    if fields is None:
        findings.append(error(
            where, "frontmatter yo'q",
            "fayl --- qatori bilan boshlanib, name va description bo'lishi kerak"))
        return

    name = fields.get("name")
    if not name:
        findings.append(error(where, "frontmatter'da name yo'q"))
    elif not NAME_RE.match(name):
        findings.append(error(
            where, "name %r qoidaga mos emas" % name,
            "faqat kichik harf, raqam va defis; defis bilan boshlanmaydi"))
    else:
        folder = os.path.basename(os.path.dirname(path))
        if folder != name:
            findings.append(warn(
                where, "name %r papka nomi %r bilan bir xil emas" % (name, folder),
                "ko'p yuklovchilar papka nomi bo'yicha topadi"))

    desc = fields.get("description")
    if not desc:
        findings.append(error(
            where, "frontmatter'da description yo'q",
            "agent skillni shu matnga qarab tanlaydi"))
    elif len(desc) > MAX_DESCRIPTION:
        findings.append(error(
            where, "description juda uzun (%d > %d)" % (len(desc), MAX_DESCRIPTION)))
    elif len(desc) < 20:
        findings.append(warn(
            where, "description juda qisqa (%d belgi)" % len(desc),
            "qachon ishlatilishini yozing, shunda agent to'g'ri paytda chaqiradi"))

    body = text[FRONTMATTER.match(text).end():].strip()
    if not body:
        findings.append(warn(where, "frontmatter'dan keyin matn yo'q"))


# ---------------------------------------------------------------- manifests


def check_plugin_json(path, findings):
    where = os.path.relpath(path)
    data, bad = read_json(path)
    if bad:
        findings.append(bad)
        return None
    if not isinstance(data, dict):
        findings.append(error(where, "yuqori darajada obyekt kutilgan"))
        return None

    name = data.get("name")
    if not name:
        findings.append(error(where, "name yo'q"))
    elif not NAME_RE.match(str(name)):
        findings.append(error(where, "name %r qoidaga mos emas" % name))

    version = data.get("version")
    if not version:
        findings.append(warn(where, "version yo'q",
                             "yuklovchilar yangilanishni shunga qarab biladi"))
    elif not VERSION_RE.match(str(version)):
        findings.append(warn(where, "version %r semver ko'rinishida emas" % version))

    if not data.get("description"):
        findings.append(warn(where, "description yo'q",
                             "katalog va ro'yxatlar shuni ko'rsatadi"))
    if not data.get("keywords"):
        findings.append(warn(where, "keywords yo'q", "qidiruvda topilmaydi"))
    return data


def check_marketplace_json(path, plugin, findings):
    where = os.path.relpath(path)
    data, bad = read_json(path)
    if bad:
        findings.append(bad)
        return
    if not isinstance(data, dict):
        findings.append(error(where, "yuqori darajada obyekt kutilgan"))
        return
    if not data.get("name"):
        findings.append(error(where, "name yo'q"))
    if not isinstance(data.get("owner"), dict):
        findings.append(warn(where, "owner yo'q yoki obyekt emas"))

    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        findings.append(error(where, "plugins bo'sh yoki ro'yxat emas"))
        return
    root = os.path.dirname(os.path.dirname(path))
    for i, entry in enumerate(plugins):
        tag = "%s plugins[%d]" % (where, i)
        if not isinstance(entry, dict):
            findings.append(error(tag, "obyekt emas"))
            continue
        if not entry.get("name"):
            findings.append(error(tag, "name yo'q"))
        source = entry.get("source")
        if not source:
            findings.append(error(tag, "source yo'q"))
        elif isinstance(source, str) and source.startswith("."):
            if not os.path.isdir(os.path.join(root, source)):
                findings.append(error(tag, "source %r mavjud emas" % source))
        if plugin and entry.get("version") and plugin.get("version") \
                and entry["version"] != plugin["version"]:
            findings.append(warn(
                tag, "version %r plugin.json dagi %r bilan mos emas"
                % (entry["version"], plugin["version"])))


def check_hooks_json(path, findings):
    where = os.path.relpath(path)
    data, bad = read_json(path)
    if bad:
        findings.append(bad)
        return
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict) or not hooks:
        findings.append(error(where, "hooks obyekti yo'q yoki bo'sh"))
        return

    root = os.path.dirname(os.path.dirname(path))
    for event, entries in hooks.items():
        if event not in KNOWN_EVENTS:
            findings.append(warn(
                where, "notanish hodisa %r" % event,
                "imlo xatosi bo'lsa hook hech qachon ishlamaydi va jim qoladi"))
        if not isinstance(entries, list):
            findings.append(error(where, "%s ro'yxat emas" % event))
            continue
        for i, entry in enumerate(entries):
            tag = "%s %s[%d]" % (where, event, i)
            if not isinstance(entry, dict):
                findings.append(error(tag, "obyekt emas"))
                continue
            if "matcher" not in entry:
                findings.append(warn(tag, "matcher yo'q",
                                     "hammasiga mos kelishi uchun \".*\" yozing"))
            inner = entry.get("hooks")
            if not isinstance(inner, list) or not inner:
                findings.append(error(tag, "ichki hooks bo'sh yoki ro'yxat emas"))
                continue
            for j, hook in enumerate(inner):
                htag = "%s.hooks[%d]" % (tag, j)
                if not isinstance(hook, dict):
                    findings.append(error(htag, "obyekt emas"))
                    continue
                if hook.get("type") != "command":
                    findings.append(error(htag, "type \"command\" bo'lishi kerak"))
                command = hook.get("command")
                if not command:
                    findings.append(error(htag, "command yo'q"))
                elif isinstance(command, str):
                    check_hook_path(command, root, htag, findings)


SCRIPT_IN_COMMAND = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"'\s]+)")


def check_hook_path(command, root, tag, findings):
    for rel in SCRIPT_IN_COMMAND.findall(command):
        if not os.path.exists(os.path.join(root, rel)):
            findings.append(error(
                tag, "command %r faylini ko'rsatadi, u mavjud emas" % rel,
                "yo'l plugin ildiziga nisbatan bo'lishi kerak"))


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
            os.path.relpath(root), "tekshiradigan narsa topilmadi",
            "skills/<nom>/SKILL.md, .claude-plugin/ yoki hooks/hooks.json kutilgan"))
        return findings, found
    for path in found["skills"]:
        check_skill(path, findings)
    plugin = check_plugin_json(found["plugin"], findings) if found["plugin"] else None
    if found["marketplace"]:
        check_marketplace_json(found["marketplace"], plugin, findings)
    if found["hooks"]:
        check_hooks_json(found["hooks"], findings)
    if found["hooks"] and not found["plugin"]:
        findings.append(warn(
            os.path.relpath(found["hooks"]), ".claude-plugin/plugin.json yo'q",
            "hooks faqat plugin sifatida o'rnatilganda ro'yxatdan o'tadi"))
    return findings, found


# ---------------------------------------------------------------- cli


def report(findings, found, root):
    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]
    for f in errors + warnings:
        mark = "XATO " if f.level == "error" else "ogoh "
        print("%s%s: %s" % (mark, f.where, f.message))
        if f.hint:
            print("       %s" % f.hint)
    checked = len(found["skills"]) + sum(
        1 for k in ("plugin", "marketplace", "hooks") if found[k])
    if not findings:
        print("toza: %d fayl tekshirildi" % checked)
    else:
        print("\n%d xato, %d ogohlantirish (%d fayl)"
              % (len(errors), len(warnings), checked))


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="skillcheck",
        description="Agent Skill va Claude Code plugin fayllarini tekshiradi.")
    p.add_argument("path", nargs="?", default=".", metavar="YO'L")
    p.add_argument("--json", action="store_true", help="mashina o'qiydigan chiqish")
    p.add_argument("--strict", action="store_true",
                   help="ogohlantirish ham xato hisoblansin")
    p.add_argument("--version", action="version", version="skillcheck " + VERSION)
    args = p.parse_args(argv)

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        print("xato: papka emas: %s" % args.path, file=sys.stderr)
        return EXIT_USAGE

    try:
        findings, found = check(root)
    except OSError as e:
        print("xato: %s" % e, file=sys.stderr)
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
