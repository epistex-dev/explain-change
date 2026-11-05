# explain-session/1

A session doc sketches a whole session, one task or many, for a reader who cannot follow it all: what was asked, what got done, what waits on the reader, what the agent decided alone, and what left the working copy. It is about the work, not the code: it shows no code, diff or file:line, and it has no risks section and no quiz. A theme that changed code links to its `explain-change/2` page for the detail.

Workflow: `collect.py --session` lists the candidate sessions; `collect.py --session --transcript <file>` prints the digest; write the doc; `validate.py <doc> --transcript <file>` checks it. With no session available, set `"transcript_unavailable": "<reason>"`; the checks that need a session then stay off and `validate.py` prints "transcript checks off". `render.py` does not render this kind yet.

## The digest

`collect.py --session --transcript <file>` streams the main transcript and its workers and prints:

- **User turns**: `[u1 …]`, `[u2 …]`: what the user typed, in order. Compaction summaries, injected context and worker briefs are not turns. A credential shows as `[ẩn]`: quote the words around it.
- **Work between turns**: the tool calls after each turn, by tool, with the first command; one line per worker.
- **Repos touched**: the directory of each git or gh command (`-C`, a `cd` before it, else the working directory of the call), with its first and last turn and its number of calls.
- **Outward actions**: each action with its turn, from calls that succeeded, and totals per kind. A call whose result is an error or starts with `Exit code N` (N above 0) is not counted, and neither is a call that has no result.

Themes are yours to draw: group the turns and the work by what the reader would call it, and name each theme as a reader would ("Config backup"), not by a file or a function.

## Top level

| field | content |
| --- | --- |
| `schema`, `lang` | `"explain-session/1"`, `"vi"` or `"en"` |
| `title`, `summary` | one line; the summary is one sentence |
| `transcript` or `transcript_unavailable` | the session file under `~/.claude/projects` (the `--transcript` flag does the same), or the reason there is none |
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

Rewriting a commit that was never pushed (`git commit --amend`, `git rebase`) stays local and is not counted; the force push that publishes it is.

## Sample

`reference/examples/portal-day.session.json` is a synthetic sample (a made-up web app, no real names) with eight themes in every status except `not_done`; `validate.py` accepts it with transcript checks off.
