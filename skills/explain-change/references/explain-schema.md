# explain.json

Schema v1 (`version` absent or 1) is described first; schema v2 (`version: 2`, the five-block page of layout 2) starts at "Schema v2" below. The `version` field picks the rules.

`validate.py` enforces everything below and prints `path: reason` for each violation. All text fields are plain strings; `` `code` `` in a text field renders as code. Text is in the page language (`lang`).

## Ref (a grounded claim)

```json
{"file": "app/Services/AttachmentCleanup.php", "line": 31, "snippet": "->limit($limit)->pluck('id')"}
```

- `snippet` is copied from the code (indentation and whitespace are ignored; several lines allowed; at least 4 characters) and must occur within 3 lines of `line`.
- It is checked against the head version; a deleted file is checked against the base version. `"side": "base"` checks a line that the change removed from a file that still exists.
- `"inferred": true` replaces `snippet` for a claim with no matching line. It renders "suy luận" and is rejected where a verified ref is required (`trace.origin.cite`).
- A verified ref renders "đã xác minh"; the reader clicks `file:line` to see the snippet.

## Top level

| field | content |
| --- | --- |
| `schema` | `"explain-change/1"` |
| `lang` | `"vi"` or `"en"` |
| `title` | what the change does, one line |
| `range` | `{base, head, label}` copied from `summary.json` `range` |
| `why` | `{conclusion, lines: [2 to 5 strings], refs: [Ref, ...]}` |
| `changes` | `{conclusion, items: [{id, title, summary, files: [path, ...], refs: [Ref, ...]}]}` |
| `flows` | `{conclusion, items: [Flow], none_reason?}` |
| `logic` | `{conclusion, items: [Logic], skipped?: [{file, function, reason}], none_reason?}` |
| `risks` | `{conclusion, items: [{kind: "break" or "similar", text, refs}]}` |
| `quiz` | `{items: [{q, a, refs}]}`, 2 or 3 items |

Every `conclusion` opens its section and answers it in one or two sentences. An empty `items` needs `none_reason`.

`changes.items[].files` lists each changed file once across all items; +/- counts come from git.

## Flow (sequence diagram)

```json
{"id": "f1", "title": "...", "summary": "...",
 "actors": [{"id": "cli", "label": "php artisan attachments:cleanup"}, {"id": "svc", "label": "AttachmentCleanup::run"}],
 "steps": [{"from": "cli", "to": "svc", "label": "run(dryRun, limit=100)", "kind": "call", "changed": false, "ref": {...}}]}
```

Every `actors[].id` and `changes.items[].id` is required, a non-empty string. `kind` is `call` (default), `return` or `async`. At least one step has `changed: true`; changed steps render highlighted. Every step has a `ref`.

## Logic (one changed function)

Common fields: `id` (required, unique non-empty string: it is the page anchor), `file, function` (the name `collect.py` printed), `title, summary, refs`, `kind`, and `change` (id of the sub-change it deepens; the page links both ways).

`kind: "flowchart"` (3 or more branches, counted as outgoing edges of `decision` nodes):

```json
"flow": {"nodes": [{"id": "n1", "label": "limit reached?", "type": "decision", "changed": true}],
         "edges": [{"from": "n1", "to": "n2", "label": "yes", "ref": {...}}]}
```

Node `type`: `start`, `step`, `decision`, `end`. Every edge has a `ref`. Draw one pass: no edge returns to an earlier node (a loop body ends in an `end` node that says "next item"); the validator rejects cycles.

`kind: "trace"` (a worked example with concrete values):

```json
"trace": {"input": [{"name": "limit", "value": "2"}],
          "steps": [{"text": "orders the ids, keeps the first 2", "value": "[11, 12]", "ref": {...}}],
          "result": "2 files deleted, 1 left for the next run",
          "origin": {"kind": "test", "cite": {...}}}
```

`origin.kind`: `test`, `fixture` or `seed` need `cite` (a verified Ref where the values come from); `run` needs `command` and `output` (what you ran and printed); `illustrative` renders "minh hoạ" for values you made up.

## Coverage

A changed non-test function with 2 or more branches (listed by `collect.py`) needs a Logic item with the same `file` and `function`, or an entry in `logic.skipped` with a reason.


# Schema v2

