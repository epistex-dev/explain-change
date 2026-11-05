# Adapter fixtures

- `copilot/tool-exercise.jsonl` and `copilot/user-shell.jsonl`: Copilot CLI 1.0.105 sessions recorded by the SpecStory project
  (`specstory-cli/pkg/providers/copilotcli/testdata/`, Apache-2.0, see `THIRD_PARTY_NOTICES.md`). `tool-exercise.jsonl` is trimmed
  to under 60 KB: bookkeeping records and telemetry are removed and long strings are cut. It keeps the typed prompts, the
  `!` command, three sub-agents, calls that failed with `success:false`, and a shell command that exited 1 with `success:true`.
- `codex/sessions/2026/11/04/`: Codex rollout files built from the record formats in openai/codex `codex-rs/core/src/tools/context.rs`
  and the SpecStory and tokscale Codex parsers. Their text is written for this repository. Together they hold:
  - `...-0001.jsonl`, a main session in `/work/repo`: both user-message shapes (`event_msg user_message` and `item_completed UserMessage`),
    an injected `<environment_context>` message, `function_call` (`exec_command`, `shell_command`, legacy `shell`), `custom_tool_call`
    (`apply_patch`), the three output shapes (plain string, JSON with `metadata.exit_code`, `[{text}]` items), both exit strings
    (`Process exited with code N`, `Exit code: N`), an `exec_command_end` event, a `compacted` record, token and unknown records.
  - `...-0002.jsonl`, the sub-agent it spawned (`source.subagent.thread_spawn`), which replays the parent's history before its own turn.
  - `...-0003.jsonl`, a user fork (`thread_source: user`) that replays the parent's history before its own turn.
- `opencode/tui-session.jsonl`, `tool-exercise.jsonl`, `model-error.jsonl` and `schema.sql`: OpenCode 2.x database captures recorded by the
  SpecStory project (`specstory-cli/pkg/providers/opencode/testdata/`, Apache-2.0, see `THIRD_PARTY_NOTICES.md`). Each line is
  `{table, row}`; the tests create the database from `schema.sql` (unchanged) and insert the rows. The three captures are trimmed:
  reasoning parts and the `native`, `snapshot`, `rawFinish` and `reasoningField` keys are removed and strings longer than 300 characters are cut.
  They hold typed prompts, a `!` shell command, `synthetic` text, calls with `status: error`, a call with `metadata.error: true`, sub-agent
  sessions linked through `metadata.sessionID`, and a session whose model call failed.
- `opencode/agent-sessions/sqlite_v2/` and `storage_legacy/`: the OpenCode fixtures of the agent-sessions project
  (`AgentSessions` `Resources/Fixtures/stage0/agents/opencode/`, MIT, see `THIRD_PARTY_NOTICES.md`), unchanged. `sqlite_v2` holds row shapes of the
  2.x database; `storage_legacy` is the JSON tree of OpenCode before 1.2 (`storage/session`, `storage/message`, and the flat `storage/part/<part id>.json`).
- `gemini/vendored/jsonl_v040.jsonl` and `small.json`: the Gemini CLI fixtures of the agent-sessions project
  (`Resources/Fixtures/stage0/agents/gemini/`, MIT), unchanged. `jsonl_v040.jsonl` is the JSONL transcript of Gemini CLI 0.40; `small.json` is the older single-object `.json` transcript.
- `gemini/tmp/`: a Gemini CLI data directory built from the record formats in google-gemini/gemini-cli
  (`chatRecordingService.ts`, `chatRecordingTypes.ts`, `tools/shell.ts`). Its text is written for this repository. `ddc5e473a09bd156` is
  `sha256("/work/repo")`, the project hash of the tests' working directory. Together they hold:
  - `chats/session-2026-11-04T10-00-0f1e2d3c.jsonl`: the metadata record, `user`, `gemini` and `info` messages, injected `<session_context>` and
    `<hook_context>` messages, shell calls whose results end in `Exit Code: N`, `Signal:` and `Process Group PGID:` lines, a call with status `error`,
    one `cancelled` and one `executing`, `$patch` records (a tool result by id, `content`, `updates` with `removeIds`), a `$set` record, a repeated
    message id and a `$rewindTo` record. (`orderIds` and `Background PIDs:` are covered by the tests, which build those records inline.)
  - `chats/0f1e2d3c-aaaa-4bbb-8ccc-000000000001/sub-1.jsonl`: the sub-agent transcript of that session (`kind: subagent`).
  - `chats/session-2026-11-03T09-00-legacy-1.json`: a transcript in the older single-object format.
  - `tmp/other-project/`: a session recorded in another project, which `find_sessions` must not return.
- `cursor-cli/projects/`: a Cursor CLI `~/.cursor/projects` directory. The transcripts are the Cursor fixtures of the agent-sessions project
  (MIT, see `THIRD_PARTY_NOTICES.md`), unchanged in content and renamed to the layout `<project>/agent-transcripts/<uuid>/<uuid>.jsonl`
  (sub-agents in `<uuid>/subagents/`) that the Cursor CLI writes:
  - `work-repo/agent-transcripts/a1b2c3d4-e5f6-4890-abcd-ef1234567890/`: `AgentSessionsTests/Fixtures/Cursor/test-session.jsonl` (a `<user_query>`
    message, injected text, two `Shell` calls) and its sub-agent `subagents/d88b213c-84e1-427d-bb5e-3859c1011087.jsonl` (`subagent-session.jsonl`).
  - `.../0c1d2e3f-4a5b-4c6d-8e7f-a0b1c2d3e4f5/`: `Resources/Fixtures/stage0/agents/cursor/subagent/parent.jsonl` and `subagents/child.jsonl`.
  - `.../11111111-2222-4333-8444-555555555555/` and `.../66666666-7777-4888-9999-aaaaaaaaaaaa/`: `stage0/agents/cursor/small.jsonl` and `schema_drift.jsonl`.
  - `other-project/`: a copy of `test-session.jsonl`, a session of another project, which `find_sessions` must not return.
  `work-repo` is the project folder name of `/work/repo`, the working directory the tests pass to `find_sessions`; `Session.cwd` is None for it because that directory does not exist on the test machine (the slug decoding is tested with a stand-in directory probe).
- Cursor IDE (`adapters/cursor_ide.py`) has no fixture file: `tests/test_adapters_cursor_ide.py` (`build_fixture`) writes a small `state.vscdb` with
  a `cursorDiskKV` table, from the record formats of SpecStory's `cursoride/CURSORIDE-FORMAT.md` (Apache-2.0). Its contents are written for this
  repository: a Cursor 3 composer with inline `fullConversationHeadersOnly` and `toolFormerData` (shell calls with output, `completed`, `cancelled`
  and `error` status; a `read_file_v2` call; a bubble no header lists), a composer whose headers are paged `composerConvHeaders:<id>:<page>` rows, an older
  composer with an inline conversation and tool data in `capabilities[].data.bubbleDataMap`, a composer of another folder, one that records no folder, and
  unrelated `checkpointId:` / `messageRequestContext:` keys. The size tests build larger databases (up to 74 MB) in a temporary directory.
