# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Session mode: `explain-session/1` docs, `collect.py --session`, and a swimlane page (`render.py` on a session doc) with a strip, one lane per theme, a side panel and a link to each theme's change page. Real deletes show as outward actions; deletes under `/tmp/` or `$TMPDIR` show as one count line. A worktree made by `git worktree add` in the transcript counts as its repo.
- `install.sh`: installs the skill for Claude Code, Codex, Gemini CLI, Copilot, Cursor, OpenCode, Goose, Amp, Kiro, Windsurf, Cline and Roo (`--harness`, `--copy`, `--project`, `--uninstall`, `--dry-run`, `--force`).
- `gemini-extension.json` (Gemini CLI extension) and a portable `plugin.json` (Agent Plugins manifest, read by Codex).
- Install section in the README with one row per harness.
- Tests for `install.sh` and the manifests, and 16 more guards in the red check.

### Changed
- `SKILL.md` names no single harness: the cold-read gate uses a fresh subagent, else the command in `EXPLAIN_COLDREAD_CMD`, else is skipped and the final reply says so.
- Without a Claude Code transcript the page is rendered with `--no-validate` and says it was not checked against the session.

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
