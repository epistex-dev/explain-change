---
name: explain-change page
mode: read
page-type: Report page for one finished agent task (map-centred layout)
family: Premium dark / Technical (dark indigo, magenta accent)
stack: static HTML + CSS variables, inline SVG (Lucide, ISC), Inter + JetBrains Mono woff2 inlined, no framework
colors:
  bg: "#0c1030 -> #141945 -> #1e1f4a (+ magenta bloom top-left, blue bloom bottom-right, dot grid)"
  surface: "rgba(24,31,81,.72) over ground (= #181f51), raised #1c236b, highlight #383471"
  text: "#f5f6ff"
  text-secondary: "#cdd1f3 (text-3 #a3abe0, muted #8f98d6)"
  border: "rgba(150,175,255,.22) ring (strong .42)"
  accent: "#bb3e95 fill, #d357b0 bar/glow, #f08ad0 text"
  success: "#228163 fill (white 4.79:1), #5fd9ae text"
  warn: "#f5c26b"
  danger: "#ff8a9a"
typography:
  display: "Inter, system-ui, sans-serif (h1 24/600/-0.025em)"
  body: "Inter, 13.5px / 1.5; JetBrains Mono only for module/file labels on the map"
  scale: [12, 13.5, 16, 24]
spacing-base: 4
radius: { control: 12, card: 20, panel: 24, pill: 999 }
depth: ring-shadow (1px light-blue ring + soft layered shadow, backdrop-blur 14px on floating surfaces)
motion:
  ease-out: "cubic-bezier(.16,1,.3,1)"
  durations: { press: 160, menu: 240, overlay: 420 }
---

# explain-change page design

Design tokens live in `reference/ui/theme.css`; the renderer carries the same values in `assets/ui/page2.css`. Contrast numbers are in that file's comments.

## Brief
| Item | Value |
| --- | --- |
| Subject | The page the repo owner reads after an agent finishes a task, so they understand what changed instead of trusting it |
| Primary action | Understand the change in about a minute by reading five blocks |
| Blocks | Request and result; Where it changed (system map); How the new logic runs (before and after); Why this way (chosen and rejected options, "inferred" where nothing grounds a claim); Evidence checked |
| Left out | Risks, remaining work, quizzes, code, diffs, file:line chips |
| Audience and device | The repo owner, desktop first, must still work at 800 and 390 px |
| Color tone | Dark indigo gradient with a dot pattern, translucent rounded panels, thin light-blue rings, magenta accent, green for the positive action |
| Page language | `vi` or `en`, set by the doc's `lang` |
| Dark or light | Dark only |

