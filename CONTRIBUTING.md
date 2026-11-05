# Contributing

## Setup

Python 3 and git. The scripts use the standard library only, so there is nothing to install.

```bash
git clone https://github.com/epistex-dev/explain-change
cd explain-change
python3 -m unittest discover -s tests
```

The full suite takes about 80 seconds. CI runs it on every push and pull request (one job, Python 3.12). The tests create throwaway git repositories, so `git config user.name` and `user.email` must be set. Tests of the edge router also use `node` when it is on `PATH`.

A change that adds a guard should also be covered by the red check, which removes each guard in a throwaway copy of the skill and requires its test to go red:

```bash
python3 tests/red_check.py
```

Validate the plugin manifests with `claude plugin validate .` and the skill with `skills-ref validate skills/explain-change` ([agentskills](https://github.com/agentskills/agentskills/tree/main/skills-ref)).

## Folder layout

```text
.claude-plugin/        Claude Code plugin.json, marketplace.json
plugin.json            portable plugin manifest (Agent Plugins, read by Codex)
gemini-extension.json  Gemini CLI extension manifest
install.sh             installer for every harness
skills/explain-change/
  SKILL.md             the skill: the steps an agent follows
  scripts/             collect.py, validate.py, render.py, lib/
  assets/              page CSS and JS, fonts, icons
  references/          transcripts.md, the doc schemas, examples/ (sample docs), ui/ (UI tokens)
tests/                 unit tests and the red check
docs/                  install, how it works, modes, design notes, images/, the intro video source (intro/)
```

## Pull requests

- One change per pull request, from a branch off `main`.
- Add a line under `## [Unreleased]` in `CHANGELOG.md`.
- Keep the manifest versions (`plugin.json`, `gemini-extension.json`, `.claude-plugin/`) equal to the newest released section of the changelog; a test pins this.
- Pull requests are squash-merged.

Security problems: see [SECURITY.md](SECURITY.md).
