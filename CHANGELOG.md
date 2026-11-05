# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-05

### Added
- `explain-change` skill: collects a diff and the Claude Code session, checks every quote, command and cited line, and renders one offline HTML page (schema v2).
- Five-block page: request and result, where it changed (system map), how the new logic runs, why this way, evidence checked.
- Grounding checks: quotes against the session transcript, tool-call evidence, redaction of credentials.
- Pages in Vietnamese (`vi`) and English (`en`).
- Plugin and marketplace manifests for `/plugin marketplace add epistex-dev/explain-change`.
- Bundled sample doc (`reference/examples/password-autofill.v2.json`) and a red-check script that proves each guard is tested.

[0.1.0]: https://github.com/epistex-dev/explain-change/releases/tag/v0.1.0
