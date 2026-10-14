"""Render the Mermaid diagrams in README.md and ARCHITECTURE.md to PNG.

GitHub's web UI renders ```mermaid blocks, but the GitHub mobile app and many
editors (PyCharm without its Mermaid extension) show the source instead. The
docs therefore embed PNGs, light and dark, and keep each diagram's source in
docs/diagrams/<name>.mmd. Edit the .mmd file, then run:

    uv run python scripts/render_diagrams.py

Needs Node (npx downloads @mermaid-js/mermaid-cli on first use).
"""

import subprocess
from pathlib import Path

DIAGRAMS = Path("docs/diagrams")
THEMES = {"light": ("default", "white"), "dark": ("dark", "#0d1117")}


def main() -> None:
    for source in sorted(DIAGRAMS.glob("*.mmd")):
        for variant, (theme, background) in THEMES.items():
            target = source.with_name(f"{source.stem}-{variant}.png")
            subprocess.run(
                [
                    "npx",
                    "-y",
                    "-p",
                    "@mermaid-js/mermaid-cli",
                    "mmdc",
                    "-q",
                    "-i",
                    str(source),
                    "-o",
                    str(target),
                    "-t",
                    theme,
                    "-b",
                    background,
                    "-s",
                    "2",
                ],
                check=True,
            )
            print(f"rendered {target}")


if __name__ == "__main__":
    main()
