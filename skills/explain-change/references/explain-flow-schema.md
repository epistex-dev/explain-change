# explain-flow/1

Read this when the user asks how existing code works ("how does X work", "luồng này chạy thế nào"), with no change to explain and no agent session to read. Set `S` (the folder of SKILL.md) as in [SKILL.md](../SKILL.md).

## Workflow

1. Collect: `python3 $S/scripts/collect.py --flow [--path <dir or file>]... [--slug <text>]`. It prints the full SHA of HEAD, the modules (`floorplan/architecture.json`, else one per directory) and the files under each `--path`, and `RUN_DIR=…`, and writes `summary.json` there. It needs no diff and never exits 3. Commit or stash first: the doc is about HEAD, and a warning says when the working copy differs.
2. Write `$RUN_DIR/flow.json` by reading the code, not from memory: put the user's question in `question` as asked, then every part, step, branch and error, each with the lines you read. The example `examples/claim-check.flow.json` explains how a claim is checked before the page renders.
3. Validate: `python3 $S/scripts/validate.py $RUN_DIR/flow.json`. Each source is checked against `git show <commit>:<path>`; fix the claim or the lines until it prints `ok`.
4. Render: `python3 $S/scripts/render.py $RUN_DIR/flow.json --text [--theme <id>]` (themes as in [session-schema.md](session-schema.md)). It dispatches on `kind`, validates the doc again (a problem prints the lines, writes nothing, exits 1; an unknown `kind` exits 1 with one line), and writes `$RUN_DIR/index.html` and `index.html.txt`. Every step is in the HTML, so print and a browser without JS show the whole flow; `#step-N` opens step N. The footer says which commit it was checked against. `--no-validate` renders an archived doc whose commit is gone, with no footer.
5. Cold-read gate: same reader choice, same fix-and-rerun loop as step 6 of SKILL.md. The reader holds only `index.html.txt` and answers these four from the page alone: what the flow does; in what order the steps run and where it branches; what happens when error X occurs; what step N takes in and gives back. Pick X and N yourself, one error from a step with several and a step with a branch. Compare each answer with the doc; where one is wrong, rewrite that field, rerun steps 3 and 4, and use a new fresh reader. Done when all four match.
6. Show the page as in step 7 of SKILL.md.

## What a flow doc is

A flow doc explains how an existing piece of code runs, for a reader who did not write it: what the parts of the system are, the steps in order, what each step takes in and gives back, where the flow branches, and what happens when it goes wrong. It needs no diff and no agent session. It is about the code at one commit: it shows no code, diff or file:line, but every step and every error is tied to the lines it was read from, and `validate.py` reads those lines.

## Top level

| field | content |
| --- | --- |
| `kind` | `"explain-flow/1"` |
| `lang` | `"vi"` (default when absent) or `"en"` |
| `title` | the flow, in one line |
| `question` | the user's question in their words, shown as asked |
| `summary` | one paragraph; the conclusion comes first |
| `commit` | the full SHA (40 hex characters) the doc was written against; every source is read from it |
| `parts` | `[Part]`, at least one |
| `steps` | `[Step]`, in order, at least one |

## Part

```json
{"id": "checker", "name": "Doc checker", "where": "inside", "role": "Reads the doc and decides ok or rejected.", "sources": [Source]}
```

- `where`: `inside` (code of this repo) or `outside` (an actor or store the repo does not hold: a person, an agent, a log file).
- `icon` (optional): the glyph on the part's card, one of `arrow-right`, `ban`, `branch`, `bug`, `circle-check`, `circle-dashed`, `circle-help`, `circle-x`, `database`, `file-code`, `file-search`, `flask-conical`, `globe`, `history`, `key-round`, `layout`, `list`, `map`, `message`, `monitor`, `panel-right`, `panel-right-close`, `plus`, `redirect`, `server`, `shield-check`, `sparkles`, `trash`, `triangle-alert`, `undo`, `upload`, `user`, `x`. Without it the card shows a generic glyph (a globe outside, a file inside). Pick one that says what the part is: `sparkles` an agent, `user` a person, `shield-check` a checker, `file-search` a reader, `database` a log or store, `key-round` a secret, `monitor` a screen or page.
- `role`: one sentence.
- `sources`: at least 1 for an `inside` part; `[]` is allowed for an `outside` one.

## Step

