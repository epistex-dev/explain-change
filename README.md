<div align="center">

# explain-change

### Your agent did the work. Now you understand it.

**A Claude Code skill that turns an agent's code change into one offline page you can actually understand.**

[![test](https://github.com/epistex-dev/explain-change/actions/workflows/test.yml/badge.svg)](https://github.com/epistex-dev/explain-change/actions/workflows/test.yml)
![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3%20stdlib%20only-3776ab)

<img src="docs/images/hero.png" alt="The explain-change page for a sample change: a system map in the centre, a side panel with the Requests tab open" width="900">

<sub>Sample page rendered from the bundled fixture <code>reference/examples/password-autofill.v2.json</code>. The change is synthetic.</sub>

</div>

## Why it exists

Agents now write code faster than their owners read it. A summary like "fixed the bug, tests pass" asks you to trust the change, and over time you ship code nobody on the team understands.

`explain-change` replaces that trust with a page. After an agent edit, the skill collects the diff and the Claude Code session, and the agent writes a structured `explain.json`. Scripts then check that file against the real repo and session, and render it as one self-contained HTML page. The page uses plain words and shows no code, diff or file:line: it is for the owner who did not write the change.

## What the page shows

Five blocks, in this order. Each opens with its one-sentence conclusion, and each fact appears in full in one block only; the others link to it.

| Block | Question it answers |
| --- | --- |
| **Request ↔ result** | What did you ask for, and what came of each request? |
| **Where it changed** | Which parts of the system changed and which stayed as they were? (the system map) |
| **How the new logic runs** | How did the logic run before, and how does it run now? (before and after pictures) |
| **Why** | Why this way, and which options were rejected? |
| **Evidence checked** | What was proven, how, and what was not checked? |

The map is the centre of the page. Click a box to filter the other four blocks to that part of the system.

<img src="docs/images/logic.png" alt="The same sample page with the Logic tab open and one map node selected" width="900">

## How claims are grounded

A claim without a source is labelled `inferred` on the page. Everything else is checked before the page is written:

- **Quotes are checked against the session transcript.** A request quote must occur in a message you typed; a rationale quote must occur in the session. A quote that is not there fails validation.
- **Tool-call evidence.** A "ran X" claim cites the command and an excerpt of its output, and both must occur in the same tool call. A worker's word with no tool call is labelled a worker's report and counted.
- **Cited code and counts.** Referenced lines are read at the right commit, and the files and +/- counts on the map must equal `git`.
- **Redaction of sensitive values.** The skill learns the secrets typed in the session (values after labels such as `password:`, and `ghp_`, `sk-`, `glpat-`, `Bearer` tokens). It rejects any doc that contains one and masks it in the digest and the page.

Details: [`references/explain-schema.md`](skills/explain-change/references/explain-schema.md).

## Install

### As a plugin (recommended)

In Claude Code:

```text
/plugin marketplace add epistex-dev/explain-change
/plugin install explain-change@explain-change
```

The skill is then available as `explain-change` (namespaced `/explain-change:explain-change`).

### Manually

Copy or symlink the skill folder into your skills directory:

```bash
git clone https://github.com/epistex-dev/explain-change.git
mkdir -p ~/.claude/skills
ln -s "$PWD/explain-change/skills/explain-change" ~/.claude/skills/explain-change   # or: cp -r
```

### Requirements

Python 3 with the standard library only (no packages to install) and `git`. Tests of the edge router also use `node` when it is on `PATH`.

## Usage

Ask Claude Code after any agent edit: "explain this change", "giải thích thay đổi", or review a diff, commit or PR. The skill's seven steps then run:

1. **Collect**: `collect.py --v2 [<base>..<head> | <commit>] [--path <dir>]...` lists the changed files per module and the matching session transcripts.
2. **Read the session**: the agent finds the transcript that matches the task and the user's own words.
3. **Write**: the agent writes `explain.json`.
4. **Validate**: `validate.py explain.json --transcript <file>` checks every claim and prints `ok`.
5. **Render**: `render.py explain.json --transcript <file> --text` writes `index.html` (one file, under 512 KB, fonts inlined) next to the doc.
6. **Cold-read gate**: a fresh subagent answers five questions from the page text alone.
7. **Show**: you get the path of `index.html`, opened in a preview.

The page language is `vi` by default and `en` through the doc's `lang` field.

To render the bundled sample without a repo or session:

```bash
python3 skills/explain-change/scripts/render.py \
  skills/explain-change/reference/examples/password-autofill.v2.json \
  --no-validate --out /tmp/sample.html
```

`--no-validate` skips the git and transcript checks, and the page says so.

Reading order for the skill itself: [`SKILL.md`](skills/explain-change/SKILL.md) (steps), [`references/explain-schema.md`](skills/explain-change/references/explain-schema.md) (doc fields and rules), [`DESIGN.md`](skills/explain-change/DESIGN.md) (page design and decisions).

## Development

```text
.claude-plugin/        plugin.json, marketplace.json
skills/explain-change/
  SKILL.md             the skill
  scripts/             collect.py, validate.py, render.py, lib/
  assets/              page CSS and JS, fonts, icons
  references/          the explain.json schema
  reference/           UI tokens and the bundled sample doc
  tests/               unit tests and the red check
docs/images/           screenshots used in this README
```

Run the tests:

```bash
python3 -m unittest discover -s skills/explain-change/tests
```

The red check removes each guard in a throwaway copy of the skill and requires its test to go red:

```bash
python3 skills/explain-change/tests/red_check.py
```

Validate the plugin manifests with `claude plugin validate .`. CI runs the unit tests on every push and pull request (one job, Python 3.12).

## License

[MIT](LICENSE). Third-party fonts, icons and Mermaid keep their own licences: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