`"schema": "explain-change/2", "version": 2`. A page answers five questions in order, one block each: what was asked (`requests`), where it happened (`map`), how the logic changed (`logic`), why this way (`rationale`), what was proven (`evidence`). Every fact is tied to the diff, the code, the architecture file or the session transcript. A fact with no tie is labelled `inferred` and renders "suy luận". The page shows prose, diagrams and quotes; refs, commands and excerpts stay in the doc for `validate.py`.

Workflow: `collect.py --v2` (add `--transcript <file>` once you know the session) prints the modules and the transcript digest, then `validate.py explain.json --transcript <file>` checks the doc. The doc may carry `"transcript": "<path>"` instead of the flag. A path outside `~/.claude/projects` is refused. With no session available (an unsupported harness, a missing or unreadable file, no agent session at all), set `"transcript_unavailable": "<reason>"`: one line of at most 200 characters, never together with a transcript (the validator refuses the pair, and the lack of both). The git, count, file-coverage, code-line and secret checks still run; quotes and commands are not compared (the validator warns and counts them), and the page reads "Not checked against the session: <reason>" with each run marked as the agent's own account.

## Top level

| field | content |
| --- | --- |
| `schema`, `version`, `lang` | `"explain-change/2"`, `2`, `"vi"` or `"en"` |
| `title`, `subtitle?` | what the change does, one line |
| `range` | `{base, head, label}` copied from `summary.json` |
| `conclusions` | `{requests, map, logic, rationale, evidence}`: one or two sentences each; each opens its block |
| `verdict?` | derived, so leave it out. Written, it must equal the derivation below |
| `requests` | `[Request]`, at least one |
| `map` | `{modules: [Module], edges?: [Edge]}` |
| `logic` | `{before: [Step], after: [Step], before_title?, after_title?, before_none_reason?, cases?: [Case], examples?: [Example]}` |
| `rationale` | `{chosen: Item, rejected: [RejectedItem], tradeoff?: Item, notes?: [Item]}` |
| `evidence` | `{ran: [Ran], not_checked: [{what, why?, modules?}]}` |

`modules` (a list of module ids from `map.modules`) may sit on any item to link it to the map; an unknown id fails.

**Verdict** (header pill, computed): `requests.done` counts `done` and `done_after_fix`; `requests.total` counts every status except `changed`; `tests_passed` is true when `evidence.ran` has a `passed` item and no `failed` item; `caveats` counts `mixed` items.

## Sources

A `Source` ties one claim to its origin. Each block accepts the kinds in its row.

| kind | shape | checked as |
| --- | --- | --- |
| `transcript` | `{kind, quote, transcript?}` | `quote` occurs in one message of any role (user, assistant, tool result, worker report) |
| `user_reported` | `{kind, quote}` | `quote` occurs in a message the user typed (main transcript) |
| `report` | `{kind, quote, transcript?}` | `quote` occurs in a worker report or assistant text. A worker's word, not tool output: the validator counts these (in a request, a rationale item or a run alike) and `validate.py` prints the count; tell the user |
| `tool_call` | `{kind, command, excerpt, transcript?}` | `command` occurs in a tool call and `excerpt` in the result of that same call |
| `code` | `{kind, ref: Ref}` | the Ref rules above |
| `url` | `{kind, url}` | the URL occurs in a message, or in a Bash command, or in the `url`, `urls` (a string or a list) or `query` of a fetch, search or preview tool call (`WebFetch`, `web_fetch`, `web_search`, `preview_navigate`, `preview_open`) |
| inferred | `{"inferred": true}` | not checked; flagged |

Quotes and excerpts are pieces of the original text (whitespace collapsed, Unicode NFC, case-sensitive, at least 4 characters); copy a short distinctive piece. `transcript` is `"main"` (default) or a worker id such as `"agent-a1b2c3"`; the digest prints the ids and which one ran each command. User messages exist only in main: a worker's "user" message is a brief from the agent that launched it.

| block | accepted |
| --- | --- |
| Request `source?` | transcript, report, tool_call, code |
| Step, Case | `refs`, or `source`: transcript, code, url; or inferred |
| Example | `evidence_id`, or `source`: tool_call, transcript, code; or inferred |
| Rationale items | `source`: transcript, report, code, url; or inferred |
| Ran `source` | tool_call, user_reported, report (an object or a list); never inferred |

