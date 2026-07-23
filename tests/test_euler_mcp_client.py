from __future__ import annotations

import unittest
from unittest.mock import patch

from utils.euler_mcp_client import EULER_KNOWN_TOOLS, EulerMCPClient


class EulerMCPClientCatalogTests(unittest.TestCase):
    def _client(self) -> EulerMCPClient:
        return EulerMCPClient(token="test-token")

    def test_live_tools_are_returned_and_marked_available(self) -> None:
        client = self._client()
        try:
            with patch.object(client, "initialize"), patch.object(
                client,
                "_post",
                return_value={"result": {"tools": [{"name": "live_only"}]}},
            ):
                tools = client.list_tools()

            self.assertEqual(tools, [{"name": "live_only"}])
            self.assertTrue(client.live_fetch_ok)
        finally:
            client.close()

    def test_empty_tools_are_not_replaced_by_known_tools(self) -> None:
        client = self._client()
        try:
            with patch.object(client, "initialize"), patch.object(
                client, "_post", return_value={"result": {"tools": []}}
            ):
                tools = client.list_tools()

            self.assertEqual(tools, [])
            self.assertFalse(client.live_fetch_ok)
            self.assertNotEqual([tool["name"] for tool in tools], [tool["name"] for tool in EULER_KNOWN_TOOLS])
        finally:
            client.close()

    def test_tools_list_error_and_transport_failure_return_empty(self) -> None:
        for response in (
            {"error": {"code": -1, "message": "token expired"}},
            RuntimeError("MCP server unavailable"),
        ):
            with self.subTest(response=response):
                client = self._client()
                try:
                    with patch.object(client, "initialize"), patch.object(
                        client, "_post", side_effect=response if isinstance(response, Exception) else None,
                        return_value=response if isinstance(response, dict) else None,
                    ):
                        tools = client.list_tools()

                    self.assertEqual(tools, [])
                    self.assertFalse(client.live_fetch_ok)
                finally:
                    client.close()

    def test_known_tools_is_display_only_catalog(self) -> None:
        known = EulerMCPClient.known_tools()
        self.assertEqual([tool["name"] for tool in known], [tool["name"] for tool in EULER_KNOWN_TOOLS])


if __name__ == "__main__":
    unittest.main()
