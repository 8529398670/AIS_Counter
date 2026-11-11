"""Login links made with an API key, over HTTP and MCP: allowed, but held to
once and a day (admin.checked_link_options). A browser session keeps every
choice. Both keys in RoutesTestCase belong to the owner."""
from __future__ import annotations

from typing import Any

from starlette.testclient import TestClient

from app.models import from_iso, utc_now
from app.routes.admin import KEY_LINK_MESSAGE
from app.tests.route_support import RoutesTestCase


class LoginLinksWithKeysTest(RoutesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.set_config(login_token_ttl_seconds=1800, multi_use_login_token_ttl_seconds=7 * 86400)

    def sign_in_with(self, reply: dict) -> int:
        credential = reply["login_path"].removeprefix("/login/")
        return TestClient(self.app).post("/api/login", json={"credential": credential}).status_code

    def tool(self, key: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(
            "/mcp",
            headers={"authorization": "Bearer " + key, "accept": "application/json, text/event-stream", "content-type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}},
        )
        return response.json()

    def tool_names(self, key: str) -> set[str]:
        response = self.client.post(
            "/mcp",
            headers={"authorization": "Bearer " + key, "accept": "application/json, text/event-stream", "content-type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        return {tool["name"] for tool in response.json()["result"]["tools"]}

    # -- HTTP --------------------------------------------------------------

    def test_a_key_makes_its_own_link_once_and_short(self) -> None:
        status, reply = self.call("POST", "/api/account/login-link", key=self.user_key, body={})
        self.assertEqual(status, 200, reply)
        self.assertEqual((reply["max_uses"], reply["unlimited"]), (1, False))
        self.assertEqual(reply["expires_in_seconds"], 1800)
        self.assertTrue(reply["login_url"].endswith(reply["login_path"]))
        self.assertEqual(self.sign_in_with(reply), 200)
        self.assertNotEqual(self.sign_in_with(reply), 200)

    def test_a_key_default_expiry_is_held_to_a_day(self) -> None:
        self.set_config(login_token_ttl_seconds=3 * 86400)
        status, reply = self.call("POST", "/api/account/login-link", key=self.user_key, body={})
        self.assertEqual(status, 200, reply)
        self.assertLessEqual(reply["expires_in_seconds"], 86400)

    def test_a_key_may_not_ask_for_more(self) -> None:
        for body in [{"max_uses": 3}, {"max_uses": 0}, {"expires_in_minutes": 0}, {"expires_in_minutes": 1441}]:
            status, reply = self.call("POST", "/api/account/login-link", key=self.user_key, body=body)
            self.assertEqual((status, reply.get("error")), (400, KEY_LINK_MESSAGE), body)
        status, reply = self.call("POST", "/api/account/login-link", key=self.user_key, body={"max_uses": 1, "expires_in_minutes": 1440})
        self.assertEqual(status, 200, reply)

    def test_a_session_still_makes_long_reusable_links(self) -> None:
        cookie = self.user_cookie
        body = {"csrf_token": self.csrf(cookie), "max_uses": 0, "expires_in_minutes": 0}
        status, reply = self.call("POST", "/api/account/login-link", cookie=cookie, body=body)
        self.assertEqual((status, reply["unlimited"], reply["expires_at"]), (200, True, None))

    def test_an_admin_key_reissues_for_someone_else(self) -> None:
        path = f"/api/admin/users/{self.user.id}/reissue-login"
        status, reply = self.call("POST", path, key=self.admin_key, body={"expires_in_minutes": 60})
        self.assertEqual((status, reply["max_uses"]), (200, 1), reply)
        self.assertLessEqual((from_iso(reply["expires_at"]) - utc_now()).total_seconds(), 3600)
        self.assertEqual(self.call("POST", path, key=self.admin_key, body={"max_uses": 5})[0], 400)
        self.assertEqual(self.call("POST", "/api/admin/users/9999/reissue-login", key=self.admin_key, body={})[0], 404)
        self.assertIn(self.call("POST", path, key=self.user_key, body={})[0], (403, 404))
        self.assertEqual(self.sign_in_with(reply), 200)

    def test_a_key_still_cannot_create_users(self) -> None:
        status, _ = self.call("POST", "/api/admin/users", key=self.admin_key, body={"display_name": "Bea", "role": "user"})
        self.assertNotIn(status, (200, 201))

    # -- MCP ---------------------------------------------------------------

    def test_mcp_own_link_and_cancel(self) -> None:
        made = self.tool(self.user_key, "create_my_login_link", {"expires_in_minutes": 30})["result"]
        self.assertFalse(made["isError"], made)
        link = made["structuredContent"]
        self.assertEqual(link["max_uses"], 1)
        self.assertTrue(link["login_url"].endswith(link["login_path"]))
        cancelled = self.tool(self.user_key, "cancel_my_login_link", {})["result"]["structuredContent"]
        self.assertEqual(cancelled, {"ok": True, "removed": True})
        self.assertNotEqual(self.sign_in_with(link), 200)

    def test_mcp_refuses_too_long(self) -> None:
        result = self.tool(self.user_key, "create_my_login_link", {"expires_in_minutes": 5000})
        self.assertTrue("error" in result or result["result"]["isError"], result)

    def test_mcp_admin_tools(self) -> None:
        made = self.tool(self.admin_key, "admin_reissue_login_link", {"user_id": self.user.id})["result"]
        self.assertFalse(made["isError"], made)
        missing = self.tool(self.admin_key, "admin_reissue_login_link", {"user_id": 9999})["result"]
        self.assertTrue(missing["isError"])
        cancelled = self.tool(self.admin_key, "admin_cancel_login_link", {"user_id": self.user.id})["result"]["structuredContent"]
        self.assertEqual(cancelled, {"ok": True, "removed": True})
        self.assertNotEqual(self.sign_in_with(made["structuredContent"]), 200)

    def test_mcp_admin_tools_are_hidden_from_a_user_key(self) -> None:
        self.assertTrue({"admin_reissue_login_link", "admin_cancel_login_link"} <= self.tool_names(self.admin_key))
        names = self.tool_names(self.user_key)
        self.assertIn("create_my_login_link", names)
        self.assertFalse({"admin_reissue_login_link", "admin_cancel_login_link"} & names)
