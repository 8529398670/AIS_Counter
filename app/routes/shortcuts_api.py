"""The API docs for AIS Counter's own keyboard shortcuts route
(account.set_shortcuts): config/openapi.json and config/api.md are written
from these by scripts/api_docs.sh (see app/apidocs). The template's shortcuts
part is not used here; this app stores each action's list of keys."""
from __future__ import annotations

from typing import Annotated, NotRequired, TypedDict

from app.apidocs import Field, doc
from app.routes import account


class SetShortcutsBody(TypedDict):
    csrf_token: NotRequired[Annotated[str, Field(doc="From GET /api/me. Browser sessions only.")]]
    shortcuts: Annotated[dict[str, list[str]], Field(doc="Action id to the keys bound to it. Replaces the whole map; {} puts every key back to its default. Action ids the screens do not know are ignored.")]


class OkReply(TypedDict):
    ok: bool


doc(
    account.set_shortcuts,
    summary="Save your rebound keyboard shortcuts",
    tag="Account",
    description="Replace the caller's rebound keyboard shortcuts with the map sent (static/js/shortcuts.js sends the whole map on every change).",
    body=SetShortcutsBody,
    reply=OkReply,
    errors=(400, 401, 403),
)
