"""Central configuration and grid constants.

The location grid is a 100x100 lattice. Every coordinate is of the form
k/99 for k in 0..99, so the grid can be addressed by integer row/column
indices 0..99. A location id is ``row * 100 + col + 1``.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Path to the locations CSV. Overridable for tests / deployments.
CSV_PATH = Path(os.environ.get("LOCATIONS_CSV", str(BASE_DIR / "locations.csv")))

# Directory whose plain filenames may be referenced by the ``link`` parameter.
LINKS_DIR = Path(os.environ.get("LINKS_DIR", str(BASE_DIR / "links")))

# Grid geometry.
GRID_N = 100              # 100 x 100 points
GRID_DIV = GRID_N - 1     # 99 -> coordinate = k / GRID_DIV

# Number of ids returned per search.
RESULT_LIMIT = int(os.environ.get("RESULT_LIMIT", "10"))

# Cap on the number of distinct parsed link payloads kept in memory.
LINK_CACHE_SIZE = int(os.environ.get("LINK_CACHE_SIZE", "32"))

# Timeout (seconds) when fetching a link from a URL.
LINK_FETCH_TIMEOUT = float(os.environ.get("LINK_FETCH_TIMEOUT", "10"))