An item that needs grounding carries exactly one of `refs` (a list of Ref), `source` (one Source or a list), `inferred: true`, `evidence_id`. A `refs` or `code` Ref on a `before` step is read at the base commit; elsewhere at the head commit; `"side"` overrides.

## Request

```json
{"quote": "open a PR for the fix", "status": "done", "result": "The PR is open against main.", "see?": "logic" | "evidence", "note?": "...", "modules?": ["web.admin"], "source?": Source}
```

**Each fact appears in full in one tab, and the other tabs link to it.** A request `result` is one short sentence about the outcome. The detail (how the code runs, which command passed and its numbers) lives in `logic` or `evidence` only. When a request has such detail, set `see` to the tab that holds it: the page draws a link "Chi tiết ở tab Logic" or "Chi tiết ở tab Bằng chứng" under the row. `validate.py` warns when a `result` repeats a long run of words (`DUP_RUN`) from a logic or evidence item, or runs past `MAX_RESULT` characters: cut it to the outcome and keep the words in the other tab.

`quote` is the user's own words, a piece of one message that the user typed. `status`: `done`, `done_after_fix` (needs `note`: what failed first), `not_done`, `changed` (needs `note`: how the user redirected; leaves the verdict total). `result` says what happened in one sentence.

## Map

Module ids come from `floorplan/architecture.json`, found at the repo root or up to 2 parents. `collect.py --v2` lists them with the files each changed module owns. Without that file the ids come from the directory rule below; `collect.py --v2` and `validate.py` run the same function (`arch.fallback_modules`), so the ids match.

**Directory rule (no architecture).** Take the deepest common directory of the in-scope changed files (the root). One module per child directory below it: the first path segment under the root; files directly in the root are module `.`. A module that would hold more than 60% of the files is split by its own child directories (files directly in it stay as the module itself), again and again, until 3 to 8 modules result or nothing can be split. A split-off single file joins the nearest module above it; with more than 8 modules the smallest merge into the nearest module above them. Ids are paths relative to the root, so they are the same on every run; a single-file change gives one module (`.`). Give each a `name` and `summary`.

**Legacy docs (no architecture).** Before this rule, a module was a file's top directory of the repo (`.` for a file at the repo root), so an older v2 doc has ids such as `skills`, `agents`, `.`. The validator (and so `render.py`, which validates first) still accepts such a doc through one function, `arch.accept_legacy`, when the doc does not fit the rule above and fits the legacy top-directory rule: every file it lists sits in its top directory's module, every changed module id is a top directory the files give, and every module id (an unchanged neighbour too) is a single directory name that exists at head, or `.`. A doc that mixes the two (some ids from each rule) fits neither and fails with the usual `is not a module of the directory map` / `belongs to module` lines. New docs use the rule above. The `summary.json` of a run made by the old `collect.py --v2` keeps its old ids; collect does not rewrite it, and a doc that follows those ids is judged by the legacy rule.

**Scope.** `collect.py --path <dir or file>` (repeatable, repo-relative; a leading `-`, `.` and anything outside the repo are refused) limits the diff, the map and the validator to those paths and stores them in `summary.json`; `validate.py` reads that scope from the run folder and wants only in-scope files on the map. Use it for files that belong to another task: they never need a module.

```json
{"id": "fe.auth", "changed": true, "what_changed": "...", "files": [{"path": "src/a.jsx", "add": 2, "del": 0}]}
{"id": "fe.api", "changed": false}
{"id": "chrome", "name": "Chrome", "summary": "...", "outside": true, "changed": false}
```

- Every changed file belongs to exactly one changed module: the one the architecture globs give it (deepest node, then longer literal prefix, then first declared; `validate.py` warns about ties). `add`/`del` equal git.
- `name`, `summary`, `kind` and the group come from the architecture; omit them. Without an architecture a module needs `name` and `summary`.
- A file the architecture does not claim goes to module `_other` (give it a `name`). A file on the architecture's `ignore` list is also `_other`. `_other` is allowed only with an architecture: without one the validator rejects it and the files outside the change are left off the map with `--path` instead.
- An unchanged neighbour has `changed: false` and no files. An outside actor (a browser, a person, a service outside the repo) has `outside: true` plus `name` and `summary`; its id must not be an architecture id.
- `edges`: `{from, to, kind, label?}`; `kind` is `arch` (the architecture file has that edge), `flow` or `tests`.
- `hidden_count` is derived by the renderer (see "Page rules"); it is not a doc field.

