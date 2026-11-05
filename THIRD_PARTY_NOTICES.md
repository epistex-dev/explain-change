# Third-party notices

The skill bundles these third-party files. Each keeps its own licence.

| Component | Where | Licence | Notice |
| --- | --- | --- | --- |
| Mermaid 12.3.0 (`mermaid.min.js`) | `skills/explain-change/assets/` | MIT | `skills/explain-change/assets/mermaid.LICENSE`, version in `mermaid.VERSION`. Only the legacy v1 report page inlines it; the v2 page does not. |
| Inter (Latin, Vietnamese subsets) | `skills/explain-change/assets/ui/fonts/` | SIL OFL 1.1 | `skills/explain-change/assets/ui/LICENSES.txt` |
| JetBrains Mono (Latin subset) | `skills/explain-change/assets/ui/fonts/` | SIL OFL 1.1 | `skills/explain-change/assets/ui/LICENSES.txt` |
| Lucide icons (inline SVG sprite) | `skills/explain-change/assets/ui/icons.svg` | ISC | `skills/explain-change/assets/ui/LICENSES.txt` |

## Code and test data derived from other projects

The transcript adapters in `skills/explain-change/scripts/lib/adapters/` read the session files that agent
harnesses write. Their record handling is ported from the projects below, and two test fixtures are trimmed
copies of them. No source file of these projects is vendored whole.

### SpecStory CLI (Apache License 2.0)

- Source: https://github.com/specstoryai/getspecstory, commit `a971fedc983d59da19c5ecf37caf8b6d3afad4cb`, folder `specstory-cli/pkg/providers/`
- Copyright 2025-2026 by SpecStory, Inc., All Rights Reserved. (the notice in `specstory-cli/README.md`; the repository has no NOTICE file, and its `LICENSE.txt` is the unfilled Apache template)
- Licence: https://www.apache.org/licenses/LICENSE-2.0
- Ported into `adapters/copilot.py`: the user-message classification of `copilotcli/events.go` (`classifyUserMessage`), the `toolRequests` / `tool.execution_complete` pairing and the shell exit-code rule; the format description in `copilotcli/COPILOTCLI-FORMAT.md` is the specification for the rest.
- Ported into `adapters/codex.py`: the record shapes and output shapes of `codexcli/agent_session.go` and `provider.go`, including `codexItemAsLegacyEvent`.
- Ported into `adapters/opencode.py`: the 2.x schema and the record handling of `opencode/OPENCODE-FORMAT.md`, `database.go` and `agent_session.go` (`session_v2` / `session_message`, matching a repository by `directory`, sub-agent sessions through `parent_id`, the message types `user`, `assistant`, `shell`, `synthetic`, `system`, `skill` and `compaction`, the tool `state` shapes and `metadata.exit`).
- Ported into `adapters/cursor_ide.py`: the storage layout and record handling of `cursoride/CURSORIDE-FORMAT.md`, `database.go` and `agent_session.go` (the `cursorDiskKV` table in `globalStorage/state.vscdb`, `composerData:<id>` with `fullConversationHeadersOnly` or the paged `composerConvHeaders:<id>:<page>` rows, `bubbleId:<id>:<bubble>` rows, bubble types 1 and 2, `toolFormerData` and the older `capabilities[].data.bubbleDataMap`, shell tool names and the `status` values, matching a composer to a folder by `workspaceIdentifier.uri.fsPath`).
- Test data: `skills/explain-change/tests/fixtures/copilot/tool-exercise.jsonl` and `user-shell.jsonl` come from `copilotcli/testdata/`, and `fixtures/opencode/tui-session.jsonl`, `tool-exercise.jsonl`, `model-error.jsonl` and `schema.sql` from `opencode/testdata/`, of that commit.
- Changes (Apache-2.0 section 4(b)): the Go code is rewritten in Python against the normalized model of `adapters/model.py`; the Copilot exit code also falls back to the trailing `<shellId: ... completed with exit code N>` line; sub-agent records become child sessions. In `adapters/cursor_ide.py` the result is the normalized model, only the rows of the matched composer are queried (by key range), the database is opened read-only, rows are streamed and capped, the exit code is not read (the format has no stable field for it) and a `cancelled` or `error` status counts as a failed call; the timestamps of `calculateTimestamp` are not ported. In `tool-exercise.jsonl`, records of turn, usage, hook, skill and model bookkeeping are removed, telemetry, opaque-reasoning and `parentId` keys are removed, and strings longer than 300 characters are cut (a string that ends in a shell exit line keeps its start and its end). `user-shell.jsonl` is unchanged. In the three OpenCode captures, reasoning parts and the `native`, `snapshot`, `rawFinish` and `reasoningField` keys are removed and strings longer than 300 characters are cut; `schema.sql` is unchanged. In `adapters/opencode.py`, the result is the normalized model, the database is opened read-only, rows are streamed and capped, the first prompt of a sub-agent session is injected rather than the user's, and a `metadata.error: true` result counts as a failed call.