## Direction
A calm, night-time reading room for a short report: an indigo ground and translucent panels so the blocks read as one family. Magenta marks only what changed or what to look at (changed map nodes, the chosen option's bar); green means done or passed. Signature element: the system map, where changed parts glow magenta and untouched parts recede.

## Components
- Header: 64 px fixed, translucent with blur; logo chip, title, verdict pills, panel button.
- Block card: radius 20, padding 16, ring and shadow; header is an icon chip plus the block name, then a conclusion heading (16/600).
- Status tag: pill 12/600, always an icon and a word (done, done after a fix, not done, redirected, passed, failed, inferred).
- Map node: radius 16, kind dot and icon chip. Changed means magenta ring, glow and a "Changed" tag; unchanged is dimmed with an "Unchanged" tag.
- Primary button: green fill `#228163`, white text, one per view.
- Icons: Lucide (ISC), inlined as an SVG sprite. Fonts: Inter (Latin and Vietnamese subsets) and JetBrains Mono (Latin), inlined. Licences are in `assets/ui/LICENSES.txt`.

## Decisions
| Decision | Rationale |
| --- | --- |
| Inter ships with a Vietnamese subset | the stock Latin file lacks U+1EA0-1EF9; without it every tone-marked letter falls back to a system font |
| JetBrains Mono for map labels only | labels are file and module names; copy stays in Inter |
| Ring and shadow instead of solid borders | thin light-blue edges on translucent panels read as one surface |
| Magenta = changed or look here, green = done or passed, amber = partial, red = not done; each paired with an icon and a word | one meaning per colour; colour is never the only signal |
| `muted` text never sits on the highlighted card (4.0:1 there); `text-3` (5.0:1) does | keeps body text at 4.5:1 or better |
| Each fact in full in one tab, linked from the others | content-structure rule: each section answers its own question and no fact repeats. A request row is a short outcome with a `see` link; `validate.py` warns when a result is over 160 characters or repeats 6 words in a row of a logic or evidence item |
| Entrance animation starts at opacity .5, with no stagger delay; motion is transform and opacity only and drops to none under `prefers-reduced-motion` | a tab that is not painting (a background preview) would otherwise freeze the page invisible |
| The map is the centre; the side panel holds the other four blocks as tabs | the map answers "where"; a fifth tab would repeat it |
| Clicking a node filters every tab to items tagged with it; the selection lives in the URL hash (`#tab=logic&node=<id>`) | a reader can share or reload a filtered view |
| Under 1000 px the panel becomes a bottom sheet, and a sticky filter line names the selected node with a "show all" control | the sheet hides the map, and a filtered list must say it is filtered |

## Map layout (`scripts/lib/page2.py`, `assets/ui/`)
| Decision | Rationale |
| --- | --- |
| Layout is generic: a zone per top-level architecture node, outside actors in one dashed zone, at most 3 columns by longest-path layering of zone edges (back edges dropped by DFS from the outside actors); test zones sit under the outside zone | real docs list 1 to about 12 modules of any shape |
| Changed modules come first inside a zone; a zone with 3 or more nodes uses 2 columns | keeps glowing nodes at the top-left of each zone |
| Container queries on the map: 960 px and wider shows all zones, 641 to 960 stacks zones, up to 640 uses one column with edges hidden | the 360 px panel changes the map width at any viewport |
| A flow edge is lit (magenta) only when it touches a changed module and both ends are changed or outside; tests edges are dashed; only `arch` edge labels sit on the map and flow labels show in the selected node's card | flow labels overlapped node text |
| A node shows at most 4 file rows (largest add+del first), then a "+N files" line; the badge keeps the full count | a node with 10 files made the map taller than the screen |
| File names wrap only after `-`, `_`, `.`, `=` or `/` (`<wbr>`) | names were cut in the middle of a word |
| `hidden_count` is derived: architecture nodes minus listed modules that are architecture nodes; shown as "+N unrelated parts" | the map may omit unrelated parts without hiding that they exist |
| A run whose sources are all `report` is labelled as a worker's report and counted in the Evidence summary | a worker's word is not tool output |
| `--no-validate --arch FILE` renders an archived doc and writes `validated=no` into the page | with no git or transcript to check against, the page says so |
| A badge says the doc was not checked against the session when it has `transcript_unavailable` | quotes and commands were never verified |

## Edge router (`assets/ui/route.js`)
Edges are orthogonal routes through the gutters. The router is pure (boxes in, polylines out): a Dijkstra over a sparse grid of box centres and gap midpoints, ports on the middle of a box side, a penalty per bend and per reused step. It is tested under node on modelled layouts and on box rectangles recorded from real pages (`tests/fixtures/geometry-*.json`), without a browser.

| Decision | Rationale |
| --- | --- |
| Boxes and zone titles are obstacles; an edge with no free route is not drawn; the arrowhead sits at the target | straight lines passed behind unrelated boxes |
| A run keeps 6 px off every zone side and title; runs of different edges on shared ground end up 8 px apart (two edges that leave one port share their first stretch) | edges ran 2 px from a zone side or from each other |
| A turn back on an axis costs `REVERSE = 250` in the search state (vertex, direction, last horizontal sense, last vertical sense) | on 400 random layouts, routes turning against their own direction fell from 41 to 24 of 1865 with no growth in total length |
| Labels go on a horizontal run, then above or below it, then beside a vertical one; ground crossed by another edge or a zone side costs extra; none fits at 800 px, so none is drawn | a label over a node is worse than no label |
| Known limit: an edge may run just under a zone title (7 px) when that is the only short route to a top port | forbidding the strip made the edge circle the whole zone in six bends |

## Collection and validation
| Decision | Rationale |
| --- | --- |
| With no architecture, `arch.fallback_modules` gives the modules, as one rule shared by `collect.py --v2` and the validator: root is the deepest common directory of the in-scope files; one module per child directory; a module over 60% of the files is split by its children until 3 to 8 modules remain; a split-off single file joins the nearest module above | piling most files into one node listed dozens of names |
| `collect.py --path` (repeatable, repo-relative) limits diff, patch, log, functions, map and validator; the scope is stored in `summary.json`. A leading `-`, `.`, control characters and anything outside the repo are refused; paths follow `--` as `:(literal)` pathspecs | other sessions commit into the same range, and their files need no module |
| A doc that fails the directory rule is checked against the legacy top-directory rule (`arch.accept_legacy`); a mix of the two fits neither | older docs keep validating |
| Run folder name: `--slug` first, else the most common commit subject among the range's commits that touch the scope | the last commit's subject can belong to another session |
| The digest fills strong runs (a runner such as pytest, vitest, unittest, `make test`) first, then other mentions, then inline scripts; runs are listed by time | the useful lines are the test runs, not the heredocs |
| A credential is hidden by its value, not only by its label: `transcript.learn()` collects the values after a label (`password:`, `glpat-`, `ghp_`, `sk-`, `Bearer`) from user messages, tool-call inputs, results and reports of the main and worker transcripts; `validate.py` rejects any doc string containing one and `redact()` removes it from page text, error lines and the digest | a session repeats a value many times, mostly with no label |
| A value that is code (an identifier, member expression, call or index such as `z.string().min(8)` or `process.env.X`) is never learned or flagged; a bare word with a digit (`Abc12345`) still is | a rule that flags code shapes would reject the diffs the page exists to explain |
| Known limit: a regex fragment or a synthetic test password in a command is still learned | no shape tells it from a credential; masking it hides test text only |
| `url` sources count the `url`, `urls` and `query` of fetch, search and preview tools | the agent reads pages through those tools |
| A user message holding a credential shows in the digest with the value as `[ẩn]` | the agent can still quote the words around it |

## Session page (`explain-session/1`: `scripts/lib/page_session.py`, `assets/ui/session.{css,js}`, `assets/ui/fit.js`)

Case: Extend. The project has a page, `page2.css` carries its tokens, and the request adds a second page that shares them. Reference: the approved mockup `design/mockups/session-mode/2-swimlanes.html` (commit `d0928e5`, branch `mockups/session-mode`) with its `NOTES.md` and `session.css`. The mockup's markers were too small, so the build enlarges them. No web survey was made: the mockup and the existing page answered every gap.

| Item | Value |
| --- | --- |
| Subject | The owner reads one page after a whole session, one task or many, and gets the context without reading the code |
| Primary action | Know in about a minute what is done, what waits on you, what the agent chose alone and what left the working copy |
| Tiers | 0: a strip (summary with per-theme status segments, Needs you, Agent decided for you, Outward actions). 1: one lane per theme and a side panel. 2: an "Open change page" button when the theme has a `change_doc` |
| Left out | Code, diffs, file:line, sources, commands, quotes; risks; quiz; any doubt label (no "unchecked" badge when `transcript_unavailable` is set) |
| Device | Desktop first (1440 x 900); 800 x 900 must work; 390 stays usable |
| Tokens added | `--mk: 32px` (40px under `pointer: coarse`), `--mk-gap: 8px`, `--lane-h: 56px`; every other value is the page's own |

| Decision | Rationale |
| --- | --- |
| Markers are real `button`s of at least 32 px with at least 8 px between them; a marker never touches its neighbour | the user asked for large markers; the same size is a safe tap target on the desktop |
| `fit.js` places markers on one shared time axis (the turn numbers), with integer positions: push right by one pitch, then pull back from the right edge. A lane with more events than `floor((W + gap) / (mk + gap))` merges its closest neighbours into count bubbles, never into a non-adjacent group | a lane must stay legible at any width and keep the order; integers keep the gap from shrinking to 7 px |
| A count bubble is a marker too: it selects its range in the panel, highlights those events and says "events a to b of n" | the cluster is not a dead end |
| Escape closes the panel and returns focus to the marker (or the bubble that now holds it, else the lane header); opening focuses the panel | the keyboard path is the mouse path |
| At 1000 px and under the panel moves to sit under the selected lane; with no JS the markers wrap and every panel shows | the page stays readable offline and without scripts |
| At wide widths theme 1 is selected on load | the panel is never an empty box on first sight |
| Each fact is told once: an event only in the panel, a Needs you and a Decided item only in its card; the panel links to them with a chip | the sections are MECE and the page does not repeat itself |
| Real deletes are outward cards; deletes whose every target is under `/tmp/` or `$TMPDIR` are one collapsed line ("Also N cleanups of temp folders (scratch), not listed") | scratch cleanup is noise, a real delete is not |
| The "Irreversible on the remote" note from the mockup was dropped | it was not in the doc; the Decided cards already mark each item reversible or not |
| Page text goes through `plain()`: credentials hidden, backticks dropped, the line number of `file.ext:NN` dropped | the page shows no code or file:line even when a doc line has one |

Checker rounds (`check.mjs` on the sample page): round 1 at 390, 768 and 1440: 0 failures, tap-target WARNs at 390 only (markers 32 px, status chips 26 px, tally 38 px), accepted for a desktop-first page and the 32 px the user asked for; round 2 at 800 and 1440: 0 failures, 0 warnings. Tiles opened at 1440 and 800. Inconsistencies seen and left alone: the v2 page still has "Not checked" and "Inferred" labels (the session page has none).
