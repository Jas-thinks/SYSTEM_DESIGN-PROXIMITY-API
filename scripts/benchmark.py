"""Measure startup load and per-query latency.

Run from the repository root:
    python scripts/benchmark.py
"""

from __future__ import annotations

import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import CSV_PATH  # noqa: E402
from app.data_store import load_locations  # noqa: E402
from app.link_parser import clear_cache, get_adjacency, parse_adjacency  # noqa: E402
from app.search import proximity_search  # noqa: E402
from scripts.make_grid_links import generate  # noqa: E402


def main() -> None:
    t0 = time.perf_counter()
    data = load_locations(CSV_PATH)
    load_ms = (time.perf_counter() - t0) * 1000

    payload = generate().encode()
    t0 = time.perf_counter()
    adjacency = parse_adjacency(payload, data.max_id)
    parse_ms = (time.perf_counter() - t0) * 1000

    clear_cache()
    t0 = time.perf_counter()
    get_adjacency(payload, data.max_id)
    cache_miss_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    get_adjacency(payload, data.max_id)
    cache_hit_ms = (time.perf_counter() - t0) * 1000

    edges = sum(len(v) for v in adjacency.values()) // 2

    rng = random.Random(1234)
    early = []   # >= 10 results -> BFS stopped early
    full = []    # < 10 results  -> BFS covered the whole component
    for _ in range(300):
        lat = rng.random()
        long = rng.random()
        cat = rng.choice(data.categories)
        rad = rng.choice([0.005, 0.01, 0.02, 0.05, 0.1, 0.2])
        t0 = time.perf_counter()
        out = proximity_search(data, adjacency, lat, long, cat, rad)
        elapsed = (time.perf_counter() - t0) * 1000
        (early if len(out) >= 10 else full).append(elapsed)

    all_times = sorted(early + full)

    def summary(label, values):
        if not values:
            print(f"{label:<22}: n/a")
            return
        values = sorted(values)
        print(
            f"{label:<22}: n={len(values):<4} "
            f"mean={statistics.mean(values):.3f} ms  "
            f"p95={values[int(len(values) * 0.95)]:.3f} ms  "
            f"max={values[-1]:.3f} ms"
        )

    print(f"locations loaded      : {data.max_id} in {load_ms:.1f} ms")
    print(f"edges parsed          : {edges} in {parse_ms:.1f} ms")
    print(f"cache miss (parse)    : {cache_miss_ms:.1f} ms")
    print(f"cache hit             : {cache_hit_ms:.3f} ms")
    print(f"queries               : {len(all_times)}")
    summary("early stop (>=10)", early)
    summary("full component (<10)", full)
    print(f"overall p95           : {all_times[int(len(all_times) * 0.95)]:.3f} ms")
    print(f"overall max           : {all_times[-1]:.3f} ms")


if __name__ == "__main__":
    main()
