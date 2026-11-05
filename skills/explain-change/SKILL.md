---
name: explain-change
description: Explain what an agent just changed, as one offline HTML page with a system map, so the user understands the code instead of trusting it. Use after any agent edit, on "giải thích thay đổi", "mình không hiểu code vừa sửa", "explain this change", or when reviewing a diff, commit or PR. Also for "how does X work", "luồng này chạy thế nào": it explains an existing flow of the code, no change needed.
---

You write `explain.json` (schema v2); scripts collect the diff and the session, check every quote, command and cited line, and render the page. The page answers five questions in order: what was asked, where it changed (a map), how the logic changed (before/after pictures), why this way, what was proven. It shows no code, diff or file:line.

Set once, as absolute paths: `S`, the folder of this SKILL.md; `REPO`, the git repo that holds the change (run every command from inside it). Page language is the user's: `vi` by default, `en` supported (`lang`). Offer this skill at the end of a task and run it when the user agrees.

## 1. Collect

```
python3 $S/scripts/collect.py --v2 [<base>..<head> | <commit>] [--path <dir or file>]... [--slug <text>]
```

No argument means uncommitted changes, else the last commit. It prints the changed files per module (the architecture's, or with no `floorplan/architecture.json` one per child directory of the files' common directory), the unchanged neighbours you may draw, `RUN_DIR=…`, and the newest session transcripts recorded for the repo, by harness. Exit 3 means no changes: tell the user and stop. `--path` (repeatable, repo-relative) keeps only the files of the task you explain, so other work in the range never needs a module; `--slug` names the run folder after that task.

Done when you hold `RUN_DIR` and can say which module each changed file belongs to.

## 2. Read the session