## Logic

`before` and `after` are lists of Steps (each at least one; `before` may be empty with `before_none_reason` for new code).

```json
{"label": "<= 60 characters", "text": "...", "modules?": [...], "visual?": Visual, "refs" | "source" | "inferred": ...}
```

`visual`: `{"kind": "form", "rows": [{label, value, state?}]}` or `{"kind": "dialog", "tone": "bad" | "good", "title": "...", "subtitle?": "..."}`. `cases`: `[{title, text, modules?, + grounding}]` for the branches of the new behaviour. `examples`: `[{text, modules?, + grounding}]`, concrete values that were measured; cite the run with `evidence_id` (an `evidence.ran[].id`) or a Source, or mark `inferred`.

## Rationale

`chosen: {text, modules?, + grounding}`; `rejected: [{option, why_not, modules?, + grounding}]` (the list may be empty); `tradeoff?` and `notes?` share the `chosen` shape. Ground a decision in the words that made it (a transcript quote), in code, or in a document URL; with no such source, write `inferred`.

**Secrets.** A password, token or key never goes into the doc, in any field, snippets included. `validate.py` learns the values typed in the session (the strings after a label such as `password:` or `Pass chung:`, and `glpat-`, `ghp_`, `sk-` or `Bearer` tokens, in user messages and tool-call inputs of the main and worker transcripts) and rejects any doc string that contains one, with or without its label. A label followed by a value in text is rejected too; a code line in a `refs[].snippet` such as `password: z.string().min(8)` is not (an identifier, member expression, call or index after a label is code, not a credential). A message that holds a secret is still quotable: the digest shows it with the value as `[ẩn]`, so quote the words before the label or after the value and leave the label and the value out.

## Evidence

```json
{"id?": "e1", "what": "...", "result": "passed" | "failed" | "mixed", "detail": "...", "modules?": [...], "source": Source | [Source]}
```

`detail` states what the source shows. A number in `detail` that no cited excerpt contains draws a warning. `not_checked` lists what stays unproven, each with `why` when known.

## Page rules (renderer)

`render.py` draws the layout-2 page from a v2 doc: the map is the centre, a side panel holds the other four blocks as tabs, and each block opens with its `conclusions` text. Refs, commands and excerpts never reach the page; backticks in text are dropped, the words stay. Every string is escaped.

- **Edges** are routed in the gutters between boxes (`assets/ui/route.js`): a run keeps 6 px off every zone side and zone title, runs of different edges on shared ground are at least 8 px apart (two edges that leave one port share their first stretch), and an arch label sits on, or beside, a free run.
- **Map layout** is automatic: a zone per top-level architecture node (outside actors in one dashed zone), columns in flow order, tests under the outside actors. Changed modules glow and show `what_changed` and their files with +/- counts (at most 4 file rows, the biggest change first, then a "+N file" line; the node's tag keeps the full count); unchanged ones show the architecture summary. Plan for 1 to about 12 listed modules.
- A `flow` edge between changed modules, or from an outside actor into a changed module, is drawn magenta; `tests` edges are dashed. Edge labels show on the map only for `arch` edges (the architecture's own label is used when the doc has none); a flow label appears in the card of the selected module.
- `hidden_count` is derived: architecture nodes minus listed modules that are architecture nodes (an outside actor or `_other` never is). It renders as "+N phần không liên quan"; with no architecture it is 0 and shows nothing.
- An item tied to modules (`modules`) shows when one of them is selected on the map; an item with none shows only in the full view. A step needs both `label` and `text`: the label is the step's title on the page.
- `inferred` items (and steps, cases, examples, rejected options, notes) carry a "Suy luận" chip. An `evidence.ran` item whose sources are all `report` is labelled a worker's report and counted in the Bằng chứng tab; one with any tool call or user quote is not.
- An example's `evidence_id` links to that run; the run is highlighted.
- Archived docs: `render.py --no-validate --arch <architecture.json>` renders without git or transcript and marks the page `validated=no`. `--text` writes the page's words for the cold-read gate.

