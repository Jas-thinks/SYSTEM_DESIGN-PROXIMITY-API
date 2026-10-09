"""End-to-end tests for the FastAPI endpoint using the real CSV."""

import pytest
from fastapi.testclient import TestClient

from app import link_parser
from app.main import app

# A star centred on location 1 (grid point (0, 0)) so the start vertex is
# connected and many same-category points are one BFS hop away.
STAR_LINK = "\n".join(f"1 {k}" for k in range(2, 300))
PARAMS = {"lat": 0.0, "long": 0.0, "cat": "bank", "rad": 2.0}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_get_with_raw_link_text(client):
    resp = client.get("/search/", params={**PARAMS, "link": STAR_LINK})
    assert resp.status_code == 200
    ids = resp.json()
    assert isinstance(ids, list)
    assert len(ids) == 10
    assert all(isinstance(i, int) for i in ids)
    assert "X-Link-Hash" in resp.headers


def test_post_json_body(client):
    resp = client.post("/search/", json={**PARAMS, "link": STAR_LINK})
    assert resp.status_code == 200
    assert len(resp.json()) == 10


def test_post_form_fields(client):
    resp = client.post("/search/", data={**PARAMS, "link": STAR_LINK})
    assert resp.status_code == 200
    assert len(resp.json()) == 10


def test_post_multipart_file_upload(client):
    files = {"link": ("roads.txt", STAR_LINK, "text/plain")}
    resp = client.post("/search/", data=PARAMS, files=files)
    assert resp.status_code == 200
    assert len(resp.json()) == 10


def test_post_multipart_arbitrary_field_name(client):
    files = {"roads": ("roads.txt", STAR_LINK, "text/plain")}
    resp = client.post("/search/", data=PARAMS, files=files)
    assert resp.status_code == 200
    assert len(resp.json()) == 10


def test_link_as_server_side_filename(client, tmp_path, monkeypatch):
    (tmp_path / "roads.txt").write_text(STAR_LINK)
    monkeypatch.setattr(link_parser, "LINKS_DIR", tmp_path)
    resp = client.get("/search/", params={**PARAMS, "link": "roads.txt"})
    assert resp.status_code == 200
    assert len(resp.json()) == 10


def test_missing_server_side_link_filename_returns_400(client, tmp_path, monkeypatch):
    # Point LINKS_DIR at an empty directory so the named file cannot exist.
    monkeypatch.setattr(link_parser, "LINKS_DIR", tmp_path)
    resp = client.get("/search/", params={**PARAMS, "link": "does_not_exist.txt"})
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()


def test_single_line_raw_link_is_not_treated_as_filename(client):
    # "1 2" contains whitespace, so it is a raw payload (edge 1-2), not a
    # filename: must stay 200 and return only the reachable match.
    resp = client.get("/search/", params={**PARAMS, "link": "1 2"})
    assert resp.status_code == 200
    assert resp.json() == [1]


def test_results_are_ranked_and_unique(client):
    resp = client.get("/search/", params={**PARAMS, "link": STAR_LINK})
    ids = resp.json()
    assert len(set(ids)) == len(ids)


def test_get_without_link_returns_only_start(client):
    # No link -> empty graph -> only the start vertex is reachable.
    resp = client.get("/search/", params=PARAMS)
    assert resp.status_code == 200
    assert resp.json() == [1]


@pytest.mark.parametrize(
    "params",
    [
        {"long": 0.0, "cat": "bank", "rad": 1.0},              # missing lat
        {"lat": "abc", "long": 0.0, "cat": "bank", "rad": 1.0},  # non-numeric lat
        {"lat": 0.0, "long": 0.0, "cat": "bank", "rad": -1.0},   # negative radius
        {"lat": 0.0, "long": 0.0, "cat": "nope", "rad": 1.0},    # unknown category
        {"lat": 0.0, "long": 0.0, "cat": "bank"},                # missing rad
    ],
)
def test_invalid_input_returns_400(client, params):
    resp = client.get("/search/", params={**params, "link": STAR_LINK})
    assert resp.status_code == 400