A transcript of any harness below grounds the doc. `collect.py` lists the sessions recorded in the repo's folder, labelled by harness; pick the one whose first user message and time span match this task (each harness lists its 3 newest; when none fits, list the harness's folder by time and open the likely files), then rerun with `--transcript <file>` (the digest lists the user's messages, test-like tool calls and worker ids). The format is detected from the file; `--format auto|claude|copilot|codex|opencode|gemini|cursor-cli|cursor-ide` names it. A file in none of these formats exits 1 with one line naming them when it lies outside every folder in the table; a text file inside the Claude Code folder is read as a Claude Code transcript (skipped lines are warned about, exit 0), and a directory exits 2 ("transcript not found"). Open the code behind each module that changed.

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

### No transcript

Take this path when the harness has no reader (Windsurf, Cline, Roo, Kiro, Goose, Amp, Aider and any other Agent Skills harness), when the transcript is missing, deleted or unreadable, or when you run the skill outside any agent session. It works for both page kinds, and the scripts check everything they still can.

1. In the doc write `"transcript_unavailable": "<reason>"`: one line of at most 200 characters, with no secret in it (for example `"Windsurf keeps no readable session log"`). Give the reason or the transcript, never both: `validate.py` and `render.py` exit 1 for a doc with neither, and for a doc with both.
2. Take each user request in the user's own words from what you hold in context, and each command and its result from the calls you made. Quote the user's text, not a paraphrase. A quote, a `tool_call` or a `user_reported` source keeps its shape and is not compared with anything.
3. Run steps 4 and 5 without `--transcript` and without `--no-validate`. The git range, the diff, the +/- counts, the file coverage, every cited code line and every secret are still checked; the quotes and commands are counted as not compared. A credential the user quoted is learned from the doc itself and refused wherever else the doc repeats it.
4. The change page then reads "Not checked against the session: <reason>", and each run and each try of the user's carries "From the agent's own account". The session page carries the same note and shows each outward count as the agent's own count, once.

A session doc follows the same four rules (step 8): count the turns and the outward actions from your own context. A theme's `change_doc` needs its own `transcript_unavailable`.

Done when each user request has its words in front of you and each claim of "ran X" has the tool call that ran it (with no transcript: the call in your own context). Text holding a password or token never goes into the doc, but its other words still can: the digest masks the value as `[ẩn]`, so quote the part before the label or after the value.

## 3. Write explain.json

Fields and rules: [references/explain-schema.md](references/explain-schema.md) ("Schema v2"). Save it as `$RUN_DIR/explain.json`; copy `range` from `summary.json`. Write for the owner who did not write the code: plain words, one name per concept, each block opening with its `conclusions` line.

- **Each fact once**: say each fact in full in one tab and link to it from the others. A request's `result` is the outcome in one short sentence; the detail goes in Logic or Bằng chứng, and `see` (`"logic"` or `"evidence"`) draws the link. `validate.py` warns when a result repeats words from those tabs.
- **Requests**: one per thing the user asked, in their words; `status` by what happened, `result` in one sentence, `see` when the detail sits in another tab.
- **Map**: every changed module with `what_changed`; add the unchanged neighbours the change touches and the outside actors (browser, person, service). Edges follow how data or calls flow.
- **Logic**: `before` and `after` as short steps; give a step a `visual` (a form's rows, a dialog) when a picture says it faster than words. Cases and measured examples come from the evidence.
- **Rationale**: the chosen option and each rejected one, grounded in the words that decided it; `inferred` where nothing grounds it.
- **Evidence**: `ran` from tool calls and the user's own reports; `report` only for a worker's word. Whatever stayed unproven goes in `not_checked`.

Done when each of the five blocks has content and every module in the map has a reason to be there.

## 4. Validate

```
python3 $S/scripts/validate.py $RUN_DIR/explain.json [--transcript <file>]
```

Each problem prints as `path: reason`. Fix the claim itself, not the quote. Done when it prints `ok`. Tell the user the number of worker reports it counts: those items rest on a worker's word.

## 5. Render

```
python3 $S/scripts/render.py $RUN_DIR/explain.json --text [--transcript <file>]
```

Pass `--transcript <file>` when step 2 found one; with none, run it as `render.py $RUN_DIR/explain.json --text` (the doc carries `transcript_unavailable`). `--no-validate` is for an archived doc whose git range is gone. Writes `$RUN_DIR/index.html` (one file, fonts inlined, under 512 KB) and `index.html.txt`, the page's words. Done when it prints the page path.

## 6. Cold-read gate

The reader is fresh: it holds `index.html.txt` and nothing else. Take the first that exists:

1. A new subagent of your harness.
2. The command in env `EXPLAIN_COLDREAD_CMD`: it reads a prompt on stdin and prints its answers on stdout (run it as `sh -c "$EXPLAIN_COLDREAD_CMD" < prompt-file`).
3. Neither: skip the gate and say so in your final reply.

Ask the reader to answer, from the page alone:

1. What did the user ask, and what came of each request?
2. Which parts of the system changed, and which stayed as they were?
3. How did the logic run before, and how does it run now?
4. Why this way, and which options were rejected?
5. What was proven, and what was not?

Compare each answer with the doc. Where one is wrong or empty, the page text is at fault: rewrite that field, rerun steps 4 and 5, and use a new fresh reader. Done when all five answers match the doc, or the gate was skipped under option 3; after 3 rounds without a match, report the gap to the user.

## 7. Show

Give the user the absolute path of `index.html` and the validate counts line. Open it with your harness's HTML preview tool if it has one (the page fits a 512 KB limit). With no such tool, serve `$RUN_DIR` with `python3 -m http.server <free port> --bind 127.0.0.1 --directory $RUN_DIR &`, open `http://127.0.0.1:<port>/index.html` in a browser tab if you can, and name the server's pid and port in your report.

Done when the user holds the path and the page is open, or no preview tool exists and you said so.

## 8. Whole session

When the user wants the context of a whole session or of several tasks, not one change, read [references/session-schema.md](references/session-schema.md) and run:

```
python3 $S/scripts/collect.py --session                         # lists candidate sessions; with none it names the no-transcript path (step 2)
python3 $S/scripts/collect.py --session --transcript <file>     # the digest: numbered turns, work between turns, repos, outward actions
```

Write `session.json` (`explain-session/1`) in a folder of your own (`$RUN_DIR` of any run, or a new one): group the turns and the work into themes a reader would name, give each theme its events with the turn number as `order`, and fill `needs_you`, `decided` and `outward` from the digest (copy its counts, including the `scratch` count of deletes). A theme whose code you explained in a v2 doc gets `change_doc`, a relative path to that doc in the same folder. Ground only what the transcript shows: a delegated worker's own commands are not in it. With no transcript (step 2, "No transcript"), write `"transcript_unavailable": "<reason>"` instead of the transcript, take the turns and the outward actions from your own context (`order` counts your turns from 1) and run the two commands below without `--transcript`.

```
python3 $S/scripts/validate.py session.json --transcript <file>
python3 $S/scripts/render.py session.json --transcript <file> --text
```

With no transcript, drop `--transcript` from both commands.

`render.py` writes `index.html` next to the doc, plus one page per `change_doc`, and prints the page path last. The page shows no code, diff or file:line, and it has no risks and no quiz. Done when `validate.py` prints `ok` and you hold the page path.

`render.py --theme <id>` sets the colour theme a session page or a change page (`explain-change/2`) opens in: `midnight` (the default), `navy`, `ocean`, `plum`, `graphite` or `pearl` (light). An unknown id exits 1 with one line naming the valid ids. The reader can switch the colour scheme with the "Appearance" picker in the page header; the pick is kept in the browser's `localStorage` under one key, so a pick made on a session page also opens its change pages, and the other way round. The flag sets the page's default for a session doc and for the change pages that render with it; the v1 report page ignores it.

Docs with `version` absent or 1 still validate and render with the older report page (`references/explain-schema.md`, top part).

## 9. Explain a flow

Use it when the user asks how existing code works ("how does X work", "luồng này chạy thế nào"), with no change to explain and no agent session to read. The doc is `explain-flow/1` ([references/explain-flow-schema.md](references/explain-flow-schema.md)): the parts of the system, the steps in order with what each takes in and gives back, the branches, and the error exits. Every step and error is tied to lines of the code at one commit. It shows no code, diff or file:line.

1. Collect: `python3 $S/scripts/collect.py --flow [--path <dir or file>]... [--slug <text>]`. It prints the full SHA of HEAD, the modules and the files under each `--path`, and `RUN_DIR=…`. It needs no diff and never exits 3. Commit or stash first: the doc is about HEAD, and a warning says when the working copy differs.
2. Write `$RUN_DIR/flow.json` by reading the code, not from memory: put the user's question in `question` as asked, then every part, step, branch and error, each with the lines you read.
3. Validate: `python3 $S/scripts/validate.py $RUN_DIR/flow.json`. Each source is checked against `git show <commit>:<path>`; fix the claim or the lines until it prints `ok`.
4. Render: `python3 $S/scripts/render.py $RUN_DIR/flow.json --text [--theme <id>]`. It dispatches on `kind`, validates the doc again (a problem prints the lines, writes nothing, exits 1; an unknown `kind` exits 1 with one line), and writes `$RUN_DIR/index.html` and `index.html.txt`: the question and summary, the counts, the numbered route, the map of parts and one panel per step (takes in, gives back, branches, errors). Every step is in the HTML, so print and a browser without JS show the whole flow; `#step-N` opens step N. The footer says which commit it was checked against. `--no-validate` renders an archived doc whose commit is gone, with no footer. Done when it prints the page path; then show it as in section 7.

Cold-read gate for a flow (section 6, same reader choice and the same fix-and-rerun loop): the reader holds only `index.html.txt` and answers these four from the page alone: what the flow does; in what order the steps run and where it branches; what happens when error X occurs; what step N takes in and gives back. Pick X and N yourself, one error from a step with several and a step with a branch. Compare each answer with the doc; where one is wrong, rewrite that field, rerun steps 3 and 4, and use a new fresh reader. Done when all four match.
