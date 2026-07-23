"""Standby Microsoft Partner Center solution."""

from ..contracts import SolutionManifest, ToolDescriptor
from ..standby import StandbyPartnerSolution


MANIFEST = SolutionManifest(
    id="microsoft",
    display_name="Microsoft Partner Center",
    status="standby",
    description="Partner Center deals, certifications, co-sell, and incentives.",
    server_url_env="MICROSOFT_PARTNER_MCP_URL",
    token_env="MICROSOFT_PARTNER_MCP_TOKEN",
    required_secrets=("MICROSOFT_PARTNER_MCP_TOKEN",),
    declared_tools=(
        ToolDescriptor("partner_center_partners", "Read Microsoft Partner Center partners."),
        ToolDescriptor("co_sell_deals", "Read co-sell opportunities and deal stages."),
        ToolDescriptor("certifications", "Read partner certifications and expiry dates."),
        ToolDescriptor("incentives", "Read incentive eligibility and payouts."),
    ),
)


def build_solution() -> StandbyPartnerSolution:
    return StandbyPartnerSolution(MANIFEST)


__all__ = ["MANIFEST", "build_solution"]
