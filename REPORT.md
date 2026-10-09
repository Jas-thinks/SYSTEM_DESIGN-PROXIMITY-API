# Proximity Search API — Report

## 1. Problem

Return the 10 locations that are closest to a query point *by road distance*,
restricted to a category and a circular (Euclidean) search radius.

Roads are supplied at query time through the `link` parameter. There is no
road data in `locations.csv`; the graph comes only from the link file, and
missing links stay missing.

## 2. API contract

**Route:** `GET` and `POST /search/` (also registered without the trailing
slash to avoid redirect issues with POST).

### Inputs

| Field | Type | Notes |
| --- | --- | --- |
| `lat` | float | query latitude (grid domain 0..1) |
| `long` | float | query longitude; aliases `lon`, `lng`, `longitude` |
| `cat` | string | category, must be one of the 8 in the CSV |
| `rad` | float | radius, Euclidean, `>= 0` |
| `link` | string / upload | road file — raw text, URL, server-side filename, or multipart file |

Inputs may arrive as query string params, a JSON body, or form fields; the
`link` may additionally be a multipart file upload (any file field name).
Aliases: `lat`/`latitude`, `cat`/`category`, `rad`/`radius`,
`link`/`links`/`roads`/`file`.

### Output

A JSON array of up to 10 integer ids, ranked best-first. Header
`X-Link-Hash` carries the SHA-256 of the parsed payload (useful for
debugging/caching checks).

```json
[42, 117, 43, 118, 44, 119, 45, 120, 46, 121]
```

### Errors

`400 Bad Request` for missing/non-numeric/ non-finite `lat`, `long`, `rad`;
negative `rad`; unknown `cat`; malformed JSON body; a link URL that cannot be
fetched; or a **named server-side link file that does not exist**. `503` while
the app is still starting.

### Where the spec was ambiguous — choices made

