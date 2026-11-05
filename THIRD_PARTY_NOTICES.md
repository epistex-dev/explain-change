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
copies of one of them. No source file of these projects is vendored whole.

### SpecStory CLI (Apache License 2.0)

- Source: https://github.com/specstoryai/getspecstory, commit `a971fedc983d59da19c5ecf37caf8b6d3afad4cb`, folder `specstory-cli/pkg/providers/`
- Copyright 2025-2026 by SpecStory, Inc., All Rights Reserved. (the notice in `specstory-cli/README.md`; the repository has no NOTICE file, and its `LICENSE.txt` is the unfilled Apache template)
- Licence: https://www.apache.org/licenses/LICENSE-2.0
- Ported into `adapters/copilot.py`: the user-message classification of `copilotcli/events.go` (`classifyUserMessage`), the `toolRequests` / `tool.execution_complete` pairing and the shell exit-code rule; the format description in `copilotcli/COPILOTCLI-FORMAT.md` is the specification for the rest.
- Ported into `adapters/codex.py`: the record shapes and output shapes of `codexcli/agent_session.go` and `provider.go`, including `codexItemAsLegacyEvent`.
- Test data: `skills/explain-change/tests/fixtures/copilot/tool-exercise.jsonl` and `user-shell.jsonl` come from `copilotcli/testdata/` of that commit.
- Changes (Apache-2.0 section 4(b)): the Go code is rewritten in Python against the normalized model of `adapters/model.py`; the Copilot exit code also falls back to the trailing `<shellId: ... completed with exit code N>` line; sub-agent records become child sessions. In `tool-exercise.jsonl`, records of turn, usage, hook, skill and model bookkeeping are removed, telemetry, opaque-reasoning and `parentId` keys are removed, and strings longer than 300 characters are cut (a string that ends in a shell exit line keeps its start and its end). `user-shell.jsonl` is unchanged.

### tokscale (MIT)

- Source: https://github.com/junhoyeo/tokscale, `crates/tokscale-core/src/sessions/codex.rs`
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
