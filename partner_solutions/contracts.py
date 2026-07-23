"""Typed contracts shared by active and standby partner solutions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


SolutionStatus = Literal["active", "standby"]
ToolOperation = Literal["read", "write"]


@dataclass(frozen=True)
class ToolDescriptor:
    """A normalized capability exposed by a partner solution."""

    name: str
    description: str
    operation: ToolOperation = "read"
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SolutionManifest:
    """Static metadata used for discovery, settings, and future widgets."""

    id: str
    display_name: str
    status: SolutionStatus
    description: str
    server_url_env: str
    token_env: str
    required_secrets: tuple[str, ...] = ()
    declared_tools: tuple[ToolDescriptor, ...] = ()


class PartnerSolution(Protocol):
    """Runtime contract implemented by every partner integration."""

    manifest: SolutionManifest

    def discover(self, *, force: bool = False) -> list[ToolDescriptor]:
        """Return available capabilities, without exposing provider details."""

    def call(self, tool_name: str, arguments: dict[str, Any] | None = None) -> str:
        """Execute one provider operation or raise a clear integration error."""

    def close(self) -> None:
        """Release provider resources."""
