"""Standby Databricks partner solution."""

from ..contracts import SolutionManifest, ToolDescriptor
from ..standby import StandbyPartnerSolution


MANIFEST = SolutionManifest(
    id="databricks",
    display_name="Databricks Partner Intelligence",
    status="standby",
    description="Usage, health scores, DBU consumption, and churn signals.",
    server_url_env="DATABRICKS_MCP_URL",
    token_env="DATABRICKS_MCP_TOKEN",
    required_secrets=("DATABRICKS_MCP_TOKEN",),
    declared_tools=(
        ToolDescriptor("partner_usage", "Read partner product usage and DBU consumption."),
        ToolDescriptor("usage_trend", "Read usage trends over a requested period."),
        ToolDescriptor("partner_health", "Read partner health and churn signals."),
    ),
)


def build_solution() -> StandbyPartnerSolution:
    return StandbyPartnerSolution(MANIFEST)


__all__ = ["MANIFEST", "build_solution"]
