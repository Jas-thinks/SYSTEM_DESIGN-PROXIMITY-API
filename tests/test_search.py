"""Unit tests for the BFS proximity search.

Small, hand-verified graphs are placed on the real grid formula so that
``nearest_grid_id`` maps the query point to a known start vertex.
"""

from collections import deque

from app.data_store import LocationData
from app.search import proximity_search, start_vertex

STEP = 1 / 99  # one grid column


def build_data(rows):
    return LocationData.from_rows(rows)


def reference_search(data, adjacency, lat, long, category, rad, limit=10):
    """Exhaustive BFS used to cross-check the early-stopping implementation."""
    start = start_vertex(lat, long)
    cat = data.cat_index(category)
    dist = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for nb in adjacency.get(node, ()):
            if nb not in dist:
                dist[nb] = dist[node] + 1
                queue.append(nb)
    candidates = []
    for node, d in dist.items():
        if data.cat_idx[node] != cat:
            continue
        if (data.lats[node] - lat) ** 2 + (data.longs[node] - long) ** 2 <= rad * rad:
            candidates.append((d, node))
    candidates.sort()
    return [node for _, node in candidates[:limit]]


def test_start_vertex_is_nearest_grid_point_and_clamped():
    assert start_vertex(0.0, 0.0) == 1
    assert start_vertex(1.0, 1.0) == 10000
    assert start_vertex(0.0, STEP) == 2       # column 1
    assert start_vertex(-5.0, -5.0) == 1       # clamped to (0, 0)
    assert start_vertex(5.0, 5.0) == 10000     # clamped to (99, 99)


def test_tiny_hand_verified_graph():
    # ids 1..4 on row 0, columns 0..3 -> ids line up with (0, col/99)
    data = build_data([
        (1, 0.0, 0.0, "bank"),
        (2, 0.0, STEP, "bank"),
        (3, 0.0, 2 * STEP, "bank"),
        (4, 0.0, 3 * STEP, "bank"),
    ])
    adjacency = {1: [2], 2: [1, 3], 3: [2]}

    result = proximity_search(data, adjacency, 0.0, 0.0, "bank", rad=1.0)
    assert result == [1, 2, 3]  # 4 is unreachable

    assert proximity_search(data, adjacency, 0.0, 0.0, "bank", rad=1.0, limit=2) == [1, 2]


def test_absent_ids_from_link_are_not_returned():
    # Synthetic dataset WITH ID GAPS: only ids 1, 2 and 5 exist; 3 and 4 do not.
    data = build_data([
        (1, 0.0, 0.0, "bank"),
        (2, 0.0, STEP, "store"),
        (5, 0.0, 4 * STEP, "bank"),
    ])
    # A (bogus) link that uses the absent id 3 as a waypoint between 1 and 5.
    adjacency = {1: [3], 3: [1, 5], 5: [3]}

    result = proximity_search(data, adjacency, 0.0, 0.0, "bank", rad=1.0)

    # Expected: a road may only join real locations. id 3 is not a location,
    # so it must never be returned, and the edge 1-3-5 must not connect 1 to 5.
    assert 3 not in result
    assert result == [1]


def test_disconnected_component_is_excluded():
    data = build_data([
        (1, 0.0, 0.0, "bank"),
        (2, 0.0, STEP, "bank"),
        (3, 0.0, 2 * STEP, "bank"),
    ])
    adjacency = {1: [2], 2: [1]}  # 3 isolated
    assert proximity_search(data, adjacency, 0.0, 0.0, "bank", rad=5.0) == [1, 2]


def test_radius_boundary_is_inclusive():
    data = build_data([
        (1, 0.0, 0.0, "bank"),
        (2, 0.0, STEP, "bank"),
        (3, 0.0, 2 * STEP, "bank"),
    ])
    adjacency = {1: [2], 2: [1, 3], 3: [2]}

    exactly = 2 * STEP
    assert proximity_search(data, adjacency, 0.0, 0.0, "bank", rad=exactly) == [1, 2, 3]
    assert proximity_search(data, adjacency, 0.0, 0.0, "bank", rad=exactly - 1e-9) == [1, 2]


def test_ties_broken_by_smaller_id():
    data = build_data([
        (1, 0.0, 0.0, "bank"),        # start
        (5, 0.0, 0.01, "bank"),       # dist 1 from 1
        (6, 0.0, 0.02, "bank"),       # dist 1 from 1
    ])
    # adjacency deliberately listed out of order
    adjacency = {1: [6, 5], 5: [1], 6: [1]}
    assert proximity_search(data, adjacency, 0.0, 0.0, "bank", rad=1.0) == [1, 5, 6]


def test_category_filter_and_stop_level():
    data = build_data([
        (1, 0.0, 0.0, "store"),       # wrong category at level 0
        (2, 0.0, 0.01, "bank"),       # level 1
        (3, 0.0, 0.02, "bank"),       # level 1
        (4, 0.0, 0.03, "bank"),       # level 1
        (5, 0.0, 0.04, "bank"),       # level 2 (via 2)
    ])
    adjacency = {1: [2, 3, 4], 2: [1, 5], 3: [1], 4: [1], 5: [2]}
    assert proximity_search(data, adjacency, 0.0, 0.0, "bank", rad=1.0, limit=2) == [2, 3]


def test_matches_reference_on_larger_graph():
    # 10x10 block of banks, chain + extra edges; compare against full BFS.
    rows = []
    for row in range(10):
        for col in range(10):
            loc_id = row * 100 + col + 1
            rows.append((loc_id, row * STEP, col * STEP, "bank"))
    data = build_data(rows)

    adjacency = {}
    for row in range(10):
        for col in range(10):
            loc_id = row * 100 + col + 1
            neighbours = []
            if col + 1 < 10:
                neighbours.append(row * 100 + col + 2)
            if row + 1 < 10:
                neighbours.append((row + 1) * 100 + col + 1)
            for nb in neighbours:
                adjacency.setdefault(loc_id, set()).add(nb)
                adjacency.setdefault(nb, set()).add(loc_id)
    adjacency = {k: sorted(v) for k, v in adjacency.items()}

    for limit in (1, 5, 10):
        got = proximity_search(data, adjacency, 0.0, 0.0, "bank", rad=1.0, limit=limit)
        want = reference_search(data, adjacency, 0.0, 0.0, "bank", 1.0, limit)
        assert got == want


def test_unknown_category_returns_empty():
    data = build_data([(1, 0.0, 0.0, "bank")])
    assert proximity_search(data, {}, 0.0, 0.0, "nope", rad=1.0) == []
