"""The URL map -- the only place that knows every route this server answers.
Read build_routes top to bottom to see the whole surface.

The API stays deliberately small: it covers logging in, managing who can log
in, issuing the API keys that let non-browser callers in, and reading the UI's
text. Everything else an app does belongs in a new module in this package
(server side) and in static/js/ (browser side) -- see
references/architecture.md for where the line sits and why.

Protection comes from where a route is registered. group() attaches guards to
each route it builds, so a protected route cannot be written without its
guard, and the list below is a complete statement of who may call what.
Guards attach per route (Starlette's Route(middleware=...)), not per path
prefix, so a group never leaks onto routes outside it.
"""
from __future__ import annotations

from typing import Callable, Sequence

from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Route

from app.core.config import Config
from app.core.security import RequireAdmin, RequireLogin, RequireSession
from app.core.security import Guard
from app.core.security import RequireOwner
from app.core.security import RequireAPIKey, RequireHelperKey
from app.core.static_files import StaticServer
from app.mcp.protocol import Server as MCPServer
from app.routes import (
    account,
    admin,
    ais,
    ais_matlab,
    api_keys,
    auth,
    invite_links,
    jobs,
    join,
    logs,
    mcp_tools,
    meta,
    openapi,
    passwords,
    sessions,
    settings,
    team,
    themes,
    two_factor,
)
from app.routes.api_keys import RequireAPIKeys
from app.routes.helpers import get_config, not_found


class RequireMCP(Guard):
    """Makes /mcp answer 404 while server.mcp or auth.api_keys is off --
    exactly what an unregistered route would say. Checked per request rather
    than by registering /mcp or not, because both can be switched while the
    server runs."""

    def refuse(self, request: Request) -> Response | None:
        cfg = get_config(request)
        if not cfg.mcp_enabled or not cfg.api_keys_enabled:
            return not_found("not found")
        return None


class RequirePasswords(Guard):
    """Makes every password route answer 404 while auth.passwords is off.
    Per request, for the same reason as RequireMCP."""

    def refuse(self, request: Request) -> Response | None:
        return None if get_config(request).passwords_enabled else not_found("not found")


class RequireTwoFactor(Guard):
    """The same for setting up 2FA while auth.two_factor is off. Finishing a
    sign-in is not behind this: one already under way may as well end."""

    def refuse(self, request: Request) -> Response | None:
        return None if get_config(request).two_factor_enabled else not_found("not found")


class RequireInviteLinks(Guard):
    """Makes every invite route answer 404 while auth.invite_links is off. Per
    request, for the same reason as RequireMCP. The /join page itself is
    StaticServer.serve_join_page, so a person gets the styled 404 instead."""

    def refuse(self, request: Request) -> Response | None:
        return None if get_config(request).invite_links_enabled else not_found("not found")


def group(*guards: type) -> Callable[..., Route]:
    """A route builder whose routes all run behind the given guards, in
    order. Usage: signed_in = group(RequireLogin); signed_in("/api/me", me)."""
    middleware = [Middleware(guard) for guard in guards]

    def route(path: str, endpoint: Callable, methods: Sequence[str] = ("GET",), max_body_size: int | None = None) -> Route:
        return Route(path, endpoint, methods=list(methods), middleware=middleware, max_body_size=max_body_size)

    return route


