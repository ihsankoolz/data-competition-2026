"""SAP Business One Service Layer mock (port 8001, base path /b1s/v2). Contract: D-004, D-014.

In-memory store. `create_app()` returns a fresh app so each test starts clean. Session expiry
uses an injectable time source (seconds, monotonic) because this mock imitates an external
system and must not depend on the API's simulated clock.

Error codes marked [unverified] are our best reading of the Service Layer, per D-004/D-014:
validation 400 / -10, duplicate key 400 / -5002, session 401 / 301, entity not found
404 / -2028, login failure 401 / -304.

Domain rule 5: request bodies (which may contain bank fields) are never logged, and
validation errors never echo the submitted values.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from services.sap_mock.models import (
    BusinessPartner,
    Item,
    LoginRequest,
    ProfitCenter,
)

BASE_PATH = "/b1s/v2"
SESSION_TIMEOUT_MINUTES = 30
SESSION_COOKIE = "B1SESSION"
ROUTE_COOKIE = "ROUTEID"
ROUTE_ID = ".node1"
SERVICE_VERSION = "1000190"


class B1Error(Exception):
    """Raised anywhere; rendered in the Service Layer error shape."""

    def __init__(self, status: int, code: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: int, message: str) -> JSONResponse:
    body = {"error": {"code": code, "message": {"lang": "en-us", "value": message}}}
    return JSONResponse(status_code=status, content=body)


@dataclass(frozen=True)
class Resource:
    name: str
    key_field: str
    model: type[BaseModel]


RESOURCES = [
    Resource("BusinessPartners", "CardCode", BusinessPartner),
    Resource("Items", "ItemCode", Item),
    Resource("ProfitCenters", "CenterCode", ProfitCenter),
]


def _describe_validation(resource: str, exc: ValidationError) -> str:
    # Only location + message: never `input`, which could contain bank details.
    parts = []
    for err in exc.errors(include_input=False, include_url=False, include_context=False):
        loc = ".".join(str(x) for x in err["loc"]) or "body"
        parts.append(f"Property '{loc}' of '{resource}' is invalid: {err['msg']}")
    return "; ".join(parts)


# --- $filter: `field eq 'x'`, `field eq 5`, `contains(field,'x')`, joined with `and` ---

_STR = r"'((?:[^']|'')*)'"
_CLAUSE = re.compile(
    rf"\s*(?:contains\(\s*(?P<cf>\w+)\s*,\s*{_STR}\s*\)"
    rf"|(?P<ef>\w+)\s+eq\s+(?:{_STR}|(?P<num>-?\d+(?:\.\d+)?)))\s*",
)


def parse_filter(expr: str, allowed: set[str]) -> list[Callable[[dict[str, Any]], bool]]:
    preds: list[Callable[[dict[str, Any]], bool]] = []
    pos = 0
    while pos < len(expr):
        m = _CLAUSE.match(expr, pos)
        if not m:
            raise B1Error(400, -10, f"Invalid $filter expression: {expr}")
        pos = m.end()
        field = m.group("cf") or m.group("ef")
        if field not in allowed:
            raise B1Error(400, -10, f"Property '{field}' is not filterable")
        if m.group("cf"):
            needle = m.group(2).replace("''", "'").lower()
            preds.append(
                lambda r, f=field, n=needle: n in str(r.get(f, "")).lower(),
            )
        else:
            if m.group("num") is not None:
                want: Any = float(m.group("num"))
                preds.append(
                    lambda r, f=field, w=want: (
                        isinstance(r.get(f), (int, float)) and float(r[f]) == w
                    ),
                )
            else:
                want = m.group(4).replace("''", "'")
                preds.append(lambda r, f=field, w=want: r.get(f) == w)
        if pos < len(expr):
            rest = re.compile(r"\s*and\s+", re.IGNORECASE).match(expr, pos)
            if not rest:
                raise B1Error(400, -10, f"Invalid $filter expression: {expr}")
            pos = rest.end()
            if pos >= len(expr):
                raise B1Error(400, -10, f"Invalid $filter expression: {expr}")
    return preds


def _int_param(request: Request, name: str) -> int | None:
    raw = request.query_params.get(name)
    if raw is None:
        return None
    if not raw.isdigit():
        raise B1Error(400, -10, f"Invalid value for {name}")
    return int(raw)


def create_app(clock: Callable[[], float] | None = None) -> FastAPI:
    """Build a mock instance. `clock` returns seconds; tests pass a fake to skip real waiting."""
    now = clock or time.monotonic
    company_db = os.environ.get("SAP_COMPANY_DB", "LIVES_DEMO")
    user = os.environ.get("SAP_USER", "mdm_integration")
    password = os.environ.get("SAP_PASSWORD", "demo")

    sessions: dict[str, float] = {}  # session id -> last activity
    stores: dict[str, dict[str, dict[str, Any]]] = {r.name: {} for r in RESOURCES}

    app = FastAPI(title="SAP B1 Service Layer mock", version="0.1.0")
    app.state.sessions = sessions
    app.state.stores = stores
    router = APIRouter(prefix=BASE_PATH)

    # ---- errors in B1 shape ----
    @app.exception_handler(B1Error)
    async def _b1(_: Request, exc: B1Error) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Replaces FastAPI's default 422. Never echo input values.
        msgs = [
            f"Property '{'.'.join(str(x) for x in e['loc'][1:])}' is invalid: {e['msg']}"
            for e in exc.errors()
        ]
        return error_response(400, -10, "; ".join(msgs))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(exc.status_code, -1, str(exc.detail))

    # ---- session handling ----
    def require_session(request: Request) -> str:
        sid = request.cookies.get(SESSION_COOKIE)
        route = request.cookies.get(ROUTE_COOKIE)
        if not sid or not route or sid not in sessions:
            raise B1Error(401, 301, "Invalid session.")
        if now() - sessions[sid] > SESSION_TIMEOUT_MINUTES * 60:
            del sessions[sid]
            raise B1Error(401, 301, "Invalid session or session already timeout.")
        sessions[sid] = now()
        return sid

    async def read_json_object(request: Request) -> dict[str, Any]:
        try:
            data = json.loads(await request.body())
        except ValueError:
            raise B1Error(400, -10, "Request body is not valid JSON.") from None
        if not isinstance(data, dict):
            raise B1Error(400, -10, "Request body must be a JSON object.")
        return data

    def validate(model: type[BaseModel], resource: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            # JSON mode + strict: no coercion (a string is never accepted as an int, etc.)
            obj = model.model_validate_json(json.dumps(data), strict=True)
        except ValidationError as exc:
            raise B1Error(400, -10, _describe_validation(resource, exc)) from None
        return obj.model_dump(mode="json", exclude_none=True)

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "sap_mock"}

    @router.post("/Login")
    async def login(request: Request) -> Response:
        data = await read_json_object(request)
        try:
            creds = LoginRequest.model_validate_json(json.dumps(data), strict=True)
        except ValidationError as exc:
            raise B1Error(400, -10, _describe_validation("Login", exc)) from None
        if (creds.CompanyDB, creds.UserName, creds.Password) != (company_db, user, password):
            raise B1Error(401, -304, "Fail to get DB credentials from DB.")
        sid = str(uuid.uuid4())
        sessions[sid] = now()
        resp = JSONResponse(
            {
                "SessionId": sid,
                "Version": SERVICE_VERSION,
                "SessionTimeout": SESSION_TIMEOUT_MINUTES,
            }
        )
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, path="/")
        resp.set_cookie(ROUTE_COOKIE, ROUTE_ID, path="/")
        return resp

    @router.post("/Logout")
    def logout(request: Request) -> Response:
        sid = require_session(request)
        del sessions[sid]
        resp = Response(status_code=204)
        resp.delete_cookie(SESSION_COOKIE, path="/")
        resp.delete_cookie(ROUTE_COOKIE, path="/")
        return resp

    def register(res: Resource) -> None:
        store = stores[res.name]
        fields = set(res.model.model_fields)
        scalar_fields = {
            n for n, f in res.model.model_fields.items() if "list" not in str(f.annotation)
        }

        def not_found() -> B1Error:
            return B1Error(404, -2028, "No matching records found (ODBC -2028)")

        async def create(request: Request) -> Response:
            require_session(request)
            entity = validate(res.model, res.name, await read_json_object(request))
            key = entity[res.key_field]
            if key in store:
                raise B1Error(
                    400,
                    -5002,
                    "This entry already exists in the following tables: "
                    f"{res.name} ({res.key_field}='{key}')",
                )
            store[key] = entity
            return JSONResponse(entity, status_code=201)

        async def list_(request: Request) -> Response:
            require_session(request)
            rows = list(store.values())
            expr = request.query_params.get("$filter")
            if expr:
                preds = parse_filter(expr, scalar_fields)
                rows = [r for r in rows if all(p(r) for p in preds)]
            skip = _int_param(request, "$skip") or 0
            top = _int_param(request, "$top")
            rows = rows[skip : skip + top if top is not None else None]
            select = request.query_params.get("$select")
            if select:
                cols = [c.strip() for c in select.split(",") if c.strip()]
                bad = [c for c in cols if c not in fields]
                if bad:
                    raise B1Error(400, -10, f"Property '{bad[0]}' of '{res.name}' is invalid")
                rows = [{c: r[c] for c in cols if c in r} for r in rows]
            return JSONResponse({"value": rows})

        async def get_one(key: str, request: Request) -> Response:
            require_session(request)
            if key not in store:
                raise not_found()
            return JSONResponse(store[key])

        async def patch_one(key: str, request: Request) -> Response:
            require_session(request)
            patch = await read_json_object(request)
            if key not in store:
                raise not_found()
            if patch.get(res.key_field, key) != key:
                raise B1Error(400, -10, f"Property '{res.key_field}' of '{res.name}' is read-only")
            store[key] = validate(res.model, res.name, {**store[key], **patch})
            return Response(status_code=204)

        router.add_api_route(f"/{res.name}", create, methods=["POST"], status_code=201)
        router.add_api_route(f"/{res.name}", list_, methods=["GET"])
        router.add_api_route(f"/{res.name}('{{key}}')", get_one, methods=["GET"])
        router.add_api_route(
            f"/{res.name}('{{key}}')", patch_one, methods=["PATCH"], status_code=204
        )

    for resource in RESOURCES:
        register(resource)

    app.include_router(router)
    return app


app = create_app()
