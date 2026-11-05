# Transcripts

Read this when no listed session fits the task, when a script refuses or cannot read the transcript file, or when the harness has no transcript reader. It holds the harness table, the rules for a transcript path, and the no-transcript path.

## Harnesses

A transcript of any harness below grounds the doc. `collect.py` lists the sessions recorded in the repo's folder, labelled by harness, each harness's 3 newest. When none fits, list the harness's folder by time and open the likely files. The format is detected from the file; `--format auto|claude|copilot|codex|opencode|gemini|cursor-cli|cursor-ide` names it. A file in none of these formats exits 1 with one line naming them when it lies outside every folder in the table; a text file inside the Claude Code folder is read as a Claude Code transcript (skipped lines are warned about, exit 0), and a directory exits 2 ("transcript not found").

| Harness | Transcript folder | `--format` |
|---|---|---|
| Claude Code | `~/.claude/projects` | `claude` |
| GitHub Copilot CLI | `~/.copilot/session-state` | `copilot` |
| Codex | `~/.codex/sessions` | `codex` |
| OpenCode | `~/.local/share/opencode` (`opencode.db`; a session is named `<database path>#<session id>`) | `opencode` |
| Gemini CLI | `~/.gemini/tmp` | `gemini` |
| Cursor CLI | `~/.cursor/projects` | `cursor-cli` |
| Cursor IDE | `~/.config/Cursor/User/globalStorage` on Linux (the same folder of Cursor's user data on macOS and Windows) | `cursor-ide` |

A transcript is read only under its harness's folder, after resolving symlinks: a file outside it, or reached through a symlink that leaves it, is refused. The folder is fixed per harness under your home directory (`$HOME`); for Claude Code `EXPLAIN_PROJECTS_DIR` also moves it. No command-line flag, `--format` included, moves it. A shell call whose output or exit code the harness did not record has an unknown result (every Cursor CLI and Cursor IDE call, an OpenCode call still running): it can back a `mixed` run or a quote, never a `passed` run or a `done`, and the validator says so in one line.

## No transcript

Take this path when the harness has no reader (Windsurf, Cline, Roo, Kiro, Goose, Amp, Aider and any other Agent Skills harness), when the transcript is missing, deleted or unreadable, or when you run the skill outside any agent session. It works for both page kinds, and the scripts check everything they still can.

1. In the doc write `"transcript_unavailable": "<reason>"`: one line of at most 200 characters, with no secret in it (for example `"Windsurf keeps no readable session log"`). Give the reason or the transcript, never both: `validate.py` and `render.py` exit 1 for a doc with neither, and for a doc with both.
2. Take each user request in the user's own words from what you hold in context, and each command and its result from the calls you made. Quote the user's text, not a paraphrase. A quote, a `tool_call` or a `user_reported` source keeps its shape and is not compared with anything.
3. Run validate and render without `--transcript` and without `--no-validate`. The git range, the diff, the +/- counts, the file coverage, every cited code line and every secret are still checked; the quotes and commands are counted as not compared. A credential the user quoted is learned from the doc itself and refused wherever else the doc repeats it.
4. The change page then reads "No session log: <reason>", and each run and each try of the user's carries "From the agent's own account". The session page carries the same note and shows each outward count as the agent's own count, once.

A session doc follows the same four rules: count the turns and the outward actions from your own context. A theme's `change_doc` needs its own `transcript_unavailable`.

Done when each user request has its words in front of you and each claim of "ran X" has the tool call that ran it (with no transcript: the call in your own context).
