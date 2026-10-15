#!/usr/bin/env bash
# Rebuilds both animations from index.html and flows/*.js: a GIF per theme and
# one still per step for the README. Edit flows/ask.js or flows/reindex.js
# (texts in STEPS and ART), then run:
#
#     docs/flow/render.sh
#
# Needs Node with puppeteer importable (e.g. NODE_PATH pointing at a
# node_modules that has it), ffmpeg with libwebp, and gifsicle.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# flow   GIF                              stills
# ask     agent-docs-flow-<theme>.gif       steps/step-NN-<theme>.webp
# reindex reindex-flow-<theme>.gif          steps/reindex-NN-<theme>.webp
for flow in ask reindex; do
  if [ "$flow" = ask ]; then gif=agent-docs-flow; still=step; else gif=reindex-flow; still=reindex; fi
  for theme in light dark; do
    node capture.js "$theme" "$tmp/$flow-$theme" 10 "$flow"
    ffmpeg -v error -y -framerate 10 -i "$tmp/$flow-$theme/f%04d.png" \
      -vf "palettegen=max_colors=128:stats_mode=diff" "$tmp/palette.png"
    ffmpeg -v error -y -framerate 10 -i "$tmp/$flow-$theme/f%04d.png" -i "$tmp/palette.png" \
      -lavfi "paletteuse=dither=none:diff_mode=rectangle" "$tmp/raw.gif"
    gifsicle -O3 --lossy=30 "$tmp/raw.gif" -o "$gif-$theme.gif"

    node capture.js "$theme" "$tmp/steps-$flow-$theme" steps "$flow"
    # f0000 is the overview; steps are numbered from 1.
    for frame in "$tmp/steps-$flow-$theme"/f*.png; do
      n=$((10#$(basename "$frame" .png | tr -d f)))
      [ "$n" -eq 0 ] && continue
      ffmpeg -v error -y -i "$frame" -c:v libwebp -quality 88 "steps/$still-$(printf %02d "$n")-$theme.webp"
    done
  done
done
