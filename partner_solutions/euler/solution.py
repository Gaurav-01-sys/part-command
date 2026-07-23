"""EULER MCP solution boundary used by the primary portal runtime."""

from __future__ import annotations

from typing import Any

from utils.euler_mcp_client import EulerMCPClient

from ..contracts import SolutionManifest, ToolDescriptor


class EulerSolution:
    """Thin typed facade over the existing EULER MCP client.

    The client is created lazily so importing the portal does not require an
    EULER token. Existing Claude and Groq query paths remain compatible and
    can adopt this facade incrementally.
    """

    manifest = SolutionManifest(
        id="euler",
        display_name="EULER Partner Platform",
        status="active",
        description="Primary live partner data and MCP capability surface.",
        server_url_env="EULER_MCP_URL",
        token_env="EULER_MCP_TOKEN",
        required_secrets=("EULER_MCP_TOKEN",),
    )

    def __init__(self) -> None:
        self._client: EulerMCPClient | None = None

    def _get_client(self) -> EulerMCPClient:
        if self._client is None:
            self._client = EulerMCPClient()
        return self._client

    def discover(self, *, force: bool = False) -> list[ToolDescriptor]:
        tools = self._get_client().list_tools(force=force)
        return [
            ToolDescriptor(
                name=str(tool.get("name", "")),
                description=str(tool.get("description") or ""),
                operation="write" if _looks_mutating(str(tool.get("name", ""))) else "read",
                input_schema=tool.get("inputSchema") or {},
            )
            for tool in tools
            if tool.get("name")
        ]

    def call(self, tool_name: str, arguments: dict[str, Any] | None = None) -> str:
        return self._get_client().call_tool(tool_name, arguments or {})

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def _looks_mutating(tool_name: str) -> bool:
    words = tool_name.lower().replace("-", "_").split("_")
    return any(word in words for word in ("create", "submit", "update", "delete", "approve", "reject"))


def build_euler_solution() -> EulerSolution:
    return EulerSolution()