def build_routes(static_server: StaticServer, cfg: Config) -> list[BaseRoute]:
    """cfg is the configuration the server started with: it decides only
    what is set up once (the activity log's routes). Everything a request
    reads, it reads from the running configuration."""
    public = group()
    # Joining through an invite link: holding the link is the permission.
    public_invites = group(RequireInviteLinks)
    signed_in = group(RequireLogin)
    sessions_only = group(RequireLogin, RequireSession)
    pin_sessions = group(RequireInviteLinks, RequireLogin, RequireSession)
    # API keys: any signed-in user manages their own, from a browser session.
    my_keys = group(RequireAPIKeys, RequireLogin, RequireSession)
    # Admin only: deciding who gets in.
    admins = group(RequireAdmin)
    # The two admin routes that hand out a login link also require a browser
    # session. A login link becomes a session, and a session can mint API
    # keys -- so if an admin-scoped key could create accounts or reissue
    # links, a leaked key could turn itself into a fresh session and a fresh
    # key, and revoking the leaked one would not end the compromise. The rule
    # is: an API key may use what an account can do, but it never creates
    # credentials. See RequireSession.
    #
    # Deleting an account requires a session too, for a different reason: it
    # cannot be undone. A leaked admin key can disable accounts, which an
    # admin can reverse; it must not be able to erase them. Who may delete
    # whom (the owner rules) is enforced in credentials.delete_user.
    admin_sessions = group(RequireAdmin, RequireSession)
    admin_invites = group(RequireInviteLinks, RequireAdmin)
    admin_invite_sessions = group(RequireInviteLinks, RequireAdmin, RequireSession)
    # Admin view of every key in the app -- "who has standing access" -- and
    # the ability to revoke or delete someone else's.
    admin_keys = group(RequireAPIKeys, RequireAdmin, RequireSession)
    # The activity log and the Settings screen: the owner only, from a
    # browser session -- not other admins, not any API key, not the signed
    # out; all of them get 404 (see RequireOwner).
    owner = group(RequireOwner)
    # Passwords and 2FA change how an account signs in, so setting them needs
    # a browser session, like the PIN: a key that could set a password could
    # turn itself into a session.
    password_login = group(RequirePasswords)
    my_password = group(RequirePasswords, RequireLogin, RequireSession)
    owner_passwords = group(RequirePasswords, RequireOwner)
    my_two_factor = group(RequireTwoFactor, RequireLogin, RequireSession)

    routes: list[BaseRoute] = [
        # Public: the login link's page and the call it makes, the UI's text
        # (needed to render the signed-out page at all), and the healthcheck.
        # Opening a login link only shows a page; the link is spent by the
        # POST that page sends when the person confirms. See auth.py.
        public("/login/{credential:path}", static_server.serve_login_page),
        public("/api/login", auth.redeem_login_link, ["POST"]),
        public("/api/login/options", passwords.login_options),
        public("/api/login/two-factor", two_factor.finish_sign_in, ["POST"]),
        password_login("/api/login/password", passwords.password_login, ["POST"]),
        public("/api/language", meta.get_language),
        public("/api/health", meta.get_health),
        public("/api/ready", meta.get_ready),
        # Public: invite links (see join.py). Holding the link is the
        # permission; like a login link, the GET only serves the page.
        public("/join/{credential:path}", static_server.serve_join_page),
        public_invites("/api/join/info", join.join_info, ["POST"]),
        public_invites("/api/join/match", join.join_match, ["POST"]),
        public_invites("/api/join/claim", join.join_claim, ["POST"]),
        public_invites("/api/join/create", join.join_create, ["POST"]),
        # Any signed-in user.
        signed_in("/api/me", account.me),
        signed_in("/api/account/rename", account.rename, ["POST"]),
        signed_in("/api/account/shortcuts", account.set_shortcuts, ["POST"]),
        signed_in("/api/account/themes", themes.set_my_themes, ["POST"]),
        signed_in("/api/account/theme", themes.set_my_theme, ["POST"]),
        # A session only: a PIN lets its holder sign in through an invite
        # link, so a key that could set one could turn itself into a session.
        pin_sessions("/api/account/pin", account.set_pin, ["POST"]),
        # A session only: this path decides what this person's zips execute.
        sessions_only("/api/account/matlab", account.set_matlab_path, ["POST"]),
        # A session only, for the same reason as every route that hands out
        # a login link: the link becomes a session. See admin_sessions above.
        sessions_only("/api/account/login-link", account.create_my_login_link, ["POST"]),
        signed_in("/api/account/login-link/cancel", account.cancel_my_login_link, ["POST"]),
        # The account's own sessions. A session only: a key has none, and
        # signing devices out is a person's decision.
        sessions_only("/api/account/sessions", sessions.list_my_sessions),
        sessions_only("/api/account/sessions/revoke-others", sessions.revoke_others, ["POST"]),
        sessions_only("/api/account/sessions/{session_id}/label", sessions.label_one, ["POST"]),
        sessions_only("/api/account/sessions/{session_id}/revoke", sessions.revoke_one, ["POST"]),
        my_password("/api/account/password", passwords.set_password, ["POST"]),
        my_two_factor("/api/account/two-factor/start", two_factor.start_setup, ["POST"]),
        my_two_factor("/api/account/two-factor/confirm", two_factor.confirm_setup, ["POST"]),
        my_two_factor("/api/account/two-factor/disable", two_factor.disable, ["POST"]),
        signed_in("/api/logout", account.logout, ["POST"]),
        signed_in("/api/team", team.list_team),
        signed_in("/api/openapi.json", openapi.get_openapi),
        # The About screen's copy of docs/ais_auto_report.md.
        signed_in("/api/about/report", meta.get_report),
        # AIS analysis (app/routes/ais.py): files, tracing, and the batches and
        # accepted AIS every signed-in user shares.
        signed_in("/api/ais/files", ais.upload, ["POST"], max_body_size=ais.UPLOAD_LIMIT_BYTES),
        signed_in("/api/ais/files/{sha}/view.png", ais.view),
        signed_in("/api/ais/files/{sha}/thumb.png", ais.thumb),
        signed_in("/api/ais/files/{sha}/channels", ais.channels),
        signed_in("/api/ais/files/{sha}/channel/{index}.png", ais.channel),
        signed_in("/api/ais/files/{sha}/slice/{index}.png", ais.slice_view),
        signed_in("/api/ais/files/{sha}/composite.png", ais.composite),
        signed_in("/api/ais/files/{sha}/somata", ais.somata),
        signed_in("/api/ais/files/{sha}/file", ais.file_bytes),
        signed_in("/api/ais/files/{sha}/processed.tif", ais.processed_tif),
        signed_in("/api/ais/files/{sha}/channel/{index}.tif", ais.channel_tif),
        signed_in("/api/ais/trace", ais.trace, ["POST"]),
        signed_in("/api/ais/detect", ais.detect, ["POST"]),
        signed_in("/api/ais/batches", ais.batch_list),
        signed_in("/api/ais/batches", ais.batch_create, ["POST"]),
        # A folder's manifest is the whole of it: thousands of slices fill the default limit.
        signed_in("/api/ais/batches/upload", ais.batch_upload, ["POST"], max_body_size=ais.UPLOAD_LIMIT_BYTES),
        # The team's priority order: admins.
        admins("/api/ais/batches/order", ais.batch_order, ["POST"]),
        # The team's folders, and filing batches in them: everyone sees them, admins change them.
        admins("/api/ais/batches/move", ais.batch_move, ["POST"]),
        signed_in("/api/ais/folders", ais.folder_list),
        admins("/api/ais/folders", ais.folder_create, ["POST"]),
        admins("/api/ais/folders/order", ais.folder_order, ["POST"]),
        admins("/api/ais/folders/{folder_id}/rename", ais.folder_rename, ["POST"]),
        admins("/api/ais/folders/{folder_id}/move", ais.folder_move, ["POST"]),
        admins("/api/ais/folders/{folder_id}/delete", ais.folder_delete, ["POST"]),
        # Backups hold the original names: admins.
        admins("/api/ais/batches/import", ais.batch_import, ["POST"], max_body_size=ais.UPLOAD_LIMIT_BYTES),
        admins("/api/ais/batches/import/missing", ais.batch_import_missing, ["POST"],
               max_body_size=ais.UPLOAD_LIMIT_BYTES),
        admins("/api/ais/batches/{batch_id}/backup", ais.batch_backup),
        signed_in("/api/ais/batches/{batch_id}", ais.batch_get),
        signed_in("/api/ais/batches/{batch_id}/status", ais.batch_status),
        signed_in("/api/ais/batches/{batch_id}/channels", ais.batch_channels),
        signed_in("/api/ais/batches/{batch_id}/upload", ais.batch_add, ["POST"], max_body_size=ais.UPLOAD_LIMIT_BYTES),
        signed_in("/api/ais/batches/{batch_id}/rename", ais.batch_rename, ["POST"]),
        signed_in("/api/ais/batches/{batch_id}/archive", ais.batch_archive, ["POST"]),
        signed_in("/api/ais/batches/{batch_id}/activity", ais.batch_activity, ["POST"]),
        signed_in("/api/ais/batches/{batch_id}/done", ais.batch_done, ["POST"]),
        signed_in("/api/ais/batches/{batch_id}/include", ais.batch_include, ["POST"]),
        signed_in("/api/ais/batches/{batch_id}/delete", ais.batch_delete, ["POST"]),
        # Admins: splitting a batch among people, and resetting its results.
        admins("/api/ais/batches/{batch_id}/assign", ais.batch_assign, ["POST"]),
        admins("/api/ais/batches/{batch_id}/reset", ais.batch_reset, ["POST"]),
        admins("/api/ais/batches/{batch_id}/translation.txt", ais.batch_translation),
        # Treatments give away what blinding hides: admins.
        admins("/api/ais/compare", ais.compare_batches, ["POST"]),
        admins("/api/ais/batches/{batch_id}/treatments", ais.batch_treatments),
        admins("/api/ais/batches/{batch_id}/treatments", ais.batch_treatments_set, ["POST"]),
        admins("/api/ais/batches/{batch_id}/translation", ais.batch_translation_load, ["POST"]),
        admins("/api/ais/batches/{batch_id}/adds/{add_id}/randomize", ais.batch_rerandomize, ["POST"]),
        # The report and auto runs for agents and scripts (API keys): the
        # Batches screen's export as JSON, and auto mode run by the server.
        signed_in("/api/ais/report", ais.batch_report),
        signed_in("/api/ais/auto", ais.auto_list),
        signed_in("/api/ais/auto/defaults", ais.auto_defaults),
        signed_in("/api/ais/auto/{run_id}", ais.auto_get),
        signed_in("/api/ais/auto/{run_id}/cancel", ais.auto_cancel, ["POST"]),
        signed_in("/api/ais/batches/{batch_id}/auto", ais.auto_start, ["POST"]),
        signed_in("/api/ais/results", ais.result_list),
        signed_in("/api/ais/results", ais.result_add, ["POST"]),
        signed_in("/api/ais/results/import", ais.result_import, ["POST"], max_body_size=ais.UPLOAD_LIMIT_BYTES),
        signed_in("/api/ais/results/{result_id}/delete", ais.result_delete, ["POST"]),
        signed_in("/api/ais/results/{result_id}/update", ais.result_update, ["POST"]),
        signed_in("/api/ais/results/{result_id}/soma", ais.result_soma, ["POST"]),
        # The Measure tool's types: everyone reads them, admins set them.
        signed_in("/api/ais/measure-types", ais.measure_types),
        admins("/api/ais/measure-types", ais.measure_types_set, ["POST"]),
        signed_in("/api/ais/measurements", ais.measurement_list),
        signed_in("/api/ais/measurements", ais.measurement_add, ["POST"]),
        signed_in("/api/ais/measurements/{measurement_id}/update", ais.measurement_update, ["POST"]),
        signed_in("/api/ais/measurements/{measurement_id}/delete", ais.measurement_delete, ["POST"]),
        # Folders on this machine (Open path) and MATLAB: admins with a
        # session, and only when cfg.local_folders_enabled -- each handler
        # checks that too.
        signed_in("/api/ais/local/status", ais.local_status),
        admin_sessions("/api/ais/batches/path", ais.batch_path, ["POST"]),
        admin_sessions("/api/ais/batches/{batch_id}/path", ais.batch_add_path, ["POST"]),
        admin_sessions("/api/ais/local/list", ais.local_list, ["POST"]),
        admin_sessions("/api/ais/local/stacks", ais.local_stacks, ["POST"]),
        admin_sessions("/api/ais/local/reveal", ais.local_reveal, ["POST"]),
        admin_sessions("/api/ais/local/open", ais.local_open, ["POST"]),
        admin_sessions("/api/ais/local/choose", ais.local_choose, ["POST"]),
        admin_sessions("/api/ais/local/matlab", ais.local_matlab, ["POST"]),
        # A MATLAB run as a zip: the images it holds are ones every signed-in
        # user can already fetch.
        signed_in("/api/ais/matlab/bundle", ais.matlab_bundle_download, ["POST"]),
        my_keys("/api/keys", api_keys.list_my_keys),
        my_keys("/api/keys", api_keys.create_my_key, ["POST"]),
        my_keys("/api/keys/{key_id}/rename", api_keys.rename_my_key, ["POST"]),
        my_keys("/api/keys/{key_id}/expiry", api_keys.set_my_key_expiry, ["POST"]),
        my_keys("/api/keys/{key_id}/revoke", api_keys.revoke_my_key, ["POST"]),
        my_keys("/api/keys/{key_id}/delete", api_keys.delete_my_key, ["POST"]),
        my_keys("/api/keys/{key_id}/restore", api_keys.restore_my_key, ["POST"]),
        admins("/api/admin/users", admin.list_users),
        admin_sessions("/api/admin/users", admin.create_user, ["POST"]),
        admin_sessions("/api/admin/users/{user_id}/reissue-login", admin.reissue_login, ["POST"]),
        admins("/api/admin/users/{user_id}/cancel-login-link", admin.cancel_login_link, ["POST"]),
        admins("/api/admin/users/{user_id}/disabled", admin.set_user_disabled, ["POST"]),
        admins("/api/admin/users/{user_id}/revoke-access", admin.revoke_access, ["POST"]),
        admin_sessions("/api/admin/users/{user_id}/rename", admin.rename_user, ["POST"]),
        admin_sessions("/api/admin/users/{user_id}/role", admin.set_user_role, ["POST"]),
        admin_sessions("/api/admin/users/{user_id}/delete", admin.delete_user, ["POST"]),
        admin_sessions("/api/admin/users/{user_id}/reset-two-factor", admin.reset_two_factor, ["POST"]),
        # A session only, like your own devices list: a key that could end
        # sessions could end the one that would revoke it.
        admin_sessions("/api/admin/users/{user_id}/sessions", sessions.list_user_sessions),
        admin_sessions("/api/admin/users/{user_id}/sessions/{session_id}/revoke", sessions.revoke_user_session, ["POST"]),
        # The themes everyone starts from. Not a credential, so a key may.
        admins("/api/admin/theme-defaults", themes.get_theme_defaults),
        admins("/api/admin/theme-defaults", themes.set_theme_defaults, ["POST"]),
        # Invite links: one link for a group, each person who opens it joins
        # as a new user (see invite_links.py). Creating one needs a session for
        # the same reason as creating a user -- the link mints accounts and
        # sessions. Deleting one needs a session like deleting a user. Listing
        # and switching one off are safe for an admin key.
        admin_invites("/api/admin/invite-links", invite_links.list_invite_links),
        admin_invite_sessions("/api/admin/invite-links", invite_links.create_invite_link, ["POST"]),
        admin_invite_sessions("/api/admin/invite-links/{link_id}/rename", invite_links.rename_invite_link, ["POST"]),
        admin_invite_sessions("/api/admin/invite-links/{link_id}/limits", invite_links.set_invite_link_limits, ["POST"]),
        admin_invite_sessions("/api/admin/invite-links/{link_id}/switch-on", invite_links.switch_on_invite_link, ["POST"]),
        admin_invites("/api/admin/invite-links/{link_id}/revoke", invite_links.revoke_invite_link, ["POST"]),
        admin_invite_sessions("/api/admin/invite-links/{link_id}/delete", invite_links.delete_invite_link, ["POST"]),
        admin_invite_sessions("/api/admin/invite-links/{link_id}/restore", invite_links.restore_invite_link, ["POST"]),
        admin_keys("/api/admin/keys", api_keys.list_all_keys),
        admin_keys("/api/admin/keys", api_keys.create_key_for_user, ["POST"]),
        admin_keys("/api/admin/keys/{key_id}/rename", api_keys.rename_any_key, ["POST"]),
        admin_keys("/api/admin/keys/{key_id}/expiry", api_keys.set_any_key_expiry, ["POST"]),
        admin_keys("/api/admin/keys/{key_id}/revoke", api_keys.revoke_any_key, ["POST"]),
        admin_keys("/api/admin/keys/{key_id}/delete", api_keys.delete_any_key, ["POST"]),
        admin_keys("/api/admin/keys/{key_id}/restore", api_keys.restore_any_key, ["POST"]),
        # config.yaml, as the owner's Settings screen. See settings.py.
        owner("/api/owner/settings", settings.get_settings),
        owner("/api/owner/settings", settings.save_settings, ["POST"]),
        # Background jobs. See app/core/jobs.py.
        owner("/api/owner/jobs", jobs.list_jobs),
        owner("/api/owner/jobs/{name}/run", jobs.run_job, ["POST"]),
        # The per-account password switch. See passwords.py.
        owner_passwords("/api/owner/users/{user_id}/password-access", passwords.set_password_access, ["POST"]),
    ]

    # The activity log (app/core/logs.py). Switched off in config.yaml, none
    # of it exists and track.js sends nothing.
    if cfg.logs.enabled:
        routes += [
            # What someone did on the page, sent by track.js. Theirs to send,
            # the owner's to read.
            signed_in("/api/logs/events", logs.record_ui_events, ["POST"]),
            owner("/api/owner/logs/days", logs.list_log_days),
            owner("/api/owner/logs/days/{date}", logs.get_log_day),
            owner("/api/owner/logs/days/{date}/download", logs.download_log_day),
            owner("/api/owner/logs/days/{date}/delete", logs.delete_log_day, ["POST"]),
            owner("/api/owner/logs/prune", logs.prune_logs, ["POST"]),
            owner("/api/owner/logs/ip-names", logs.list_ip_names),
            owner("/api/owner/logs/ip-names", logs.set_ip_name, ["POST"]),
            owner("/api/owner/logs/ip-names/delete", logs.delete_ip_name, ["POST"]),
            owner("/api/owner/logs/stream", logs.stream_log_changes),
        ]

    # MCP: agents calling the app with an API key (see app/mcp and
    # mcp_tools.py). Keys only -- RequireAPIKey turns a browser session away --
    # and every tool runs at the key's effective role, so this is the API above
    # in another shape, not a wider one.
    #
    # Always registered: server.mcp and auth.api_keys can be switched while
    # the server runs, so RequireMCP checks them per request and answers 404
    # when either is off -- without API keys nothing could authenticate to it.
    mcp = MCPServer(mcp_tools.build_registry())
    routes += [
        group(RequireMCP, RequireAPIKey)("/mcp", mcp.endpoint, ["POST"]),
        group(RequireMCP)("/mcp", mcp.method_not_allowed, ["GET", "DELETE"]),
    ]


    # The MATLAB helper (app/routes/ais_matlab.py). A session sends a run to its
    # own helper; only that session can, so a stolen helper key cannot start
    # anything. The helper authenticates with its own kind of key and nothing
    # else, so without API keys these are not registered either.
    if cfg.matlab_helper and cfg.api_keys_enabled:
        helper = group(RequireHelperKey)
        routes += [
            sessions_only("/api/ais/matlab/send", ais_matlab.send, ["POST"]),
            sessions_only("/api/ais/matlab/helper/key", ais_matlab.mint_key, ["POST"]),
            # Signed in, not helper-only: the install line fetches this with
            # the new key, and a person can from their browser.
            signed_in("/api/ais/matlab/helper/download/{platform}", ais_matlab.download),
            helper("/api/ais/matlab/helper/next", ais_matlab.next_job),
            helper("/api/ais/matlab/helper/jobs/{job_id}/bundle", ais_matlab.job_bundle),
            helper("/api/ais/matlab/helper/jobs/{job_id}/done", ais_matlab.job_done, ["POST"]),
        ]

    return routes + [
        # Any other /api/ path is a JSON 404, not the index.html fallback.
        Route("/api/{rest:path}", meta.unknown_api),
        # Catch-all static serving. Must stay last -- it matches every
        # remaining path, so anything added after this line never runs.
        Route("/{path:path}", static_server.endpoint),
    ]
