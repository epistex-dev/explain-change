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
