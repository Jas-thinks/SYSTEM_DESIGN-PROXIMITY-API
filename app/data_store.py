"""In-memory location store.

The CSV is read exactly once at process start. Data is kept in flat,
id-indexed lists (index 0 is unused) so lookups during BFS are O(1) list
indexing rather than dictionary hashing.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from app.config import CSV_PATH

Row = Tuple[int, float, float, str]


@dataclass
class LocationData:
    """Flat, id-indexed location table plus a per-category index."""

    lats: List[float]                 # lats[id]
    longs: List[float]                # longs[id]
    cat_idx: List[int]                # cat_idx[id] -> index into categories
    present: List[bool]               # present[id]
    categories: List[str]             # sorted unique category names
    ids_by_category: Dict[str, List[int]] = field(default_factory=dict)
    max_id: int = 0

    def cat_name(self, idx: int) -> str:
        return self.categories[idx]

    def cat_index(self, name: str):
        """Return the integer index for a category name, or None."""
        try:
            return self.categories.index(name)
        except ValueError:
            return None

    @classmethod
    def from_rows(cls, rows: Iterable[Row]) -> "LocationData":
        """Build a store from (id, lat, long, category) tuples.

        Used by tests to construct tiny, hand-verifiable datasets.
        """
        rows = list(rows)
        if not rows:
            raise ValueError("location table is empty")
        max_id = max(r[0] for r in rows)
        if max_id < 1:
            raise ValueError("location ids must be positive")

        categories = sorted({r[3] for r in rows})
        cat_lookup = {name: i for i, name in enumerate(categories)}

        lats = [0.0] * (max_id + 1)
        longs = [0.0] * (max_id + 1)
        cat_idx = [0] * (max_id + 1)
        present = [False] * (max_id + 1)
        ids_by_category: Dict[str, List[int]] = {name: [] for name in categories}

        for loc_id, lat, long, cat in rows:
            if loc_id < 1:
                raise ValueError(f"invalid location id {loc_id}")
            lats[loc_id] = lat
            longs[loc_id] = long
            cat_idx[loc_id] = cat_lookup[cat]
            present[loc_id] = True
            ids_by_category[cat].append(loc_id)

        return cls(
            lats=lats,
            longs=longs,
            cat_idx=cat_idx,
            present=present,
            categories=categories,
            ids_by_category=ids_by_category,
            max_id=max_id,
        )


def load_locations(path: Path | str = CSV_PATH) -> LocationData:
    """Read the locations CSV into a :class:`LocationData`."""
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = {"ID", "Latitude", "Longitude", "Category"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"CSV must contain columns {sorted(required)}; "
                f"found {reader.fieldnames}"
            )
        rows: List[Row] = []
        for lineno, raw in enumerate(reader, start=2):
            try:
                loc_id = int(raw["ID"])
                lat = float(raw["Latitude"])
                long = float(raw["Longitude"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"bad numeric value on CSV line {lineno}") from exc
            cat = (raw["Category"] or "").strip()
            rows.append((loc_id, lat, long, cat))

    if not rows:
        raise ValueError(f"no rows found in {path}")
    return LocationData.from_rows(rows)
