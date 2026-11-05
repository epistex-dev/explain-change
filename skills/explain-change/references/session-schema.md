# explain-session/1

A session doc sketches a whole session, one task or many, for a reader who cannot follow it all: what was asked, what got done, what waits on the reader, what the agent decided alone, and what left the working copy. It is about the work, not the code: it shows no code, diff or file:line, and it has no risks section and no quiz. A theme that changed code links to its `explain-change/2` page for the detail.

Workflow: `collect.py --session` lists the candidate sessions; `collect.py --session --transcript <file>` prints the digest; write the doc; `validate.py <doc> --transcript <file>` checks it; `render.py <doc> --transcript <file>` writes the page. With no session available (an unsupported harness, a missing or unreadable file, no agent session at all), set `"transcript_unavailable": "<reason>"` (one line, at most 200 characters, never together with a transcript; a doc with neither is refused); the checks that need a session then stay off and `validate.py` prints "transcript checks off". The schema, theme, order and secret checks still run. The page reads "Not checked against the session: <reason>" and shows each outward count as the agent's own count, once.

## The page

`render.py <doc> [--transcript <file>] [--out <file>] [--text]` validates the doc (the same checks as `validate.py`; nothing is written on a problem) and writes one offline HTML page, `index.html` next to the doc (fonts inlined, under 512 KB), in the language of `lang`. `--no-validate` skips the checks for an archived doc whose session is gone. It prints the page path on its last line.

- **Tier 0, a strip at the top.** The `summary` with one status segment per theme; *Needs you*; *Agent decided for you*, each item marked reversible or not; *Outward actions*, one card per kind. Each block opens with a conclusion line built from the counts.
- **Tier 1, the journey.** One lane per theme, in the doc's order. Its events sit in `(order, list position)` order along a shared time axis, as markers of at least 32 px with at least 8 px between them. A lane with more events than fit shows count bubbles for the crowded stretches. A marker, a bubble or a theme name opens the theme's journey in the side panel (below its lane under 1000 px wide); Escape closes it and puts focus back where it came from. The legend names the seven event kinds.
- **Tier 2, the change page.** A theme with `change_doc` gets an "Open change page" button in its panel. `render.py` renders that `explain-change/2` doc as a sibling page next to the session page (`<change_doc without .json>.html`, with `/` written as `__`) and links to it with that relative name. It is validated unless `--no-validate` is given.
- **What the page leaves out.** Code, diffs, file:line (a line number after a file name is dropped), sources, commands and quotes; there is no risks section and no quiz. Each fact is told in full in one place: an event only in the panel, a *Needs you* or *Decided* item only in its block (the panel links to it), an outward action only as a count on its card.

## The digest

`collect.py --session --transcript <file>` streams the main transcript and its workers and prints:

