"""Generate a synthetic road-link file from the 100x100 grid.

The real assignment ships a link file; this helper produces a full
4-neighbour grid graph so the service can be exercised locally.

Usage:
    python scripts/make_grid_links.py links/grid.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

GRID_N = 100


def generate(diagonal: bool = False) -> str:
    lines = []
    for row in range(GRID_N):
        for col in range(GRID_N):
            here = row * GRID_N + col + 1
            if col + 1 < GRID_N:
                lines.append(f"{here} {here + 1}")
            if row + 1 < GRID_N:
                lines.append(f"{here} {here + GRID_N}")
            if diagonal and row + 1 < GRID_N and col + 1 < GRID_N:
                lines.append(f"{here} {here + GRID_N + 1}")
    return "\n".join(lines) + "\n"


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("links/grid.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(generate(diagonal="--diagonal" in sys.argv))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
