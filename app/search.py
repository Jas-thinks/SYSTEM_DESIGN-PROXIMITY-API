"""Proximity search: BFS over the road graph + radius/category filter."""

from __future__ import annotations

from typing import List

from app.config import RESULT_LIMIT
from app.data_store import LocationData
from app.link_parser import Adjacency, nearest_grid_id


def start_vertex(lat: float, long: float) -> int:
    """Nearest grid point to (lat, long), clamped to the grid."""
    return nearest_grid_id(lat, long)


def proximity_search(
    data: LocationData,
    adjacency: Adjacency,
    lat: float,
    long: float,
    category: str,
    rad: float,
    limit: int = RESULT_LIMIT,
) -> List[int]:
    """Return up to ``limit`` location ids ranked by BFS edge distance.

    Ranking: shortest number of road edges from the start vertex first,
    ties broken by smaller id. Locations outside ``rad`` of the raw query
    point or of another category are not eligible; unreachable ones are
    excluded. BFS stops after the first level at which the cumulative
    number of eligible locations reaches ``limit``.
    """
    cat = data.cat_index(category)
    if cat is None or limit <= 0:
        return []

    lats = data.lats
    longs = data.longs
    cat_idx = data.cat_idx
    present = data.present
    max_id = data.max_id

    start = start_vertex(lat, long)
    if start < 1 or start > max_id or not present[start]:
        return []

    r2 = rad * rad
    visited = bytearray(max_id + 1)
    visited[start] = 1

    found = []  # (bfs_distance, id)
    frontier = [start]
    dist = 0

    while frontier:
        nxt = []
        for node in frontier:
            if present[node] and cat_idx[node] == cat:
                dx = lats[node] - lat
                dy = longs[node] - long
                if dx * dx + dy * dy <= r2:
                    found.append((dist, node))
            for nb in adjacency.get(node, ()):
                if nb <= max_id and present[nb] and not visited[nb]:
                    visited[nb] = 1
                    nxt.append(nb)
        if len(found) >= limit:
            break
        frontier = nxt
        dist += 1

    found.sort()
    return [loc_id for _, loc_id in found[:limit]]
