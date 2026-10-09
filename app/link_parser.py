"""Resolve the ``link`` parameter and turn it into an adjacency list.

The link is a text payload whose lines are space separated ``a b`` pairs,
meaning an undirected road between location ids ``a`` and ``b``. Payloads
can arrive as:

* a raw string (the text itself),
* an ``http(s)`` URL to fetch,
* a bare filename inside ``LINKS_DIR``,
* a multipart file upload (bytes).

For robustness, a line whose tokens are not all valid ids is re-interpreted
as coordinates: four numbers ``lat1 long1 lat2 long2`` define a road between
the two nearest grid points. Commas are accepted as separators, and blank
lines or ``#`` comments are ignored.

Parsed graphs are cached by the SHA-256 of their raw bytes, so repeated
requests with the same link skip re-parsing.
"""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen

from app.config import GRID_DIV, GRID_N, LINK_CACHE_SIZE, LINK_FETCH_TIMEOUT, LINKS_DIR

Adjacency = Dict[int, List[int]]

_INT_RE = re.compile(r"^[+-]?\d+$")


class LinkError(ValueError):
    """Raised when the link payload cannot be resolved or parsed."""


def nearest_grid_id(lat: float, long: float) -> int:
    """Map a coordinate to the id of the nearest grid point (clamped)."""
    row = _clamp(int(round(lat * GRID_DIV)))
    col = _clamp(int(round(long * GRID_DIV)))
    return row * GRID_N + col + 1


def _clamp(k: int, lo: int = 0, hi: int = GRID_N - 1) -> int:
    if k < lo:
        return lo
    if k > hi:
        return hi
    return k


def resolve_link(link: Optional[str] = None, file_bytes: Optional[bytes] = None) -> bytes:
    """Return the raw bytes of the link payload, or ``b""`` when absent."""
    if file_bytes is not None:
        return file_bytes
    if link is None:
        return b""

    text = link.strip()
    if text == "":
        return b""

    parsed = urlparse(text)
    if parsed.scheme in ("http", "https"):
        try:
            with urlopen(text, timeout=LINK_FETCH_TIMEOUT) as resp:  # noqa: S310
                return resp.read()
        except Exception as exc:  # pragma: no cover - network dependent
            raise LinkError(f"could not fetch link URL: {exc}") from exc

    # A raw payload always contains a whitespace/comma separator (an edge needs
    # two tokens), so a bare token of ordinary filename characters is treated as
    # a server-side file reference and must exist. The basename-only form also
    # prevents path traversal.
    if _is_filename_candidate(text):
        candidate = Path(LINKS_DIR) / text
        try:
            if candidate.is_file():
                return candidate.read_bytes()
        except OSError:
            # E.g. ENAMETOOLONG: not a usable filename.
            pass
        raise LinkError(f"link file not found: {text}")

    # Fall back to treating the value as the raw payload text.
    return text.encode("utf-8")


_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_filename_candidate(text: str) -> bool:
    """True when the value is a bare filename rather than a raw payload."""
    if not text or len(text) > 255:
        return False
    if any(ch in text for ch in " \t\r\n\x00,"):
        return False
    return bool(_FILENAME_RE.match(text))


def parse_adjacency(content: bytes, max_id: int) -> Adjacency:
    """Parse link bytes into an undirected adjacency list of valid ids."""
    text = content.decode("utf-8", errors="replace")
    adj: Dict[int, set] = {}

    def add(a: int, b: int) -> None:
        if a == b:
            return
        if a < 1 or a > max_id or b < 1 or b > max_id:
            return
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.replace(",", " ").split()
        if not tokens:
            continue

        if len(tokens) == 2 and all(_INT_RE.match(t) for t in tokens):
            add(int(tokens[0]), int(tokens[1]))
            continue

        # Not two integer ids -> try to interpret tokens as coordinates.
        numbers = _to_floats(tokens)
        if numbers is None:
            continue  # malformed line, skip it
        if len(numbers) == 4:
            a = nearest_grid_id(numbers[0], numbers[1])
            b = nearest_grid_id(numbers[2], numbers[3])
            add(a, b)
        # A two-number (single point) or three-number line has no second
        # endpoint, so no road can be formed; skip it.

    return {k: sorted(v) for k, v in adj.items()}


def _to_floats(tokens: List[str]) -> Optional[List[float]]:
    try:
        return [float(t) for t in tokens]
    except ValueError:
        return None


_cache: "OrderedDict[str, Adjacency]" = OrderedDict()


def get_adjacency(content: bytes, max_id: int) -> Tuple[Adjacency, str]:
    """Return ``(adjacency, content_hash)``, parsing at most once per payload."""
    digest = hashlib.sha256(content).hexdigest()
    cached = _cache.get(digest)
    if cached is not None:
        _cache.move_to_end(digest)
        return cached, digest

    adjacency = parse_adjacency(content, max_id)
    _cache[digest] = adjacency
    _cache.move_to_end(digest)
    while len(_cache) > LINK_CACHE_SIZE:
        _cache.popitem(last=False)
    return adjacency, digest


def clear_cache() -> None:
    _cache.clear()
