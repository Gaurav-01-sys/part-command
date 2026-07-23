"""Safe placeholders for partner integrations not yet enabled in the portal.

Standby solutions are intentionally non-operational. They describe the future
contract and capabilities but never create a client, read a token, or make a
network request. This keeps future partner work out of the EULER-first runtime.
"""

from __future__ import annotations

from typing import Any

from .contracts import SolutionManifest, ToolDescriptor


class StandbyPartnerSolution:
    """Manifest-only solution that fails closed until explicitly activated."""

    def __init__(self, manifest: SolutionManifest) -> None:
        if manifest.status != "standby":
            raise ValueError("StandbyPartnerSolution requires a standby manifest")
        self.manifest = manifest

    def discover(self, *, force: bool = False) -> list[ToolDescriptor]:
        del force
        return list(self.manifest.declared_tools)

    def call(self, tool_name: str, arguments: dict[str, Any] | None = None) -> str:
        del arguments
        raise RuntimeError(
            f"Partner solution '{self.manifest.id}' is standby. "
            f"Activate it before calling '{tool_name}'."
        )

    def close(self) -> None:
        return None