| Ambiguity | Choice | Alternatives accepted |
| --- | --- | --- |
| Link format | `a b` id pairs, undirected | commas as separators; `#` comments/blank lines; **4-number coordinate lines** mapped to nearest grid ids |
| Response shape | bare JSON array of ids | — (chosen as the literal reading of "a JSON list of 10 IDs") |
| Tie order | smaller id first | final sort is `(bfs_distance, id)`, so any input order gives the same answer |
| Start point included? | yes, if it matches category and is within `rad` | |
| `rad` boundary | inclusive (`distance <= rad`) | |
| Rounding to grid | Python `round` (banker's) on `coord*99` | |
| No `link` given | empty graph → only the start vertex can be reachable | |

### OpenAPI / Swagger

`/docs` (Swagger UI), `/redoc` and `/openapi.json` document every route. Because
the search handlers parse the request manually (to accept query, JSON, form and
multipart on one route), the operations are described with FastAPI
`openapi_extra`: required query parameters for `GET`, a request body offering
`application/json`, `application/x-www-form-urlencoded` and
`multipart/form-data` (`link` as a binary file) for `POST`, a `200`
array-of-ids response plus the `X-Link-Hash` header, and documented `400`/`503`
errors. `/health` and `/` use `HealthResponse` / `RootResponse` models.

## 3. Data structures

**Locations** (`app/data_store.py`): the CSV is read once at startup into
flat id-indexed Python lists `lats[]`, `longs[]`, `cat_idx[]`, `present[]`
(index 0 unused). A `categories` list plus `ids_by_category` dict gives an
O(1) category lookup and O(1) membership for eligibility checks.

**Road graph** (`app/link_parser.py`): an adjacency dict
`{id: sorted([neighbours])}`. Every id on a line is validated against
`1..max_id`; self-loops and out-of-range ids are dropped. Parsed graphs are
kept in an LRU-bounded dict keyed by the SHA-256 of the payload bytes.

**Search** (`app/search.py`): BFS over the adjacency dict with a `bytearray`
visited set, recording `(distance, id)` for eligible nodes.

### Algorithm

1. Start vertex = nearest grid point to `(lat, long)`:
   `row = round(lat*99)`, `col = round(long*99)`, each clamped to `0..99`,
   `id = row*100 + col + 1`.
2. BFS level by level from the start vertex.
3. A node is *eligible* if `cat_idx[node] == cat` and
   `(lat[node]-lat)² + (long[node]-long)² <= rad²` (raw query point is the
   circle centre).
4. After completing the level at which the cumulative eligible count
   reaches 10, stop; sort eligible by `(distance, id)` and return the first 10.
5. Unreachable nodes are excluded (they never enter the visited set).

Because ranking is dominated by BFS distance, stopping early cannot change
the result — it only avoids exploring strictly-worse levels. This is
verified in `test_matches_reference_on_larger_graph` against a full BFS.

## 4. Complexity

Let `N` = locations, `E` = links, `V` = component size reached by BFS.

| Operation | Time | Space |
| --- | --- | --- |
| Startup CSV load | O(N) | O(N) |
| Link parse (cache miss) | O(E log d) (sorting neighbour lists) | O(N + E) |
| Link resolve (cache hit) | O(L) hash of payload | O(1) new |
| Query BFS | O(V + E) worst case; O(reached) with early stop | O(N) visited + result |

For the given data `N = 10000`, `E = 19800` (full grid), worst case ≈ 2 ms.

## 5. Tests

`pytest -q` → **53 passed**. Coverage of the required scenarios:

- **Tiny hand-verified graph** — 4 nodes, one disconnected; asserts exact `[1,2,3]`.
- **Disconnected nodes** — isolated node excluded from results.
- **Radius boundary** — a node exactly at `rad` is included; `rad - 1e-9` excludes it.
- **Ties** — two nodes at equal BFS distance returned in ascending id order, even with reversed input order.
- **Malformed input** — missing/non-numeric `lat`, negative `rad`, unknown category, bad JSON body → 400; malformed link lines skipped without error; out-of-range ids and self-loops dropped.
- **Category filter + level stop** — wrong-category start, correct results at level 1.
- **Input surfaces** — GET query string, POST JSON, POST form, multipart upload, server-side filename.
- **Reference cross-check** — early-stop implementation equals exhaustive BFS on a 100-node grid for several limits.
- **Cache** — repeated payload returns the identical cached object; different payload differs.
- **Regression: absent ids** — a link that references an id not present in the CSV is neither returned nor traversed (`present` guard); dataset with id gaps, expected `[1]`.
- **Regression: missing link file** — a named server-side link file that does not exist → `400`; raw payloads (whitespace/comma separated) unaffected.
- **Regression** — a long raw-text link is not mistaken for a filename (which otherwise raised `ENAMETOOLONG` once `LINKS_DIR` existed).
- **OpenAPI schema** — `/openapi.json` declares the search query parameters (required vs optional), the JSON/form/multipart request bodies (with a binary `link`), the array-of-integer `200` response plus the `X-Link-Hash` header, and the `400`/`503` errors; `/health` and `/` expose response schemas; `/search` and `/search/` document identically except for the unique `operationId`.
- **Swagger UI** — `/docs` returns `200`; the aliases return identical results.

## 6. Measured runtimes

Machine: Linux, Python 3.12, single process. `python scripts/benchmark.py`
with a full 100×100 grid link graph (19 800 edges), 300 random queries.

| Stage | Result |
| --- | --- |
| CSV load (10 000 rows) | 14.9 ms (one-off) |
| Parse 19 800 edges (cache miss) | 24.1 ms |
| Cache hit (re-parse skipped) | 0.104 ms |
| Query, ≥10 results reached (early stop), n=135 | mean 0.018 ms, p95 0.026 ms |
| Query, <10 results (full component), n=165 | mean 1.599 ms, p95 1.712 ms, max 2.141 ms |
| Overall p95 / max | 1.685 ms / 2.141 ms |

The two regimes are expected: when the query is dense, BFS stops within a
couple of levels; when few points qualify, it must exhaust the component.

## 7. Assumptions

- Coordinates are planar and Euclidean; lattice coordinates are exactly `k/99`.
- `id = row*100 + col + 1`, `row = round(lat*99)`, `col = round(long*99)`.
- Eligibility uses the raw query `(lat, long)` as the circle centre, not the snapped grid point.
- BFS traverses all nodes regardless of category; only the result filter is category-specific.
- The road file is undirected.
- Every hidden query has ≥10 reachable in-radius matches, so the early stop triggers.

## 8. Limitations

- The adjacency cache is per-process and in memory; multiple uvicorn workers
  do not share it.
- URL fetching is synchronous inside the request coroutine, so a slow link
  URL can briefly block the event loop.
- Server-side filename lookup is restricted to a bare token inside `LINKS_DIR`
  to prevent path traversal — values containing `/` or `\\` are treated as raw
  payload text, and a bare filename that does not exist returns `400`.
- An id referenced by a link but absent from the CSV is treated as a non-existent
  location (never returned, never traversed); links through it are dropped.
- Grid snapping uses Python's round-half-to-even; a query landing exactly on
  `k + 0.5` could snap differently than a half-up implementation.
- Coordinates in the CSV are stored with 6 decimals, i.e. to within `5e-7`
  of the true `k/99`; snapping is unaffected.

## 9. Change log

Two scoped correctness fixes (2026-10-09), applied test-first; no change to grid
rounding, category case sensitivity, coordinate clamping or response shape.

| # | File | Change | Reason | Evidence |
| --- | --- | --- | --- | --- |
| 1 | `app/search.py` | Use `present[]`: reject an absent start node; skip absent ids as candidates; do not enqueue absent neighbours | Absent ids defaulted to `(0,0)`/category-0 and could leak into results | New test `test_absent_ids_from_link_are_not_returned` was red (`[1,3,5]`) → green (`[1]`) |
| 2 | `app/link_parser.py` | Treat a bare filename token as a server-side file; missing → `LinkError` → HTTP 400; removed the now-unused `os` import and `_looks_like_filename`, added `_is_filename_candidate` | A missing filename silently degraded to raw text and returned `200` with an empty graph | New tests `test_missing_server_side_link_filename_returns_400`, `test_single_line_raw_link_is_not_treated_as_filename`; updated `test_resolve_link_missing_filename_raises` |

Effect on performance: none claimed. The `present` checks add a small constant
cost on the full-component path (pure BFS mean ≈1.56 ms → ≈1.89 ms); cold link
parsing (~25 ms) and cached requests (≈0.6–0.9 ms) are unchanged within noise.

