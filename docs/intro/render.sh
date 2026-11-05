#!/usr/bin/env bash
# Re-renders the intro: docs/media/intro.mp4 and docs/images/intro.avif (and a GIF with GIF=1).
#   bash docs/intro/render.sh [workdir]        default workdir /tmp/explain-change-intro
# Needs node >= 22, ffmpeg, avifenc (libavif) and (for the page crops only) chromium. Installs HyperFrames and GSAP under <workdir>/tools (nothing global).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
W="${1:-/tmp/explain-change-intro}"; TOOLS="${TOOLS:-$W/tools}"; OUT="$W/out"
mkdir -p "$TOOLS" "$OUT"
[ "$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)" -ge 4000 ] || { echo "less than 4 GB available; wait and retry"; exit 1; }
if ps -eo args | grep -q "[c]hromium --headless"; then echo "another headless browser is running; wait and retry"; exit 1; fi
export XDG_CACHE_HOME="$TOOLS/cache" npm_config_cache="$TOOLS/npm-cache"
[ -x "$TOOLS/node_modules/.bin/hyperframes" ] || npm i --prefix "$TOOLS" hyperframes@0.9.15 gsap
export PATH="$TOOLS/node_modules/.bin:$PATH"
node "$HERE/build.mjs" >/dev/null                                  # data.js from the sample session
node "$HERE/stage.mjs" "$W/proj" "$TOOLS/node_modules/gsap/dist/gsap.min.js"
(cd "$W/proj" && hyperframes lint)
(cd "$W/proj" && systemd-run --user --scope -p MemoryMax=3G -- hyperframes render . --output "$OUT/raw.mp4" --fps 30 --workers 1 --quality delivery)
ffmpeg -v error -y -i "$OUT/raw.mp4" -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -r 30 -movflags +faststart -an "$OUT/intro.mp4"
# README image: animated AVIF (small, smooth glows)
ffmpeg -v error -y -i "$OUT/intro.mp4" -vf "fps=15,scale=800:-2:flags=lanczos" -pix_fmt yuv420p -strict -1 "$OUT/intro.y4m"
avifenc -s 6 -j 4 --min 0 --max 8 --autotiling "$OUT/intro.y4m" "$OUT/intro.avif" >/dev/null && rm -f "$OUT/intro.y4m"   # avifenc (libavif) needed
if [ "${GIF:-0}" = 1 ]; then   # for comparison only: a GIF under 5 MB bands (see NOTES.md)
  ffmpeg -v error -y -i "$OUT/intro.mp4" -vf "fps=5,scale=800:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=48:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" -loop 0 "$OUT/intro.gif"
fi
ls -l "$OUT"; echo "copy: cp $OUT/intro.mp4 $REPO/docs/media/intro.mp4; cp $OUT/intro.avif $REPO/docs/images/"
