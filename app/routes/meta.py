"""Public endpoints that are about the app rather than about anyone in it."""
from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, Response


async def get_language(request: Request) -> Response:
    """The whole language.yaml tree as JSON. Deliberately public: the
    signed-out page has text too, and none of it is secret. Do not put
    anything sensitive in language.yaml -- it is, by design, readable by
    anyone who can reach the server."""
    return Response(
        request.app.state.language.json,
        media_type="application/json",
        headers={"cache-control": "no-store"},
    )


async def get_health(request: Request) -> Response:
    """What the Dockerfile HEALTHCHECK hits. Trivial on purpose -- if it
    touched the database, a slow query would get the container killed and
    restarted, turning a small problem into an outage."""
    return JSONResponse({"ok": True})


# The About screen renders this, so the report has one copy: the one in docs/.
REPORT = Path(__file__).resolve().parents[2] / "docs" / "ais_auto_report.md"


async def get_report(request: Request) -> Response:
    """docs/ais_auto_report.md as {"markdown": ...}, for the About screen.
    Read on every call so an edited report shows without a restart."""
    try:
        text = REPORT.read_text(encoding="utf-8")
    except OSError:
        return JSONResponse({"error": "report not found"}, status_code=404)
    return JSONResponse({"markdown": text}, headers={"cache-control": "no-store"})


async def unknown_api(request: Request) -> Response:
    """An /api/ path nothing claims. Without this the static catch-all would
    answer with index.html and a 200, which is a confusing reply to a script
    that mistyped an endpoint."""
    return JSONResponse({"error": "not found"}, status_code=404)
