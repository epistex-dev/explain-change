# How it works

Agents write code faster than their owners read it, and "fixed the bug, tests pass" asks for trust. `explain-change` replaces the trust with a page that is checked.

After an agent edit, the skill collects the diff and the session transcript, and the agent writes a structured `explain.json`. Scripts check that file against the real repo and session, and render it as one self-contained HTML page. The page uses plain words and shows no code, diff or file:line: it is for the owner who did not write the change. The steps the agent follows are in [SKILL.md](../skills/explain-change/SKILL.md); the page language is `vi` by default and `en` through the doc's `lang` field.

## How claims are grounded

A claim without a source is labelled `inferred` on the page. Everything else is checked before the page is written:

- **Quotes are checked against the session transcript.** A request quote must occur in a message the user typed; a rationale quote must occur in the session. A quote that is not there fails validation. The bundled change and session samples are held to the same rule: each ships with a synthetic transcript (`skills/explain-change/references/examples/*.transcript.jsonl`, made-up content only) and validates against it in a throwaway `HOME`.
- **Tool-call evidence.** A "ran X" claim cites the command and an excerpt of its output, and both must occur in the same tool call. A worker's word with no tool call is labelled a worker's report and counted.
- **Cited code and counts.** Referenced lines are read at the right commit, and the files and +/- counts on the map must equal `git`.
- **Redaction of sensitive values.** The skill learns the secrets typed in the session (values after labels such as `password:`, and `ghp_`, `sk-`, `glpat-`, `Bearer` tokens). It rejects any doc that contains one and masks it in the digest and the page.
- **A cold read.** A fresh reader gets only the page text and answers five questions; a wrong answer sends the agent back to rewrite that field.

The doc fields and rules are in [`explain-schema.md`](../skills/explain-change/references/explain-schema.md).

## Transcript readers

The skill reads the session of seven harnesses (readers in `skills/explain-change/scripts/lib/adapters/`; the folder and `--format` of each are in the [README table](../README.md#supported-harnesses)). Each reader turns its harness's records into one model (user messages, tool calls with their exit codes, outputs), and `collect.py`, `validate.py` and `render.py` ground a change doc or a session doc in any of them.

- Pass `--transcript <file>`; the format is detected, and `--format` names it.
- A transcript is read only under the harness's own folder after resolving symlinks, so a file the agent wrote itself cannot ground a claim. The folder is fixed per harness under `$HOME`; for Claude Code `EXPLAIN_PROJECTS_DIR` also moves it. No command-line flag, `--format` included, moves it.
- A shell call whose output or exit code the harness did not record (every Cursor CLI and Cursor IDE call, an OpenCode call still running) has an unknown result: it can back a quote or a `mixed` run, never a `passed` run or a `done`.

The readers are ported from open-source projects: see [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## When no transcript is readable

Windsurf, Cline, Roo, Kiro, Goose, Amp, Aider and other Agent Skills harnesses keep no session log the skill reads. The same goes for a transcript that is missing, deleted or unreadable, and for a run outside any agent session. The skill still works, for the change page and the session page alike: the agent writes the doc from its own context and gives the reason in `"transcript_unavailable"` (one line, no secret).

`validate.py` and `render.py` still check the git range, the diff, the +/- counts, the file coverage, every cited code line and every secret; they refuse a doc that has neither a transcript nor a reason, and a doc that has both. The page says so in a short badge "No session log" on the change page (the reason is one line in its Evidence tab) and in one line "No session log: <reason>" on the session page, marks each run as the agent's own account, and on a session page shows the outward counts as the agent's own.
