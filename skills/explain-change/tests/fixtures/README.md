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