- **User turns**: `[u1 …]`, `[u2 …]`: what the user typed, in order. Compaction summaries, injected context and worker briefs are not turns. A credential shows as `[ẩn]`: quote the words around it.
- **Work between turns**: the tool calls after each turn, by tool, with the first command; one line per worker.
- **Repos touched**: the directory of each git or gh command (`-C`, a `cd` before it, else the working directory of the call), with its first and last turn and its number of calls. A worktree made by `git [-C <repo>] worktree add <path>` in the transcript counts as `<repo>`, and so does a folder inside it. This reads the command text only: no git runs, and a path that is gone still maps. A worktree made in another session (a delegated worker's) has no `worktree add` here and stays its own entry.
- **Outward actions**: each action with its turn, from calls that succeeded, and totals per kind. A call whose result is an error or starts with `Exit code N` (N above 0) is not counted, and neither is a call that has no result. A delete under `/tmp/` or `$TMPDIR` is scratch (see Outward below): the digest lists real deletes one by one and scratch ones as a single line.

Themes are yours to draw: group the turns and the work by what the reader would call it, and name each theme as a reader would ("Config backup"), not by a file or a function.

## Top level

| field | content |
| --- | --- |
| `schema`, `lang` | `"explain-session/1"`, `"vi"` or `"en"` |
| `title`, `summary` | one line; the summary is one sentence |
| `transcript` or `transcript_unavailable` | the session file under its harness's folder (the `--transcript` flag does the same), or the reason there is none (exactly one of the two) |
| `themes` | `[Theme]`, at least one, in the order the work started |
| `needs_you` | `[{text, theme, source}]`: what only the reader can do. `[]` when nothing |
| `decided` | `[{text, reversible, theme, source}]`: choices the agent made without asking. `reversible` is true or false. `[]` when nothing |
| `outward` | `[Outward]`: one entry per kind. `[]` when nothing left the working copy |

`theme` in `needs_you` and `decided` is a theme `id`; an unknown id fails.

## Theme

```json
{"id": "backup", "title": "Config backup", "status": "done", "outcome": "Your settings are in a private repo.",
 "change_doc": "backup.v2.json", "events": [Event]}
```

- `status`: `done`, `done_by_user` (the reader did the last step), `done_needs_you` (done, and a `needs_you` item points at it), `in_progress`, `not_done`.
- `outcome`: one line.
- `change_doc?`: a relative path, inside the folder of the session doc, to an `explain-change/2` doc for the tier-2 drill-down. `validate.py` reads it and checks its `schema`.
- `events`: at least one.

## Event

```json
{"kind": "outward", "text": "Private repo created", "order": 12, "source": {"kind": "tool_call", "command": "gh repo create …", "excerpt": "Created repository"}}
```

- `kind`: `asked`, `decided`, `redirected`, `blocked`, `done`, `outward`, `in_progress`.
- `text`: one line.
- `order?`: the digest's turn number `u<N>` in which it happened. Within a theme the numbers do not go down, and equal numbers keep the list order. With a transcript, `order` must exist in the session, and for a `user_reported` source it must be a turn where the user typed that quote.
- `source`: one Source or a list.

## Sources and checks

A Source has the shape and the check of schema v2 (`explain-schema.md`, "Sources"). Events, `needs_you` and `decided` accept `transcript`, `user_reported`, `report`, `tool_call`, `url` and `{"inferred": true}`; `code` is not accepted. `validate.py` applies these checks:

- A quote occurs in a message of the user (`user_reported`) or in any message of the session (`transcript`, `report`). A `tool_call` names a command that a Bash call ran and a piece of that same call's result; a command with no printed result needs a `report` or `user_reported` source.
- A `done` event whose `tool_call` sources all ran with an error result fails, unless a `user_reported` or `report` source also backs it.
- Every theme has at least one event; events follow `order`; a `done_needs_you` theme has a `needs_you` item.
- A credential never reaches the doc: a value the session shows, or one that looks like a password, token or key by its label, fails anywhere in the doc, keys included. Error lines hide the value.

## Outward

```json
{"kind": "push", "count": 2, "themes": ["backup", "lib"], "evidence": [{"kind": "tool_call", "command": "git push -u origin main", "excerpt": "set up to track"}]}
```

- `kind`: `repo_created`, `push`, `force_push`, `history_rewrite`, `delete`, `deploy`, `pr`, `message`, `other`. A force push is a `force_push`, not also a `push`.
- `count`: the number of actions of that kind in successful calls. With a transcript the validator recounts and compares: a different number fails, and so does a kind that the session shows and the doc leaves out.
- `scratch?` (a `delete` entry only): how many of the `count` deletes are scratch, that is every target is under `/tmp/` or `$TMPDIR` (a worker's temp dirs). `count` stays the total; the digest prints the line to copy (`delete 60 = 13 real + 47 scratch`). A relative target counts against the directory of the call or of an earlier absolute `cd`; `~`, a `$VAR` (other than a leading `$TMPDIR`), a `..` that climbs out, `/tmp` itself, or a command with a mix of scratch and other targets is real. With a transcript the validator recounts and a different number fails, an omitted one counts as 0. The page shows `count - scratch` real deletes as an outward card and the scratch deletes as one collapsed count line.
- `themes`: every theme listed has an event of kind `outward`.
- `evidence`: at least one Source; a `tool_call` command must be an action of that kind.

The classifier (`scripts/lib/outward.py`) reads a command the way a shell does, so text that only mentions a command (an `echo`, a `grep`, a heredoc, a comment, a commit message) is not an action. It sees `git push` in any form (`-C`, `--force`, `-f`, `--force-with-lease`, `+refspec`, `&&` and `;` chains, `cd x &&`, `bash -c '…'`, `eval`, subshells) and skips `--dry-run` and `-n`. By kind:

- `repo_created`: `gh repo create`.
- `push`, `force_push`: `git push`; a `gh repo create --push` also counts one `push`.
- `history_rewrite`: `git filter-repo`, `git filter-branch`.
- `delete`: `rm -r`, `rmdir`, `find -delete`, `git worktree remove`, `git branch -D`, `git clean` with force, `git push --delete`, `gh repo delete`, `kubectl delete`.
- `deploy`: `vercel`, `fly deploy`, `kubectl apply`, `docker push`, `npm publish` and the other publish and apply commands in `DEPLOY`, `gh release create`.
- `pr`: `gh pr create`, `gh pr merge`.
- `message`: `gh pr comment`, `gh pr review`, `gh issue create`, `gh issue comment`.
- `other`: `gh api` with a method other than GET.

Rewriting a commit that was never pushed (`git commit --amend`, `git rebase`) stays local and is not counted; the force push that publishes it is. `history_rewrite` is only `git filter-repo` and `git filter-branch`: a rewrite that gets published is already a `force_push`, and counting it twice would double-count.

## Sample

`reference/examples/portal-day.session.json` is a synthetic sample (a made-up web app, no real names) with eight themes in every status except `not_done`, and `password-autofill.v2.json` beside it as the change page of its `login` theme; `validate.py` accepts it with transcript checks off, and `render.py --no-validate` renders both pages.
