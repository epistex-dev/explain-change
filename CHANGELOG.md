# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- The flow page: `render.py` on an `explain-flow/1` doc writes one offline page (question and summary, counts, numbered route, map of the parts, one panel per step with branches and error exits, all steps in the HTML without JS, `#step-N`, the five themes, `vi` and `en`, a footer naming the checked commit); a doc with an unknown `kind` exits 1 with one line.
- `explain-flow/1`, a doc that explains how an existing flow of the code works, with no diff and no agent session (`references/explain-flow-schema.md`). `collect.py --flow [--path …] [--slug …]` prints HEAD, the modules and the files, and never exits 3. `validate.py` reads every source from the doc's commit (`git show <commit>:<path>`) and checks its lines and excerpt, the structure of parts, steps, branches and errors, and that the visible text holds no code and no secret. The example `reference/examples/claim-check.flow.json` explains how a claim is checked.
- The change page (`explain-change/2`) has the same five colour themes and "Appearance" picker as the session page, in the same `localStorage` key, so a pick carries across both pages. `render.py --theme <id>` now sets the theme of a change page too, and of the change pages a session render writes. Navy is unchanged; the before/after blocks, map nodes, edges and chips follow the theme, and every theme keeps text at 4.5:1 and rings at 3:1.
- A change doc and a session doc work with no readable transcript (a harness without a reader, a missing or unreadable file, a run outside any agent session). The doc gives `"transcript_unavailable": "<reason>"`; `validate.py` and `render.py` refuse a doc with neither a transcript nor a reason, and a doc with both, and still check git, diff, counts, file coverage, cited code and secrets. A credential in the doc's own quotes is refused wherever the doc repeats it. The change page shows a short badge "Not checked against the session", gives the reason as one line in the Evidence tab, and marks runs as the agent's own account; the session page carries "Not checked against the session: <reason>" beside its status key and shows each outward count as the agent's own, once. `collect.py --session` with no session names this path.
- `collect.py`, `validate.py` and `render.py` take a transcript of Copilot CLI, Codex, OpenCode, Gemini CLI, Cursor CLI or Cursor IDE, for change docs and session docs. `--transcript` detects the format; `--format auto|claude|copilot|codex|opencode|gemini|cursor-cli|cursor-ide` names it, and a file in none of them and outside every harness folder exits 1 with one line naming the formats (a directory exits 2). `collect.py` lists the sessions of the repo's folder labelled by harness.
- A shell call whose output or exit code a harness did not record has an unknown result: it cannot back a `passed` run or a `done`, and the validator says why. Text a harness injected into the user channel never matches a request quote.
- A README and `SKILL.md` table of the supported harnesses and their transcript folders, kept equal to the readers by a test.
- Transcript readers for GitHub Copilot CLI, Codex, OpenCode (database and JSON tree), Gemini CLI, Cursor CLI and Cursor IDE, each limited to its harness's own transcript folder, with fixtures, guards in the red check, and sharded, time-limited `red_check.py` runs.
- Five colour themes for the session page (navy, ocean, plum, graphite, pearl), an "Appearance" picker in its header that remembers the pick in `localStorage`, and `render.py --theme <id>` to set the theme the page opens in. An unknown id exits 1 with one line naming the valid ids.
- Session mode: `explain-session/1` docs, `collect.py --session`, and a swimlane page (`render.py` on a session doc) with a strip, one lane per theme, a side panel and a link to each theme's change page. Real deletes show as outward actions; deletes under `/tmp/` or `$TMPDIR` show as one count line. A worktree made by `git worktree add` in the transcript counts as its repo.
- `install.sh`: installs the skill for Claude Code, Codex, Gemini CLI, Copilot, Cursor, OpenCode, Goose, Amp, Kiro, Windsurf, Cline and Roo (`--harness`, `--copy`, `--project`, `--uninstall`, `--dry-run`, `--force`).
- `gemini-extension.json` (Gemini CLI extension) and a portable `plugin.json` (Agent Plugins manifest, read by Codex).
- Install section in the README with one row per harness.
- Tests for `install.sh` and the manifests, and 16 more guards in the red check.

### Fixed
- A label such as `mk:` inside a CSS name (`--mk:`, `.mk:hover`) is no longer learned as a secret: the short label `mk` must follow the start of the text, white space or punctuation other than `-`, `_` and `.`. The other labels (`password=`, `db_password=`, `--token=`) match as before.

### Changed
- `transcript_unavailable` must be a single line of at most 200 characters; a longer, empty, non-text or multi-line value is an error, and a doc that gives both a transcript and a reason is refused (it was accepted before).
- The session page has a compact band (summary and Needs you side by side), shows all lanes on a 1440 x 900 screen, and its side panel opens on what the agent decided (irreversible choices always listed, reversible ones in an accordion) and the outward actions.
- The session page has `header` and `nav` landmarks; an open count bubble stays pressed and keeps focus when the lanes are laid out again.
- `SKILL.md` names no single harness: the cold-read gate uses a fresh subagent, else the command in `EXPLAIN_COLDREAD_CMD`, else is skipped and the final reply says so.
- Without a transcript the doc is validated and rendered like any other (`validate.py` and `render.py` without `--transcript`), and the page says it was not checked against the session.

## [0.1.0] - 2026-11-05

### Added
- `explain-change` skill: collects a diff and the Claude Code session, checks every quote, command and cited line, and renders one offline HTML page (schema v2).
- Five-block page: request and result, where it changed (system map), how the new logic runs, why this way, evidence checked.
- Grounding checks: quotes against the session transcript, tool-call evidence, redaction of credentials.
- Pages in Vietnamese (`vi`) and English (`en`).
- Plugin and marketplace manifests for `/plugin marketplace add epistex-dev/explain-change`.
- Bundled sample doc (`reference/examples/password-autofill.v2.json`) and a red-check script that proves each guard is tested.

[Unreleased]: https://github.com/epistex-dev/explain-change/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/epistex-dev/explain-change/releases/tag/v0.1.0
