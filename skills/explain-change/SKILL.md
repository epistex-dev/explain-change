---
name: explain-change
description: Explain what an agent changed, a whole agent session, or an existing logic flow as one fact-checked offline HTML page with a system map, so the user understands the code instead of trusting it. Claims are checked against the transcript and the code, and secrets are masked. Use after any agent edit, on "explain this change", "giải thích thay đổi", "mình không hiểu code vừa sửa", or when reviewing a diff, commit or PR; on "summarize this session", "tóm tắt phiên này" for a whole session; on "how does X work", "luồng này chạy thế nào" for how existing code runs, no change needed.
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

`collect.py` lists the session transcripts recorded for the repo, labelled by harness. Pick the one whose first user message and time span match this task, then rerun step 1 with `--transcript <file>`: the digest lists the user's messages, test-like tool calls and worker ids. Open the code behind each module that changed.

Read [references/transcripts.md](references/transcripts.md) when no listed session fits, when a script refuses the transcript file, when you need to pass `--format`, or when the harness has no transcript reader (Windsurf, Cline, Roo, Kiro, Goose, Amp, Aider): it holds the harness table (folder and `--format`) and the no-transcript path, where the doc carries `"transcript_unavailable": "<reason>"`.

Done when each user request has its words in front of you and each claim of "ran X" has the tool call that ran it. Text holding a password or token never goes into the doc, but its other words still can: the digest masks the value as `[ẩn]`, so quote the part before the label or after the value.

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

Pass `--transcript <file>` when step 2 found one; with none, run it as `render.py $RUN_DIR/explain.json --text` (the doc carries `transcript_unavailable`). `--no-validate` is for an archived doc whose git range is gone. Writes `$RUN_DIR/index.html` (one file, fonts inlined, under 512 KB) and `index.html.txt`, the page's words. `--theme <id>` sets the colour theme the page opens in: `midnight` (the default), `navy`, `ocean`, `plum`, `graphite` or `pearl` (light); an unknown id exits 1 naming the valid ids. Done when it prints the page path.

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

## 8. Other modes

Each file opens with its full workflow (collect, write, validate, render, show):

- Read [references/session-schema.md](references/session-schema.md) when the user wants the context of a whole session or of several tasks, not one change.
- Read [references/explain-flow-schema.md](references/explain-flow-schema.md) when the user asks how existing code works ("how does X work", "luồng này chạy thế nào"), with no change to explain and no session to read.
