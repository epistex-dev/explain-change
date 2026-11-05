# explain-change intro clip

30 s, 1280x720, 30 fps, English, dark navy ("style A"). Built with [HyperFrames](https://github.com/heygen-com/hyperframes) 0.9.15: `index.html` is one composition with one paused, seekable GSAP timeline, so every render is identical. Design record: [DESIGN.md](DESIGN.md).

| Time | Scene |
|---|---|
| 0.0-3.4 s | Hook: "Session in. One checked page out." |
| 3.1-13.3 s | Flow: 7 harness chips, Transcript + Code diff, Doc, Checks (Quotes, Tool calls, Secrets masked), One page; tilted plane, camera pans along it |
| 12.9-14.4 s | The camera dives into the One page card |
| 13.7-18.9 s | Chart: 8 themes with their status colour and icon, legend |
| 18.9-23.9 s | The real session page (navy): journey lanes, 4 counts |
| 23.7-27.7 s | The real page: "Agent decided for you" and "Outward actions", the count 10 |
| 27.5-30.0 s | End card |

## Re-render

```bash
# needs node >= 22, ffmpeg, avifenc (libavif); installs hyperframes@0.9.15 and gsap under <workdir>/tools, nothing global
bash docs/intro/render.sh /tmp/explain-change-intro        # -> /tmp/explain-change-intro/out/intro.mp4, intro.avif (GIF=1 adds intro.gif)
cp /tmp/explain-change-intro/out/intro.mp4 docs/media/intro.mp4
cp /tmp/explain-change-intro/out/intro.avif docs/images/
```

`render.sh` stops (retry later) if less than 4 GB is free or another headless Chromium runs, builds `data.js` from the sample (`build.mjs`), stages a project (`stage.mjs`: inlines the icon sprite, copies assets and GSAP), runs `hyperframes lint`, renders with one worker under `systemd-run -p MemoryMax=3G` (about 30 s) and encodes the mp4 (H.264, CRF 18, `+faststart`) and the animated AVIF. GSAP is not committed (its licence is not open source). Open a staged `index.html?at=<seconds>` in a browser to freeze one frame.

The three crops in `assets/page/` come from the real page: render the sample with `render.py --theme navy --no-validate`, then `crops.mjs` (needs puppeteer-core and Chromium; see its header). They are committed, so a normal re-render does not need it.

## Data (only the bundled sample, never a real session)

Source file: `skills/explain-change/reference/examples/portal-day.session.json` (`explain-session/1`, synthetic). `build.mjs` reads it and writes `data.js`; the crops are rendered from the same file.

| On screen | Value | Source field |
|---|---|---|
| 8 theme names (chart, journey) | Export report design, Test credential leak, CI runner outage, Saved-login fix and 6 small fixes, Cleanup, Config backup, Library repo, UI evaluation and tagline | `themes[].title`, unshortened |
| Status colour, icon, name | Done, Done, needs you, Done by you, In progress | `themes[].status` (names from `scripts/lib/i18n2.py`) |
| Bars 4, 3, 2, 2, 3, 5, 6, 3 | events per theme | `len(themes[].events)` |
| Legend 5, 1, 1, 1 | Done, Done needs you, Done by you, In progress | count of `themes[].status` |
| 28 events | 28 | sum of `len(themes[].events)` |
| 8 themes | 8 | `len(themes)` |
| 3 hit a blocker, 2 redirected | 3, 2 | count of `events[].kind` = `blocked`, `redirected` |
| 6 choices made for you (card label "decided for you") | 6 | `len(decided)` |
| 1 cannot be undone | 1 | `decided[]` with `reversible: false` |
| 10 outward actions | 10 | sum of `outward[].count` (2 + 2 + 2 + 1 + 3) |
| 5 kinds | 5 | `len(outward)` |
| 8 on the list, 2 temp-folder cleanups | 8, 2 | `outward[].count` minus `outward[].scratch`, and `scratch` (the page prints "Also 2 cleanups of temp folders") |
| 7 harnesses | 7 | the README harness table, one row per transcript reader |
| Real-page crops | as on the page | rendered from the file above, navy theme |

The dots in the "One page" card are the 8 themes in their status colours. No frame shows code, a diff or a file path, and none of the sample's caveat lines: the crops cut the page's hint lines, and the summary card (with the sample note) never enters a frame.

## Format of the README image: animated AVIF

All at 800 px wide, 15 fps, from the same mp4. The blocks were judged in the T3 browser (Chromium with its normal renderer) on a local page showing the same `<img>` at 100% zoom, the dark-glow region cropped and brightened to expose blocks; the first row of the table is what a reviewer saw on the README.

| Format | Settings | Size | Dark purple glow, in a real browser |
|---|---|---|---|
| WebP (v1) | quality 76, grain 2 | 4.25 MB | 8 px blocks: rejected |
| WebP | quality 90 | 6.66 MB | smooth, a few speckles (decoded with PIL) |
| WebP | quality 90, 720 px | 5.83 MB | slight blocks left: rejected |
| WebP | quality 92 | 8.06 MB | smooth, but over 8 MB |
| WebP | quality 94, 12 fps | 7.71 MB | smooth, faint horizontal banding |
| WebP | quality 95 | 10.2 MB | smooth, too big |
| WebP | quality 85 / 90, grain 3 to 4 | 9.1 / 11.8 MB | smooth, too big (grain costs bytes) |
| WebP | quality 91, compression 6 | 7.60 MB | smooth |
| AVIF | libavif `--min 18 --max 30` | 0.42 MB | smooth with faint contour rings |
| AVIF | `--min 12 --max 22` | 0.65 MB | faint contour rings |
| AVIF | `--min 6 --max 16` | 1.12 MB | glow smooth, but 32 px blocks in the near-black first frames on the GitHub README: rejected |
| **AVIF (used)** | libavif `--min 0 --max 8`, speed 6 | 3.87 MB | smooth in the glows and in the first frames, no blocks |
| GIF | 12 fps 256 colours / 10 fps 128 / 5 fps 48 | 24.9 / 13.1 / 4.93 MB | too big, or bands into contour rings at 5 fps |

The README shows the AVIF as an `<img>` inside a link to the mp4. WebP was dropped: at the quality that hides the glow blocks it was 7.6 MB, twice the AVIF. Fewer glow gradients were not needed. The mp4 (6.5 MB) is the link target.