### tokscale (MIT)

- Source: https://github.com/junhoyeo/tokscale, `crates/tokscale-core/src/sessions/codex.rs` and `opencode.rs`
- Ported into `adapters/opencode.py`: the reading of the 1.x `session` / `message` / `part` tables, whose `data` column holds a JSON object, and of the JSON tree before 1.2.
- Ported into `adapters/codex.py`: the way a forked or sub-agent Codex rollout replays its parent's history before its own first turn (the UUIDv7 comparison of `turn_id` against the child's id, `task_started` announcements, `thread_source` and `source.subagent` for thread kinds), and the treatment of `compacted` records.

```
MIT License

Copyright (c) 2025 Junho Yeo

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### openai/codex (Apache License 2.0)

- Source: https://github.com/openai/codex, `codex-rs/core/src/tools/context.rs` and `codex-rs/core/src/tools/mod.rs`
- Copyright 2025 OpenAI (the copyright line of its `LICENSE`)
- Licence: https://www.apache.org/licenses/LICENSE-2.0
- Used in `adapters/codex.py`: the exit-code lines of a shell tool output, `Process exited with code N` and the older `Exit code: N`. The Codex fixture under `skills/explain-change/tests/fixtures/codex/` is built from the record formats in these files and in the SpecStory and tokscale code above; its contents are written for this repository.

### agent-sessions (MIT)

- Source: https://github.com/jazzyalex/agent-sessions, commit `555fbfddaa286b63cdef2ef13db88cb9cf320d87`
- Ported into `adapters/opencode.py`: the OpenCode storage layouts of `AgentSessions/OpenCode/` (`OpenCodeSqliteReader.swift`, `OpenCodeV2MessageAdapter.swift`, `OpenCodeBackendDetector.swift`) and `Services/OpenCodeSessionParser.swift`, namely the 2.x row shapes, the 1.x tables and the JSON tree with its flat `part/` layout.
- Ported into `adapters/cursor_cli.py`: `Services/CursorSessionParser.swift` (the line shape `{role, message: {content}}`, the unwrapping of `<user_query>`, the `tool_use` block names, the `Shell` tool's `input.command`, sub-agent files in `<uuid>/subagents/` from `detectSubagentInfo`, and the project-folder decoding of `inferCWD` / `inferCWDBestEffort`).
- Changes: the Swift code is rewritten in Python against the normalized model of `adapters/model.py`; only the text inside `<user_query>` is the user's and all other user text is injected; the tool calls carry no output, exit code or failure flag because the format records no results; `find_sessions` matches a project folder by the folder name of the real path of the working directory; every path is confined to the root.
- Test data, unchanged in content: `skills/explain-change/tests/fixtures/cursor-cli/projects/`, from `AgentSessionsTests/Fixtures/Cursor/` (`test-session.jsonl`, `subagent-session.jsonl`) and `Resources/Fixtures/stage0/agents/cursor/` (`small.jsonl`, `schema_drift.jsonl`, `subagent/parent.jsonl`, `subagent/subagents/child.jsonl`) of that commit, renamed into the Cursor CLI directory layout.
- Test data, unchanged: `skills/explain-change/tests/fixtures/opencode/agent-sessions/sqlite_v2/` and `storage_legacy/`, and `fixtures/gemini/vendored/jsonl_v040.jsonl` and `small.json`, from `Resources/Fixtures/stage0/agents/` of that commit.

```
MIT License

Copyright (c) 2026 Alexander Malakhov

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### google-gemini/gemini-cli (Apache License 2.0)

- Source: https://github.com/google-gemini/gemini-cli, commit `1fe22af5f800d8c3024e9968d35bb75bd09e6b79`
- Copyright 2025 Google LLC (the header of the source files listed below; its `LICENSE` is the unfilled Apache template and the repository has no NOTICE file)
- Licence: https://www.apache.org/licenses/LICENSE-2.0
- Used in `adapters/gemini.py`: the transcript record format of `packages/core/src/services/chatRecordingService.ts` and `chatRecordingTypes.ts` (message, `$set`, `$patch` and `$rewindTo` records, repeated message ids, sub-agent files), `isIgnoredUserContent` in `utils/sessionUtils.ts`, and the `run_shell_command` output format of `packages/core/src/tools/shell.ts`.
- Changes (Apache-2.0 section 4(b)): the TypeScript logic is rewritten in Python against the normalized model of `adapters/model.py`; the exit code is read from the footer lines only. The fixtures under `skills/explain-change/tests/fixtures/gemini/tmp/` are built from these formats and their contents are written for this repository.
