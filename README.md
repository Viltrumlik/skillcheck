<h1 align="center">skillcheck</h1>

<p align="center">
  <b>Lint Agent Skills and Claude Code plugins before they silently fail to load.</b>
</p>

<p align="center">
  <a href="https://github.com/Viltrumlik/skillcheck/actions/workflows/ci.yml"><img src="https://github.com/Viltrumlik/skillcheck/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/dependencies-0-brightgreen" alt="Zero dependencies">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT"></a>
</p>

A malformed skill does not fail loudly. It just never loads, or loads and is ignored, and you find out when someone tells you it does not work. A typo in a hook event name is silent. A `source` that points nowhere is silent. A description over the limit is silent.

```bash
skillcheck
```

```
ERROR skills/demo/SKILL.md: name 'Demo_Skill' breaks the pattern
       lowercase letters, digits and hyphens; cannot start or end with a hyphen
ERROR hooks/hooks.json SessionStart[0].hooks[0]: command points at
       'scripts/gone.py', which does not exist
warn  .claude-plugin/plugin.json: no keywords
       it will not turn up in search

2 errors, 1 warning (4 files)
```

## What it checks

**`skills/<name>/SKILL.md`** — frontmatter present; `name` matches the documented pattern and the folder it lives in; `description` present and within the 1024-character limit; a body after the frontmatter.

**`.claude-plugin/plugin.json`** — valid JSON; `name` present and well formed; `version`, `description`, `keywords` present.

**`.claude-plugin/marketplace.json`** — valid JSON; `plugins` non-empty; each `source` actually exists on disk; versions agree with `plugin.json`.

**`hooks/hooks.json`** — valid JSON; event names are ones that exist; every hook is `type: "command"` with a command; and any `${CLAUDE_PLUGIN_ROOT}/…` script the command names is really there.

## Errors and warnings

**Errors** are things that are definitely wrong: invalid JSON, a missing required field, a name that breaks the documented pattern, a path that does not exist.

**Warnings** are judgement: a missing `keywords`, a short description, a name that disagrees with its folder. They do not fail the run unless you ask.

```bash
skillcheck --strict    # warnings fail too
skillcheck --json      # machine-readable
```

Exit codes: `0` clean · `1` error reading files · `2` usage · `3` problems found.

This tool is not the specification. When it is unsure, it warns rather than fails.

## Install

```bash
pipx install git+https://github.com/Viltrumlik/skillcheck
```

Or just take the file — it is one script with no dependencies:

```bash
curl -O https://raw.githubusercontent.com/Viltrumlik/skillcheck/main/skillcheck.py
python3 skillcheck.py
```

## In CI

```yaml
- run: pipx install git+https://github.com/Viltrumlik/skillcheck
- run: skillcheck
```

## Development

```bash
python3 -m unittest discover -s tests -v
```

CI runs on Ubuntu, macOS and Windows with Python 3.9 through 3.13. Every check has a test that builds a deliberately broken project and asserts the finding.

## License

[MIT](LICENSE) © Alisher Muhammadaliyev ([@Viltrumlik](https://github.com/Viltrumlik))