```json
{"id": "s2", "name": "Judge it", "part": "checker", "takes_in": "The text.", "gives_back": "A yes, or an error.",
 "sources": [Source],
 "branches": [{"when": "The text is empty", "to": "problems"}, {"when": "It has content", "to": "s3"}],
 "errors": [{"id": "e1", "name": "Empty document", "result": "The check stops with an error.", "sources": [Source]}]}
```

- `part`: the `id` of a part. `takes_in` and `gives_back`: plain words, what goes into the step and what comes out.
- `sources`: at least 1.
- `branches`: the exits of the step, each `{when, to}`. `to` is a step `id`, `"problems"` (the flow ends in the list of problems) or `"end"` (the flow ends well). A step with no `branches` goes to the next step in the list, and the last one to `"end"`. A step with `branches` leaves by them alone, so list the ordinary way on too.
- `reads` (optional): the ids of other parts the step takes its input from, such as a log or a store that is not a step of its own. The map draws a line from each of them to the step's part. Not the step's own part, no duplicates.
- `errors`: what can go wrong in the step, each `{id, name, result, sources}` with at least 1 source. `result` says what the reader sees.

## Source

```json
{"path": "scripts/lib/ground.py", "lines": [135, 136], "excerpt": "too short to ground anything"}
```

`validate.py` reads the file with `git show <commit>:<path>`, never from the working copy:

- `path` is repo-relative, with `/`: no absolute path, no `..`. It must exist at the commit as a file; a symlink or a folder in the tree is refused, and so is a binary or non-UTF-8 file.
- `lines` is `[first, last]` with `1 <= first <= last <=` the number of lines of the file, and a span of at most 80 lines.
- `excerpt` is text copied from those lines. Whitespace is squeezed before the comparison; it must be 8 to 300 characters long and occur inside the span.

## Checks

`validate.py` prints one `path: reason` line per problem, all together (exit 1), or `ok` and a counts line (exit 0).

- **Ids** are unique across parts, steps and errors, 1 to 40 letters, digits, `-` or `_`; `end` and `problems` are reserved.
- **References** resolve: each `part` to a part, each `to` to a step, `"problems"` or `"end"`, each `reads` entry to a part, each `icon` to a name above.
- **Types**: a field of the wrong type (a list or an object where an id or text goes, a number, null) is one `path: reason` line, never a crash. Text that cannot be written as UTF-8 (a lone surrogate such as `\ud800`) is refused in a visible field and in a source path.
- **Graph**: every step is reachable from the first one, and some reachable step leads to `"end"`. A loop is fine as long as the flow can leave it.
- **Visible text** (`title`, `summary`, `name`, `role`, `takes_in`, `gives_back`, `when`, `result`) holds no code, by one rule for every field. Refused: a backtick, braces or brackets, an operator or assignment (`=`, `==`, `+=`, `=>`, `->`, `::`, `&&`, `||`, or `<` / `>` between two words), a statement (`return x`, `lambda x: ...`, a text that ends in `:` or `;`), a call such as `run()` or `foo(bar)`, a member such as `doc.text`, a snake_case name such as `user_id`, a tag, and a file with a line number (`file.py:12`). Prose passes: "e.g.", "claim(s)", "$5.50", "v1.2.3", "CI/CD", "A → B", a colon or semicolon inside a sentence, and a bare file, product or domain name such as `README.md`, `Node.js` or `example.com` (a name that ends in a file extension or a domain suffix; a member such as `doc.text` does not). These fields and `question` also hold no password, token or key; the error line never shows the value. `question` is the user's own words, so only the secret check applies to it.
- **commit** must be a full SHA that exists in the repo (`--repo`, else the repo of the doc).

## What the page draws

The lines of the map come from the doc: consecutive steps in different parts, and the `branches` of a step, give a line from the earlier part to the later one (or to the problem list or the happy end); `reads` gives a line from the part read to the part of the step. Two parts that hand over to each other share one line with a head at both ends. A line is routed around the cards. Where lines are hidden (under 1100 px, print, no script) each card carries a one-line "hands over to" list of the same targets.

The map comes from `parts` (`where` picks the zone, `role` the line under the name) and the steps grouped by `part`; the route is `steps` in order, one panel each with `takes_in`, `gives_back`, `branches` and `errors`. Counts: steps, branch points (steps with `branches`), error exits, parts. Each concept has one name on the page, in both languages: error exit (the chip, the panel heading and the E-numbered cards), branch point (the chip and the panel heading), part (the chip and the legend), problem list (the end mark and the legend). `sources`, `commit` and `excerpt` are for the checker, not the page.
