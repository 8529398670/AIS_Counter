# AIS Counter API

Every route this server answers, apart from the pages at /login/* and /join/*. Generated from the code by scripts/api_docs.sh: an app's own routes get their docs the same way, and a test fails until they do.

This file is generated: do not edit it. Change the docs next to the handlers and run `scripts/api_docs.sh`.

## Contents

- [Calling the API](#calling-the-api)
- [Errors](#errors)
- [Account](#account)
- [Sign-in](#sign-in)
- [API keys](#api-keys)
- [Admin](#admin)
- [Invite links](#invite-links)
- [Owner](#owner)
- [Monitoring](#monitoring)
- [AIS](#ais)
- [About](#about)
- [Schemas](#schemas)
- [MCP tools](#mcp-tools)

## Calling the API

| Way in | How |
|---|---|
| Browser session | A browser session. Its POSTs carry csrf_token in the body. The cookie's name is server.cookie_name. |
| API key | An API key, as Authorization: Bearer <id>.<secret>. |

## Errors

An error reply is a JSON object whose `error` says what went wrong.

| Status | Meaning | Body |
|---|---|---|
| 400 | The request was refused as it stands. | [`Error`](#error) |
| 401 | Not signed in. | [`Error`](#error) |
| 403 | Not allowed, or a bad csrf_token. | [`Error`](#error) |
| 404 | No such thing, or this feature is switched off. | [`Error`](#error) |
| 409 | The record has moved on: an undo too late, or a stale edit. | [`Error`](#error) |
| 429 | Too many requests. | [`Error`](#error) |
| 503 | In maintenance mode. Retry-After says when to try again. | [`Maintenance`](#maintenance) |

## Account

| Method | Path | Summary | Who may call |
|---|---|---|---|
| POST | [`/api/account/login-link`](#post-apiaccountlogin-link) | A login link for yourself | browser session or API key, anyone signed in |
| POST | [`/api/account/login-link/cancel`](#post-apiaccountlogin-linkcancel) | Stop your own login link working | browser session or API key, anyone signed in |
| POST | [`/api/account/matlab`](#post-apiaccountmatlab) | Set where MATLAB is on your computer | browser session only, anyone signed in |
| POST | [`/api/account/password`](#post-apiaccountpassword) | Set or clear your password | browser session only, anyone signed in |
| POST | [`/api/account/pin`](#post-apiaccountpin) | Set or clear your PIN | browser session only, anyone signed in |
| POST | [`/api/account/rename`](#post-apiaccountrename) | Rename your account | browser session or API key, anyone signed in |
| GET | [`/api/account/sessions`](#get-apiaccountsessions) | Your signed-in devices | browser session or API key, anyone signed in |
| POST | [`/api/account/sessions/revoke-others`](#post-apiaccountsessionsrevoke-others) | Sign out every other device | browser session or API key, anyone signed in |
| POST | [`/api/account/sessions/{session_id}/label`](#post-apiaccountsessionssession_idlabel) | Name one of your devices | browser session or API key, anyone signed in |
| POST | [`/api/account/sessions/{session_id}/revoke`](#post-apiaccountsessionssession_idrevoke) | Sign out one of your devices | browser session or API key, anyone signed in |
| POST | [`/api/account/shortcuts`](#post-apiaccountshortcuts) | Save your rebound keyboard shortcuts | browser session or API key, anyone signed in |
| POST | [`/api/account/theme`](#post-apiaccounttheme) | Pick your theme | browser session or API key, anyone signed in |
| POST | [`/api/account/themes`](#post-apiaccountthemes) | Replace your own themes | browser session or API key, anyone signed in |
| POST | [`/api/account/two-factor/confirm`](#post-apiaccounttwo-factorconfirm) | Turn two-factor on | browser session only, anyone signed in |
| POST | [`/api/account/two-factor/disable`](#post-apiaccounttwo-factordisable) | Turn two-factor off | browser session only, anyone signed in |
| POST | [`/api/account/two-factor/start`](#post-apiaccounttwo-factorstart) | Begin two-factor setup | browser session only, anyone signed in |
| GET | [`/api/language`](#get-apilanguage) | The UI's text | anyone |
| POST | [`/api/logout`](#post-apilogout) | Sign out | browser session or API key, anyone signed in |
| POST | [`/api/logs/events`](#post-apilogsevents) | Record what happened on the page | browser session or API key, anyone signed in |
| GET | [`/api/me`](#get-apime) | Who am I | browser session or API key, anyone signed in |
| GET | [`/api/team`](#get-apiteam) | List team | browser session or API key, anyone signed in |

### POST /api/account/login-link

A login link for yourself

A link that signs your own account in on a browser or another device. Only a key with your account's full role may ask: one scoped down to user on an admin account is refused.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`create_my_login_link`](#create_my_login_link) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `expires_in_seconds` | integer | yes |  | 0 when it never expires. |
| `login_path` | string | yes |  | Path of the login link. A credential: treat it like a password. |
| `login_url` | string | yes |  | The same link as a full address, on server.public_url (or a guess from the listen address). A credential: treat it like a password. |
| `max_uses` | integer | yes |  | 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |

### POST /api/account/login-link/cancel

Stop your own login link working

Void your account's live login link without making a new one. Devices it already signed in stay signed in. Answers with removed: 0 or 1.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`cancel_my_login_link`](#cancel_my_login_link) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | integer | yes |  | Links removed: 0 or 1. |

### POST /api/account/matlab

Set where MATLAB is on your computer

Body: {path}: where MATLAB is on the caller's own computer, written into their replay zips (app/analysis/matlab_bundle.py). Empty clears it. A session only: this value decides what those scripts execute.

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `path` | string | yes |  | Where MATLAB is on your computer. Empty clears it. No double quotes. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `path` | string | yes |  | As saved, trimmed. |

### POST /api/account/password

Set or clear your password

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `code` | string | no |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `password_digest` | string | yes |  |  |
| `username` | string | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `has_password` | boolean | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/account/pin

Set or clear your PIN

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `pin` | string | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `has_pin` | boolean | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/account/rename

Rename your account

Change your own display name (1-80 characters). expect, when given, is the name you think it has now; if someone changed it meanwhile the rename is refused with the current name, so nothing is overwritten unseen.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`rename_account`](#rename_account) |
| Errors | 400, 401, 403, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `display_name` | string | yes | 1 to 80 characters |  |
| `expect` | string or null | no |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### GET /api/account/sessions

Your signed-in devices

Where your account is signed in, a page at a time: id, when it started and was last seen, the browser, and the name you gave it. Through an API key no device is current. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_my_sessions`](#list_my_sessions) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `sessions` | array of [`Session`](#session) | yes |  |  |
| `total` | integer | yes |  |  |

### POST /api/account/sessions/revoke-others

Sign out every other device

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`revoke_my_other_sessions`](#revoke_my_other_sessions) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | integer | yes |  |  |

### POST /api/account/sessions/{session_id}/label

Name one of your devices

Give one of your devices a name (at most 80 characters; empty clears it). expect, when given, is the name you think it has now.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`label_my_session`](#label_my_session) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `session_id` | path | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `label` | string | yes | at most 80 characters | At most 80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `label` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/account/sessions/{session_id}/revoke

Sign out one of your devices

End one of your signed-in sessions; that browser has to sign in again.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`revoke_my_session`](#revoke_my_session) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `session_id` | path | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/account/shortcuts

Save your rebound keyboard shortcuts

Replace the caller's rebound keyboard shortcuts with the map sent (static/js/shortcuts.js sends the whole map on every change).

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_shortcuts`](#set_shortcuts) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `shortcuts` | map of array of string | yes |  | Action id to the keys bound to it. Replaces the whole map; {} puts every key back to its default. Action ids the screens do not know are ignored. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/account/theme

Pick your theme

Switch to another theme from your list (or the defaults), by its id.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_theme`](#set_theme) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `theme_id` | string | yes |  | A theme's id. Empty for the first in the list. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `theme_id` | string | yes |  |  |

### POST /api/account/themes

Replace your own themes

Replace your whole list of color themes (1 to 40) and pick the one you use. themes: null goes back to following the app's defaults. A theme is the Theme schema in the API reference (config/openapi.json): id, name, mode light|dark, accent, second, and optional colors as #rrggbb.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_themes`](#set_themes) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `theme_id` | string | no |  | The theme you use. |
| `themes` | array of [`Theme`](#theme) or null | no |  | Your whole list, 1 to 40 themes. null goes back to following the app's defaults. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `theme_id` | string | yes |  |  |
| `themes` | array of [`Theme`](#theme) or null | yes |  | What you now see; null while the built-in themes apply. |
| `themes_custom` | boolean | yes |  |  |

### POST /api/account/two-factor/confirm

Turn two-factor on

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `code` | string | yes |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `recovery_codes` | array of string | yes |  |  |

### POST /api/account/two-factor/disable

Turn two-factor off

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `code` | string | yes |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/account/two-factor/start

Begin two-factor setup

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `secret` | string | yes |  |  |

### GET /api/language

The UI's text

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 429, 503 |

**Reply 200**: Success

An empty object.

### POST /api/logout

Sign out

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: Ends a browser session; a key has none to end. |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/logs/events

Record what happened on the page

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The browser's own activity reports (track.js), not an action. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `events` | array of object | yes |  |  |
| `tab` | string | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `accepted` | integer | yes |  |  |

### GET /api/me

Who am I

The account this API key belongs to, the role it acts with (role -- never higher than the key's own scope), and the account's own role.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`whoami`](#whoami) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

[`Me`](#me).

### GET /api/team

List team

People with an active account, a page at a time: id and display name.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_team`](#list_team) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `members` | array of [`Member`](#member) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

## Sign-in

| Method | Path | Summary | Who may call |
|---|---|---|---|
| POST | [`/api/login`](#post-apilogin) | Redeem a login link | anyone |
| GET | [`/api/login/options`](#get-apiloginoptions) | What sign-in offers | anyone |
| POST | [`/api/login/password`](#post-apiloginpassword) | Sign in with a password | anyone |
| POST | [`/api/login/two-factor`](#post-apilogintwo-factor) | Finish a sign-in with a code | anyone |

### POST /api/login

Redeem a login link

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  |  |

**Reply 200**: Success

[`SignIn`](#signin).

### GET /api/login/options

What sign-in offers

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `passwords` | boolean | yes |  |  |
| `salt` | string | no |  |  |
| `two_factor` | boolean | yes |  |  |

### POST /api/login/password

Sign in with a password

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `password_digest` | string | yes |  |  |
| `username` | string | yes |  |  |

**Reply 200**: Success

[`SignIn`](#signin).

### POST /api/login/two-factor

Finish a sign-in with a code

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `challenge` | string | yes |  |  |
| `code` | string | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

## API keys

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/admin/keys`](#get-apiadminkeys) | Every key in the app | browser session only, admins |
| POST | [`/api/admin/keys`](#post-apiadminkeys) | Create a key that acts as someone else | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/delete`](#post-apiadminkeyskey_iddelete) | Delete anyone's key | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/expiry`](#post-apiadminkeyskey_idexpiry) | Change when anyone's key expires | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/rename`](#post-apiadminkeyskey_idrename) | Rename anyone's key | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/restore`](#post-apiadminkeyskey_idrestore) | Undo deleting anyone's key | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/revoke`](#post-apiadminkeyskey_idrevoke) | Revoke anyone's key | browser session only, admins |
| GET | [`/api/keys`](#get-apikeys) | Your API keys | browser session only, anyone signed in |
| POST | [`/api/keys`](#post-apikeys) | Create an API key | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/delete`](#post-apikeyskey_iddelete) | Delete one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/expiry`](#post-apikeyskey_idexpiry) | Change when one of your keys expires | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/rename`](#post-apikeyskey_idrename) | Rename one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/restore`](#post-apikeyskey_idrestore) | Undo deleting one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/revoke`](#post-apikeyskey_idrevoke) | Revoke one of your keys | browser session only, anyone signed in |

### GET /api/admin/keys

Every key in the app

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep keys whose name or owner contains this, in any case. |
| `live` | query | string | no | one of `true` | Leave out revoked and expired keys. |
| `sort` | query | string | no | one of `display_name`, `name`, `role`, `last_used_at`, `expires_at`, `created_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `keys` | array of [`APIKey`](#apikey) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

### POST /api/admin/keys

Create a key that acts as someone else

Any admin may do this for an ordinary user, and only the owner for another admin. Nobody may do it for the owner. The key records who made it and shows that to the person it acts as.

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer or null | no | 0 to 3650 | Absent or null: the configured default. 0: never expires. |
| `name` | string | yes | 1 to 80 characters |  |
| `role` | string | no | one of `admin`, `user`; default `user` |  |
| `user_id` | integer | yes | at least 1 |  |

**Reply 201**: Success

[`NewAPIKey`](#newapikey).

### POST /api/admin/keys/{key_id}/delete

Delete anyone's key

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/keys/{key_id}/expiry

Change when anyone's key expires

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer | yes | 0 to 3650 | Counted from now. 0 means it never expires. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/admin/keys/{key_id}/rename

Rename anyone's key

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `name` | string | yes | 1 to 80 characters | 1-80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/admin/keys/{key_id}/restore

Undo deleting anyone's key

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/admin/keys/{key_id}/revoke

Revoke anyone's key

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/keys

Your API keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep keys whose name contains this, in any case. |
| `live` | query | string | no | one of `true` | Leave out revoked and expired keys. |
| `sort` | query | string | no | one of `name`, `role`, `last_used_at`, `expires_at`, `created_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `keys` | array of [`APIKey`](#apikey) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

### POST /api/keys

Create an API key

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer or null | no | 0 to 3650 | Absent or null: the configured default. 0: never expires. |
| `name` | string | yes | 1 to 80 characters |  |
| `role` | string | no | one of `admin`, `user`; default `user` |  |

**Reply 201**: Success

[`NewAPIKey`](#newapikey).

### POST /api/keys/{key_id}/delete

Delete one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/keys/{key_id}/expiry

Change when one of your keys expires

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer | yes | 0 to 3650 | Counted from now. 0 means it never expires. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/keys/{key_id}/rename

Rename one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `name` | string | yes | 1 to 80 characters | 1-80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/keys/{key_id}/restore

Undo deleting one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/keys/{key_id}/revoke

Revoke one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

## Admin

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/admin/theme-defaults`](#get-apiadmintheme-defaults) | Default themes | browser session or API key, admins |
| POST | [`/api/admin/theme-defaults`](#post-apiadmintheme-defaults) | Replace the default themes | browser session or API key, admins |
| GET | [`/api/admin/users`](#get-apiadminusers) | List users | browser session or API key, admins |
| POST | [`/api/admin/users`](#post-apiadminusers) | Create an account | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/cancel-login-link`](#post-apiadminusersuser_idcancel-login-link) | Stop an account's login link working | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/delete`](#post-apiadminusersuser_iddelete) | Delete an account | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/disabled`](#post-apiadminusersuser_iddisabled) | Disable or enable a user | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/reissue-login`](#post-apiadminusersuser_idreissue-login) | A new login link for an account | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/rename`](#post-apiadminusersuser_idrename) | Rename someone | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/reset-two-factor`](#post-apiadminusersuser_idreset-two-factor) | Turn off an account's two-factor | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/revoke-access`](#post-apiadminusersuser_idrevoke-access) | Revoke a user's access | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/role`](#post-apiadminusersuser_idrole) | Change an account's role | browser session or API key, admins |
| GET | [`/api/admin/users/{user_id}/sessions`](#get-apiadminusersuser_idsessions) | An account's signed-in devices | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/sessions/{session_id}/revoke`](#post-apiadminusersuser_idsessionssession_idrevoke) | Sign out one of an account's devices | browser session or API key, admins |

### GET /api/admin/theme-defaults

Default themes

The theme list everyone without their own list sees. themes is null while the built-in ones apply.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_get_theme_defaults`](#admin_get_theme_defaults) |
| Errors | 401, 403, 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `themes` | array of [`Theme`](#theme) or null | yes |  | null while the built-in themes apply. |

### POST /api/admin/theme-defaults

Replace the default themes

Replace the theme list everyone without their own list sees, 1 to 40 themes in the Theme schema of the API reference. null puts the built-in themes back.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_set_theme_defaults`](#admin_set_theme_defaults) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `themes` | array of [`Theme`](#theme) or null | no |  | 1 to 40 themes. null goes back to the built-in ones. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `themes` | array of [`Theme`](#theme) or null | yes |  |  |

### GET /api/admin/users

List users

Accounts, a page at a time, including disabled ones, with each one's role and which is the owner. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_list_users`](#admin_list_users) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep accounts whose name or username contains this, in any case. |
| `sort` | query | string | no | one of `display_name`, `role`, `disabled`, `created_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |
| `users` | array of [`User`](#user) | yes |  |  |

### POST /api/admin/users

Create an account

Make a new account and its first login link, to hand to the person. role is admin or user. Answers with user_id and the link.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_create_user`](#admin_create_user) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `display_name` | string | yes | 1 to 80 characters |  |
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |
| `role` | string | yes | one of `admin`, `user` |  |

**Reply 201**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `expires_in_seconds` | integer | yes |  | 0 when it never expires. |
| `login_path` | string | yes |  | Path of the login link. A credential: treat it like a password. |
| `login_url` | string | yes |  | The same link as a full address, on server.public_url (or a guess from the listen address). A credential: treat it like a password. |
| `max_uses` | integer | yes |  | 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |
| `user_id` | integer | yes |  |  |

### POST /api/admin/users/{user_id}/cancel-login-link

Stop an account's login link working

Void an account's live login link without making a new one: a link that went somewhere it should not have.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_cancel_login_link`](#admin_cancel_login_link) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | integer | yes |  | Links removed: 0 or 1. |

### POST /api/admin/users/{user_id}/delete

Delete an account

Remove an account for good, with its sessions, login link and API keys.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_delete_user`](#admin_delete_user) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | [`Revoked`](#revoked) | yes |  |  |

### POST /api/admin/users/{user_id}/disabled

Disable or enable a user

Switch an account off (disabled: true) or back on (false). Disabling signs it out everywhere and voids its live login link; its API keys stop working while it is off. Reversible. The owner and your own account cannot be disabled.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_set_user_disabled`](#admin_set_user_disabled) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `disabled` | boolean | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/reissue-login

A new login link for an account

For someone who lost their device or their link: a fresh login link for their account.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_reissue_login`](#admin_reissue_login) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `expires_in_seconds` | integer | yes |  | 0 when it never expires. |
| `login_path` | string | yes |  | Path of the login link. A credential: treat it like a password. |
| `login_url` | string | yes |  | The same link as a full address, on server.public_url (or a guess from the listen address). A credential: treat it like a password. |
| `max_uses` | integer | yes |  | 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/rename

Rename someone

Change another account's display name (1-80 characters). Only the owner renames an admin. expect, when given, is the name you think it has now; if it changed meanwhile the rename is refused with the current name.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_rename_user`](#admin_rename_user) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `display_name` | string | yes | 1 to 80 characters | 1-80 characters. |
| `expect` | string or null | no |  | The name you think they have. Answers 409 if it is another. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/reset-two-factor

Turn off an account's two-factor

For someone who lost both their phone and their recovery codes: switches their two-factor sign-in off so a login link lets them in again. Only the owner resets an admin's; the owner's is reset from a shell.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_reset_two_factor`](#admin_reset_two_factor) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/revoke-access

Revoke a user's access

For an account that may be compromised: ends every session and voids its live login link and every API key it holds, at once.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_revoke_access`](#admin_revoke_access) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `revoked` | [`Revoked`](#revoked) | yes |  |  |

### POST /api/admin/users/{user_id}/role

Change an account's role

Make an account an admin or an ordinary user. Only the owner takes an admin's rights away; the owner is always an admin, and nobody changes their own role. Becoming an admin ends the account's sessions and live login link.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_set_user_role`](#admin_set_user_role) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `role` | string | yes | one of `admin`, `user` |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `role` | string | yes |  |  |

### GET /api/admin/users/{user_id}/sessions

An account's signed-in devices

Where an account is signed in: every session, with when it started and was last seen. Addresses are shown to the owner only, and only the owner sees the owner's.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_list_user_sessions`](#admin_list_user_sessions) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `sessions` | array of [`Session`](#session) | yes |  |  |
| `total` | integer | yes |  |  |

### POST /api/admin/users/{user_id}/sessions/{session_id}/revoke

Sign out one of an account's devices

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_revoke_user_session`](#admin_revoke_user_session) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `session_id` | path | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

## Invite links

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/admin/invite-links`](#get-apiadmininvite-links) | List invite links | browser session or API key, admins |
| POST | [`/api/admin/invite-links`](#post-apiadmininvite-links) | Create an invite link | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/delete`](#post-apiadmininvite-linkslink_iddelete) | Delete an invite link | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/limits`](#post-apiadmininvite-linkslink_idlimits) | Change an invite link's places and expiry | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/rename`](#post-apiadmininvite-linkslink_idrename) | Rename an invite link | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/restore`](#post-apiadmininvite-linkslink_idrestore) | Undo deleting an invite link | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/revoke`](#post-apiadmininvite-linkslink_idrevoke) | Switch off an invite link | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/switch-on`](#post-apiadmininvite-linkslink_idswitch-on) | Switch an invite link back on | browser session or API key, admins |
| POST | [`/api/join/claim`](#post-apijoinclaim) | Sign in as an existing account | anyone |
| POST | [`/api/join/create`](#post-apijoincreate) | Join as a new account | anyone |
| POST | [`/api/join/info`](#post-apijoininfo) | What an invite link is | anyone |
| POST | [`/api/join/match`](#post-apijoinmatch) | Accounts matching a name | anyone |

### GET /api/admin/invite-links

List invite links

Group invite links, a page at a time: label, places used and left, expiry, and whether each still works. The links themselves are never shown again after creation. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_list_invite_links`](#admin_list_invite_links) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep links whose label or maker contains this, in any case. |
| `sort` | query | string | no | one of `label`, `used`, `expires_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `invite_links` | array of [`InviteLink`](#invitelink) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

### POST /api/admin/invite-links

Create an invite link

One link for a group: each person who opens it joins as a new user, up to max_uses people, for days days.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_create_invite_link`](#admin_create_invite_link) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `days` | integer | yes | 1 to 365 |  |
| `label` | string | yes | 1 to 80 characters |  |
| `max_uses` | integer | yes | 1 to 1000 |  |

**Reply 201**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_by` | integer | yes |  |  |
| `created_by_name` | string | no |  |  |
| `expires_at` | string (date-time) | yes |  |  |
| `id` | string | yes |  |  |
| `join_path` | string | yes |  | The link to hand out, shown in this response only. A credential: treat it like a password. |
| `label` | string | yes |  |  |
| `live` | boolean | yes |  |  |
| `max_uses` | integer | yes |  |  |
| `remaining` | integer | yes |  |  |
| `revoked` | boolean | yes |  |  |
| `used` | integer | yes |  |  |

### POST /api/admin/invite-links/{link_id}/delete

Delete an invite link

Take an invite link off the list and stop it working. The accounts it made stay.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_delete_invite_link`](#admin_delete_invite_link) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/invite-links/{link_id}/limits

Change an invite link's places and expiry

Set how many people the link may take in (never fewer than have joined) and, when days is given, a new expiry counted from now. The link then counts as this key's: revoking the key switches it off.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_set_invite_link_limits`](#admin_set_invite_link_limits) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `days` | integer or null | no | 1 to 365 | Counted from now. Leave out to keep the expiry. |
| `max_uses` | integer | yes | 1 to 1000 | Not fewer than have joined. |

**Reply 200**: Success

[`InviteLink`](#invitelink).

### POST /api/admin/invite-links/{link_id}/rename

Rename an invite link

Change the label people see on an invite link's join page (1-80 characters). expect, when given, is the label you think it has now.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_rename_invite_link`](#admin_rename_invite_link) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The label you think it has. Answers 409 if it has another. |
| `label` | string | yes | 1 to 80 characters | 1-80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `label` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/admin/invite-links/{link_id}/restore

Undo deleting an invite link

Bring back an invite link deleted in the last few minutes, working as before. The link then counts as this key's: revoking the key switches it off.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_restore_invite_link`](#admin_restore_invite_link) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`InviteLink`](#invitelink).

### POST /api/admin/invite-links/{link_id}/revoke

Switch off an invite link

Stop an invite link from letting anyone else join or sign in through it. Accounts it already made keep working. Cannot be switched back on.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_revoke_invite_link`](#admin_revoke_invite_link) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/invite-links/{link_id}/switch-on

Switch an invite link back on

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_switch_on_invite_link`](#admin_switch_on_invite_link) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`InviteLink`](#invitelink).

### POST /api/join/claim

Sign in as an existing account

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  |  |
| `display_name` | string | no |  |  |
| `pin` | string | no |  |  |
| `user_id` | integer | no |  |  |

**Reply 200**: Success

[`Joined`](#joined).

### POST /api/join/create

Join as a new account

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  |  |
| `display_name` | string | no |  |  |
| `pin` | string | no |  |  |
| `user_id` | integer | no |  |  |

**Reply 201**: Success

[`Joined`](#joined).

### POST /api/join/info

What an invite link is

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  |  |
| `display_name` | string | no |  |  |
| `pin` | string | no |  |  |
| `user_id` | integer | no |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `label` | string | yes |  |  |
| `remaining` | integer | yes |  |  |

### POST /api/join/match

Accounts matching a name

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  |  |
| `display_name` | string | no |  |  |
| `pin` | string | no |  |  |
| `user_id` | integer | no |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `can_create` | boolean | yes |  |  |
| `matches` | array of object | yes |  |  |
| `matches[].display_name` | string | yes |  |  |
| `matches[].has_pin` | boolean | yes |  |  |
| `matches[].id` | integer | yes |  |  |

## Owner

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/owner/jobs`](#get-apiownerjobs) | Background jobs | browser session only, the owner |
| POST | [`/api/owner/jobs/{name}/run`](#post-apiownerjobsnamerun) | Run a job now | browser session only, the owner |
| GET | [`/api/owner/logs/days`](#get-apiownerlogsdays) | The days on record | browser session only, the owner |
| GET | [`/api/owner/logs/days/{date}`](#get-apiownerlogsdaysdate) | One day's entries | browser session only, the owner |
| POST | [`/api/owner/logs/days/{date}/delete`](#post-apiownerlogsdaysdatedelete) | Delete one day | browser session only, the owner |
| GET | [`/api/owner/logs/days/{date}/download`](#get-apiownerlogsdaysdatedownload) | One day's entries as a file | browser session only, the owner |
| GET | [`/api/owner/logs/ip-names`](#get-apiownerlogsip-names) | What the owner calls addresses | browser session only, the owner |
| POST | [`/api/owner/logs/ip-names`](#post-apiownerlogsip-names) | Name an address or a range, or rename one | browser session only, the owner |
| POST | [`/api/owner/logs/ip-names/delete`](#post-apiownerlogsip-namesdelete) | Take a name off an address or a range | browser session only, the owner |
| POST | [`/api/owner/logs/prune`](#post-apiownerlogsprune) | Apply the retention rules now | browser session only, the owner |
| GET | [`/api/owner/logs/stream`](#get-apiownerlogsstream) | New log entries as they happen | browser session only, the owner |
| GET | [`/api/owner/settings`](#get-apiownersettings) | config.yaml, as a form | browser session only, the owner |
| POST | [`/api/owner/settings`](#post-apiownersettings) | Save settings | browser session only, the owner |
| POST | [`/api/owner/users/{user_id}/password-access`](#post-apiownerusersuser_idpassword-access) | Allow or block an account's password | browser session only, the owner |

### GET /api/owner/jobs

Background jobs

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `jobs` | array of [`Job`](#job) | yes |  |  |

### POST /api/owner/jobs/{name}/run

Run a job now

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `name` | path | string | yes |  | The job's name, from GET /api/owner/jobs. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 202**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/owner/logs/days

The days on record

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `q` | query | string | no |  | The Logs screen's search. |

**Reply 200**: Success

[`LogDays`](#logdays).

### GET /api/owner/logs/days/{date}

One day's entries

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `date` | path | string | yes |  | The day's date, from GET /api/owner/logs/days. |
| `q` | query | string | no |  | The Logs screen's search. |
| `before` | query | integer or null | no | at least 0 |  |
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |

**Reply 200**: Success

[`LogDay`](#logday).

### POST /api/owner/logs/days/{date}/delete

Delete one day

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `date` | path | string | yes |  | The day's date, from GET /api/owner/logs/days. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `deleted` | boolean | yes |  |  |

### GET /api/owner/logs/days/{date}/download

One day's entries as a file

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `date` | path | string | yes |  | The day's date, from GET /api/owner/logs/days. |

**Reply 200**: Success

Text, as `application/x-ndjson`.

### GET /api/owner/logs/ip-names

What the owner calls addresses

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 403, 404, 429, 503 |

**Reply 200**: Success

[`IPNames`](#ipnames).

### POST /api/owner/logs/ip-names

Name an address or a range, or rename one

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `name` | string | yes | 1 to 80 characters |  |
| `target` | string | yes | e.g. `10.0.0.0/24` | An address, or a range such as 10.0.0.0/24. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |
| `target` | string | yes |  |  |

### POST /api/owner/logs/ip-names/delete

Take a name off an address or a range

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `target` | string | yes | e.g. `10.0.0.0/24` | An address, or a range such as 10.0.0.0/24. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `deleted` | boolean | yes |  |  |

### POST /api/owner/logs/prune

Apply the retention rules now

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`PruneResult`](#pruneresult).

### GET /api/owner/logs/stream

New log entries as they happen

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `q` | query | string | no |  | The Logs screen's search. |

**Reply 200**: Success

Text, as `text/event-stream`.

### GET /api/owner/settings

config.yaml, as a form

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 404, 429, 503 |

**Reply 200**: Success

[`SettingsSnapshot`](#settingssnapshot).

### POST /api/owner/settings

Save settings

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `changes` | object | yes |  | Setting paths and their new values. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `version` | string | yes |  |  |

**Reply 200**: Success

[`SettingsResult`](#settingsresult).

### POST /api/owner/users/{user_id}/password-access

Allow or block an account's password

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `allowed` | boolean | yes |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `password_blocked` | boolean | yes |  |  |

## Monitoring

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/health`](#get-apihealth) | Is the process up | anyone |
| GET | [`/api/mcp.json`](#get-apimcpjson) | The MCP tools: every tool /mcp has, its arguments, and the route it stands for | browser session or API key, anyone signed in |
| GET | [`/api/openapi.json`](#get-apiopenapijson) | This document | browser session or API key, anyone signed in |
| GET | [`/api/ready`](#get-apiready) | Can the server do real work | anyone |
| GET | [`/mcp`](#get-mcp) | Refused: this server has no stream | anyone |
| POST | [`/mcp`](#post-mcp) | Model Context Protocol, at the key's role | API key only, anyone signed in |
| DELETE | [`/mcp`](#delete-mcp) | Refused: this server keeps no sessions | anyone |

### GET /api/health

Is the process up

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/mcp.json

The MCP tools: every tool /mcp has, its arguments, and the route it stands for

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The MCP reference itself; tools/list gives the same list. |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

An empty object.

### GET /api/openapi.json

This document

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The API reference itself; GET /api/mcp.json is the MCP one. |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

An empty object.

### GET /api/ready

Can the server do real work

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /mcp

Refused: this server has no stream

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 404, 429, 503 |

**Reply 405**: Success

### POST /mcp

Model Context Protocol, at the key's role

|  |  |
|---|---|
| Who may call | API key only, anyone signed in |
| MCP tool | None, HTTP only: The MCP endpoint itself. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

An empty object.

**Reply 200**: Success

An empty object.

### DELETE /mcp

Refused: this server keeps no sessions

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 404, 429, 503 |

**Reply 405**: Success

## AIS

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/ais/auto`](#get-apiaisauto) | Auto runs on the server | browser session or API key, anyone signed in |
| GET | [`/api/ais/auto/defaults`](#get-apiaisautodefaults) | Auto mode defaults | browser session or API key, anyone signed in |
| GET | [`/api/ais/auto/{run_id}`](#get-apiaisautorun_id) | One auto run | browser session or API key, anyone signed in |
| POST | [`/api/ais/auto/{run_id}/cancel`](#post-apiaisautorun_idcancel) | Stop an auto run | browser session or API key, anyone signed in |
| GET | [`/api/ais/batches`](#get-apiaisbatches) | Every batch with its progress | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches`](#post-apiaisbatches) | Create a batch | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/import`](#post-apiaisbatchesimport) | Import a batch backup | browser session or API key, admins |
| POST | [`/api/ais/batches/import/missing`](#post-apiaisbatchesimportmissing) | Add the images a batch import was missing | browser session or API key, admins |
| POST | [`/api/ais/batches/move`](#post-apiaisbatchesmove) | File batches in a folder | browser session or API key, admins |
| POST | [`/api/ais/batches/order`](#post-apiaisbatchesorder) | Set the batches' priority order | browser session or API key, admins |
| POST | [`/api/ais/batches/path`](#post-apiaisbatchespath) | Create a batch from a folder on this computer | browser session only, admins |
| POST | [`/api/ais/batches/upload`](#post-apiaisbatchesupload) | Create a batch from an uploaded folder | browser session or API key, anyone signed in |
| GET | [`/api/ais/batches/{batch_id}`](#get-apiaisbatchesbatch_id) | One batch | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/{batch_id}/activity`](#post-apiaisbatchesbatch_idactivity) | Report an auto run on a batch | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/{batch_id}/adds/{add_id}/randomize`](#post-apiaisbatchesbatch_idaddsadd_idrandomize) | Re-randomize one folder's names | browser session or API key, admins |
| POST | [`/api/ais/batches/{batch_id}/archive`](#post-apiaisbatchesbatch_idarchive) | Archive or unarchive a batch | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/{batch_id}/assign`](#post-apiaisbatchesbatch_idassign) | Split a batch among people | browser session or API key, admins |
| POST | [`/api/ais/batches/{batch_id}/auto`](#post-apiaisbatchesbatch_idauto) | Start an auto run | browser session or API key, anyone signed in |
| GET | [`/api/ais/batches/{batch_id}/backup`](#get-apiaisbatchesbatch_idbackup) | What a backup ZIP holds besides the image files | browser session or API key, admins |
| GET | [`/api/ais/batches/{batch_id}/channels`](#get-apiaisbatchesbatch_idchannels) | A batch's channels | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/{batch_id}/delete`](#post-apiaisbatchesbatch_iddelete) | Delete a batch | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/{batch_id}/done`](#post-apiaisbatchesbatch_iddone) | Mark an image done or not done | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/{batch_id}/fill-areas`](#post-apiaisbatchesbatch_idfill-areas) | Fill in missing AIS areas | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/{batch_id}/include`](#post-apiaisbatchesbatch_idinclude) | Include or exclude an image | browser session or API key, anyone signed in |
| GET | [`/api/ais/batches/{batch_id}/layouts`](#get-apiaisbatchesbatch_idlayouts) | A batch's channel layouts | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/{batch_id}/layouts`](#post-apiaisbatchesbatch_idlayouts) | Set a batch's channel roles | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/{batch_id}/path`](#post-apiaisbatchesbatch_idpath) | Add a folder on this computer to a batch | browser session only, admins |
| POST | [`/api/ais/batches/{batch_id}/rename`](#post-apiaisbatchesbatch_idrename) | Rename a batch | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/{batch_id}/reset`](#post-apiaisbatchesbatch_idreset) | Reset a batch's results | browser session or API key, admins |
| GET | [`/api/ais/batches/{batch_id}/status`](#get-apiaisbatchesbatch_idstatus) | Each image's progress in a batch | browser session or API key, anyone signed in |
| POST | [`/api/ais/batches/{batch_id}/translation`](#post-apiaisbatchesbatch_idtranslation) | Load a batch's translation file | browser session or API key, admins |
| GET | [`/api/ais/batches/{batch_id}/translation.txt`](#get-apiaisbatchesbatch_idtranslationtxt) | The batch's __Translation.txt (admins) | browser session or API key, admins |
| GET | [`/api/ais/batches/{batch_id}/treatments`](#get-apiaisbatchesbatch_idtreatments) | Each image's original name, saved treatment and guessed one (admins) | browser session or API key, admins |
| POST | [`/api/ais/batches/{batch_id}/treatments`](#post-apiaisbatchesbatch_idtreatments) | Save a batch's treatments | browser session or API key, admins |
| POST | [`/api/ais/batches/{batch_id}/upload`](#post-apiaisbatchesbatch_idupload) | Add images to a batch | browser session or API key, anyone signed in |
| POST | [`/api/ais/compare`](#post-apiaiscompare) | Compare treatments across batches | browser session or API key, admins |
| POST | [`/api/ais/detect`](#post-apiaisdetect) | Find every AIS on an image (auto mode) | browser session or API key, anyone signed in |
| POST | [`/api/ais/files`](#post-apiaisfiles) | Upload an image (TIFF or .czi) | browser session or API key, anyone signed in |
| GET | [`/api/ais/files/{sha}/channel/{index}.png`](#get-apiaisfilesshachannelindexpng) | One .czi channel, for the viewer | browser session or API key, anyone signed in |
| GET | [`/api/ais/files/{sha}/channel/{index}.tif`](#get-apiaisfilesshachannelindextif) | One .czi channel, its data as a 16-bit TIFF, for exports | browser session or API key, anyone signed in |
| GET | [`/api/ais/files/{sha}/channels`](#get-apiaisfilesshachannels) | A .czi's channels | browser session or API key, anyone signed in |
| GET | [`/api/ais/files/{sha}/composite.png`](#get-apiaisfilesshacompositepng) | A .czi's channels merged in their display colors, for exports | browser session or API key, anyone signed in |
| GET | [`/api/ais/files/{sha}/file`](#get-apiaisfilesshafile) | The stored file itself (a .czi or TIFF as it was added), for exports | browser session or API key, anyone signed in |
| POST | [`/api/ais/files/{sha}/pair`](#post-apiaisfilesshapair) | Guess each AIS's soma end and soma, and the soma ellipses | browser session or API key, anyone signed in |
| GET | [`/api/ais/files/{sha}/processed.tif`](#get-apiaisfilesshaprocessedtif) | A .czi's processed AIS channel as a TIFF (what tracing uses), for exports | browser session or API key, anyone signed in |
| GET | [`/api/ais/files/{sha}/slice/{index}.png`](#get-apiaisfilesshasliceindexpng) | One slice of a Z-stack, for the viewer's Z slider | browser session or API key, anyone signed in |
| GET | [`/api/ais/files/{sha}/somata`](#get-apiaisfilesshasomata) | A .czi's soma outlines | browser session or API key, anyone signed in |
| GET | [`/api/ais/files/{sha}/thumb.png`](#get-apiaisfilesshathumbpng) | An image's thumbnail | browser session or API key, anyone signed in |
| GET | [`/api/ais/files/{sha}/view.png`](#get-apiaisfilesshaviewpng) | An image for the viewer | browser session or API key, anyone signed in |
| GET | [`/api/ais/folders`](#get-apiaisfolders) | The Batches screen's folders | browser session or API key, anyone signed in |
| POST | [`/api/ais/folders`](#post-apiaisfolders) | Create a folder | browser session or API key, admins |
| POST | [`/api/ais/folders/order`](#post-apiaisfoldersorder) | Set the order of one folder's folders | browser session or API key, admins |
| POST | [`/api/ais/folders/{folder_id}/delete`](#post-apiaisfoldersfolder_iddelete) | Delete a folder | browser session or API key, admins |
| POST | [`/api/ais/folders/{folder_id}/move`](#post-apiaisfoldersfolder_idmove) | Move a folder into another | browser session or API key, admins |
| POST | [`/api/ais/folders/{folder_id}/rename`](#post-apiaisfoldersfolder_idrename) | Rename a folder | browser session or API key, admins |
| POST | [`/api/ais/local/channels`](#post-apiaislocalchannels) | Find channel layouts in a folder on this computer | browser session only, admins |
| POST | [`/api/ais/local/choose`](#post-apiaislocalchoose) | Pick a folder on this computer | browser session only, admins |
| POST | [`/api/ais/local/list`](#post-apiaislocallist) | List a folder on this computer | browser session only, admins |
| POST | [`/api/ais/local/matlab`](#post-apiaislocalmatlab) | Verify an image in MATLAB on this computer | browser session only, admins |
| POST | [`/api/ais/local/open`](#post-apiaislocalopen) | Open a file on this computer | browser session only, admins |
| POST | [`/api/ais/local/reveal`](#post-apiaislocalreveal) | Show a file in Finder | browser session only, admins |
| POST | [`/api/ais/local/stacks`](#post-apiaislocalstacks) | Find Z-stacks in a folder on this computer | browser session only, admins |
| GET | [`/api/ais/local/status`](#get-apiaislocalstatus) | Whether folders on this computer and MATLAB are available | browser session or API key, anyone signed in |
| POST | [`/api/ais/matlab/bundle`](#post-apiaismatlabbundle) | Download a MATLAB replay zip | browser session or API key, anyone signed in |
| GET | [`/api/ais/matlab/helper/download/{platform}`](#get-apiaismatlabhelperdownloadplatform) | The helper for one OS and CPU, from helper/build.sh | browser session or API key, anyone signed in |
| GET | [`/api/ais/matlab/helper/jobs/{job_id}/bundle`](#get-apiaismatlabhelperjobsjob_idbundle) | The claimed run's zip, built now rather than held in memory waiting | API key only, anyone signed in |
| POST | [`/api/ais/matlab/helper/jobs/{job_id}/done`](#post-apiaismatlabhelperjobsjob_iddone) | Report what the helper launched | API key only, anyone signed in |
| POST | [`/api/ais/matlab/helper/key`](#post-apiaismatlabhelperkey) | Make a MATLAB helper key | browser session only, anyone signed in |
| GET | [`/api/ais/matlab/helper/next`](#get-apiaismatlabhelpernext) | The helper's next run | API key only, anyone signed in |
| POST | [`/api/ais/matlab/send`](#post-apiaismatlabsend) | Send a MATLAB run to your helper | browser session only, anyone signed in |
| GET | [`/api/ais/measure-types`](#get-apiaismeasure-types) | The team's measurement types for the Measure tool's Type picker | browser session or API key, anyone signed in |
| POST | [`/api/ais/measure-types`](#post-apiaismeasure-types) | Set the measurement types | browser session or API key, admins |
| GET | [`/api/ais/measurements`](#get-apiaismeasurements) | Recorded measurements | browser session or API key, anyone signed in |
| POST | [`/api/ais/measurements`](#post-apiaismeasurements) | Record a measurement | browser session or API key, anyone signed in |
| POST | [`/api/ais/measurements/{measurement_id}/delete`](#post-apiaismeasurementsmeasurement_iddelete) | Delete a measurement | browser session or API key, anyone signed in |
| POST | [`/api/ais/measurements/{measurement_id}/update`](#post-apiaismeasurementsmeasurement_idupdate) | Change a measurement | browser session or API key, anyone signed in |
| GET | [`/api/ais/report`](#get-apiaisreport) | The batch report as JSON | browser session or API key, anyone signed in |
| GET | [`/api/ais/results`](#get-apiaisresults) | Accepted AIS | browser session or API key, anyone signed in |
| POST | [`/api/ais/results`](#post-apiaisresults) | Accept an AIS | browser session or API key, anyone signed in |
| POST | [`/api/ais/results/import`](#post-apiaisresultsimport) | Import results | browser session or API key, anyone signed in |
| POST | [`/api/ais/results/{result_id}/delete`](#post-apiaisresultsresult_iddelete) | Delete an accepted AIS | browser session or API key, anyone signed in |
| POST | [`/api/ais/results/{result_id}/soma`](#post-apiaisresultsresult_idsoma) | Set an accepted AIS's soma | browser session or API key, anyone signed in |
| POST | [`/api/ais/results/{result_id}/update`](#post-apiaisresultsresult_idupdate) | Change an accepted AIS | browser session or API key, anyone signed in |
| POST | [`/api/ais/trace`](#post-apiaistrace) | Trace an AIS from a click (ais_auto.m) | browser session or API key, anyone signed in |
| GET | [`/api/ais/trash`](#get-apiaistrash) | The Batches screen's trash | browser session or API key, anyone signed in |
| POST | [`/api/ais/trash/{trash_id}/purge`](#post-apiaistrashtrash_idpurge) | Delete from the trash for good | browser session or API key, admins |
| POST | [`/api/ais/trash/{trash_id}/restore`](#post-apiaistrashtrash_idrestore) | Restore from the trash | browser session or API key, anyone signed in |

### GET /api/ais/auto

Auto runs on the server

The auto runs the server has done since it started, newest first. ?batch=<id> narrows them.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_auto_runs`](#list_auto_runs) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch` | query | integer | no |  | A batch id: only its runs. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `runs` | array of [`AutoRun`](#autorun) | yes |  | Newest first. |

### GET /api/ais/auto/defaults

Auto mode defaults

What a run uses unless it says otherwise (static/js/settings.js defaults), and what it may set: general, ranges, methods, starts, threshold, settings, engines, z_methods.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`auto_defaults`](#auto_defaults) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `engines` | array of any | yes |  | Each null (the original port) or fast (app/analysis/fast.py). |
| `general` | object | yes |  | Settings' general fields and their defaults. |
| `methods` | array of string | yes |  |  |
| `ranges` | map of array of number | yes |  | The [lowest, highest] each number in general may be. |
| `settings` | object | yes |  | The method's settings and their defaults. |
| `starts` | array of string | yes |  |  |
| `threshold` | number | yes |  |  |
| `z_methods` | array of string | yes |  | The Z-stack length methods ready to use. |

### GET /api/ais/auto/{run_id}

One auto run

How far the run has got: state (queued, running, finished, stopped, failed), done, total, found, hidden, saved, errors.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`get_auto_run`](#get_auto_run) |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `run_id` | path | string | yes |  |  |

**Reply 200**: Success

[`AutoRun`](#autorun).

### POST /api/ais/auto/{run_id}/cancel

Stop an auto run

Stops after the image it is on; what it saved stays. Whoever started it, or an admin.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`cancel_auto_run`](#cancel_auto_run) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `run_id` | path | string | yes |  |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`AutoRun`](#autorun).

### GET /api/ais/batches

Every batch with its progress

Every batch with its progress: uploads, completion, per assignee, and any auto run going on (the Batches screen polls this as its monitor).

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_batches`](#list_batches) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batches` | array of object | yes |  |  |
| `batches[].activity` | array of object | yes |  | Auto runs going on in people's browsers. |
| `batches[].activity[].at` | string | yes |  |  |
| `batches[].activity[].done` | integer | yes |  |  |
| `batches[].activity[].kind` | string | yes | one of `auto` |  |
| `batches[].activity[].name` | string | yes |  |  |
| `batches[].activity[].state` | string | yes | one of `running`, `paused`, `finished`, `stopped` |  |
| `batches[].activity[].total` | integer | yes |  |  |
| `batches[].activity[].user_id` | integer | yes |  |  |
| `batches[].adds` | array of object | yes |  | Each time images were added, with added_by_name. |
| `batches[].ais` | integer | yes |  |  |
| `batches[].archived_at` | string or null | yes |  |  |
| `batches[].assignees` | array of object | yes |  |  |
| `batches[].assignees[].ais` | integer | yes |  |  |
| `batches[].assignees[].completed` | integer | yes |  |  |
| `batches[].assignees[].images` | integer | yes |  |  |
| `batches[].assignees[].last_at` | string or null | yes |  | When an AIS on their images was last accepted or edited. |
| `batches[].assignees[].name` | string | yes |  |  |
| `batches[].assignees[].percent` | number | yes |  |  |
| `batches[].assignees[].user_id` | integer | yes |  |  |
| `batches[].auto` | integer | yes |  |  |
| `batches[].completed` | integer | yes |  |  |
| `batches[].created_at` | string | yes |  |  |
| `batches[].created_by` | integer | yes |  |  |
| `batches[].created_by_name` | string | yes |  |  |
| `batches[].duplicates` | integer | yes |  |  |
| `batches[].earlier` | integer | yes |  | Images from before adds were recorded. |
| `batches[].files` | integer | yes |  |  |
| `batches[].folder_id` | integer or null | yes |  |  |
| `batches[].id` | integer | yes |  |  |
| `batches[].images` | integer | yes |  |  |
| `batches[].included` | integer | yes |  |  |
| `batches[].mine` | object or null | yes |  |  |
| `batches[].mine.ais` | integer | yes |  |  |
| `batches[].mine.completed` | integer | yes |  |  |
| `batches[].mine.images` | integer | yes |  |  |
| `batches[].mine.last_at` | string or null | yes |  | When an AIS on their images was last accepted or edited. |
| `batches[].mine.name` | string | yes |  |  |
| `batches[].mine.percent` | number | yes |  |  |
| `batches[].mine.user_id` | integer | yes |  |  |
| `batches[].name` | string | yes |  |  |
| `batches[].path` | string or null | yes |  | An Open-path batch's folder. |
| `batches[].position` | integer | yes |  |  |
| `batches[].randomized` | boolean | yes |  |  |
| `batches[].source` | string | yes | one of `upload`, `path` |  |
| `batches[].stored` | integer | yes |  | Of files, how many the server can show. |
| `batches[].treatments` | array of array of any | no |  | Admins: [[name, images], ...], most images first. |
| `batches[].unnamed` | integer | yes |  |  |
| `batches[].untreated` | integer | no |  | Admins: included images with no treatment. |
| `batches[].updated_at` | string | yes |  |  |
| `folders` | array of object | yes |  |  |
| `folders[].created_at` | string | yes |  |  |
| `folders[].created_by` | integer | yes |  |  |
| `folders[].id` | integer | yes |  |  |
| `folders[].name` | string | yes |  |  |
| `folders[].parent_id` | integer or null | yes |  | null at the top. |
| `folders[].position` | integer | yes |  |  |
| `folders[].updated_at` | string | yes |  |  |

### POST /api/ais/batches

Create a batch

Body: {name}: an empty batch, its images added afterwards.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`create_batch`](#create_batch) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `folder_id` | integer or null | no |  | The folder to put it in; null for the top. |
| `name` | string | yes |  |  |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.

An empty object.

### POST /api/ais/batches/import

Import a batch backup

Body: one batch of a backup ({format, version, users, batch, results}), which becomes a new batch.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | None, HTTP only: A backup zip: MCP messages are JSON, and clients cap their size. Send it over HTTP with the same key. |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch` | object | yes |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `format` | string | yes | one of `ais-batch-backup` |  |
| `measurements` | array of object | no |  |  |
| `results` | array of object | yes |  |  |
| `users` | map of string | no |  | user id -> name, in the backup. |
| `version` | integer | yes | one of `1` |  |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.

An empty object.

### POST /api/ais/batches/import/missing

Add the images a batch import was missing

Body: {shas}. Which of a backup's files the store does not have yet, to upload with POST /api/ais/files before importing.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | None, HTTP only: A backup zip: MCP messages are JSON, and clients cap their size. Send it over HTTP with the same key. |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `shas` | array of string | yes |  | sha-256 hex digests, at most 200000. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `missing` | array of string | yes |  | Those of shas the server does not have. |

### POST /api/ais/batches/move

File batches in a folder

Body: {ids, folder_id}: those batches into that folder, null for the top (admins).

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`move_batches`](#move_batches) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `folder_id` | integer or null | yes |  | null for the top. |
| `ids` | array of integer | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `moved` | integer | yes |  | How many of ids were there to move. |

### POST /api/ais/batches/order

Set the batches' priority order

Body: {ids}: the team's priority order, first on top (admins).

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`order_batches`](#order_batches) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `ids` | array of integer | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/ais/batches/path

Create a batch from a folder on this computer

Body: {path}: an Open-path batch, hashed and recorded by the server.

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `channels` | array of object or null | no |  | Channel roles per layout. |
| `channels[].layout` | object | yes |  | {kind, names}: a layout as GET .../layouts gives it. |
| `channels[].roles` | array of object | yes |  | One per channel: exactly one ais, at most one soma. |
| `channels[].roles[].label` | string | yes |  | The channel's name; empty unless role is other. |
| `channels[].roles[].role` | string | yes | one of `ais`, `soma`, `other` |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `czi_stack` | object or null | no |  |  |
| `czi_stack.apotome` | string | no | one of `sectioned`, `widefield` | How ApoTome phases become slices. Default sectioned. |
| `path` | string | yes |  | A folder on this machine. |
| `randomize` | boolean | no |  | Blind the names. Default true. |
| `stack` | object or null | no |  |  |
| `stack.pixel_um` | number | yes |  |  |
| `stack.plane` | integer | yes | 0 to 3 | The channel of each slice that is the AIS. |
| `stack.z_step_um` | number | yes |  |  |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.

An empty object.

### POST /api/ais/batches/upload

Create a batch from an uploaded folder

Body: {name, files: [{name, rel, sha, size}], translations?: [{dir, text}]} -- a folder picked in the browser, hashed there. Upload the files afterwards with POST /api/ais/files.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`create_batch_from_files`](#create_batch_from_files) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `channels` | array of object or null | no |  | Channel roles per layout. |
| `channels[].layout` | object | yes |  | {kind, names}: a layout as GET .../layouts gives it. |
| `channels[].roles` | array of object | yes |  | One per channel: exactly one ais, at most one soma. |
| `channels[].roles[].label` | string | yes |  | The channel's name; empty unless role is other. |
| `channels[].roles[].role` | string | yes | one of `ais`, `soma`, `other` |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `czi_stack` | object or null | no |  |  |
| `czi_stack.apotome` | string | no | one of `sectioned`, `widefield` | How ApoTome phases become slices. Default sectioned. |
| `files` | array of object | yes |  | 1 to 5000. |
| `files[].layout` | object | no |  | Its channels as the browser read them. |
| `files[].modified` | string | no |  | When it was last changed, ISO. |
| `files[].name` | string | yes |  |  |
| `files[].rel` | string | no |  | Its path under the folder picked. Default name. |
| `files[].sha` | string | yes |  | sha-256, hex. |
| `files[].size` | integer | no |  |  |
| `files[].zstack` | object | no |  | A .czi with more than one slice: what it says of itself. |
| `files[].zstack.phases` | integer | no | at least 1 | Its ApoTome grid phases; 1 (the default) without. |
| `files[].zstack.pixel_um` | number or null | yes |  | Its X scaling; null without, when stack's is used. |
| `files[].zstack.slices` | integer | yes | at least 2 | Its Z planes. |
| `files[].zstack.z_step_um` | number or null | yes |  | Its Z scaling; null without, when stack's is used. |
| `name` | string | yes |  |  |
| `randomize` | boolean | no |  | Blind the names. Default true. |
| `stack` | object or null | no |  |  |
| `stack.pixel_um` | number | yes |  |  |
| `stack.plane` | integer | yes | 0 to 3 | The channel of each slice that is the AIS. |
| `stack.z_step_um` | number | yes |  |  |
| `translations` | array of object | no |  |  |
| `translations[].dir` | string | yes |  |  |
| `translations[].text` | string | yes |  | A __Translation.txt's contents. |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.

An empty object.

### GET /api/ais/batches/{batch_id}

One batch

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`get_batch`](#get_batch) |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.

An empty object.

### POST /api/ais/batches/{batch_id}/activity

Report an auto run on a batch

Body: {kind: "auto", state, done, total}: how far this person's auto run on the batch has got, so everyone's Batches screen can show it.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The Process screen reporting that someone is working on a batch, not an action. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `done` | integer | yes | at least 0 |  |
| `kind` | string | yes | one of `auto` |  |
| `state` | string | yes | one of `running`, `paused`, `finished`, `stopped` |  |
| `total` | integer | yes | 0 to 5000 |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `at` | string | yes |  |  |
| `done` | integer | yes |  |  |
| `kind` | string | yes | one of `auto` |  |
| `state` | string | yes | one of `running`, `paused`, `finished`, `stopped` |  |
| `total` | integer | yes |  |  |
| `user_id` | integer | yes |  |  |

### POST /api/ais/batches/{batch_id}/adds/{add_id}/randomize

Re-randomize one folder's names

New random names for one folder of the batch (admins); its results, done marks, exclusions and assignment move with them.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`rerandomize_add`](#rerandomize_add) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |
| `add_id` | path | string | yes |  | An add's id, or earlier for the images from before adds were recorded. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded. Plus renamed and measured: images renamed, and AIS that moved with them.

An empty object.

### POST /api/ais/batches/{batch_id}/archive

Archive or unarchive a batch

Body: {archived}: archive the batch (hidden, results kept) or bring it back.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`archive_batch`](#archive_batch) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `archived` | boolean | yes |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.

An empty object.

### POST /api/ais/batches/{batch_id}/assign

Split a batch among people

Body: {shares: [{user_id, percent}]}: split the batch among these people (admins). An empty list clears the assignment.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`assign_batch`](#assign_batch) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `shares` | array of object | yes |  |  |
| `shares[].percent` | number | yes |  | Above 0; the shares are scaled to sum 100. |
| `shares[].user_id` | integer | yes |  |  |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.

An empty object.

### POST /api/ais/batches/{batch_id}/auto

Start an auto run

Body: {general?, settings?, threshold?, engine?, skip_done?, mark_done?, images?}: auto mode over the batch's included images, run by the server, each AIS the filters keep saved as the browser's review "all" saves it. Answers at once with the run (409 while one is going on the batch). See app/analysis/auto_runner.py.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`start_auto_run`](#start_auto_run) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `engine` | string | no | one of `fast` |  |
| `general` | object or null | no |  | Settings' general fields (auto_method, fitted_min_length, ...). |
| `images` | array of string or null | no |  | Only these image keys. |
| `mark_done` | boolean | no |  | Default false. |
| `settings` | object or null | no |  | The method's (pixconv, smooth, ...). |
| `skip_done` | boolean or null | no |  | Leave out images with an AIS or a done mark. Default: general's auto_skip_done. |
| `threshold` | number or null | no | 0 to 1 |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes |  |  |
| `choices` | object | yes |  |  |
| `choices.engine` | string or null | yes |  |  |
| `choices.general` | object | yes |  |  |
| `choices.settings` | object | yes |  |  |
| `choices.threshold` | number | yes |  |  |
| `created_at` | string | yes |  |  |
| `current` | string or null | yes |  | The image being worked on. |
| `done` | integer | yes |  |  |
| `errors` | array of object | yes |  |  |
| `errors[].error` | string | yes |  |  |
| `errors[].image` | string or null | yes |  |  |
| `finished_at` | string or null | yes |  |  |
| `found` | integer | yes |  |  |
| `hidden` | integer | yes |  |  |
| `id` | string | yes |  |  |
| `images` | array of string | yes |  | The image keys it goes through, in order. |
| `mark_done` | boolean | yes |  |  |
| `marked_done` | integer | yes |  |  |
| `saved` | integer | yes |  |  |
| `skip_done` | boolean | yes |  |  |
| `started_at` | string or null | yes |  |  |
| `state` | string | yes | one of `queued`, `running`, `finished`, `stopped`, `failed` |  |
| `total` | integer | yes |  |  |
| `user_id` | integer | yes |  |  |

### GET /api/ais/batches/{batch_id}/backup

What a backup ZIP holds besides the image files

What a backup ZIP holds besides the image files. Admins only: it has the original names in it.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`get_backup`](#get_backup) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Reply 200**: {format, version, users, stored, batch, results, measurements}: what POST /api/ais/batches/import takes.

An empty object.

### GET /api/ais/batches/{batch_id}/channels

A batch's channels

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`batch_channels`](#batch_channels) |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `channels` | array of object | yes |  |  |
| `channels[].color` | string | yes |  |  |
| `channels[].files` | integer | yes |  | How many files have it. |
| `channels[].name` | string | yes |  |  |
| `czis` | integer | yes |  | Included .czi files. |
| `unread` | integer | yes |  | Of those, the ones not stored or not readable. |

### POST /api/ais/batches/{batch_id}/delete

Delete a batch

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: Deleting a whole batch is kept out of agents' reach on purpose. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `trash_id` | integer | yes |  | Its entry in GET /api/ais/trash. |

### POST /api/ais/batches/{batch_id}/done

Mark an image done or not done

Body: {image, done}: mark an image done by hand (shared progress).

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_image_done`](#set_image_done) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `done` | boolean | yes |  |  |
| `image` | string | yes |  | The image's key. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `skipped` | array of string | yes |  | The keys of every image now marked done. |

### POST /api/ais/batches/{batch_id}/fill-areas

Fill in missing AIS areas

Body: {after?: result id, limit?: 1-50 (default 10), with_soma?: only AIS whose soma distance has been measured}: fill in the area (and on a Z-stack the volume) of the batch's accepted AIS that have none, tracing each again from its saved clicks, threshold and settings; only an AIS that comes out on the same pixels is filled in, and nothing else about it changes. A few at a time: call again with after until remaining is 0. {filled, failed: [result ids], after, remaining}.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`fill_missing_areas`](#fill_missing_areas) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `after` | integer | no | at least 0 | A result id. Default 0. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `limit` | integer | no | 1 to 50 | Default 10. |
| `with_soma` | boolean | no |  | Only AIS whose soma distance has been measured. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `after` | integer | yes |  | Give it back as after. |
| `failed` | array of integer | yes |  | Result ids not filled in. |
| `filled` | integer | yes |  |  |
| `remaining` | integer | yes |  |  |

### POST /api/ais/batches/{batch_id}/include

Include or exclude an image

Body: {keys, included}: include these images, or leave them out, for the whole team.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_images_included`](#set_images_included) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `included` | boolean | yes |  |  |
| `keys` | array of string | yes |  |  |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.

An empty object.

### GET /api/ais/batches/{batch_id}/layouts

A batch's channel layouts

?add=<id>: the channel layouts of a batch's images, or one add's: each with its channel names, colours, how many images, the roles in use and how many already have results; stacks: its Z-stacks' {count, z_step_um, pixel_um, mixed}, or null; pixel: its other images' {count, pixel_um (null: Settings', 40x by default), mixed}, or null.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`get_channel_layouts`](#get_channel_layouts) |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |
| `add` | query | integer | no | at least 1 | Only this add's images. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `images` | integer | yes |  |  |
| `layouts` | array of object | yes |  |  |
| `layouts[].colors` | array of string or null | yes |  |  |
| `layouts[].count` | integer | yes |  |  |
| `layouts[].layout` | object | yes |  | {kind, names}. |
| `layouts[].results` | integer | yes |  | Images with this layout that have results. |
| `layouts[].roles` | array of object | yes |  |  |
| `layouts[].roles[].label` | string | yes |  | The channel's name; empty unless role is other. |
| `layouts[].roles[].role` | string | yes | one of `ais`, `soma`, `other` |  |
| `pixel` | object or null | yes |  |  |
| `pixel.count` | integer | yes |  |  |
| `pixel.mixed` | boolean | yes |  |  |
| `pixel.pixel_um` | number or null | yes |  | null: Settings', 40x by default. |
| `stacks` | object or null | yes |  |  |
| `stacks.count` | integer | yes |  |  |
| `stacks.from_file` | integer | yes |  | How many are .czi files, calibrated from the file. |
| `stacks.mixed` | boolean | yes |  |  |
| `stacks.pixel_um` | number | yes |  |  |
| `stacks.z_step_um` | number | yes |  |  |
| `unread` | integer | yes |  |  |

### POST /api/ais/batches/{batch_id}/layouts

Set a batch's channel roles

Body: {add?, channels: [{layout, roles}], stack?: {z_step_um, pixel_um}, pixel_um?: number or null}: which channel is the AIS, soma/dendrite or other, for the images of a batch (or one add) with those layouts, its Z-stacks' slice spacing and pixel size, and the microns per pixel its other images are measured with (null: back to the 40x default; left out: unchanged). Answers with the batch and the keys of the images now traced from other channels or calibration.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_channel_roles`](#set_channel_roles) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `add` | integer or null | no |  | Only this add's images. |
| `channels` | array of object | yes |  |  |
| `channels[].layout` | object | yes |  | {kind, names}: a layout as GET .../layouts gives it. |
| `channels[].roles` | array of object | yes |  | One per channel: exactly one ais, at most one soma. |
| `channels[].roles[].label` | string | yes |  | The channel's name; empty unless role is other. |
| `channels[].roles[].role` | string | yes | one of `ais`, `soma`, `other` |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `pixel_um` | number or null | no |  | null: back to the 40x default; left out: unchanged. |
| `stack` | object or null | no |  |  |
| `stack.pixel_um` | number | yes |  |  |
| `stack.z_step_um` | number | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch` | object | yes |  | The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded. |
| `changed` | array of string | yes |  | Keys of the images now traced from other channels or calibration. |

### POST /api/ais/batches/{batch_id}/path

Add a folder on this computer to a batch

Body: {path}: a folder on this machine added to an existing batch.

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `channels` | array of object or null | no |  | Channel roles per layout. |
| `channels[].layout` | object | yes |  | {kind, names}: a layout as GET .../layouts gives it. |
| `channels[].roles` | array of object | yes |  | One per channel: exactly one ais, at most one soma. |
| `channels[].roles[].label` | string | yes |  | The channel's name; empty unless role is other. |
| `channels[].roles[].role` | string | yes | one of `ais`, `soma`, `other` |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `czi_stack` | object or null | no |  |  |
| `czi_stack.apotome` | string | no | one of `sectioned`, `widefield` | How ApoTome phases become slices. Default sectioned. |
| `path` | string | yes |  | A folder on this machine. |
| `randomize` | boolean | no |  | Blind the names. Default true. |
| `stack` | object or null | no |  |  |
| `stack.pixel_um` | number | yes |  |  |
| `stack.plane` | integer | yes | 0 to 3 | The channel of each slice that is the AIS. |
| `stack.z_step_um` | number | yes |  |  |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.

An empty object.

### POST /api/ais/batches/{batch_id}/rename

Rename a batch

Body: {name}. Its accepted AIS carry the new name too.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`rename_batch`](#rename_batch) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `name` | string | yes |  |  |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.

An empty object.

### POST /api/ais/batches/{batch_id}/reset

Reset a batch's results

Body: {scope: all | auto}: delete the batch's results (admins), to run it again. The Batches screen offers a backup export first.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`reset_batch_auto`](#reset_batch_auto) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `scope` | string | yes | one of `all`, `auto` |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch` | object | yes |  | The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded. |
| `deleted` | integer | yes |  | AIS deleted. |
| `trash_id` | integer or null | yes |  | null when nothing went. |

### GET /api/ais/batches/{batch_id}/status

Each image's progress in a batch

Per image: files on the server, accepted AIS, done, duplicate, assignee.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`batch_status`](#batch_status) |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `id` | integer | yes |  |  |
| `images` | array of object | yes |  |  |
| `images[].add_id` | integer or null | yes |  |  |
| `images[].ais` | integer | yes |  |  |
| `images[].assignee` | integer or null | yes |  |  |
| `images[].assignee_name` | string | yes |  |  |
| `images[].auto` | integer | yes |  |  |
| `images[].cell` | string | yes |  |  |
| `images[].dir` | string | yes |  |  |
| `images[].done` | boolean | yes |  |  |
| `images[].dup_of` | string or null | yes |  | The key of the image it duplicates. |
| `images[].files` | integer | yes |  |  |
| `images[].included` | boolean | yes |  |  |
| `images[].key` | string | yes |  |  |
| `images[].original_key` | string | no |  | Admins, for a blinded image. |
| `images[].stored` | integer | yes |  |  |

### POST /api/ais/batches/{batch_id}/translation

Load a batch's translation file

Body: {text}: a __Translation.txt for a batch blinded somewhere else (admins): the original names of the files it names.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`load_translation`](#load_translation) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `text` | string | yes |  | A __Translation.txt's contents. |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded. Plus named and unnamed: how many images it named, and how many are still without.

An empty object.

### GET /api/ais/batches/{batch_id}/translation.txt

The batch's __Translation.txt (admins)

The batch's __Translation.txt (admins): original/random per file.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`get_translation`](#get_translation) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Reply 200**: Success

Text, as `text/plain`.

### GET /api/ais/batches/{batch_id}/treatments

Each image's original name, saved treatment and guessed one (admins)

Each image's original name, saved treatment and guessed one (admins).

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`get_treatments`](#get_treatments) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `treatments` | array of object | yes |  |  |
| `treatments[].folder` | string | yes |  |  |
| `treatments[].guess` | string | yes |  |  |
| `treatments[].guess_key` | string | yes |  |  |
| `treatments[].guess_written` | string | yes |  |  |
| `treatments[].included` | boolean | yes |  |  |
| `treatments[].key` | string | yes |  |  |
| `treatments[].original` | string | yes |  | The image's original name. |
| `treatments[].treatment` | string | yes |  | Saved; empty if none. |

### POST /api/ais/batches/{batch_id}/treatments

Save a batch's treatments

Body: {treatments: {key: name}} (admins); "" takes one off.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`set_treatments`](#set_treatments) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `treatments` | map of string | yes |  | Image key -> treatment; "" takes one off. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `treatments` | array of object | yes |  |  |
| `treatments[].folder` | string | yes |  |  |
| `treatments[].guess` | string | yes |  |  |
| `treatments[].guess_key` | string | yes |  |  |
| `treatments[].guess_written` | string | yes |  |  |
| `treatments[].included` | boolean | yes |  |  |
| `treatments[].key` | string | yes |  |  |
| `treatments[].original` | string | yes |  | The image's original name. |
| `treatments[].treatment` | string | yes |  | Saved; empty if none. |

### POST /api/ais/batches/{batch_id}/upload

Add images to a batch

Body: {files: [{name, rel, sha, size, modified?}], randomize?, add_name?, translations?: [{dir, text}]}: more files picked in the browser for an existing batch, named by any __Translation.txt picked with them, blinded unless randomize is false. Upload them afterwards as for a new one.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`add_files_to_batch`](#add_files_to_batch) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `add_name` | string | no |  |  |
| `channels` | array of object or null | no |  | Channel roles per layout. |
| `channels[].layout` | object | yes |  | {kind, names}: a layout as GET .../layouts gives it. |
| `channels[].roles` | array of object | yes |  | One per channel: exactly one ais, at most one soma. |
| `channels[].roles[].label` | string | yes |  | The channel's name; empty unless role is other. |
| `channels[].roles[].role` | string | yes | one of `ais`, `soma`, `other` |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `czi_stack` | object or null | no |  |  |
| `czi_stack.apotome` | string | no | one of `sectioned`, `widefield` | How ApoTome phases become slices. Default sectioned. |
| `files` | array of object | yes |  | 1 to 5000. |
| `files[].layout` | object | no |  | Its channels as the browser read them. |
| `files[].modified` | string | no |  | When it was last changed, ISO. |
| `files[].name` | string | yes |  |  |
| `files[].rel` | string | no |  | Its path under the folder picked. Default name. |
| `files[].sha` | string | yes |  | sha-256, hex. |
| `files[].size` | integer | no |  |  |
| `files[].zstack` | object | no |  | A .czi with more than one slice: what it says of itself. |
| `files[].zstack.phases` | integer | no | at least 1 | Its ApoTome grid phases; 1 (the default) without. |
| `files[].zstack.pixel_um` | number or null | yes |  | Its X scaling; null without, when stack's is used. |
| `files[].zstack.slices` | integer | yes | at least 2 | Its Z planes. |
| `files[].zstack.z_step_um` | number or null | yes |  | Its Z scaling; null without, when stack's is used. |
| `randomize` | boolean | no |  | Blind the names. Default true. |
| `stack` | object or null | no |  |  |
| `stack.pixel_um` | number | yes |  |  |
| `stack.plane` | integer | yes | 0 to 3 | The channel of each slice that is the AIS. |
| `stack.z_step_um` | number | yes |  |  |
| `translations` | array of object | no |  |  |
| `translations[].dir` | string | yes |  |  |
| `translations[].text` | string | yes |  | A __Translation.txt's contents. |

**Reply 200**: The batch record: its images (each file with stored, and for admins the original names), adds, assignment, skipped, created_by_name, assignee_names, adder_names and excluded.

An empty object.

### POST /api/ais/compare

Compare treatments across batches

Body: {batch_ids, labels?, tests?, units?, design?, sheets?, plots?}: the batches' measurements grouped by treatment, and with two or more, tested and plotted (admins: it has the original names and treatments). sheets: true adds comparison.xlsx's sheets as JSON ({columns, rows} each) and then keeps the SVG plots only with plots: true. See app/analysis/compare.py and report.py.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`compare_batches`](#compare_batches) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_ids` | array of integer | yes |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `design` | any | no |  | The two-way ANOVA's factors. |
| `labels` | any | no |  |  |
| `plots` | boolean | no |  | With sheets: keep the SVG plots. Default true. |
| `sheets` | boolean | no |  | Add comparison.xlsx's sheets. Default false. |
| `tests` | array of string or null | no |  | The stats rows; every one when left out. |
| `units` | array of string or null | no |  | The stats rows; every one when left out. |

**Reply 200**: {measures, treatments, images, values, groups, pooled, stats, dropped, plots}, and sheets with sheets: true.

An empty object.

### POST /api/ais/detect

Find every AIS on an image (auto mode)

Auto mode. Body: {processed, raw?, threshold?, settings?, start?, exclude?: [[[x, y], ...], ...], engine?: "fast"}. Every AIS found on the image without a click (app/analysis/detect.py); start is both | brighter | dimmer | soma (a .czi only) | fitted | fitted2 | learned, exclude the traces already accepted on it.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`detect_image`](#detect_image) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `engine` | string | no | one of `fast` |  |
| `exclude` | array of array of array of integer or null | no |  | The traces already accepted, each [[x, y], ...]. |
| `processed` | string | yes |  | The traced image's sha. |
| `raw` | string or null | no |  | The raw image's sha, for a TIFF pair. |
| `settings` | object | no |  | The method's settings; missing ones are the original's. |
| `start` | string | no | one of `both`, `brighter`, `dimmer`, `soma`, `fitted`, `fitted2`, `learned` |  |
| `threshold` | number | no | 0 to 1 | Default 0.01; 0 is Otsu. |
| `z_method` | string | no |  | On a Z-stack: how its 3D length is measured. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `candidates` | array of object | yes |  | Each a trace's answer, plus seed, filter and soma_gap_um. |
| `components` | integer | yes |  |  |
| `failed` | integer | yes |  |  |
| `known` | integer | yes |  |  |
| `merged` | integer | yes |  |  |
| `somata` | array of array of array of integer | no |  | The soma outlines, when it found any. |

### POST /api/ais/files

Upload an image (TIFF or .czi)

The file's bytes as application/octet-stream with the CSRF token in X-CSRF-Token (what the page sends: no base64, no JSON parse of a 6 MB string), or JSON {data: base64} like every other POST.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`upload_instructions`](#upload_instructions), [`files_stored`](#files_stored) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `X-CSRF-Token` | header | string | no |  | From GET /api/me. Browser sessions only. |

**Request body**

Raw bytes, as `application/octet-stream`.

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `czi` | boolean | yes |  |  |
| `dtype` | string | yes |  | The pixels' numpy type, uint16 say. |
| `height` | integer | yes |  |  |
| `sha256` | string | yes |  |  |
| `width` | integer | yes |  |  |

### GET /api/ais/files/{sha}/channel/{index}.png

One .czi channel, for the viewer

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: Viewer images for the Process screen; get_image gives an agent the processed view. |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `sha` | path | string | yes |  | The file's sha-256, as POST /api/ais/files answered. |
| `index` | path | integer | yes | at least 0 | 0-based. |

**Reply 200**: Success

Text, as `image/png`.

### GET /api/ais/files/{sha}/channel/{index}.tif

One .czi channel, its data as a 16-bit TIFF, for exports

One .czi channel, its data as a 16-bit TIFF, for exports.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: File bytes: MCP messages are JSON, and clients cap their size. Fetch it over HTTP with the same key. |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `sha` | path | string | yes |  | The file's sha-256, as POST /api/ais/files answered. |
| `index` | path | integer | yes | at least 0 | 0-based. |

**Reply 200**: Success

Text, as `image/tiff`.

### GET /api/ais/files/{sha}/channels

A .czi's channels

A .czi's channels [{index, name, color}] for the channel buttons; [] for a TIFF.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: Viewer detail for the Process screen's channel picker; get_batch names each image's files. |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `sha` | path | string | yes |  | The file's sha-256, as POST /api/ais/files answered. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `channels` | array of object | yes |  |  |
| `channels[].color` | string | yes |  | #rrggbb. |
| `channels[].index` | integer | yes |  |  |
| `channels[].name` | string | yes |  |  |

### GET /api/ais/files/{sha}/composite.png

A .czi's channels merged in their display colors, for exports

A .czi's channels merged in their display colors, for exports.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: Reached through get_image with kind composite. |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `sha` | path | string | yes |  | The file's sha-256, as POST /api/ais/files answered. |

**Reply 200**: Success

Text, as `image/png`.

### GET /api/ais/files/{sha}/file

The stored file itself (a .czi or TIFF as it was added), for exports

The stored file itself (a .czi or TIFF as it was added), for exports.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: File bytes: MCP messages are JSON, and clients cap their size. Fetch it over HTTP with the same key. |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `sha` | path | string | yes |  | The file's sha-256, as POST /api/ais/files answered. |

**Reply 200**: Success: image/tiff for a TIFF, else application/octet-stream.

Raw bytes, as `application/octet-stream`.

### POST /api/ais/files/{sha}/pair

Guess each AIS's soma end and soma, and the soma ellipses

Body {pixel_um, traces: [{id, pixels}], split?, soma?: {min_um, max_um, roundness}}: for each accepted AIS on the image, the Measure tool's guess (app/analysis/pairing.py): which end starts at the soma (the thicker), the soma in front of it, and B on that soma's ellipse (the largest inside it the soma size and roundness allow); and the image's soma ellipses (split, the default: one per hotspot, else one per outline). {pairs: [{id, end, by, widths, a, b, body, gap_um, angle_deg, confident, other}], bodies: [{cx, cy, a, b, angle_deg, ais}]}.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: A first guess for the Measure tool on the Process screen; it stores nothing. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `sha` | path | string | yes |  | The file's sha-256, as POST /api/ais/files answered. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `pixel_um` | number | yes |  | Microns per pixel, above 0. |
| `soma` | object | no |  | 0 <= min_um < max_um <= 200. |
| `soma.max_um` | number | no |  |  |
| `soma.min_um` | number | no |  |  |
| `soma.roundness` | number | no | 0 to 1 |  |
| `split` | boolean | no |  | One soma per hotspot. Default true. |
| `traces` | array of object | yes |  | At most 500. |
| `traces[].id` | any | yes |  | Yours, given back with its pair. |
| `traces[].pixels` | array of array of integer | yes |  | 1-based [x, y] whole numbers. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `bodies` | array of object | yes |  |  |
| `bodies[].a` | number | yes |  |  |
| `bodies[].ais` | any | yes |  | The id of the AIS it faces, or null. |
| `bodies[].angle_deg` | number | yes |  |  |
| `bodies[].b` | number | yes |  |  |
| `bodies[].cx` | number | yes |  |  |
| `bodies[].cy` | number | yes |  |  |
| `bodies[].z` | number | no |  | A Z-stack's: the soma's depth, in slice numbers. |
| `pairs` | array of object | yes |  |  |
| `pairs[].a` | array of number | yes |  |  |
| `pairs[].angle_deg` | number or null | yes |  |  |
| `pairs[].b` | array of number or null | yes |  |  |
| `pairs[].body` | integer or null | yes |  | Index into bodies. |
| `pairs[].by` | string | yes | one of `width`, `soma`, `default` |  |
| `pairs[].confident` | boolean | yes |  |  |
| `pairs[].end` | string | yes | one of `first`, `last` | The end at the soma. |
| `pairs[].gap_um` | number or null | yes |  |  |
| `pairs[].id` | any | yes |  |  |
| `pairs[].other` | object | yes |  | The same from the other end. |
| `pairs[].other.a` | array of number | yes |  |  |
| `pairs[].other.b` | array of number or null | yes |  |  |
| `pairs[].other.body` | integer or null | yes |  |  |
| `pairs[].other.end` | string | yes | one of `first`, `last` |  |
| `pairs[].other.gap_um` | number or null | yes |  |  |
| `pairs[].soma` | integer or null | yes |  | The same as body. |
| `pairs[].widths` | array of number or null | yes |  | [first, last] in um. |

### GET /api/ais/files/{sha}/processed.tif

A .czi's processed AIS channel as a TIFF (what tracing uses), for exports

A .czi's processed AIS channel as a TIFF (what tracing uses), for exports.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: File bytes: MCP messages are JSON, and clients cap their size. Fetch it over HTTP with the same key. |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `sha` | path | string | yes |  | The file's sha-256, as POST /api/ais/files answered. |

**Reply 200**: Success

Text, as `image/tiff`.

### GET /api/ais/files/{sha}/slice/{index}.png

One slice of a Z-stack, for the viewer's Z slider

One slice of a Z-stack, for the viewer's Z slider.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: Viewer images for the Process screen's z-stack slider; get_image gives an agent the processed view. |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `sha` | path | string | yes |  | The file's sha-256, as POST /api/ais/files answered. |
| `index` | path | integer | yes | at least 0 | 0-based. |

**Reply 200**: Success

Text, as `image/png`.

### GET /api/ais/files/{sha}/somata

A .czi's soma outlines

A .czi's soma outlines (soma.py), each its edge pixels as 1-based [x, y], for the Soma button; [] for a TIFF.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: Viewer overlay for the Process screen; detect_image and trace_click give an agent the results. |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `sha` | path | string | yes |  | The file's sha-256, as POST /api/ais/files answered. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `somata` | array of array of array of integer | yes |  | Per soma, its edge pixels as 1-based [x, y]. |

### GET /api/ais/files/{sha}/thumb.png

An image's thumbnail

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: Reached through get_image with kind thumb. |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `sha` | path | string | yes |  | The file's sha-256, as POST /api/ais/files answered. |

**Reply 200**: Success

Text, as `image/png`.

### GET /api/ais/files/{sha}/view.png

An image for the viewer

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`get_image`](#get_image) |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `sha` | path | string | yes |  | The file's sha-256, as POST /api/ais/files answered. |

**Reply 200**: Success

Text, as `image/png`.

### GET /api/ais/folders

The Batches screen's folders

Every folder: id, name, parent_id (null at the top), position.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_folders`](#list_folders) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `folders` | array of object | yes |  |  |
| `folders[].created_at` | string | yes |  |  |
| `folders[].created_by` | integer | yes |  |  |
| `folders[].id` | integer | yes |  |  |
| `folders[].name` | string | yes |  |  |
| `folders[].parent_id` | integer or null | yes |  | null at the top. |
| `folders[].position` | integer | yes |  |  |
| `folders[].updated_at` | string | yes |  |  |

### POST /api/ais/folders

Create a folder

Body: {name, parent_id}: a new folder, first in its parent (null: the top) (admins).

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`create_folder`](#create_folder) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `name` | string | yes |  |  |
| `parent_id` | integer or null | yes |  | null: the top. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string | yes |  |  |
| `created_by` | integer | yes |  |  |
| `id` | integer | yes |  |  |
| `name` | string | yes |  |  |
| `parent_id` | integer or null | yes |  | null at the top. |
| `position` | integer | yes |  |  |
| `updated_at` | string | yes |  |  |

### POST /api/ais/folders/order

Set the order of one folder's folders

Body: {parent_id, ids} (admins).

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`order_folders`](#order_folders) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `ids` | array of integer | yes |  |  |
| `parent_id` | integer or null | yes |  | null: the top. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/ais/folders/{folder_id}/delete

Delete a folder

What was in it, folders and batches, moves up to its parent (admins).

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | None, HTTP only: Deleting a folder is kept out of agents' reach on purpose. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `folder_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `trash_id` | integer | yes |  | Its entry in GET /api/ais/trash. |

### POST /api/ais/folders/{folder_id}/move

Move a folder into another

Body: {parent_id}: null for the top; not into itself or anything inside it (admins).

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`move_folder`](#move_folder) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `folder_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `parent_id` | integer or null | yes |  | null: the top. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string | yes |  |  |
| `created_by` | integer | yes |  |  |
| `id` | integer | yes |  |  |
| `name` | string | yes |  |  |
| `parent_id` | integer or null | yes |  | null at the top. |
| `position` | integer | yes |  |  |
| `updated_at` | string | yes |  |  |

### POST /api/ais/folders/{folder_id}/rename

Rename a folder

Body: {name} (admins).

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`rename_folder`](#rename_folder) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `folder_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `name` | string | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string | yes |  |  |
| `created_by` | integer | yes |  |  |
| `id` | integer | yes |  |  |
| `name` | string | yes |  |  |
| `parent_id` | integer or null | yes |  | null at the top. |
| `position` | integer | yes |  |  |
| `updated_at` | string | yes |  |  |

### POST /api/ais/local/channels

Find channel layouts in a folder on this computer

Body: {path}. The channel layouts of a folder's images, for the Add dialog to ask about before the server hashes anything.

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `path` | string | yes |  | An absolute path on this machine. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `layouts` | array of object | yes |  |  |
| `layouts[].colors` | array of string or null | yes |  | #rrggbb per channel, for a .czi; null for a TIFF. |
| `layouts[].count` | integer | yes |  | Files with this layout. |
| `layouts[].layout` | object | yes |  |  |
| `layouts[].layout.kind` | string | yes | one of `czi`, `tiff` |  |
| `layouts[].layout.names` | array of string | yes |  |  |
| `layouts[].roles` | array of object | yes |  |  |
| `layouts[].roles[].label` | string | yes |  |  |
| `layouts[].roles[].role` | string | yes | one of `ais`, `soma`, `other` |  |
| `layouts[].stacks` | integer | yes |  | How many of those files are Z-stack slices. |

### POST /api/ais/local/choose

Pick a folder on this computer

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `cancelled` | boolean | yes |  |  |
| `path` | string or null | yes |  | null when cancelled. |

### POST /api/ais/local/list

List a folder on this computer

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `path` | string | yes |  | An absolute path on this machine. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `dirs` | array of string | yes |  |  |
| `files` | array of object | yes |  | Its TIFFs. |
| `files[].name` | string | yes |  |  |
| `files[].size` | integer | yes |  | Bytes. |
| `parent` | string or null | yes |  | null at the top. |
| `path` | string | yes |  |  |

### POST /api/ais/local/matlab

Verify an image in MATLAB on this computer

Body: see matlab_run. Starts MATLAB's desktop on the original ais_auto.m for that image, on this machine (app/analysis/matlab.py).

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `cell` | string | yes |  | The cell's name as the browser shows it: a blinded name stays blind. |
| `clicks` | array of array of number | no |  | replay: one or two clicks as [x, y]. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `mode` | string | no | one of `open`, `run`, `replay` | Default run. |
| `processed` | string | yes |  | The traced image's file id (its sha-256). |
| `raw` | string or null | no |  | The profile image's file id, when the cell has both. |
| `settings` | object or null | no |  | The method settings (app/analysis/ais_auto.Settings); missing ones are the original's. |
| `threshold` | number | no | 0 to 1 | Default 0.01. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `folder` | string | yes |  | Where the image was staged for MATLAB. |
| `matlab` | string | yes |  | The MATLAB that was started. |
| `ok` | boolean | yes |  |  |

### POST /api/ais/local/open

Open a file on this computer

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `path` | string | yes |  | An absolute path on this machine. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/ais/local/reveal

Show a file in Finder

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `path` | string | yes |  | An absolute path on this machine. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/ais/local/stacks

Find Z-stacks in a folder on this computer

Body: {path}. The Z-stacks under a folder, by name, for the Add dialog to ask about before the server hashes anything.

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `path` | string | yes |  | An absolute path on this machine. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `stacks` | array of object | yes |  |  |
| `stacks[].cell` | string | yes |  |  |
| `stacks[].slices` | integer | yes |  |  |

### GET /api/ais/local/status

Whether folders on this computer and MATLAB are available

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: Whether Open path and MATLAB work on this machine: those routes need a browser session. |
| Errors | 401, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `enabled` | boolean | yes |  | Open path works for you: an admin with a browser session, on a server that allows it. |
| `helper` | boolean | yes |  | Your MATLAB helper has polled lately. |
| `helper_enabled` | boolean | yes |  | The MATLAB helper is switched on. |
| `matlab` | boolean | yes |  | MATLAB can open on this machine and you are sitting at it. |
| `platform` | string | yes | one of `mac`, `windows`, `linux` | The server's. |

### POST /api/ais/matlab/bundle

Download a MATLAB replay zip

Body: see matlab_run. The zip "Download MATLAB Replay" saves: the same images /file and /processed.tif already give a signed-in person, so this needs nothing more than that.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: A MATLAB run as a zip download for a person's computer. |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `cell` | string | yes |  | The cell's name as the browser shows it: a blinded name stays blind. |
| `clicks` | array of array of number | no |  | replay: one or two clicks as [x, y]. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `mode` | string | no | one of `open`, `run`, `replay` | Default run. |
| `processed` | string | yes |  | The traced image's file id (its sha-256). |
| `raw` | string or null | no |  | The profile image's file id, when the cell has both. |
| `settings` | object or null | no |  | The method settings (app/analysis/ais_auto.Settings); missing ones are the original's. |
| `threshold` | number | no | 0 to 1 | Default 0.01. |

**Reply 200**: Success

Text, as `application/zip`.

### GET /api/ais/matlab/helper/download/{platform}

The helper for one OS and CPU, from helper/build.sh

The helper for one OS and CPU, from helper/build.sh.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The MATLAB helper program itself, a download for a person's computer. |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `platform` | path | string | yes | one of `darwin-arm64`, `darwin-x86_64`, `darwin-amd64`, `linux-x86_64`, `linux-amd64`, `linux-aarch64`, `linux-arm64`, `windows-amd64` | `uname -s`-`uname -m`, lowercased, or Go's name for it. |

**Reply 200**: Success

Raw bytes, as `application/octet-stream`.

### GET /api/ais/matlab/helper/jobs/{job_id}/bundle

The claimed run's zip, built now rather than held in memory waiting

The claimed run's zip, built now rather than held in memory waiting.

|  |  |
|---|---|
| Who may call | API key only, anyone signed in |
| MCP tool | None, HTTP only: Called by the MATLAB helper program, not by agents; the bundle is a zip. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `job_id` | path | string | yes |  |  |

**Reply 200**: Success

Text, as `application/zip`.

### POST /api/ais/matlab/helper/jobs/{job_id}/done

Report what the helper launched

Body: {ok, message?}: what the helper did with the job.

|  |  |
|---|---|
| Who may call | API key only, anyone signed in |
| MCP tool | None, HTTP only: Called by the MATLAB helper program, not by agents. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `job_id` | path | string | yes |  |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `message` | string | no |  | Why not, shown to the person. Cut to 500 characters. |
| `ok` | boolean | yes |  | Whether MATLAB started. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/ais/matlab/helper/key

Make a MATLAB helper key

The Connect button: a key good for the helper's routes and nothing else (app/models/api_keys.py). The credential appears here and nowhere else.

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 201**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  | The helper's key, sent as Authorization: Bearer. Shown only here: treat it like a password. |

### GET /api/ais/matlab/helper/next

The helper's next run

Polled by the helper: also how the server knows it is there.

|  |  |
|---|---|
| Who may call | API key only, anyone signed in |
| MCP tool | None, HTTP only: Called by the MATLAB helper program, not by agents. |
| Errors | 401, 403, 404, 429, 503 |

**Reply 200**: The run to open, now claimed. 204 with no body when there is none.

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `cell` | string | yes |  | The cell's name, safe as a file name. |
| `id` | string | yes |  | The job's id, for its bundle and done routes. |
| `mode` | string | yes | one of `open`, `run`, `replay` |  |

### POST /api/ais/matlab/send

Send a MATLAB run to your helper

Body: see matlab_run. Hands the run to the caller's own helper and answers with what became of it.

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `cell` | string | yes |  | The cell's name as the browser shows it: a blinded name stays blind. |
| `clicks` | array of array of number | no |  | replay: one or two clicks as [x, y]. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `mode` | string | no | one of `open`, `run`, `replay` | Default run. |
| `processed` | string | yes |  | The traced image's file id (its sha-256). |
| `raw` | string or null | no |  | The profile image's file id, when the cell has both. |
| `settings` | object or null | no |  | The method settings (app/analysis/ais_auto.Settings); missing ones are the original's. |
| `threshold` | number | no | 0 to 1 | Default 0.01. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/ais/measure-types

The team's measurement types for the Measure tool's Type picker

The team's measurement types for the Measure tool's Type picker.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_measure_types`](#list_measure_types) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `types` | array of string | yes |  |  |

### POST /api/ais/measure-types

Set the measurement types

Body: {types: [name, ...]}: the team's new list (admins).

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`set_measure_types`](#set_measure_types) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `types` | array of string | yes |  | 1 to 50 names, up to 100 characters each, in order. Repeats are dropped. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `types` | array of string | yes |  | The list as saved. |

### GET /api/ais/measurements

Recorded measurements

?batch=<id> for one batch, anything else for all.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_measurements`](#list_measurements) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch` | query | string | no |  | A batch id; anything else lists every batch's. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `measurements` | array of [`Measurement`](#measurement) | yes |  | Oldest first. |

### POST /api/ais/measurements

Record a measurement

Body: {batch_id, image, measurement}: a line recorded on an image.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`add_measurement`](#add_measurement) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes |  |  |
| `client_id` | string | no |  | Your own id for it (8-64 letters, digits, dashes): sent again, it answers with the line already made. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `image` | string | yes |  | The image's key in the batch. |
| `measurement` | object | yes |  | Every number 0 or more. |
| `measurement.a_x` | number | yes |  |  |
| `measurement.a_y` | number | yes |  |  |
| `measurement.b_x` | number | yes |  |  |
| `measurement.b_y` | number | yes |  |  |
| `measurement.label` | string | no |  |  |
| `measurement.length_px` | number | yes |  |  |
| `measurement.length_um` | number | yes |  |  |
| `measurement.pixconv` | number | yes |  |  |
| `measurement.type` | string | no |  | One of the team's measurement types, or empty. |

**Reply 200**: Success

[`Measurement`](#measurement).

### POST /api/ais/measurements/{measurement_id}/delete

Delete a measurement

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_measurement`](#delete_measurement) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `measurement_id` | path | integer | yes |  |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | integer | no | at least 0 | The rev you last saw. Answers 409, with the record as it is now, if it has moved on. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `renumbered` | array of object | yes |  | The image's other lines whose number changed, with their new n. |
| `renumbered[].id` | integer | yes |  |  |
| `renumbered[].n` | integer | yes |  |  |

### POST /api/ais/measurements/{measurement_id}/update

Change a measurement

Body: {measurement}: a recorded line's new ends, length and label.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`update_measurement`](#update_measurement) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `measurement_id` | path | integer | yes |  |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | integer | no | at least 0 | The rev you last saw. Answers 409, with the record as it is now, if it has moved on. |
| `measurement` | object | yes |  |  |
| `measurement.a_x` | number | yes |  |  |
| `measurement.a_y` | number | yes |  |  |
| `measurement.b_x` | number | yes |  |  |
| `measurement.b_y` | number | yes |  |  |
| `measurement.label` | string | no |  |  |
| `measurement.length_px` | number | yes |  |  |
| `measurement.length_um` | number | yes |  |  |
| `measurement.pixconv` | number | yes |  |  |
| `measurement.type` | string | no |  | One of the team's measurement types, or empty. |

**Reply 200**: Success

[`Measurement`](#measurement).

### GET /api/ais/report

The batch report as JSON

The Batches screen's report (report.xlsx) as JSON sheets, each {columns, rows}: summary, images, assignees, ais, measurements, measurement_types, and for admins original_names, by_treatment and statistics. Images left out are not in it unless everything=1; unblind=1 (admins only) puts blinded images under their original names. See app/analysis/report.py.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`export_report`](#export_report) |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch` | query | string | no |  | all (default), a batch id, or ids separated by commas |
| `everything` | query | string | no | one of `0`, `1`, `false`, `true` | 0 or 1: also the images left out |
| `unblind` | query | string | no | one of `0`, `1`, `false`, `true` | 0 or 1 (admins): original names |
| `sheets` | query | string | no |  | sheet names separated by commas: only those |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batches` | array of object | yes |  |  |
| `batches[].id` | integer | yes |  |  |
| `batches[].name` | string | yes |  |  |
| `everything` | boolean | yes |  |  |
| `sheets` | map of object | yes |  | By name: summary, images, assignees, ais, measurements, measurement_types, and for admins original_names, by_treatment and statistics once images have treatments. |
| `unblinded` | boolean | yes |  | Whether blinded images are under their original names. |

### GET /api/ais/results

Accepted AIS

?batch=<id> for one batch, anything else for all.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_results`](#list_results) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch` | query | string | no |  | A batch id; anything else lists every batch's. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `results` | array of [`AISResult`](#aisresult) | yes |  | Oldest first. |

### POST /api/ais/results

Accept an AIS

Body: {batch_id, image, row} with row the accepted trace's numbers.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`save_result`](#save_result) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes |  |  |
| `client_id` | string | no |  | Your own id for it (8-64 letters, digits, dashes): sent again, it answers with the AIS already made. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `image` | string | yes |  | The image's key in the batch. |
| `row` | object | yes |  | The accepted trace's numbers, texts and pixels, as POST /api/ais/trace gives them. |

**Reply 200**: Success

[`AISResult`](#aisresult).

### POST /api/ais/results/import

Import results

Body: {name, rows}: results kept in a browser before they lived here.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: A results file upload: MCP messages are JSON, and clients cap their size. Send it over HTTP with the same key. |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `name` | string | no |  | The new batch's name. Default Imported from browser. |
| `rows` | array of object | yes |  | 1 to 5000 accepted rows, each with its image (the cell) and optionally its sha. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes |  | The new batch they went into. |

### POST /api/ais/results/{result_id}/delete

Delete an accepted AIS

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_result`](#delete_result) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `result_id` | path | integer | yes |  |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | integer | no | at least 0 | The rev you last saw. Answers 409, with the record as it is now, if it has moved on. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `renumbered` | array of object | yes |  | The image's other AIS whose number changed, with their new n. |
| `renumbered[].id` | integer | yes |  |  |
| `renumbered[].n` | integer | yes |  |  |

### POST /api/ais/results/{result_id}/soma

Set an accepted AIS's soma

Body: {soma}: an accepted AIS's distance to its soma (the Measure tool), or null to clear it. The trace is left as it is.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_result_soma`](#set_result_soma) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `result_id` | path | integer | yes |  |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | integer | no | at least 0 | The rev you last saw. Answers 409, with the record as it is now, if it has moved on. |
| `soma` | object or null | yes |  |  |
| `soma.soma_ais_x` | number | yes |  |  |
| `soma.soma_ais_y` | number | yes |  |  |
| `soma.soma_dz_um` | number | no |  | Z-stacks: the distance in depth. |
| `soma.soma_px` | number | yes |  |  |
| `soma.soma_um` | number | yes |  |  |
| `soma.soma_x` | number | yes |  |  |
| `soma.soma_xy_um` | number | no |  | Z-stacks: the distance across the image. |
| `soma.soma_y` | number | yes |  |  |

**Reply 200**: Success

[`AISResult`](#aisresult).

### POST /api/ais/results/{result_id}/update

Change an accepted AIS

Body: {row}: an accepted AIS traced again (the Edit tool). It keeps its number and origin.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`update_result`](#update_result) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `result_id` | path | integer | yes |  |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | integer | no | at least 0 | The rev you last saw. Answers 409, with the record as it is now, if it has moved on. |
| `row` | object | yes |  | The new trace's numbers, texts and pixels, as POST /api/ais/trace gives them. |

**Reply 200**: Success

[`AISResult`](#aisresult).

### POST /api/ais/trace

Trace an AIS from a click (ais_auto.m)

Body: {processed, raw?, click: [x, y], click2?: [x, y], threshold?, settings?: {smooth, kernel, sigma, ...}, engine?: "fast"}. Clicks are MATLAB axes coordinates (x = column, y = row, pixel centres at 1..n). click2 stands in for the second ginput after re-thresholding; by default the first click is used again. threshold defaults to 0.01, what the original was called with (0 means Otsu, as in the original). engine "fast" is Settings' Method "ais_auto.m (fast)": the same answer, sooner.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`trace_click`](#trace_click) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `click` | array of number | yes |  | [x, y]. |
| `click2` | array of number or null | no |  | [x, y]. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `engine` | string | no | one of `fast` |  |
| `processed` | string | yes |  | The traced image's sha. |
| `raw` | string or null | no |  | The raw image's sha, for a TIFF pair. |
| `settings` | object | no |  | The method's settings; missing ones are the original's. |
| `threshold` | number | no | 0 to 1 | Default 0.01; 0 is Otsu. |
| `z_method` | string | no |  | On a Z-stack: how its 3D length is measured. |

**Reply 200**: ais_auto.m's answer: ok, pixels, measures, shape, notes, and z on a Z-stack.

An empty object.

### GET /api/ais/trash

The Batches screen's trash

What deleting a batch or folder, or resetting a batch, took away in the last 30 days, newest first: {entries: [{id, kind (batch | folder | reset), name, deleted_at, deleted_by, deleted_by_name, expires_at, can_restore, counts}], days}.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The trash only holds what the Batches screen deleted, which agents cannot do. |
| Errors | 401, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `days` | integer | yes |  | How long an entry is kept. |
| `entries` | array of object | yes |  | Newest first. |
| `entries[].batch_id` | integer | no |  | A batch or reset. |
| `entries[].batches` | integer | no |  | A folder: the batches it held. |
| `entries[].can_restore` | boolean | yes |  | Whether you may put it back. |
| `entries[].deleted_at` | string | yes |  |  |
| `entries[].deleted_by` | integer or null | yes |  |  |
| `entries[].deleted_by_name` | string | yes |  |  |
| `entries[].expires_at` | string | yes |  |  |
| `entries[].folders` | integer | no |  | A folder: the folders it held. |
| `entries[].id` | integer | yes |  |  |
| `entries[].images` | integer | no |  | A batch. |
| `entries[].kind` | string | yes | one of `batch`, `folder`, `reset` |  |
| `entries[].measurements` | integer | no |  | A batch or reset: the recorded lines. |
| `entries[].name` | string | yes |  |  |
| `entries[].results` | integer | no |  | A batch or reset: the AIS. |
| `entries[].scope` | string | no | one of `all`, `auto` | A reset. |

### POST /api/ais/trash/{trash_id}/purge

Delete from the trash for good

The entry gone for good (admins).

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | None, HTTP only: Deleting for good is kept out of agents' reach on purpose. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `trash_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/ais/trash/{trash_id}/restore

Restore from the trash

Put a deleted batch (with its AIS and lines), folder or reset back. A batch: whoever deleted it or an admin; a folder or reset: admins.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The trash only holds what the Batches screen deleted, which agents cannot do. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `trash_id` | path | integer | yes | at least 1 |  |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | no |  | A batch or reset. |
| `batches` | integer | no |  | A folder: the batches it held. |
| `deleted_at` | string | yes |  |  |
| `deleted_by` | integer or null | yes |  |  |
| `expires_at` | string | yes |  |  |
| `folders` | integer | no |  | A folder: the folders it held. |
| `id` | integer | yes |  |  |
| `images` | integer | no |  | A batch. |
| `kind` | string | yes | one of `batch`, `folder`, `reset` |  |
| `measurements` | integer | no |  | A batch or reset: the recorded lines. |
| `name` | string | yes |  |  |
| `results` | integer | no |  | A batch or reset: the AIS. |
| `scope` | string | no | one of `all`, `auto` | A reset. |

## About

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/about/report`](#get-apiaboutreport) | The ais_auto.m report, as Markdown | browser session or API key, anyone signed in |

### GET /api/about/report

The ais_auto.m report, as Markdown

docs/ais_auto_report.md as {"markdown": ...}, for the About screen. Read on every call so an edited report shows without a restart.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The About screen's copy of a document in the repository; nothing to act on. |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `markdown` | string | yes |  | docs/ais_auto_report.md as it is on disk. |

## Schemas

The shapes the routes above refer to by name.

### AISResult

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `accepted_at` | string (date-time) | yes |  |  |
| `arc_um` | number or null | yes |  |  |
| `area_blob_um2` | number or null | no |  | Missing on AIS accepted before area was measured. |
| `area_width_um2` | number or null | no |  |  |
| `auto_max_branchiness` | number | no |  |  |
| `auto_max_soma_gap` | number | no |  |  |
| `auto_method` | string | no |  |  |
| `auto_min_brightness` | number | no |  |  |
| `auto_min_contrast` | number | no |  |  |
| `auto_min_length` | number | no |  |  |
| `auto_min_length_shown` | number | no |  |  |
| `auto_min_score` | number | no |  |  |
| `auto_min_width` | number | no |  |  |
| `auto_review` | string | no |  |  |
| `auto_start` | string | no |  |  |
| `batch_id` | integer | yes |  |  |
| `batch_name` | string | yes |  |  |
| `brightness` | number or null | no |  |  |
| `cell` | string | yes |  |  |
| `click2_x` | number or null | yes |  |  |
| `click2_y` | number or null | yes |  |  |
| `click_x` | number or null | yes |  |  |
| `click_y` | number or null | yes |  |  |
| `client_id` | string | no |  | The browser's own id for it, when it sent one. |
| `created_by` | integer | yes |  | Who accepted it. |
| `edited_at` | string (date-time) | no |  |  |
| `edited_by` | integer | no |  |  |
| `end_um` | number or null | yes |  |  |
| `f` | number or null | yes |  |  |
| `file` | string | yes |  |  |
| `id` | integer | yes |  |  |
| `image` | string | yes |  | The image's key in its batch. |
| `kernel` | number or null | yes |  |  |
| `length_3d_um` | number | no |  |  |
| `length_str` | string | yes |  |  |
| `length_um` | number or null | yes |  |  |
| `length_xy_um` | number | no |  |  |
| `max_passes` | number or null | yes |  |  |
| `max_path` | number or null | yes |  |  |
| `max_um` | number or null | yes |  |  |
| `mid_um` | number or null | yes |  |  |
| `min_pixels` | number or null | yes |  |  |
| `n` | integer | yes |  | Its number on the image, 1..k. |
| `notes` | string | yes |  |  |
| `origin` | string | yes |  | auto for one auto mode found, empty for a click. |
| `pixconv` | number or null | yes |  |  |
| `pixels` | array of array of integer | yes |  | The trace, as [x, y] pairs. |
| `profile_points` | number or null | yes |  |  |
| `rev` | integer | no |  | Bumped by each change; missing until the first. |
| `sha` | string | yes |  |  |
| `sigma` | number or null | yes |  |  |
| `smooth` | string | yes |  |  |
| `soma_ais_x` | number or null | no |  |  |
| `soma_ais_y` | number or null | no |  |  |
| `soma_at` | string (date-time) or null | no |  |  |
| `soma_by` | integer or null | no |  |  |
| `soma_dz_um` | number | no |  |  |
| `soma_px` | number or null | no |  |  |
| `soma_um` | number or null | no |  | Distance from its start to the soma (the Measure tool); null when cleared. |
| `soma_x` | number or null | no |  |  |
| `soma_xy_um` | number | no |  |  |
| `soma_y` | number or null | no |  |  |
| `source` | string | yes |  |  |
| `spline_p` | number or null | yes |  |  |
| `start_um` | number or null | yes |  |  |
| `strel` | number or null | yes |  |  |
| `threshold` | number or null | yes |  |  |
| `threshold_initial` | number or null | yes |  |  |
| `volume_tube_um3` | number | no |  |  |
| `volume_voxel_um3` | number | no |  |  |
| `width_um` | number or null | no |  |  |
| `window_um` | number or null | yes |  |  |
| `z_ais_end` | number | no |  | Ends from the slices: the AIS end found on the 3D route, a profile point. |
| `z_ais_start` | number | no |  | Ends from the slices: the AIS start found on the 3D route, a profile point. |
| `z_clipped` | number | no |  | 0 or 1. |
| `z_confidence` | number | no |  |  |
| `z_end` | number | no |  |  |
| `z_method` | string | no |  |  |
| `z_path` | array of any | no |  | The z of each pixel (a number), null outside the AIS. Z-stacks only. |
| `z_span_um` | number | no |  |  |
| `z_start` | number | no |  |  |
| `z_step_um` | number | no |  |  |

### APIKey

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `created_by` | integer | no |  | The admin who made this key for its owner. Absent if the owner made it. |
| `created_by_name` | string | no |  |  |
| `display_name` | string | no |  | The key's owner. On the admin list only. |
| `expired` | boolean | yes |  |  |
| `expires_at` | string (date-time) | no |  |  |
| `id` | string | yes |  |  |
| `last_used_at` | string (date-time) | no |  |  |
| `live` | boolean | yes |  |  |
| `name` | string | yes |  |  |
| `purpose` | string | no |  | What the key is for, when it is a special one: matlab_helper for a MATLAB helper's key. |
| `revoked` | boolean | yes |  |  |
| `revoked_at` | string (date-time) | no |  |  |
| `role` | string | yes | one of `admin`, `user` |  |
| `user_id` | integer | yes |  |  |

### AutoRun

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes |  |  |
| `choices` | object | yes |  |  |
| `choices.engine` | string or null | yes |  | fast, or null for the original port. |
| `choices.general` | object | yes |  | Settings' general fields, as GET /api/ais/auto/defaults lists them. |
| `choices.settings` | object | yes |  | The method's settings. |
| `choices.threshold` | number | yes |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `current` | string or null | yes |  | The image it is on. |
| `done` | integer | yes |  | Images worked through. |
| `errors` | array of object | yes |  |  |
| `errors[].error` | string | yes |  |  |
| `errors[].image` | string or null | yes |  | The image's key; null when the run failed between images. |
| `finished_at` | string (date-time) or null | yes |  |  |
| `found` | integer | yes |  | AIS that passed the filters. |
| `hidden` | integer | yes |  | AIS the filters left out. |
| `id` | string | yes |  |  |
| `images` | array of string | yes |  | The image keys it works through, in order. |
| `mark_done` | boolean | yes |  |  |
| `marked_done` | integer | yes |  |  |
| `saved` | integer | yes |  | AIS saved to the batch. |
| `skip_done` | boolean | yes |  |  |
| `started_at` | string (date-time) or null | yes |  |  |
| `state` | string | yes | one of `queued`, `running`, `finished`, `stopped`, `failed` |  |
| `total` | integer | yes |  | Images it will work through. |
| `user_id` | integer | yes |  | Who started it. |

### Error

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `error` | string | yes |  |  |
| `request_id` | string | no |  | On a 5xx: the reference that finds this failure in the log. |

### IPNames

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `names` | array of object | yes |  |  |
| `names[].created_at` | string (date-time) | yes |  |  |
| `names[].name` | string | yes |  |  |
| `names[].target` | string | yes |  |  |

### InviteLink

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_by` | integer | yes |  |  |
| `created_by_name` | string | no |  |  |
| `expires_at` | string (date-time) | yes |  |  |
| `id` | string | yes |  |  |
| `label` | string | yes |  |  |
| `live` | boolean | yes |  |  |
| `max_uses` | integer | yes |  |  |
| `remaining` | integer | yes |  |  |
| `revoked` | boolean | yes |  |  |
| `used` | integer | yes |  |  |

### Job

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `interrupted` | boolean | yes |  |  |
| `interval_seconds` | integer | yes |  |  |
| `last_error` | string | no |  |  |
| `last_finished` | string (date-time) | no |  |  |
| `last_note` | string | no |  |  |
| `last_ok` | boolean or null | no |  |  |
| `last_started` | string (date-time) | no |  |  |
| `name` | string | yes |  |  |
| `next_due` | string (date-time) | yes |  |  |
| `running` | boolean | yes |  |  |
| `runs` | integer | yes |  |  |

### Joined

One of these:

1. An object:

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

2. An object:

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `challenge` | string | yes |  |  |
| `two_factor` | boolean | yes |  |  |

### LogDay

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `date` | string | yes |  |  |
| `entries` | array of object | yes |  |  |
| `next` | integer or null | yes |  |  |

### LogDays

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `days` | array of object | yes |  |  |
| `dropped` | integer | yes |  |  |
| `settings` | object | yes |  |  |
| `total_bytes` | integer | yes |  |  |

### LoginLink

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `last_used_at` | string (date-time) or null | yes |  |  |
| `max_uses` | integer | yes |  | Sign-ins it allows. 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |
| `uses` | integer | yes |  | Sign-ins so far. |

### Maintenance

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `error` | string | yes |  |  |
| `maintenance` | string | yes | one of `read_only`, `full` |  |

### Me

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `account_role` | string | yes |  |  |
| `announcement` | string | yes |  | server.announcement. Empty when there is none. |
| `api_key_id` | string | no |  | API keys only. |
| `api_key_name` | string | no |  | API keys only. |
| `api_keys_enabled` | boolean | yes |  |  |
| `auth` | string | yes |  |  |
| `authenticated` | boolean | yes |  |  |
| `csrf_token` | string | no |  | Browser sessions only. |
| `description` | string | yes |  | app.description. Empty when there is none. |
| `display_name` | string | yes |  |  |
| `has_password` | boolean | yes |  |  |
| `has_pin` | boolean | yes |  |  |
| `id` | integer | yes |  |  |
| `invite_links_enabled` | boolean | yes |  | Whether invite links are on. |
| `is_owner` | boolean | yes |  |  |
| `login_link` | [`LoginLink`](#loginlink) or null | yes |  | Your own live login link, or null. |
| `logs_enabled` | boolean | yes |  |  |
| `logs_ui_clicks` | boolean | yes |  |  |
| `maintenance` | string | yes | one of `none`, `read_only`, `full` |  |
| `matlab_path` | string | no |  | Where MATLAB is on your computer, for your replay zips. Browser sessions only. |
| `mcp_enabled` | boolean | yes |  | server.mcp: whether POST /mcp answers. |
| `mcp_url` | string | yes |  | Where to read the MCP reference: config/mcp.json in app.repo, or /api/mcp.json when there is no repo. Only with server.mcp on. |
| `openapi_url` | string | yes |  | Where to read this API's reference: config/openapi.json in app.repo, or /api/openapi.json when there is no repo. |
| `password_blocked` | boolean | yes |  |  |
| `passwords_enabled` | boolean | yes |  |  |
| `repo` | string | yes |  | app.repo without a trailing / or .git: where the source lives. Empty when it is not set. |
| `role` | string | yes |  | The effective role: never higher than an API key's own. |
| `shortcuts` | map of array of string | yes |  | The keyboard shortcuts you rebound: each action's keys. An action left out keeps its default. |
| `show_about` | boolean | yes |  | app.show_about: whether the menu has About. |
| `theme_id` | string | yes |  | The theme you use. Empty: the first. |
| `themes` | array of [`Theme`](#theme) or null | yes |  | Your themes (see the Theme schema): your own list, else the app's defaults, else null for the built-in ones. |
| `themes_custom` | boolean | yes |  | Whether you have your own list rather than following the defaults. |
| `two_factor` | boolean | yes |  |  |
| `two_factor_enabled` | boolean | yes |  |  |
| `username` | string | yes |  |  |
| `version` | string | yes |  | The running build. dev when none was stamped. |

### Measurement

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `a_x` | number | yes |  |  |
| `a_y` | number | yes |  |  |
| `b_x` | number | yes |  |  |
| `b_y` | number | yes |  |  |
| `batch_id` | integer | yes |  |  |
| `batch_name` | string | yes |  |  |
| `client_id` | string | no |  |  |
| `created_at` | string (date-time) | yes |  |  |
| `created_by` | integer | yes |  |  |
| `edited_at` | string (date-time) | no |  |  |
| `edited_by` | integer | no |  |  |
| `id` | integer | yes |  |  |
| `image` | string | yes |  |  |
| `label` | string | yes |  |  |
| `length_px` | number | yes |  |  |
| `length_um` | number | yes |  |  |
| `n` | integer | yes |  | Its number on the image, 1..k. |
| `pixconv` | number | yes |  |  |
| `rev` | integer | no |  |  |
| `type` | string | no |  | One of the team's measurement types, or empty. |

### Member

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `id` | integer | yes |  |  |

### NewAPIKey

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `created_by` | integer | no |  | The admin who made this key for its owner. Absent if the owner made it. |
| `created_by_name` | string | no |  |  |
| `credential` | string | yes |  | Shown in this response only, and never recoverable. |
| `display_name` | string | no |  | The key's owner. On the admin list only. |
| `expired` | boolean | yes |  |  |
| `expires_at` | string (date-time) | no |  |  |
| `id` | string | yes |  |  |
| `last_used_at` | string (date-time) | no |  |  |
| `live` | boolean | yes |  |  |
| `name` | string | yes |  |  |
| `purpose` | string | no |  | What the key is for, when it is a special one: matlab_helper for a MATLAB helper's key. |
| `revoked` | boolean | yes |  |  |
| `revoked_at` | string (date-time) | no |  |  |
| `role` | string | yes | one of `admin`, `user` |  |
| `user_id` | integer | yes |  |  |

### PruneResult

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `bytes_after` | integer | yes |  |  |
| `bytes_before` | integer | yes |  |  |
| `compressed` | integer | yes |  |  |
| `deleted` | integer | yes |  |  |

### Revoked

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `api_keys` | integer | yes |  |  |
| `login_links` | integer | yes |  |  |
| `passwords` | integer | yes |  |  |
| `sessions` | integer | yes |  |  |

### Session

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `current` | boolean | yes |  |  |
| `expires_at` | string (date-time) | yes |  |  |
| `id` | string | yes |  |  |
| `ip` | string | no |  |  |
| `ip_name` | string | no |  | What the owner calls this address on the Logs screen. The owner's own list only. |
| `label` | string | no |  | The name you gave this device. |
| `last_seen_at` | string (date-time) | no |  |  |
| `user_agent` | string | no |  |  |

### SettingsResult

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `applied` | array of string or null | yes |  |  |
| `changes` | array of object or null | yes |  |  |
| `restart` | array of string or null | yes |  |  |
| `scripts` | array of string or null | yes |  |  |
| `unchanged` | array of string or null | yes |  |  |
| `version` | string | yes |  |  |

### SettingsSnapshot

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `error` | object or null | yes |  |  |
| `error.at` | string (date-time) | yes |  |  |
| `error.message` | string | yes |  |  |
| `error.origin` | string | yes |  |  |
| `file` | string | yes |  |  |
| `in_container` | boolean | yes |  |  |
| `secret_file` | string | yes |  |  |
| `sections` | array of object | yes |  |  |
| `sections[].help` | string | yes |  |  |
| `sections[].keys` | array of object | yes |  |  |
| `sections[].keys[].apply` | string | yes |  |  |
| `sections[].keys[].default` | any | yes |  |  |
| `sections[].keys[].file_only` | boolean | yes |  | A path: change it in config.yaml, never here. |
| `sections[].keys[].help` | string | yes |  |  |
| `sections[].keys[].in_file` | boolean | yes |  |  |
| `sections[].keys[].key` | string | yes |  |  |
| `sections[].keys[].locked` | boolean | yes |  |  |
| `sections[].keys[].name` | string | yes |  |  |
| `sections[].keys[].pending_restart` | boolean | yes |  |  |
| `sections[].keys[].running` | any | yes |  |  |
| `sections[].keys[].type` | string | yes |  |  |
| `sections[].keys[].value` | any | yes |  |  |
| `sections[].name` | string | yes |  |  |
| `stale` | boolean | yes |  |  |
| `version` | string | yes |  | Send it back when saving: a changed file is refused with a 409. |
| `writable` | boolean | yes |  |  |

### SignIn

One of these:

1. An object:

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

2. An object:

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `challenge` | string | yes |  |  |
| `two_factor` | boolean | yes |  |  |

### Theme

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `accent` | string | yes |  | The main color: what you can press. |
| `background` | string | no |  | The page. Left out: the mode's own. |
| `button` | object or null | no |  | How the theme's buttons look. A choice left out is the default (rounded, normal, raised, normal). |
| `button.case` | string | no | one of `normal`, `upper` |  |
| `button.depth` | string | no | one of `flat`, `raised`, `glossy` |  |
| `button.shape` | string | no | one of `square`, `soft`, `rounded`, `pill` |  |
| `button.weight` | string | no | one of `normal`, `medium`, `bold` |  |
| `dark` | object or null | no |  | A light theme's colors for dark mode, kept while it is light. Switching the theme to dark swaps them in. A light theme's light (or a dark theme's dark) is dropped. |
| `dark.accent` | string | yes |  | The main color: what you can press. |
| `dark.background` | string | no |  | The page. Left out: the mode's own. |
| `dark.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `dark.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `dark.surface` | string | no |  | Cards. Left out: the mode's own. |
| `id` | string | yes |  | Lower-case letters, digits, - and _, up to 32. |
| `light` | object or null | no |  | A dark theme's colors for light mode, kept while it is dark. Switching the theme to light swaps them in. |
| `light.accent` | string | yes |  | The main color: what you can press. |
| `light.background` | string | no |  | The page. Left out: the mode's own. |
| `light.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `light.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `light.surface` | string | no |  | Cards. Left out: the mode's own. |
| `mode` | string | yes | one of `light`, `dark` |  |
| `name` | string | yes |  | 1 to 60 characters. |
| `overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `surface` | string | no |  | Cards. Left out: the mode's own. |

### User

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `disabled` | boolean | yes |  |  |
| `display_name` | string | yes |  |  |
| `has_password` | boolean | yes |  |  |
| `id` | integer | yes |  |  |
| `login_link` | [`LoginLink`](#loginlink) or null | yes |  | The account's live login link, or null. |
| `owner` | boolean | yes |  |  |
| `password_blocked` | boolean | yes |  |  |
| `role` | string | yes | one of `admin`, `user` |  |
| `two_factor` | boolean | yes |  |  |
| `username` | string | yes |  | Empty until a password is set. |

## MCP tools

Every tool POST /mcp offers. Written by scripts/api_docs.sh from the registered tools; do not edit by hand. A key sees the tools its role allows (adminOnly ones need an admin key), and a tool whose feature is switched off answers like one that does not exist. route is the HTTP route the tool stands for, with the same rules; http_only are the routes a key may call that have no tool, and why.

|  |  |
|---|---|
| Endpoint | `POST /mcp` |
| Transport | Streamable HTTP, stateless: one JSON-RPC message per POST, a JSON reply |
| Auth | Authorization: Bearer <API key> |

| Tool | Route | Who | What |
|---|---|---|---|
| [`admin_cancel_login_link`](#admin_cancel_login_link) | `POST /api/admin/users/{user_id}/cancel-login-link` | admin keys | Stop an account's login link working (admin) |
| [`admin_create_invite_link`](#admin_create_invite_link) | `POST /api/admin/invite-links` | admin keys | Create an invite link (admin) |
| [`admin_create_user`](#admin_create_user) | `POST /api/admin/users` | admin keys | Create an account (admin) |
| [`admin_delete_invite_link`](#admin_delete_invite_link) | `POST /api/admin/invite-links/{link_id}/delete` | admin keys | Delete an invite link (admin) |
| [`admin_delete_user`](#admin_delete_user) | `POST /api/admin/users/{user_id}/delete` | admin keys | Delete an account (admin) |
| [`admin_get_theme_defaults`](#admin_get_theme_defaults) | `GET /api/admin/theme-defaults` | admin keys | Default themes (admin) |
| [`admin_list_invite_links`](#admin_list_invite_links) | `GET /api/admin/invite-links` | admin keys | List invite links (admin) |
| [`admin_list_user_sessions`](#admin_list_user_sessions) | `GET /api/admin/users/{user_id}/sessions` | admin keys | An account's signed-in devices (admin) |
| [`admin_list_users`](#admin_list_users) | `GET /api/admin/users` | admin keys | List users (admin) |
| [`admin_reissue_login`](#admin_reissue_login) | `POST /api/admin/users/{user_id}/reissue-login` | admin keys | A new login link for an account (admin) |
| [`admin_rename_invite_link`](#admin_rename_invite_link) | `POST /api/admin/invite-links/{link_id}/rename` | admin keys | Rename an invite link (admin) |
| [`admin_rename_user`](#admin_rename_user) | `POST /api/admin/users/{user_id}/rename` | admin keys | Rename someone (admin) |
| [`admin_reset_two_factor`](#admin_reset_two_factor) | `POST /api/admin/users/{user_id}/reset-two-factor` | admin keys | Turn off an account's two-factor (admin) |
| [`admin_restore_invite_link`](#admin_restore_invite_link) | `POST /api/admin/invite-links/{link_id}/restore` | admin keys | Undo deleting an invite link (admin) |
| [`admin_revoke_access`](#admin_revoke_access) | `POST /api/admin/users/{user_id}/revoke-access` | admin keys | Revoke a user's access (admin) |
| [`admin_revoke_invite_link`](#admin_revoke_invite_link) | `POST /api/admin/invite-links/{link_id}/revoke` | admin keys | Switch off an invite link (admin) |
| [`admin_revoke_user_session`](#admin_revoke_user_session) | `POST /api/admin/users/{user_id}/sessions/{session_id}/revoke` | admin keys | Sign out one of an account's devices (admin) |
| [`admin_set_invite_link_limits`](#admin_set_invite_link_limits) | `POST /api/admin/invite-links/{link_id}/limits` | admin keys | Change an invite link's places and expiry (admin) |
| [`admin_set_theme_defaults`](#admin_set_theme_defaults) | `POST /api/admin/theme-defaults` | admin keys | Replace the default themes (admin) |
| [`admin_set_user_disabled`](#admin_set_user_disabled) | `POST /api/admin/users/{user_id}/disabled` | admin keys | Disable or enable a user (admin) |
| [`admin_set_user_role`](#admin_set_user_role) | `POST /api/admin/users/{user_id}/role` | admin keys | Change an account's role (admin) |
| [`admin_switch_on_invite_link`](#admin_switch_on_invite_link) | `POST /api/admin/invite-links/{link_id}/switch-on` | admin keys | Switch an invite link back on (admin) |
| [`cancel_my_login_link`](#cancel_my_login_link) | `POST /api/account/login-link/cancel` | any key | Stop your own login link working |
| [`create_my_login_link`](#create_my_login_link) | `POST /api/account/login-link` | any key | A login link for yourself |
| [`label_my_session`](#label_my_session) | `POST /api/account/sessions/{session_id}/label` | any key | Name one of your devices |
| [`list_my_sessions`](#list_my_sessions) | `GET /api/account/sessions` | any key | Your signed-in devices |
| [`list_team`](#list_team) | `GET /api/team` | any key | List team |
| [`rename_account`](#rename_account) | `POST /api/account/rename` | any key | Rename your account |
| [`revoke_my_other_sessions`](#revoke_my_other_sessions) | `POST /api/account/sessions/revoke-others` | any key | Sign out all your devices |
| [`revoke_my_session`](#revoke_my_session) | `POST /api/account/sessions/{session_id}/revoke` | any key | Sign out one of your devices |
| [`set_shortcuts`](#set_shortcuts) | `POST /api/account/shortcuts` | any key | Set your keyboard shortcuts |
| [`set_theme`](#set_theme) | `POST /api/account/theme` | any key | Pick your theme |
| [`set_themes`](#set_themes) | `POST /api/account/themes` | any key | Replace your own themes |
| [`whoami`](#whoami) | `GET /api/me` | any key | Who am I |
| [`list_batches`](#list_batches) | `GET /api/ais/batches` | any key | List batches |
| [`list_folders`](#list_folders) | `GET /api/ais/folders` | any key | List folders |
| [`get_batch`](#get_batch) | `GET /api/ais/batches/{batch_id}` | any key | Get a batch |
| [`batch_status`](#batch_status) | `GET /api/ais/batches/{batch_id}/status` | any key | Batch image status |
| [`batch_channels`](#batch_channels) | `GET /api/ais/batches/{batch_id}/channels` | any key | Batch .czi channels |
| [`list_results`](#list_results) | `GET /api/ais/results` | any key | List results |
| [`list_measurements`](#list_measurements) | `GET /api/ais/measurements` | any key | List recorded lines |
| [`list_measure_types`](#list_measure_types) | `GET /api/ais/measure-types` | any key | List measurement types |
| [`create_batch`](#create_batch) | `POST /api/ais/batches` | any key | Create an empty batch |
| [`create_batch_from_files`](#create_batch_from_files) | `POST /api/ais/batches/upload` | any key | Create a batch from files |
| [`add_files_to_batch`](#add_files_to_batch) | `POST /api/ais/batches/{batch_id}/upload` | any key | Add files to a batch |
| [`get_channel_layouts`](#get_channel_layouts) | `GET /api/ais/batches/{batch_id}/layouts` | any key | List a batch's channel layouts |
| [`set_channel_roles`](#set_channel_roles) | `POST /api/ais/batches/{batch_id}/layouts` | any key | Set channel roles |
| [`fill_missing_areas`](#fill_missing_areas) | `POST /api/ais/batches/{batch_id}/fill-areas` | any key | Fill in missing AIS areas |
| [`rename_batch`](#rename_batch) | `POST /api/ais/batches/{batch_id}/rename` | any key | Rename a batch |
| [`archive_batch`](#archive_batch) | `POST /api/ais/batches/{batch_id}/archive` | any key | Archive or bring back a batch |
| [`set_images_included`](#set_images_included) | `POST /api/ais/batches/{batch_id}/include` | any key | Include or leave out images |
| [`set_image_done`](#set_image_done) | `POST /api/ais/batches/{batch_id}/done` | any key | Mark an image done |
| [`assign_batch`](#assign_batch) | `POST /api/ais/batches/{batch_id}/assign` | admin keys | Assign a batch (admin) |
| [`order_batches`](#order_batches) | `POST /api/ais/batches/order` | admin keys | Order batches (admin) |
| [`move_batches`](#move_batches) | `POST /api/ais/batches/move` | admin keys | Move batches into a folder (admin) |
| [`create_folder`](#create_folder) | `POST /api/ais/folders` | admin keys | Create a folder (admin) |
| [`rename_folder`](#rename_folder) | `POST /api/ais/folders/{folder_id}/rename` | admin keys | Rename a folder (admin) |
| [`move_folder`](#move_folder) | `POST /api/ais/folders/{folder_id}/move` | admin keys | Move a folder (admin) |
| [`order_folders`](#order_folders) | `POST /api/ais/folders/order` | admin keys | Order folders (admin) |
| [`get_treatments`](#get_treatments) | `GET /api/ais/batches/{batch_id}/treatments` | admin keys | Get treatments (admin) |
| [`set_treatments`](#set_treatments) | `POST /api/ais/batches/{batch_id}/treatments` | admin keys | Set treatments (admin) |
| [`get_translation`](#get_translation) | `GET /api/ais/batches/{batch_id}/translation.txt` | admin keys | Get __Translation.txt (admin) |
| [`load_translation`](#load_translation) | `POST /api/ais/batches/{batch_id}/translation` | admin keys | Load a __Translation.txt (admin) |
| [`rerandomize_add`](#rerandomize_add) | `POST /api/ais/batches/{batch_id}/adds/{add_id}/randomize` | admin keys | New random names for a folder (admin) |
| [`get_backup`](#get_backup) | `GET /api/ais/batches/{batch_id}/backup` | admin keys | Back up a batch (admin) |
| [`save_result`](#save_result) | `POST /api/ais/results` | any key | Save an AIS |
| [`update_result`](#update_result) | `POST /api/ais/results/{result_id}/update` | any key | Change an AIS |
| [`set_result_soma`](#set_result_soma) | `POST /api/ais/results/{result_id}/soma` | any key | Set an AIS's soma distance |
| [`delete_result`](#delete_result) | `POST /api/ais/results/{result_id}/delete` | any key | Delete an AIS |
| [`add_measurement`](#add_measurement) | `POST /api/ais/measurements` | any key | Record a line |
| [`update_measurement`](#update_measurement) | `POST /api/ais/measurements/{measurement_id}/update` | any key | Change a recorded line |
| [`delete_measurement`](#delete_measurement) | `POST /api/ais/measurements/{measurement_id}/delete` | any key | Delete a recorded line |
| [`set_measure_types`](#set_measure_types) | `POST /api/ais/measure-types` | admin keys | Set measurement types (admin) |
| [`reset_batch_auto`](#reset_batch_auto) | `POST /api/ais/batches/{batch_id}/reset` | admin keys | Delete a batch's auto AIS (admin) |
| [`auto_defaults`](#auto_defaults) | `GET /api/ais/auto/defaults` | any key | Auto mode defaults |
| [`start_auto_run`](#start_auto_run) | `POST /api/ais/batches/{batch_id}/auto` | any key | Start an auto run |
| [`get_auto_run`](#get_auto_run) | `GET /api/ais/auto/{run_id}` | any key | Auto run status |
| [`list_auto_runs`](#list_auto_runs) | `GET /api/ais/auto` | any key | List auto runs |
| [`cancel_auto_run`](#cancel_auto_run) | `POST /api/ais/auto/{run_id}/cancel` | any key | Stop an auto run |
| [`export_report`](#export_report) | `GET /api/ais/report` | any key | Export a report as JSON |
| [`compare_batches`](#compare_batches) | `POST /api/ais/compare` | admin keys | Compare batches by treatment (admin) |
| [`upload_instructions`](#upload_instructions) | `POST /api/ais/files` | any key | How to upload files |
| [`files_stored`](#files_stored) | `POST /api/ais/files` | any key | Which files the server has |
| [`get_image`](#get_image) | `GET /api/ais/files/{sha}/view.png` | any key | Look at an image |
| [`trace_click`](#trace_click) | `POST /api/ais/trace` | any key | Trace an AIS from a click |
| [`detect_image`](#detect_image) | `POST /api/ais/detect` | any key | Find AIS on one image |

### admin_cancel_login_link

Void an account's live login link without making a new one: a link that went somewhere it should not have. Devices it already signed in stay signed in; admin_revoke_access ends those too. Answers with removed: 0 or 1.

|  |  |
|---|---|
| Route | `POST /api/admin/users/{user_id}/cancel-login-link` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

### admin_create_invite_link

One link for a group: each person who opens it joins as a new user, up to max_uses people, for days days. Answers with join_url (shown only now) and the link's details. Revoking or deleting this API key switches the link off.

|  |  |
|---|---|
| Route | `POST /api/admin/invite-links` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `days` | integer | yes | 1 to 365 |  |
| `label` | string | yes | 1 to 80 characters |  |
| `max_uses` | integer | yes | 1 to 1000 |  |

### admin_create_user

Make a new account and its first login link, to hand to the person. role is admin or user. Answers with user_id and the link. Answers with login_url (open it to sign in), expires_at and max_uses. The link works once and expires within a day (links made with an API key are held to that; a browser can make longer or reusable ones). Any older link the account could still use stops working; its signed-in devices stay signed in. Revoking or deleting this API key voids the link while it is unused, and signs out every device it signed in.

|  |  |
|---|---|
| Route | `POST /api/admin/users` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes | 1 to 80 characters |  |
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |
| `role` | string | yes | one of `admin`, `user` |  |

### admin_delete_invite_link

Take an invite link off the list and stop it working. The accounts it made stay. admin_restore_invite_link undoes it for a few minutes.

|  |  |
|---|---|
| Route | `POST /api/admin/invite-links/{link_id}/delete` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

### admin_delete_user

Remove an account for good, with its sessions, login link and API keys. Cannot be undone: admin_set_user_disabled is the reversible version. Only the owner deletes an admin; nobody deletes the owner or themselves.

|  |  |
|---|---|
| Route | `POST /api/admin/users/{user_id}/delete` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

### admin_get_theme_defaults

The theme list everyone without their own list sees. themes is null while the built-in ones apply.

|  |  |
|---|---|
| Route | `GET /api/admin/theme-defaults` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

### admin_list_invite_links

Group invite links, a page at a time: label, places used and left, expiry, and whether each still works. The links themselves are never shown again after creation. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Route | `GET /api/admin/invite-links` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `dir` | string | no | one of `asc`, `desc` | Default asc. |
| `limit` | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | string | no |  | Keep links whose label or maker contains this, in any case. |
| `sort` | string | no | one of `label`, `used`, `expires_at` | Field to sort the whole list by. Rows without it go last. |

### admin_list_user_sessions

Where an account is signed in: every session, with when it started and was last seen. Addresses are shown to the owner only, and only the owner sees the owner's.

|  |  |
|---|---|
| Route | `GET /api/admin/users/{user_id}/sessions` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `limit` | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

### admin_list_users

Accounts, a page at a time, including disabled ones, with each one's role and which is the owner. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Route | `GET /api/admin/users` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `dir` | string | no | one of `asc`, `desc` | Default asc. |
| `limit` | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | string | no |  | Keep accounts whose name or username contains this, in any case. |
| `sort` | string | no | one of `display_name`, `role`, `disabled`, `created_at` | Field to sort the whole list by. Rows without it go last. |

### admin_reissue_login

For someone who lost their device or their link: a fresh login link for their account. Answers with login_url (open it to sign in), expires_at and max_uses. The link works once and expires within a day (links made with an API key are held to that; a browser can make longer or reusable ones). Any older link the account could still use stops working; its signed-in devices stay signed in. Revoking or deleting this API key voids the link while it is unused, and signs out every device it signed in.

|  |  |
|---|---|
| Route | `POST /api/admin/users/{user_id}/reissue-login` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

### admin_rename_invite_link

Change the label people see on an invite link's join page (1-80 characters). expect, when given, is the label you think it has now.

|  |  |
|---|---|
| Route | `POST /api/admin/invite-links/{link_id}/rename` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | string or null | no |  | The label you think it has. Answers 409 if it has another. |
| `label` | string | yes | 1 to 80 characters | 1-80 characters. |
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

### admin_rename_user

Change another account's display name (1-80 characters). Only the owner renames an admin. expect, when given, is the name you think it has now; if it changed meanwhile the rename is refused with the current name.

|  |  |
|---|---|
| Route | `POST /api/admin/users/{user_id}/rename` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes | 1 to 80 characters | 1-80 characters. |
| `expect` | string or null | no |  | The name you think they have. Answers 409 if it is another. |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

### admin_reset_two_factor

For someone who lost both their phone and their recovery codes: switches their two-factor sign-in off so a login link lets them in again. Only the owner resets an admin's; the owner's is reset from a shell.

|  |  |
|---|---|
| Route | `POST /api/admin/users/{user_id}/reset-two-factor` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

### admin_restore_invite_link

Bring back an invite link deleted in the last few minutes, working as before. The link then counts as this key's: revoking the key switches it off.

|  |  |
|---|---|
| Route | `POST /api/admin/invite-links/{link_id}/restore` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

### admin_revoke_access

For an account that may be compromised: ends every session and voids its live login link and every API key it holds, at once. The account stays enabled; admin_reissue_login lets its owner back in. The owner and your own account cannot be revoked.

|  |  |
|---|---|
| Route | `POST /api/admin/users/{user_id}/revoke-access` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

### admin_revoke_invite_link

Stop an invite link from letting anyone else join or sign in through it. Accounts it already made keep working. Cannot be switched back on.

|  |  |
|---|---|
| Route | `POST /api/admin/invite-links/{link_id}/revoke` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

### admin_revoke_user_session

End one of an account's sessions, rather than all of them with admin_revoke_access.

|  |  |
|---|---|
| Route | `POST /api/admin/users/{user_id}/sessions/{session_id}/revoke` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

### admin_set_invite_link_limits

Set how many people the link may take in (never fewer than have joined) and, when days is given, a new expiry counted from now. The link then counts as this key's: revoking the key switches it off.

|  |  |
|---|---|
| Route | `POST /api/admin/invite-links/{link_id}/limits` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `days` | integer or null | no | 1 to 365 | Counted from now. Leave out to keep the expiry. |
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |
| `max_uses` | integer | yes | 1 to 1000 | Not fewer than have joined. |

### admin_set_theme_defaults

Replace the theme list everyone without their own list sees, 1 to 40 themes in the Theme schema of the API reference. null puts the built-in themes back.

|  |  |
|---|---|
| Route | `POST /api/admin/theme-defaults` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `themes` | array of object or null | no |  | 1 to 40 themes. null goes back to the built-in ones. |
| `themes[].accent` | string | yes |  | The main color: what you can press. |
| `themes[].background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].button` | object or null | no |  | How the theme's buttons look. A choice left out is the default (rounded, normal, raised, normal). |
| `themes[].button.case` | string | no | one of `normal`, `upper` |  |
| `themes[].button.depth` | string | no | one of `flat`, `raised`, `glossy` |  |
| `themes[].button.shape` | string | no | one of `square`, `soft`, `rounded`, `pill` |  |
| `themes[].button.weight` | string | no | one of `normal`, `medium`, `bold` |  |
| `themes[].dark` | object or null | no |  | A light theme's colors for dark mode, kept while it is light. Switching the theme to dark swaps them in. A light theme's light (or a dark theme's dark) is dropped. |
| `themes[].dark.accent` | string | yes |  | The main color: what you can press. |
| `themes[].dark.background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].dark.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].dark.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].dark.surface` | string | no |  | Cards. Left out: the mode's own. |
| `themes[].id` | string | yes |  | Lower-case letters, digits, - and _, up to 32. |
| `themes[].light` | object or null | no |  | A dark theme's colors for light mode, kept while it is dark. Switching the theme to light swaps them in. |
| `themes[].light.accent` | string | yes |  | The main color: what you can press. |
| `themes[].light.background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].light.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].light.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].light.surface` | string | no |  | Cards. Left out: the mode's own. |
| `themes[].mode` | string | yes | one of `light`, `dark` |  |
| `themes[].name` | string | yes |  | 1 to 60 characters. |
| `themes[].overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].surface` | string | no |  | Cards. Left out: the mode's own. |

### admin_set_user_disabled

Switch an account off (disabled: true) or back on (false). Disabling signs it out everywhere and voids its live login link; its API keys stop working while it is off. Reversible. The owner and your own account cannot be disabled.

|  |  |
|---|---|
| Route | `POST /api/admin/users/{user_id}/disabled` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `disabled` | boolean | yes |  |  |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

### admin_set_user_role

Make an account an admin or an ordinary user. Only the owner takes an admin's rights away; the owner is always an admin, and nobody changes their own role. Becoming an admin ends the account's sessions and live login link.

|  |  |
|---|---|
| Route | `POST /api/admin/users/{user_id}/role` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `role` | string | yes | one of `admin`, `user` |  |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

### admin_switch_on_invite_link

Undo admin_revoke_invite_link: anyone still holding the link can use it again. The link then counts as this key's: revoking the key switches it off.

|  |  |
|---|---|
| Route | `POST /api/admin/invite-links/{link_id}/switch-on` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

### cancel_my_login_link

Void your account's live login link without making a new one. Devices it already signed in stay signed in. Answers with removed: 0 or 1.

|  |  |
|---|---|
| Route | `POST /api/account/login-link/cancel` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

### create_my_login_link

A link that signs your own account in on a browser or another device. Only a key with your account's full role may ask: one scoped down to user on an admin account is refused. Answers with login_url (open it to sign in), expires_at and max_uses. The link works once and expires within a day (links made with an API key are held to that; a browser can make longer or reusable ones). Any older link the account could still use stops working; its signed-in devices stay signed in. Revoking or deleting this API key voids the link while it is unused, and signs out every device it signed in.

|  |  |
|---|---|
| Route | `POST /api/account/login-link` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |

### label_my_session

Give one of your devices a name (at most 80 characters; empty clears it). expect, when given, is the name you think it has now.

|  |  |
|---|---|
| Route | `POST /api/account/sessions/{session_id}/label` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `label` | string | yes | at most 80 characters | At most 80 characters. |
| `session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

### list_my_sessions

Where your account is signed in, a page at a time: id, when it started and was last seen, the browser, and the name you gave it. Through an API key no device is current. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Route | `GET /api/account/sessions` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `limit` | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

### list_team

People with an active account, a page at a time: id and display name. Use the id wherever another tool asks for a user. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Route | `GET /api/team` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `limit` | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

### rename_account

Change your own display name (1-80 characters). expect, when given, is the name you think it has now; if someone changed it meanwhile the rename is refused with the current name, so nothing is overwritten unseen.

|  |  |
|---|---|
| Route | `POST /api/account/rename` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes | 1 to 80 characters |  |
| `expect` | string or null | no |  |  |

### revoke_my_other_sessions

End every session your account has: through an API key there is no current device to keep, so every browser signs in again. API keys keep working. Answers with how many were removed.

|  |  |
|---|---|
| Route | `POST /api/account/sessions/revoke-others` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

### revoke_my_session

End one of your signed-in sessions; that browser has to sign in again.

|  |  |
|---|---|
| Route | `POST /api/account/sessions/{session_id}/revoke` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

### set_shortcuts

Replace your rebound keyboard shortcuts: action id to its list of keys, such as "undo": ["Mod+Z"] (Mod is Cmd on a Mac, Ctrl elsewhere). Send the whole map; an empty list switches an action's keys off, and {} puts every key back to its default. whoami shows the current map.

|  |  |
|---|---|
| Route | `POST /api/account/shortcuts` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `shortcuts` | map of array of string | yes |  | Action id to the keys bound to it. Replaces the whole map; {} puts every key back to its default. Action ids the screens do not know are ignored. |

### set_theme

Switch to another theme from your list (or the defaults), by its id.

|  |  |
|---|---|
| Route | `POST /api/account/theme` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `theme_id` | string | yes |  | A theme's id. Empty for the first in the list. |

### set_themes

Replace your whole list of color themes (1 to 40) and pick the one you use. themes: null goes back to following the app's defaults. A theme is the Theme schema in the API reference (config/openapi.json): id, name, mode light|dark, accent, second, and optional colors as #rrggbb. whoami shows the current list.

|  |  |
|---|---|
| Route | `POST /api/account/themes` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `theme_id` | string | no |  | The theme you use. |
| `themes` | array of object or null | no |  | Your whole list, 1 to 40 themes. null goes back to following the app's defaults. |
| `themes[].accent` | string | yes |  | The main color: what you can press. |
| `themes[].background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].button` | object or null | no |  | How the theme's buttons look. A choice left out is the default (rounded, normal, raised, normal). |
| `themes[].button.case` | string | no | one of `normal`, `upper` |  |
| `themes[].button.depth` | string | no | one of `flat`, `raised`, `glossy` |  |
| `themes[].button.shape` | string | no | one of `square`, `soft`, `rounded`, `pill` |  |
| `themes[].button.weight` | string | no | one of `normal`, `medium`, `bold` |  |
| `themes[].dark` | object or null | no |  | A light theme's colors for dark mode, kept while it is light. Switching the theme to dark swaps them in. A light theme's light (or a dark theme's dark) is dropped. |
| `themes[].dark.accent` | string | yes |  | The main color: what you can press. |
| `themes[].dark.background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].dark.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].dark.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].dark.surface` | string | no |  | Cards. Left out: the mode's own. |
| `themes[].id` | string | yes |  | Lower-case letters, digits, - and _, up to 32. |
| `themes[].light` | object or null | no |  | A dark theme's colors for light mode, kept while it is dark. Switching the theme to light swaps them in. |
| `themes[].light.accent` | string | yes |  | The main color: what you can press. |
| `themes[].light.background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].light.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].light.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].light.surface` | string | no |  | Cards. Left out: the mode's own. |
| `themes[].mode` | string | yes | one of `light`, `dark` |  |
| `themes[].name` | string | yes |  | 1 to 60 characters. |
| `themes[].overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].surface` | string | no |  | Cards. Left out: the mode's own. |

### whoami

The account this API key belongs to, the role it acts with (role -- never higher than the key's own scope), and the account's own role.

|  |  |
|---|---|
| Route | `GET /api/me` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

### list_batches

Batches in the team's order, a page at a time, with progress (images, included, completed, ais, auto, stored, assignees, live activity) and the folders. Archived ones only with archived: true. next is the offset of the following page, or null.

|  |  |
|---|---|
| Route | `GET /api/ais/batches` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `archived` | boolean | no |  |  |
| `folder_id` | integer | no | at least 1 | The folder's id, from list_folders. |
| `limit` | integer | no | 1 to 1000 | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | string | no |  | Only names containing this. |

### list_folders

The batch folders, each with its parent and order.

|  |  |
|---|---|
| Route | `GET /api/ais/folders` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

### get_batch

One batch whole: its images (key, cell, dir, files per role with sha and whether the server has them stored), adds, done marks (skipped), excluded images, assignment. Admins also see original names.

|  |  |
|---|---|
| Route | `GET /api/ais/batches/{batch_id}` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |

### batch_status

Per image, a page at a time: files and how many are stored, accepted AIS (and how many by auto mode), done, duplicate of, assignee, included.

|  |  |
|---|---|
| Route | `GET /api/ais/batches/{batch_id}/status` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `limit` | integer | no | 1 to 1000 | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

### batch_channels

The channels of the batch's included .czi files, by name, with how many files have each.

|  |  |
|---|---|
| Route | `GET /api/ais/batches/{batch_id}/channels` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |

### list_results

Accepted AIS, a page at a time: one batch's, or every batch's without batch_id; image narrows it to one image. Each row's numbers as the export has them (length_um, ...), its rev for update_result, created_by. pixels only with include_pixels: true.

|  |  |
|---|---|
| Route | `GET /api/ais/results` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | no | at least 1 | The batch's id, from list_batches. |
| `image` | string | no |  | The image's key in the batch (batch_status or get_batch: key). |
| `include_pixels` | boolean | no |  |  |
| `limit` | integer | no | 1 to 1000 | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

### list_measurements

Lines recorded with the Measure tool, a page at a time: one batch's, or every batch's; image narrows it.

|  |  |
|---|---|
| Route | `GET /api/ais/measurements` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | no | at least 1 | The batch's id, from list_batches. |
| `image` | string | no |  | The image's key in the batch (batch_status or get_batch: key). |
| `limit` | integer | no | 1 to 1000 | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

### list_measure_types

The team's types a recorded line can have.

|  |  |
|---|---|
| Route | `GET /api/ais/measure-types` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

### create_batch

A new batch with no images yet, in that folder or at the top. Add files with add_files_to_batch.

|  |  |
|---|---|
| Route | `POST /api/ais/batches` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `folder_id` | integer | no | at least 1 | The folder's id, from list_folders. |
| `name` | string | yes |  |  |

### create_batch_from_files

A new batch from files you hashed (name, rel, sha, size each), grouped into images as the browser does (<cell>.tif raw, '<cell>.tif - Processed method 2.5.tif' processed, .czi, *_zNNN.tif with stack). Duplicates start left out. Answers with the files the server still needs and how to upload them (POST each file's bytes to /api/ais/files with your API key).

|  |  |
|---|---|
| Route | `POST /api/ais/batches/upload` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `channels` | array of object | no |  | Channel roles per layout: [{layout: {kind, names}, roles: [{role: ais \| soma \| other, label}]}], one role per channel, exactly one ais, at most one soma, a label for each other. Images whose file layout matches get them; left out, the AIS is guessed (a .czi's Alexa Fluor 488, a TIFF's first plane). |
| `channels[].layout` | object | no |  |  |
| `channels[].roles` | array of any | no |  |  |
| `czi_stack` | object | no |  | Z-stack .czi files (files with zstack) become one image each: {apotome: sectioned (default) \| widefield}, how an ApoTome stack's grid phases are made into slices. Their AIS channel is guessed (Alexa Fluor 488) unless channels says. |
| `czi_stack.apotome` | string | no | one of `sectioned`, `widefield` |  |
| `files` | array of object | yes |  | The files, hashed on your side: name and rel (path inside the picked folder) as they are, sha256 of the bytes, size in bytes. |
| `files[].layout` | object | no |  | Its channels, for channels: {kind: czi \| tiff, names: [...]} (a .czi's channel names; a TIFF's planes as Red/Green/Blue or Channel N). |
| `files[].modified` | number | no |  |  |
| `files[].name` | string | yes |  |  |
| `files[].rel` | string | yes |  |  |
| `files[].sha` | string | yes |  | sha-256 of the file, lower-case hex. |
| `files[].size` | integer | yes |  |  |
| `files[].zstack` | object | no |  | A .czi with more than one Z plane (a Z-stack): {slices, phases (ApoTome grid phases, 1 without), z_step_um, pixel_um} from its metadata (Scaling X and Z, in microns). Needs layout. |
| `name` | string | yes |  |  |
| `randomize` | boolean | no |  | Blind the names (default true): images get random n-n-n names, the originals kept for admins. |
| `stack` | object | no |  | Z-stack TIFF slices (name_zNNN.tif) become one image each stack: {plane: 0 red \| 1 green \| 2 blue \| 3, z_step_um, pixel_um}. |
| `stack.pixel_um` | number | no |  |  |
| `stack.plane` | integer | no |  |  |
| `stack.z_step_um` | number | no |  |  |
| `translations` | array of object | no |  | __Translation.txt files that came with them: [{dir, text}]. |
| `translations[].dir` | string | no |  |  |
| `translations[].text` | string | no |  |  |

### add_files_to_batch

More files into an existing batch, as create_batch_from_files. add_name names this add (a folder name).

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/upload` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `add_name` | string | no |  |  |
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `channels` | array of object | no |  | Channel roles per layout: [{layout: {kind, names}, roles: [{role: ais \| soma \| other, label}]}], one role per channel, exactly one ais, at most one soma, a label for each other. Images whose file layout matches get them; left out, the AIS is guessed (a .czi's Alexa Fluor 488, a TIFF's first plane). |
| `channels[].layout` | object | no |  |  |
| `channels[].roles` | array of any | no |  |  |
| `czi_stack` | object | no |  | Z-stack .czi files (files with zstack) become one image each: {apotome: sectioned (default) \| widefield}, how an ApoTome stack's grid phases are made into slices. Their AIS channel is guessed (Alexa Fluor 488) unless channels says. |
| `czi_stack.apotome` | string | no | one of `sectioned`, `widefield` |  |
| `files` | array of object | yes |  | The files, hashed on your side: name and rel (path inside the picked folder) as they are, sha256 of the bytes, size in bytes. |
| `files[].layout` | object | no |  | Its channels, for channels: {kind: czi \| tiff, names: [...]} (a .czi's channel names; a TIFF's planes as Red/Green/Blue or Channel N). |
| `files[].modified` | number | no |  |  |
| `files[].name` | string | yes |  |  |
| `files[].rel` | string | yes |  |  |
| `files[].sha` | string | yes |  | sha-256 of the file, lower-case hex. |
| `files[].size` | integer | yes |  |  |
| `files[].zstack` | object | no |  | A .czi with more than one Z plane (a Z-stack): {slices, phases (ApoTome grid phases, 1 without), z_step_um, pixel_um} from its metadata (Scaling X and Z, in microns). Needs layout. |
| `randomize` | boolean | no |  | Blind the names (default true): images get random n-n-n names, the originals kept for admins. |
| `stack` | object | no |  | Z-stack TIFF slices (name_zNNN.tif) become one image each stack: {plane: 0 red \| 1 green \| 2 blue \| 3, z_step_um, pixel_um}. |
| `stack.pixel_um` | number | no |  |  |
| `stack.plane` | integer | no |  |  |
| `stack.z_step_um` | number | no |  |  |
| `translations` | array of object | no |  | __Translation.txt files that came with them: [{dir, text}]. |
| `translations[].dir` | string | no |  |  |
| `translations[].text` | string | no |  |  |

### get_channel_layouts

The channel layouts of a batch's images (or one add's): each with its channel names, how many images, the roles in use and how many already have results.

|  |  |
|---|---|
| Route | `GET /api/ais/batches/{batch_id}/layouts` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `add` | integer | no |  |  |
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |

### set_channel_roles

Which channel is the AIS, soma/dendrite or other, for a batch's (or one add's) images with those layouts; stack: {z_step_um, pixel_um} also sets its Z-stacks' slice spacing and pixel size (the files don't record them); pixel_um sets the microns per pixel its other images are measured with (null: back to the 40x default). Images now traced from other channels or calibration are no longer done; their results stay (3D measures as measured), so look at them again.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/layouts` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `add` | integer | no |  |  |
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `channels` | array of object | yes |  | Channel roles per layout: [{layout: {kind, names}, roles: [{role: ais \| soma \| other, label}]}], one role per channel, exactly one ais, at most one soma, a label for each other. Images whose file layout matches get them; left out, the AIS is guessed (a .czi's Alexa Fluor 488, a TIFF's first plane). |
| `channels[].layout` | object | no |  |  |
| `channels[].roles` | array of any | no |  |  |
| `pixel_um` | number or null | no |  |  |
| `stack` | object | no |  |  |
| `stack.pixel_um` | number | no |  |  |
| `stack.z_step_um` | number | no |  |  |

### fill_missing_areas

For a batch's accepted AIS saved before area (and on Z-stacks volume) was measured: trace each again from its saved clicks and settings and, when it comes out on the same pixels, fill in area_blob_um2, area_width_um2 (and volume_voxel_um3, volume_tube_um3); nothing else changes. with_soma: only AIS whose soma distance has been measured. A few at a time: call again with after until remaining is 0.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/fill-areas` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `after` | integer | no |  |  |
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `limit` | integer | no |  |  |
| `with_soma` | boolean | no |  |  |

### rename_batch

Its accepted AIS carry the new name too. Whoever opened it, or an admin.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/rename` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `name` | string | yes |  |  |

### archive_batch

archived: true hides it from the list (its results stay); false brings it back.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/archive` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `archived` | boolean | yes |  |  |
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |

### set_images_included

Include these images (included: true) or leave them out for the whole team. Left-out images are skipped by auto runs and the report.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/include` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `included` | boolean | yes |  |  |
| `keys` | array of string | yes |  |  |

### set_image_done

Mark (done: true) or unmark an image done by hand: for images with no AIS worth accepting.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/done` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `done` | boolean | yes |  |  |
| `image` | string | yes |  | The image's key in the batch (batch_status or get_batch: key). |

### assign_batch

Split the batch's images among people: shares [{user_id, percent}] (ids from list_team). An empty list clears it.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/assign` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `shares` | array of object | yes |  |  |

### order_batches

The team's priority order: batch ids, first on top.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/order` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ids` | array of integer | yes |  |  |

### move_batches

Those batches into that folder; folder_id null for the top.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/move` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `folder_id` | integer or null | yes |  | The parent folder's id, or null for the top. |
| `ids` | array of integer | yes |  |  |

### create_folder

A new folder, first in its parent (null: the top).

|  |  |
|---|---|
| Route | `POST /api/ais/folders` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |
| `parent_id` | integer or null | no |  | The parent folder's id, or null for the top. |

### rename_folder



|  |  |
|---|---|
| Route | `POST /api/ais/folders/{folder_id}/rename` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `folder_id` | integer | yes | at least 1 | The folder's id, from list_folders. |
| `name` | string | yes |  |  |

### move_folder

Into another folder; parent_id null for the top.

|  |  |
|---|---|
| Route | `POST /api/ais/folders/{folder_id}/move` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `folder_id` | integer | yes | at least 1 | The folder's id, from list_folders. |
| `parent_id` | integer or null | yes |  | The parent folder's id, or null for the top. |

### order_folders

The order of one folder's folders (parent_id null: the top).

|  |  |
|---|---|
| Route | `POST /api/ais/folders/order` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ids` | array of integer | yes |  |  |
| `parent_id` | integer or null | yes |  | The parent folder's id, or null for the top. |

### get_treatments

Each image's original name, saved treatment and the guessed one.

|  |  |
|---|---|
| Route | `GET /api/ais/batches/{batch_id}/treatments` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |

### set_treatments

treatments: {image key: treatment name}; "" takes one off.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/treatments` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `treatments` | object | yes |  |  |

### get_translation

The batch's original/random name per file, as text.

|  |  |
|---|---|
| Route | `GET /api/ais/batches/{batch_id}/translation.txt` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |

### load_translation

For a batch blinded somewhere else: the original names of the files it names.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/translation` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `text` | string | yes |  |  |

### rerandomize_add

New random names for one add of the batch (add_id from get_batch adds, or "earlier"); its results, done marks, exclusions and assignment move with them.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/adds/{add_id}/randomize` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `add_id` | string | yes |  |  |
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |

### get_backup

The batch as data, with its results and recorded lines and the people in it: what a restorable backup's manifest holds.

|  |  |
|---|---|
| Route | `GET /api/ais/batches/{batch_id}/backup` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |

### save_result

Accept an AIS on an image: row as trace_click or detect_image gives it (or your own numbers). Give a client_id so a retry never saves it twice.

|  |  |
|---|---|
| Route | `POST /api/ais/results` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `client_id` | string | no |  | Your own id for this create (8-64 letters, digits, -). Sent again, it finds the first one instead of adding a second. |
| `image` | string | yes |  | The image's key in the batch (batch_status or get_batch: key). |
| `row` | object | yes |  | The row as save_result takes it: the 'row' a trace_click or detect_image candidate gives, or your own numbers (app/models/ais.py RESULT_NUMBERS). |

### update_result

An accepted AIS traced again: it keeps its number and origin. Whoever accepted it, the image's assignee, or an admin.

|  |  |
|---|---|
| Route | `POST /api/ais/results/{result_id}/update` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | integer | no | at least 0 | The rev you last saw (optional). If someone changed it since, the call is refused with the current one. |
| `result_id` | integer | yes | at least 1 | The result's id, from list_results. |
| `row` | object | yes |  | The row as save_result takes it: the 'row' a trace_click or detect_image candidate gives, or your own numbers (app/models/ais.py RESULT_NUMBERS). |

### set_result_soma

soma: {soma_um, soma_px, soma_ais_x, soma_ais_y, soma_x, soma_y}, plus on a Z-stack soma_xy_um and soma_dz_um (soma_um is then the 3D distance), or null to clear it. The trace stays as it is.

|  |  |
|---|---|
| Route | `POST /api/ais/results/{result_id}/soma` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | integer | no | at least 0 | The rev you last saw (optional). If someone changed it since, the call is refused with the current one. |
| `result_id` | integer | yes | at least 1 | The result's id, from list_results. |
| `soma` | object or null | yes |  |  |

### delete_result

One accepted AIS gone; the image's others renumbered. Whoever accepted it, the image's assignee, or an admin. Cannot be undone.

|  |  |
|---|---|
| Route | `POST /api/ais/results/{result_id}/delete` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | integer | no | at least 0 | The rev you last saw (optional). If someone changed it since, the call is refused with the current one. |
| `result_id` | integer | yes | at least 1 | The result's id, from list_results. |

### add_measurement

A line measured on an image (the Measure tool's Record).

|  |  |
|---|---|
| Route | `POST /api/ais/measurements` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `client_id` | string | no |  | Your own id for this create (8-64 letters, digits, -). Sent again, it finds the first one instead of adding a second. |
| `image` | string | yes |  | The image's key in the batch (batch_status or get_batch: key). |
| `measurement` | object | yes |  | {a_x, a_y, b_x, b_y, length_px, length_um, pixconv, label?, type?}: a line's ends in MATLAB axes and its length. |

### update_measurement

Its new ends, length, label and type.

|  |  |
|---|---|
| Route | `POST /api/ais/measurements/{measurement_id}/update` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | integer | no | at least 0 | The rev you last saw (optional). If someone changed it since, the call is refused with the current one. |
| `measurement` | object | yes |  | {a_x, a_y, b_x, b_y, length_px, length_um, pixconv, label?, type?}: a line's ends in MATLAB axes and its length. |
| `measurement_id` | integer | yes | at least 1 | The recorded line's id, from list_measurements. |

### delete_measurement

Cannot be undone.

|  |  |
|---|---|
| Route | `POST /api/ais/measurements/{measurement_id}/delete` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | integer | no | at least 0 | The rev you last saw (optional). If someone changed it since, the call is refused with the current one. |
| `measurement_id` | integer | yes | at least 1 | The recorded line's id, from list_measurements. |

### set_measure_types

The team's new list of types: names.

|  |  |
|---|---|
| Route | `POST /api/ais/measure-types` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `types` | array of string | yes |  |  |

### reset_batch_auto

Deletes every AIS auto mode saved on the batch (the rest renumbered) and the done marks of the images they were on, to run auto again. What went is kept in the Batches screen's Trash for 30 days, where a person can put it back.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/reset` |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |

### auto_defaults

What an auto run or detect_image uses unless told otherwise, and what may be set: general (methods, filters), settings (the method's), threshold, engines, z_methods.

|  |  |
|---|---|
| Route | `GET /api/ais/auto/defaults` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

### start_auto_run

Auto mode over a whole batch, run by the server: every included image (less the complete ones unless skip_done: false), each AIS the filters keep saved straight to the batch, as the browser's review 'all'. Answers at once; follow it with get_auto_run. mark_done also marks each image done. images: only these keys.

|  |  |
|---|---|
| Route | `POST /api/ais/batches/{batch_id}/auto` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `engine` | string or null | no | one of `fast`, `null` | fast: Settings' Method 'ais_auto.m (fast)', the same answer, sooner. |
| `general` | object | no |  | Settings' general auto mode fields (see auto_defaults), e.g. {auto_method: 'fitted', fitted_min_length: 13}. Left out: the defaults. |
| `images` | array of string | no |  |  |
| `mark_done` | boolean | no |  |  |
| `settings` | object | no |  | The method settings (see auto_defaults: settings), e.g. {pixconv: 0.161}. Left out: the defaults. |
| `skip_done` | boolean | no |  |  |
| `threshold` | number | no | 0 to 1 | Default 0.01 (0 = Otsu). |

### get_auto_run

How far a run has got: state (queued, running, finished, stopped, failed), done/total images, found, hidden, saved, errors per image.

|  |  |
|---|---|
| Route | `GET /api/ais/auto/{run_id}` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `run_id` | string | yes |  |  |

### list_auto_runs

The server's auto runs since it started, newest first; batch_id narrows them.

|  |  |
|---|---|
| Route | `GET /api/ais/auto` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | no | at least 1 | The batch's id, from list_batches. |

### cancel_auto_run

Stops after the image it is on; what it saved stays. Whoever started it, or an admin.

|  |  |
|---|---|
| Route | `POST /api/ais/auto/{run_id}/cancel` |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `run_id` | string | yes |  |  |

### export_report

The Batches screen's report (report.xlsx) as JSON sheets -- summary, images, assignees, ais, measurements, measurement_types, and for admins original_names, by_treatment, statistics -- each {columns, rows}. batch: one id, several separated by commas, or all. Left-out images only with everything. unblind (admins): blinded images under their original names. sheets narrows it to those.

|  |  |
|---|---|
| Route | `GET /api/ais/report` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch` | string | yes |  | A batch id, ids separated by commas, or all. |
| `everything` | boolean | no |  |  |
| `sheets` | string | no |  | Sheet names separated by commas. |
| `unblind` | boolean | no |  |  |

### compare_batches

The comparison export (comparison.xlsx) as JSON: per measure the culture means, the treatment summary, every test with Holm-corrected p and stars, all values and original names, each sheet {columns, rows}; plus the raw groups, pooled, stats. Two batches or more (one culture each) for the tests between cultures. tests: anova, tukey, welch, dunnett, twoway, paired, unpaired, ks; units: culture means, individual values (every one when left out; nothing is averaged per image: each AIS of a treatment within a culture counts alike, and each culture is one n). design: the two-way ANOVA's factors, "drug x add-on" (default) or "treatment x culture". plots: true adds the box and cumulative plots as SVG.

|  |  |
|---|---|
| Route | `POST /api/ais/compare` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_ids` | array of integer | yes |  |  |
| `design` | string | no | one of `drug x add-on`, `treatment x culture` |  |
| `labels` | object | no |  | {measure id: name} for the plots' titles. |
| `plots` | boolean | no |  |  |
| `tests` | array of string | no |  |  |
| `units` | array of string | no |  |  |

### upload_instructions

Image bytes do not go through MCP: POST each file's raw bytes to the url given, with your API key (Content-Type: application/octet-stream). With batch_id, also the files that batch still needs (sha, name, rel, image).

|  |  |
|---|---|
| Route | `POST /api/ais/files` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | no | at least 1 | A batch: also list the files it still needs. |

### files_stored

For each sha-256, whether the server already holds that file (so it need not be uploaded again).

|  |  |
|---|---|
| Route | `POST /api/ais/files` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `shas` | array of string | yes |  | sha-256s, lower-case hex. |

### get_image

An image as PNG: the processed view the Process screen traces on (view), a thumbnail (thumb), or a .czi's channels together (composite).

|  |  |
|---|---|
| Route | `GET /api/ais/files/{sha}/view.png` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `kind` | string | no | one of `view`, `thumb`, `composite` | view (default): the processed image as the Process screen shows it; thumb: small; composite: a .czi's channels together. |
| `sha` | string | yes |  | The file's sha (get_batch: images[].files[role].sha). |

### trace_click

What a click on the Process screen does: the AIS traced from that point, with the row to save (save_result) when it worked. Uses the auto_defaults settings unless given.

|  |  |
|---|---|
| Route | `POST /api/ais/trace` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `click` | array of number | yes |  | [x, y] in MATLAB axes: x = column, y = row, pixel centres at 1..n. |
| `click2` | array of number | no |  | The second click after re-thresholding; default the first again. |
| `engine` | string or null | no | one of `fast`, `null` | fast: Settings' Method 'ais_auto.m (fast)', the same answer, sooner. |
| `image` | string | yes |  | The image's key in the batch (batch_status or get_batch: key). |
| `settings` | object | no |  | The method settings (see auto_defaults: settings), e.g. {pixconv: 0.161}. Left out: the defaults. |
| `threshold` | number | no | 0 to 1 | Default 0.01 (0 = Otsu). |
| `z_method` | string | no |  | A Z-stack's method (default trace_lift). |

### detect_image

Auto mode on one image without saving: every candidate the filters keep (include_hidden: the rest too), each with passes and the row save_result takes -- so you can review and save them yourself. The image's saved AIS are left out of the search.

|  |  |
|---|---|
| Route | `POST /api/ais/detect` |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | integer | yes | at least 1 | The batch's id, from list_batches. |
| `engine` | string or null | no | one of `fast`, `null` | fast: Settings' Method 'ais_auto.m (fast)', the same answer, sooner. |
| `general` | object | no |  | Settings' general auto mode fields (see auto_defaults), e.g. {auto_method: 'fitted', fitted_min_length: 13}. Left out: the defaults. |
| `image` | string | yes |  | The image's key in the batch (batch_status or get_batch: key). |
| `include_hidden` | boolean | no |  | Also list the candidates the filters leave out (default false). |
| `settings` | object | no |  | The method settings (see auto_defaults: settings), e.g. {pixconv: 0.161}. Left out: the defaults. |
| `threshold` | number | no | 0 to 1 | Default 0.01 (0 = Otsu). |
| `verbose` | boolean | no |  | Keep each candidate's whole trace data (path, spline, profile, component). Default false. |

### HTTP only

Routes an API key may call that have no tool, and why.

| Route | Why |
|---|---|
| `GET /api/about/report` | The About screen's copy of a document in the repository; nothing to act on. |
| `GET /api/ais/files/{sha}/channel/{index}.png` | Viewer images for the Process screen; get_image gives an agent the processed view. |
| `GET /api/ais/files/{sha}/channel/{index}.tif` | File bytes: MCP messages are JSON, and clients cap their size. Fetch it over HTTP with the same key. |
| `GET /api/ais/files/{sha}/channels` | Viewer detail for the Process screen's channel picker; get_batch names each image's files. |
| `GET /api/ais/files/{sha}/composite.png` | Reached through get_image with kind composite. |
| `GET /api/ais/files/{sha}/file` | File bytes: MCP messages are JSON, and clients cap their size. Fetch it over HTTP with the same key. |
| `GET /api/ais/files/{sha}/processed.tif` | File bytes: MCP messages are JSON, and clients cap their size. Fetch it over HTTP with the same key. |
| `GET /api/ais/files/{sha}/slice/{index}.png` | Viewer images for the Process screen's z-stack slider; get_image gives an agent the processed view. |
| `GET /api/ais/files/{sha}/somata` | Viewer overlay for the Process screen; detect_image and trace_click give an agent the results. |
| `GET /api/ais/files/{sha}/thumb.png` | Reached through get_image with kind thumb. |
| `GET /api/ais/local/status` | Whether Open path and MATLAB work on this machine: those routes need a browser session. |
| `GET /api/ais/matlab/helper/download/{platform}` | The MATLAB helper program itself, a download for a person's computer. |
| `GET /api/ais/matlab/helper/jobs/{job_id}/bundle` | Called by the MATLAB helper program, not by agents; the bundle is a zip. |
| `GET /api/ais/matlab/helper/next` | Called by the MATLAB helper program, not by agents. |
| `GET /api/ais/trash` | The trash only holds what the Batches screen deleted, which agents cannot do. |
| `GET /api/mcp.json` | The MCP reference itself; tools/list gives the same list. |
| `GET /api/openapi.json` | The API reference itself; GET /api/mcp.json is the MCP one. |
| `POST /api/ais/batches/import` | A backup zip: MCP messages are JSON, and clients cap their size. Send it over HTTP with the same key. |
| `POST /api/ais/batches/import/missing` | A backup zip: MCP messages are JSON, and clients cap their size. Send it over HTTP with the same key. |
| `POST /api/ais/batches/{batch_id}/activity` | The Process screen reporting that someone is working on a batch, not an action. |
| `POST /api/ais/batches/{batch_id}/delete` | Deleting a whole batch is kept out of agents' reach on purpose. |
| `POST /api/ais/files/{sha}/pair` | A first guess for the Measure tool on the Process screen; it stores nothing. |
| `POST /api/ais/folders/{folder_id}/delete` | Deleting a folder is kept out of agents' reach on purpose. |
| `POST /api/ais/matlab/bundle` | A MATLAB run as a zip download for a person's computer. |
| `POST /api/ais/matlab/helper/jobs/{job_id}/done` | Called by the MATLAB helper program, not by agents. |
| `POST /api/ais/results/import` | A results file upload: MCP messages are JSON, and clients cap their size. Send it over HTTP with the same key. |
| `POST /api/ais/trash/{trash_id}/purge` | Deleting for good is kept out of agents' reach on purpose. |
| `POST /api/ais/trash/{trash_id}/restore` | The trash only holds what the Batches screen deleted, which agents cannot do. |
| `POST /api/logout` | Ends a browser session; a key has none to end. |
| `POST /api/logs/events` | The browser's own activity reports (track.js), not an action. |
| `POST /mcp` | The MCP endpoint itself. |
