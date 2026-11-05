# explain-change intro clip

One 30 s clip, 1280x720, English, pearl palette (the README images use pearl too). It is a fixed timeline: every animation is a paused Web Animation and `window.seek(ms)` sets them all, so a re-record is identical.

| Time | Scene |
|---|---|
| 0.0-2.4 s | Hook: "Session in. One checked page out." |
| 2.0-13.65 s | How it works: 7 harness chips flow into Transcript; Transcript + Code diff become Doc; Doc goes through Checks (Quotes, Tool calls, Secrets masked); the result is one page |
| 13.55-17.8 s | Chart 1: one day, eight pieces of work (timeline bars) |
| 17.75-21.85 s | Chart 2: 28 events by kind, and the two counts the agent made on its own |
| 21.8-26.0 s | The real pearl page: two windows onto the bundled screenshot |
| 25.85-29.85 s | End card: slogan, icon, `github.com/epistex-dev/explain-change` |

## Re-record

```bash
# needs node >= 22, chromium and ffmpeg
systemd-run --user --scope -p MemoryMax=3G -- node docs/intro/record.mjs /tmp/explain-change-intro/out
# -> intro.mp4, intro.gif, intro-poster.png in that folder; copy them to docs/media/ and docs/images/
```

`build.mjs` inlines the fonts, icons and `docs/images/themes/pearl-1440x900.png` into one HTML file (default `<tmp>/explain-change-intro/intro.html`). Open it in a browser to see the live loop, or add `?at=<ms>` to freeze one frame. `SHOTS=1000,5000` writes single PNGs instead of the video. `record.mjs` stops when another headless browser is running.

## Data (only bundled samples, never a real session)

Source file: `skills/explain-change/reference/examples/portal-day.session.json` (`schema explain-session/1`, synthetic). Each number below was counted from it by script.

| On screen | Value | Source field |
|---|---|---|
| Lanes, 8 | Report design ... UI + tagline | `themes[].title` (shortened: "Library repo" etc.) |
| Lane extent | e.g. Report design 1-3, Library repo 14-18 | min and max of `themes[].events[].order` |
| Bars by kind | Done 8, Outward 7, Asked 4, Decided 3, Blocked 3, Redirected 2, In progress 1 | count of `themes[].events[].kind` |
| 28 events | 28 | number of events over all themes |
| Agent decided for you | 6 | `len(decided)` |
| 1 cannot be undone | 1 | `decided[]` with `reversible: false` |
| Outward actions | 10 | sum of `outward[].count` (2 repos, 2 pushes, 2 force pushes, 1 history rewrite, 3 deletes) |
| 5 kinds | 5 | `len(outward)` |
| 2 force pushes | 2 | `outward[kind=force_push].count` |
| 7 harnesses | 7 | the README harness table, one row per transcript reader (a test keeps the table equal to the readers) |
| Real page: "8 themes, 28 events; 3 hit a blocker, 2 were redirected" | as in the image | `docs/images/themes/pearl-1440x900.png`, rendered from the same file |

The small dots inside the "One page" card of the flow scene are decorative marks in the page's own marker style; they carry no data.

## Decisions

- **One palette.** `src/lib.css` holds the pearl values copied from `[data-theme=pearl]` in `skills/explain-change/assets/ui/page2.css`.
- **No code, no unchecked wording.** No frame shows code, a diff or file:line. The page screenshot is cropped (below) so the summary card, with its sample note, never enters the frame, and the right window stops above the panel's one-line note about the agent's own counts. Checked on frames at 21.8, 22.5, 24.5 and 25.2 s.
- **Real page scene.** Two windows cut from the screenshot: the journey lanes (x 44-1000, y 262-900) and the "Agent decided for you" / "Outward actions" panel (x 1016-1396, y 262-586). The zoom is 3-5 % about a point chosen so nothing is cut off; a bigger zoom clipped the first legend icon. At 800 px the page text is small: two 30 px captions say what each window is for.
- **Charts (web-ui-design dataviz rules).** Bars start at 0 and are sorted by value and direct-labelled; the 7 kinds are bars, not a donut (a donut is for 5 slices or fewer). Kind colours always carry an icon and a word. Day bars show no invented clock times: the axis says Earlier / Later, like the page. The one in-progress theme is a dashed outline, the page's own way to mark unfinished.
- **Motion (web-ui-design motion rules).** Entrances use a strong ease-out, things that move on screen use ease-in-out. Scenes hand off one after the other: the next fades in as the last finishes fading out (0.05-0.2 s overlap), so no frame shows two scenes at once and there is no ghosting in the video or the GIF. Rare delight only: pop-ins, drawn check marks and counters are on the first viewing of each scene, nothing loops.
- **Pacing.** Flow captions stay on screen for at least 1.5 s each; the end card holds about 2 s after it finishes building. `prefers-reduced-motion` does not apply: this is a video.
- **GIF.** 800 px wide, 12 fps, rendered natively (not scaled down) from a flat variant (`?gif`: no dot grid, soft shadows or blur). It is packed with ffmpeg: one 256-colour palette for the whole clip and a lossless frame diff. `gifski` was tried first and left a faint ghost of the old scene in every cross-fade (its lossy diff keeps pixels that changed only a little, and a fade changes them a little at a time), also at quality 100; per-frame palettes in ffmpeg were 7.5 MB. Checked by reading GIF frames around all five hand-offs. Frames of the slow zoom are held 3 at a time to stay small. The recorder tries 10, 8 and 6 fps only when the file is over 3 MB (now 2.4 MB at 12 fps).

## web-ui-design check (`scripts/check.mjs`)

Run on frames at 1.1, 12.4, 17.3, 21.2, 24.0 and 29.5 s (`?at=<ms>`), tiles opened at 390, 768 and 1440 px.

- **1440 px: the frame.** Clean: nothing clipped, no overlap, all text readable. The one reported item is a 7 px sideways scroll, the fixed 1280x720 canvas inside a 1440 px window (it is cut off by the recorder).
- **390 and 768 px: not applicable.** The clip is a fixed 1280x720 canvas that is recorded, not a responsive page, so the reported viewport meta tag, sideways overflow and reflow findings do not apply. Tap targets, keyboard focus and the performance budget do not apply to a video either.
- **Contrast notes ("text over a gradient, check visually").** Checked on the tiles: body text is `--text` / `--text-2` / `--text-3` of pearl on near-white (4.5:1 or better, per page2.css); bars are the page's own kind colours.
- **WARN clipped on the two page windows** is intended: they are crops.
- Readability at 640 px wide: chart labels, captions and counts are 24 px or larger on the 1280 canvas (12 px at 640). The real-page screenshot text is not (it is the product's own UI); it is there as a visual, with its meaning in the large captions.
