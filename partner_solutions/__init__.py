"""Partner solution boundaries for the Partner Command Portal.

The Dash application imports only the primary EULER solution. Other partner
solutions are deliberately lazy-loaded by :mod:`partner_solutions.registry`
when an operator explicitly asks for the full standby catalog.
"""

from .contracts import PartnerSolution, SolutionManifest, ToolDescriptor
from .registry import build_full_registry, build_primary_registry

__all__ = [
    "PartnerSolution",
    "SolutionManifest",
    "ToolDescriptor",
    "build_full_registry",
    "build_primary_registry",
]
