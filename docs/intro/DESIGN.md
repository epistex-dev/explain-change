---
name: explain-change intro video
mode: persuade
page-type: product launch video (30 s, 1280x720, 30 fps), not a web page
family: Premium dark x Technical (style A, "Ra mắt tối", picked by the user from three previews)
stack: HyperFrames 0.9.15 (HTML + one paused GSAP timeline), Inter variable (OFL), Lucide icons (ISC)
colors:
  bg: "#0a0d2b"
  surface: "rgba(44,54,130,.62) to rgba(22,29,80,.7)"
  text: "#f5f6ff"
  text-secondary: "#d0d6fb"
  border: "rgba(150,166,255,.26)"
  accent: "#f08ad0"
  status-done: "#5fd9ae (Done, Done by you)"
  status-needs-you: "#f08ad0"
  status-in-progress: "#8fb4ff"
typography:
  display: "Inter, system-ui, sans-serif"
  body: "Inter, system-ui, sans-serif"
  scale: [19, 21, 23, 30, 50, 72, 92, 210]
spacing-base: 4
radius: { chip: 16, panel: 20, window: 22, pill: 999 }
depth: ring + inner highlight + soft shadow + faint coloured glow (one strategy)
motion:
  ease-out: "power3.out (entrances)"
  ease-in-out: "power3.inOut (camera moves)"
  durations: { entrance: 550, camera: 1700, dive: 1000, scene-fade: 450 }
---

# explain-change intro design

Case: **New** (a final 30 s intro for the README; v1 is replaced). The preview in `design/intro-v2` (style A) is the reference; this is the full video built on it.

## Brief
| Item | Value | Source |
| --- | --- | --- |
| Subject | explain-change: a session in, one checked page out | user |
| Primary action | watch, then read the README / open the repo | user |
| Audience and device | README visitors, inline animation, mp4 on click | user |
| Feel | A: dark product launch, tilted real UI, smooth camera, large type | user (picked from 3 previews) |
| Structure | flow diagram first, then charts and the real page ("Ghép 2 + 3") | user |
| Content | 7 harness chips, Transcript + Code diff, Doc, Checks, One page; 8 themes with status; real session page | user |
| Standing rules | no code or diff in any frame; no "unverified" wording | user |

Question round: skipped, every gap is answered by the request and the earlier previews.

## Direction
A lit path across a tilted plane. The camera drifts along the flow, dives into the "One page" card, and the page opens as a chart of its own data and then as the real page. Type is large and tight, glows carry the mood, nothing is decoration without a meaning: the dots in "One page" are the eight themes in their status colours.

## Scenes
| Time | Scene |
| --- | --- |
| 0.0-3.4 s | Hook: "Session in. One checked page out." over the ghost of the flow board, so the frame is never empty |
| 3.1-13.3 s | Flow: 5 steps (Input, Read, Fold, Check, Page), camera pans along a tilted plane (stops at 0, 780 and 1040 px, so no card is held cut at an edge), step caption and progress rail |
| 12.9-14.4 s | Dive into the One page card |
| 13.7-18.9 s | Chart: 8 themes with their status colour and icon, legend, spotlight on "Done, needs you" then "In progress" |
| 18.9-23.9 s | Real page, journey card (navy theme) + 4 counts |
| 23.7-27.7 s | Real page, "Agent decided for you" and "Outward actions" + the count 10 |
| 27.5-30.0 s | End card |

## Motion decisions (web-ui-design motion rules)
- Entrances ease out (`power3.out`), things already on screen move ease in-out; stagger 40-120 ms; one orchestrated hand-off per scene change (dive, then slide-and-tilt of the next scene). Only `transform`, `opacity`, SVG dash offset and glow position animate. Nothing loops, no `Math.random()` or `Date.now()`: the timeline is seekable, so a re-render is identical.
- The camera is a rotated plane (`rotateY -11 to -6`, `rotateX 6 to 3`, perspective 1700 px) with the world translating under it, so the pivot never leaves the screen; the dive scales a wrapper around the card.
- The flow's left and right edges fade out (CSS mask, 110 px) so a card passing the frame edge dissolves instead of being cut.
- Numbers never count up: an intermediate "27" or "7" would be a wrong value in a 1 fps check. Bars grow, numbers fade in at their final value.
- Not applicable: `prefers-reduced-motion`, focus, tap targets, responsive widths, performance budget (a recorded video, not a page).

## Content rules kept
- Data only from `skills/explain-change/reference/examples/portal-day.session.json` (`build.mjs` writes `data.js` from it, and refuses an unknown status).
- Status colour, icon and name come from each theme's `status`: Done, Done, needs you (the page's own wording, with a comma), Done by you, In progress.
- Each theme keeps its title from the sample, in the chart and on the page.
- Text in the real-page crops is the page's own 12 px and up, shown at 1.64x to 1.66x: 19.7 px or more. The page's hint lines (sample caveats) are cut from the crops, and the summary card never appears.
- Frame 2-3 s holds the hook at 92 px over the ghost board.

## Checks
`scripts/check.mjs` on stills at `?at=4, 7, 16, 22, 25, 29` (1280 px): 0 real failures. It reports "clipped" for `#root` (the 1900 px flow world is wider than the frame by design) and three contrast FAILs for text over a glow, computed against the glow's flat colour at full opacity (`#3b4bd8`, `#a43ac0`); the glows show at 35-55 % and blurred. Measured on rendered pixels behind the same text: 7.0:1 to 10.8:1. A clean pass is the floor; what makes this belong to its subject is that every shape on screen is a piece of the real page (its chips, lanes, status colours and panels).

## Decisions
| Decision | Rationale | Date |
| --- | --- | --- |
| Animated AVIF in the README, no WebP fallback, GIF not used | GIF under 5 MB bands; WebP at quality 76 showed 8 px blocks in the dark glows in a real browser, quality 91 is clean but 7.6 MB, twice the AVIF (see NOTES.md) | 2026-11-05 |
| Camera stops: the far cards (Checks, One page) appear only as the camera moves to them | a card sitting cut at the right frame edge for seconds read as a layout bug; at each held stop every card is whole or fully out of frame | 2026-11-05 |
| Real-page crops carry the side panel's own 12 px padding | text no longer touches the crop edge; shown at 1.64x, the page's 12 px text is 19.7 px | 2026-11-05 |
| Stat-card labels are one line ("redirected", "decided for you") | a two-line label ate the bottom padding of the card | 2026-11-05 |
| Step labels 21 px in #f9b6e2 | the accent pink measured 4.4:1 over the glows at 18 px | 2026-11-05 |
| "Done, needs you" with a comma | It is the page's own status name (`i18n2.py`) | 2026-11-05 |
| `10` as one number: 8 on the list + 2 temp-folder cleanups | The page shows 8 cards' worth plus "Also 2 cleanups", the sum is `outward[].count` | 2026-11-05 |
| GSAP is fetched, not committed | Its licence is not open source; `render.sh` installs it with npm | 2026-11-05 |
