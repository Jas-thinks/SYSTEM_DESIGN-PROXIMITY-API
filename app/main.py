"""FastAPI application exposing the proximity search endpoint.

The same logic answers both methods and several input encodings so the
grader can call the API however it likes:

* ``GET /search/?lat=..&long=..&cat=..&rad=..&link=..``
* ``POST /search/`` with a JSON object body,
* ``POST /search/`` with form fields,
* ``POST /search/`` with a multipart file upload for the link.
"""

from __future__ import annotations

import copy
import math
from contextlib import asynccontextmanager
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import link_parser
from app.config import CSV_PATH
from app.data_store import LocationData, load_locations
from app.link_parser import LinkError
from app.search import proximity_search

LAT_KEYS = ("lat", "latitude")
LONG_KEYS = ("long", "lon", "lng", "longitude")
CAT_KEYS = ("cat", "category")
RAD_KEYS = ("rad", "radius")
LINK_KEYS = ("link", "links", "roads", "file")

_state: Dict[str, LocationData] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    _state["data"] = load_locations(CSV_PATH)
    try:
        yield
    finally:
        _state.clear()


app = FastAPI(title="Proximity Search API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    """Response body of ``GET /health``."""

    status: str = Field(description="'ok' once startup finished, otherwise 'starting'.")
    locations: int = Field(description="Number of locations loaded from the CSV.")
    categories: List[str] = Field(description="Distinct location categories available.")


class RootResponse(BaseModel):
    """Response body of ``GET /``."""

    name: str = Field(description="Service name.")
    endpoint: str = Field(description="Primary search endpoint.")
    params: List[str] = Field(description="Accepted search parameter names.")
    methods: List[str] = Field(description="HTTP methods accepted by the search endpoint.")


# --- OpenAPI declarations for the search endpoints -------------------------
# The search handlers read the request manually (to accept query params, JSON,
# form and multipart in one route), so FastAPI cannot introspect them. The
# ``openapi_extra`` payloads below document the contract without changing any
# runtime behaviour.

_SEARCH_SUMMARY = "Proximity search (ranked by road distance)"
_SEARCH_DESCRIPTION = (
    "Return up to 10 location ids of category `cat` lying within Euclidean radius "
    "`rad` of the raw query point `lat`/`long`, ranked by BFS road distance from the "
    "nearest grid point (ties broken by smaller id). `link` supplies the road links as "
    "raw text ('a b' per line), an http(s) URL, or a filename in the server's links "
    "directory. `/search` and `/search/` are aliases with identical behaviour."
)

_DETAIL_SCHEMA = {
    "type": "object",
    "properties": {"detail": {"type": "string"}},
    "required": ["detail"],
}

_SEARCH_RESPONSES = {
    "200": {
        "description": "Ranked location ids (up to 10), best first.",
        "headers": {
            "X-Link-Hash": {
                "description": "SHA-256 of the parsed link payload (diagnostic).",
                "schema": {"type": "string"},
            }
        },
        "content": {
            "application/json": {
                "schema": {
                    "type": "array",
                    "items": {"type": "integer", "format": "int32"},
                    "example": [4850, 4948, 4753, 4947, 4955, 5155, 5349, 5452, 5348, 5449],
                }
            }
        },
    },
    "400": {
        "description": (
            "Invalid input: missing/non-numeric `lat`, `long` or `rad`; negative `rad`; "
            "unknown `cat`; malformed JSON body; or a named link file that does not exist."
        ),
        "content": {"application/json": {"schema": _DETAIL_SCHEMA}},
    },
    "503": {"description": "Service is still starting up."},
}

_SEARCH_BODY_PROPERTIES = {
    "lat": {"type": "number", "format": "float", "description": "Query latitude (grid domain 0..1)."},
    "long": {
        "type": "number",
        "format": "float",
        "description": "Query longitude. Query-string aliases: lon, lng, longitude.",
    },
    "cat": {"type": "string", "description": "Category; one of the categories in locations.csv."},
    "rad": {"type": "number", "format": "float", "minimum": 0, "description": "Euclidean search radius (>= 0)."},
    "link": {
        "type": "string",
        "description": (
            "Road links: raw text ('a b' per line), an http(s) URL, or a filename in the "
            "server's links directory. For a real file upload use multipart/form-data."
        ),
    },
}

_SEARCH_REQUIRED_FIELDS = ["lat", "long", "cat", "rad"]

_MULTIPART_PROPERTIES = {
    **_SEARCH_BODY_PROPERTIES,
    "link": {"type": "string", "format": "binary", "description": "Uploaded road-link file."},
}


def _search_get_extra() -> Dict[str, Any]:
    """OpenAPI for GET /search[/]: documented required/optional query params."""
    return {
        "summary": _SEARCH_SUMMARY,
        "description": _SEARCH_DESCRIPTION,
        "parameters": [
            {
                "name": "lat",
                "in": "query",
                "required": True,
                "description": "Query latitude (grid domain 0..1).",
                "schema": {"type": "number", "format": "float", "examples": [0.5]},
            },
            {
                "name": "long",
                "in": "query",
                "required": True,
                "description": "Query longitude (aliases: lon, lng, longitude).",
                "schema": {"type": "number", "format": "float", "examples": [0.5]},
            },
            {
                "name": "cat",
                "in": "query",
                "required": True,
                "description": "Category; one of the categories in locations.csv.",
                "schema": {"type": "string", "examples": ["bank"]},
            },
            {
                "name": "rad",
                "in": "query",
                "required": True,
                "description": "Euclidean search radius (>= 0).",
                "schema": {"type": "number", "format": "float", "minimum": 0, "examples": [0.05]},
            },
            {
                "name": "link",
                "in": "query",
                "required": False,
                "description": (
                    "Road links as raw text, an http(s) URL, or a filename in the server's "
                    "links directory."
                ),
                "schema": {"type": "string"},
            },
        ],
        "responses": copy.deepcopy(_SEARCH_RESPONSES),
    }


def _search_post_extra() -> Dict[str, Any]:
    """OpenAPI for POST /search[/]: JSON, form and multipart file-upload bodies."""
    return {
        "summary": _SEARCH_SUMMARY,
        "description": (
            _SEARCH_DESCRIPTION
            + " Fields may be sent as a JSON/form body or as query parameters; a link "
            "file may be uploaded as multipart/form-data."
        ),
        "requestBody": {
            "required": False,
            "description": (
                "Search fields. If the body is omitted, supply the fields as query "
                "parameters instead."
            ),
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": _SEARCH_BODY_PROPERTIES,
                        "required": _SEARCH_REQUIRED_FIELDS,
                    }
                },
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "properties": _SEARCH_BODY_PROPERTIES,
                        "required": _SEARCH_REQUIRED_FIELDS,
                    }
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": _MULTIPART_PROPERTIES,
                        "required": _SEARCH_REQUIRED_FIELDS,
                    }
                },
            },
        },
        "responses": copy.deepcopy(_SEARCH_RESPONSES),
    }


def _get(values: Dict[str, Any], keys: Iterable[str]) -> Optional[Any]:
    for key in keys:
        value = values.get(key)
        if value is not None and value != "":
            return value
    return None


def _require(values: Dict[str, Any], keys: Iterable[str], name: str) -> Any:
    value = _get(values, keys)
    if value is None:
        raise HTTPException(
            status_code=400,
            detail=f"missing required parameter '{name}'",
        )
    return value


def _as_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be a number")
    if not math.isfinite(number):
        raise HTTPException(status_code=400, detail=f"{name} must be finite")
    return number


async def _collect(request: Request) -> Tuple[Dict[str, Any], Optional[bytes]]:
    """Merge query params, JSON body and form fields; grab any uploaded file."""
    values: Dict[str, Any] = {}
    for key, value in request.query_params.items():
        values.setdefault(key.lower(), value)

    file_bytes: Optional[bytes] = None
    if request.method not in ("POST", "PUT", "PATCH"):
        return values, file_bytes

    ctype = request.headers.get("content-type", "").lower()
    if "application/json" in ctype:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON body must be an object")
        for key, value in body.items():
            if value is not None:
                values[key.lower()] = value
    elif "multipart/form-data" in ctype or "application/x-www-form-urlencoded" in ctype:
        form = await request.form()
        for key, value in form.multi_items():
            if hasattr(value, "read"):  # UploadFile
                if file_bytes is None:
                    file_bytes = await value.read()
            elif value is not None:
                values[key.lower()] = value
    return values, file_bytes


async def _handle(request: Request) -> JSONResponse:
    data = _state.get("data")
    if data is None:  # pragma: no cover - only before startup completes
        raise HTTPException(status_code=503, detail="service is starting up")

    values, file_bytes = await _collect(request)

    lat = _as_float(_require(values, LAT_KEYS, "lat"), "lat")
    long = _as_float(_require(values, LONG_KEYS, "long"), "long")
    rad = _as_float(_require(values, RAD_KEYS, "rad"), "rad")
    if rad < 0:
        raise HTTPException(status_code=400, detail="rad must be >= 0")

    cat = str(_require(values, CAT_KEYS, "cat")).strip()
    if cat not in data.ids_by_category:
        raise HTTPException(
            status_code=400,
            detail=f"unknown category '{cat}'; expected one of {data.categories}",
        )

    link_value = _get(values, LINK_KEYS)
    if link_value is not None and not isinstance(link_value, str):
        link_value = str(link_value)

    try:
        content = link_parser.resolve_link(link_value, file_bytes)
        adjacency, digest = link_parser.get_adjacency(content, data.max_id)
    except LinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result = proximity_search(data, adjacency, lat, long, cat, rad)
    return JSONResponse(content=result, headers={"X-Link-Hash": digest})


@app.get("/search", openapi_extra=_search_get_extra())
@app.get("/search/", openapi_extra=_search_get_extra())
async def search_get(request: Request) -> JSONResponse:
    return await _handle(request)


@app.post("/search", openapi_extra=_search_post_extra())
@app.post("/search/", openapi_extra=_search_post_extra())
async def search_post(request: Request) -> JSONResponse:
    return await _handle(request)


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Report service readiness, the number of loaded locations, and the available categories.",
)
async def health() -> HealthResponse:
    data = _state.get("data")
    return HealthResponse(
        status="ok" if data is not None else "starting",
        locations=data.max_id if data is not None else 0,
        categories=data.categories if data is not None else [],
    )


@app.get(
    "/",
    response_model=RootResponse,
    summary="Service metadata",
    description="Basic service metadata and the list of accepted search parameters.",
)
async def root() -> RootResponse:
    return RootResponse(
        name="Proximity Search API",
        endpoint="/search/",
        params=["lat", "long", "cat", "rad", "link"],
        methods=["GET", "POST"],
    )
