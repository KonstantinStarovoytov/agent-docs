#!/usr/bin/env bash
# Rebuilds the animated flow from index.html: a GIF per theme and one still
# per step for the README. Edit index.html (texts in STEPS and ART), then run:
#
#     docs/flow/render.sh
#
# Needs Node with puppeteer importable (e.g. NODE_PATH pointing at a
# node_modules that has it), ffmpeg with libwebp, and gifsicle.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

for theme in light dark; do
  node capture.js "$theme" "$tmp/$theme" 10
  ffmpeg -v error -y -framerate 10 -i "$tmp/$theme/f%04d.png" \
    -vf "palettegen=max_colors=128:stats_mode=diff" "$tmp/palette.png"
  ffmpeg -v error -y -framerate 10 -i "$tmp/$theme/f%04d.png" -i "$tmp/palette.png" \
    -lavfi "paletteuse=dither=none:diff_mode=rectangle" "$tmp/raw.gif"
  gifsicle -O3 --lossy=30 "$tmp/raw.gif" -o "agent-docs-flow-$theme.gif"

  node capture.js "$theme" "$tmp/steps-$theme" steps
  # f0000 is the overview; steps are numbered from 1.
  for still in "$tmp/steps-$theme"/f*.png; do
    n=$((10#$(basename "$still" .png | tr -d f)))
    [ "$n" -eq 0 ] && continue
    ffmpeg -v error -y -i "$still" -c:v libwebp -quality 88 "steps/step-$(printf %02d "$n")-$theme.webp"
  done
done
