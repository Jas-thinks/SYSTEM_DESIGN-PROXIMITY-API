"""Unit tests for link parsing, resolution and caching."""

import pytest

from app import link_parser
from app.link_parser import (
    LinkError,
    clear_cache,
    get_adjacency,
    nearest_grid_id,
    parse_adjacency,
    resolve_link,
)

MAX_ID = 10000


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_cache()
    yield
    clear_cache()


def test_parse_id_pairs_undirected():
    adj = parse_adjacency(b"1 2\n2 3\n", MAX_ID)
    assert adj == {1: [2], 2: [1, 3], 3: [2]}


def test_parse_accepts_commas_comments_and_blank_lines():
    content = b"# roads\n\n1,2\n3 4\n"
    assert parse_adjacency(content, MAX_ID) == {1: [2], 2: [1], 3: [4], 4: [3]}


def test_parse_coordinate_lines_fall_back_to_grid_points():
    # two coordinates: (0,0) -> id 1 ; (0, 1/99) -> id 2
    content = b"0.0 0.0 0.0 0.010101010101\n"
    assert parse_adjacency(content, MAX_ID) == {1: [2], 2: [1]}


def test_parse_out_of_range_ids_are_dropped():
    assert parse_adjacency(b"1 99999\n", MAX_ID) == {}
    assert parse_adjacency(b"0 1\n", MAX_ID) == {}


def test_parse_self_loops_are_dropped():
    assert parse_adjacency(b"3 3\n", MAX_ID) == {}


def test_parse_malformed_lines_are_skipped():
    content = b"hello world\n1 2\n0.1 0.2\n3\n"
    assert parse_adjacency(content, MAX_ID) == {1: [2], 2: [1]}


def test_nearest_grid_id_clamps():
    assert nearest_grid_id(0.0, 0.0) == 1
    assert nearest_grid_id(1.0, 1.0) == 10000
    assert nearest_grid_id(-1.0, -1.0) == 1
    assert nearest_grid_id(5.0, 5.0) == 10000


def test_resolve_link_raw_text_and_empty():
    assert resolve_link("1 2") == b"1 2"
    assert resolve_link(None) == b""
    assert resolve_link("   ") == b""


def test_resolve_link_prefers_uploaded_file_bytes():
    assert resolve_link("1 2", b"5 6") == b"5 6"


def test_resolve_link_server_side_filename(tmp_path, monkeypatch):
    (tmp_path / "roads.txt").write_text("7 8")
    monkeypatch.setattr(link_parser, "LINKS_DIR", tmp_path)
    assert resolve_link("roads.txt") == b"7 8"


def test_resolve_link_long_raw_text_with_existing_links_dir(tmp_path, monkeypatch):
    # Regression: a long raw-text payload must not be treated as a filename
    # (which would raise ENAMETOOLONG when LINKS_DIR exists).
    monkeypatch.setattr(link_parser, "LINKS_DIR", tmp_path)
    multiline = "\n".join(f"1 {k}" for k in range(2, 300))
    assert resolve_link(multiline) == multiline.encode("utf-8")
    single_line = "1 " + " ".join(["2"] * 300)  # > 255 chars, no newline
    assert resolve_link(single_line) == single_line.encode("utf-8")


def test_resolve_link_missing_filename_raises():
    # A bare filename that does not exist must be reported, not silently
    # treated as raw payload text.
    with pytest.raises(LinkError):
        resolve_link("no_such_file.txt")


def test_resolve_link_unreachable_url_raises(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr(link_parser, "urlopen", boom)
    with pytest.raises(LinkError):
        resolve_link("http://example.invalid/roads.txt")


def test_adjacency_cache_returns_same_object():
    first, h1 = get_adjacency(b"1 2", MAX_ID)
    second, h2 = get_adjacency(b"1 2", MAX_ID)
    assert first is second
    assert h1 == h2
    third, h3 = get_adjacency(b"1 3", MAX_ID)
    assert h3 != h1