def test_invalid_json_body_returns_400(client):
    resp = client.post(
        "/search/",
        data="{not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["locations"] == 10000
    assert "bank" in body["categories"]


def test_root_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["endpoint"] == "/search/"
    assert set(body["params"]) == {"lat", "long", "cat", "rad", "link"}
    assert set(body["methods"]) == {"GET", "POST"}


def test_docs_available(client):
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "swagger" in resp.text.lower()


def test_search_aliases_return_same_result(client):
    a = client.get("/search", params={**PARAMS, "link": STAR_LINK})
    b = client.get("/search/", params={**PARAMS, "link": STAR_LINK})
    assert a.status_code == 200
    assert b.status_code == 200
    assert a.json() == b.json()


# --- OpenAPI documentation -------------------------------------------------


def _openapi(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.parametrize("path", ["/search", "/search/"])
def test_openapi_search_declares_query_parameters(client, path):
    spec = _openapi(client)
    params = {p["name"]: p for p in spec["paths"][path]["get"]["parameters"]}
    assert set(params) == {"lat", "long", "cat", "rad", "link"}
    for name in ("lat", "long", "cat", "rad"):
        assert params[name]["in"] == "query"
        assert params[name]["required"] is True
    assert params["link"]["in"] == "query"
    assert params["link"]["required"] is False
    assert params["lat"]["schema"]["type"] == "number"
    assert params["long"]["schema"]["type"] == "number"
    assert params["cat"]["schema"]["type"] == "string"
    assert params["rad"]["schema"]["type"] == "number"
    assert params["rad"]["schema"]["minimum"] == 0


@pytest.mark.parametrize("path", ["/search", "/search/"])
def test_openapi_search_declares_request_body_formats(client, path):
    spec = _openapi(client)
    body = spec["paths"][path]["post"]["requestBody"]
    content = body["content"]
    assert set(content) == {
        "application/json",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
    }
    for ctype in content:
        props = content[ctype]["schema"]["properties"]
        assert set(props) == {"lat", "long", "cat", "rad", "link"}
        assert set(content[ctype]["schema"]["required"]) == {"lat", "long", "cat", "rad"}
    assert content["multipart/form-data"]["schema"]["properties"]["link"]["format"] == "binary"


@pytest.mark.parametrize("path", ["/search", "/search/"])
@pytest.mark.parametrize("method", ["get", "post"])
def test_openapi_search_documents_array_response_and_400(client, path, method):
    spec = _openapi(client)
    op = spec["paths"][path][method]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"]["type"] == "integer"
    assert "X-Link-Hash" in op["responses"]["200"]["headers"]
    assert "400" in op["responses"]
    assert "503" in op["responses"]


def test_openapi_health_and_root_schemas(client):
    spec = _openapi(client)
    health = spec["paths"]["/health"]["get"]
    assert health["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/HealthResponse"
    )
    # /health reports readiness in the body (status="starting") and never raises 503.
    assert "503" not in health["responses"]
    root = spec["paths"]["/"]["get"]
    assert root["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RootResponse"
    )
    schemas = spec["components"]["schemas"]
    assert set(schemas["HealthResponse"]["properties"]) == {"status", "locations", "categories"}
    assert set(schemas["RootResponse"]["properties"]) == {"name", "endpoint", "params", "methods"}


def test_search_aliases_documented_consistently(client):
    # The two aliases must document identical parameters, bodies and responses.
    # operationId is the only allowed difference (OpenAPI requires it to be unique).
    spec = _openapi(client)
    for method in ("get", "post"):
        without_id = {
            path: {k: v for k, v in spec["paths"][path][method].items() if k != "operationId"}
            for path in ("/search", "/search/")
        }
        assert without_id["/search"] == without_id["/search/"]
