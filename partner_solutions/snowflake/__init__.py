"""Standby Snowflake partner solution."""

from ..contracts import SolutionManifest, ToolDescriptor
from ..standby import StandbyPartnerSolution


MANIFEST = SolutionManifest(
    id="snowflake",
    display_name="Snowflake Partner Analytics",
    status="standby",
    description="Partner dimensions, deal facts, recognized revenue, and pipeline.",
    server_url_env="SNOWFLAKE_MCP_URL",
    token_env="SNOWFLAKE_MCP_TOKEN",
    required_secrets=("SNOWFLAKE_MCP_TOKEN",),
    declared_tools=(
        ToolDescriptor("partner_dimension", "Read normalized Snowflake partner dimensions."),
        ToolDescriptor("deal_facts", "Read deal facts and weighted pipeline."),
        ToolDescriptor("revenue_summary", "Read recognized revenue summaries."),
    ),
)


def build_solution() -> StandbyPartnerSolution:
    return StandbyPartnerSolution(MANIFEST)


__all__ = ["MANIFEST", "build_solution"]
