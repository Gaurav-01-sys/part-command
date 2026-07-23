"""Partner-hub layouts for the Dash portal.

The hub is deliberately driven by ``SolutionManifest`` objects.  Adding a
partner solution to the registry automatically gives it a discoverable home
card and a routed workspace without accidentally treating a standby
integration as live.
"""

from __future__ import annotations

from collections.abc import Iterable

from dash import html

from partner_solutions.contracts import SolutionManifest


_BRAND_MARKS = {
    "euler": "EU",
    "databricks": "DB",
    "snowflake": "SF",
    "microsoft": "MS",
}


def _status_label(manifest: SolutionManifest) -> str:
    return "Live" if manifest.status == "active" else "Integration-ready"


def _partner_mark(manifest: SolutionManifest, *, compact: bool = False) -> html.Div:
    size_class = "partner-mark-compact" if compact else ""
    return html.Div(
        _BRAND_MARKS.get(manifest.id, manifest.display_name[:2].upper()),
        className=f"partner-mark partner-mark-{manifest.id} {size_class}",
        **{"aria-hidden": "true"},
    )


def _systech_logo() -> html.Div:
    """Compact vector treatment of the supplied Systech wordmark."""
    return html.Div(
        [
            html.Span(className="systech-swoosh", **{"aria-hidden": "true"}),
            html.Span("SYSTECH", className="systech-wordmark"),
        ],
        className="systech-logo-tile",
        role="img",
        **{"aria-label": "Systech"},
    )


def _manifest_capability_copy(manifest: SolutionManifest) -> str:
    count = len(manifest.declared_tools)
    if manifest.status == "active":
        return "Live MCP capabilities"
    return f"{count} declared capabilities"


def _partner_card(manifest: SolutionManifest) -> html.A:
    is_live = manifest.status == "active"
    return html.A(
        className=(
            f"partner-card partner-card-{manifest.id} "
            f"{'partner-card-live' if is_live else 'partner-card-standby'}"
        ),
        href=f"/partners/{manifest.id}",
        children=[
            html.Div(
                [
                    _partner_mark(manifest),
                    html.Span(
                        _status_label(manifest),
                        className=(
                            "partner-status partner-status-live"
                            if is_live
                            else "partner-status partner-status-standby"
                        ),
                    ),
                ],
                className="partner-card-topline",
            ),
            html.Div(manifest.display_name, className="partner-card-title"),
            html.P(manifest.description, className="partner-card-description"),
            html.Div(
                [
                    html.Span(_manifest_capability_copy(manifest), className="partner-card-capability"),
                    html.Span("Open workspace", className="partner-card-action"),
                ],
                className="partner-card-footer",
            ),
        ],
    )


def build_partner_home(manifests: Iterable[SolutionManifest]) -> html.Div:
    """Build the default workspace selector shown at ``/``."""
    manifest_list = list(manifests)
    live_count = sum(manifest.status == "active" for manifest in manifest_list)
    standby_count = len(manifest_list) - live_count

    return html.Div(
        className="partner-hub-shell",
        children=[
            html.Div(
                className="partner-hub-content",
                children=[
                    html.Header(
                        [
                            html.Div(
                                [
                                    _systech_logo(),
                                    html.Div(
                                        [
                                            html.Div("Partner Fabric", className="partner-nav-brand"),
                                            html.Div("Unified partner operations", className="partner-nav-subtitle"),
                                        ]
                                    ),
                                ],
                                className="partner-nav-branding",
                            ),
                            html.Div(
                                [
                                    html.Span(f"{live_count} live", className="hub-metric"),
                                    html.Span(f"{standby_count} integration-ready", className="hub-metric hub-metric-muted"),
                                ],
                                className="hub-metrics",
                            ),
                        ],
                        className="partner-hub-nav",
                    ),
                    html.Main(
                        [
                            html.Section(
                                [
                                    html.Div("PARTNER ECOSYSTEM", className="hub-eyebrow"),
                                    html.H1("One home for every partner motion.", className="hub-title"),
                                    html.P(
                                        "Choose a partner workspace to enter its portal. Live data remains isolated to "
                                        "connected integrations, while the rest of your ecosystem is ready to activate.",
                                        className="hub-lede",
                                    ),
                                ],
                                className="hub-hero",
                            ),
                            html.Section(
                                [
                                    html.Div(
                                        [
                                            html.H2("Your partner workspaces", className="hub-section-title"),
                                            html.P(
                                                "Each workspace has a dedicated route, capability surface, and connection state.",
                                                className="hub-section-copy",
                                            ),
                                        ],
                                        className="hub-section-heading",
                                    ),
                                    html.Div(
                                        [_partner_card(manifest) for manifest in manifest_list],
                                        className="partner-card-grid",
                                    ),
                                ],
                                className="hub-workspace-section",
                            ),
                        ],
                    ),
                    html.Footer(
                        "Partner Fabric keeps every integration visible without presenting an unconnected partner as live.",
                        className="partner-hub-footer",
                    ),
                ],
            )
        ],
    )


def _workspace_header(manifest: SolutionManifest, actions) -> html.Div:
    is_live = manifest.status == "active"
    return html.Header(
        [
            html.Div(
                [
                    html.A("All partners", href="/", className="workspace-backlink"),
                    html.Span("/", className="workspace-separator", **{"aria-hidden": "true"}),
                    html.Div(manifest.display_name, className="workspace-current-name"),
                ],
                className="workspace-breadcrumb",
            ),
            html.Div(
                [
                    html.Span(
                        _status_label(manifest),
                        className=(
                            "partner-status partner-status-live"
                            if is_live
                            else "partner-status partner-status-standby"
                        ),
                    ),
                    actions or html.Div(),
                ],
                className="workspace-header-actions",
            ),
        ],
        className="partner-workspace-nav",
    )


def _workspace_hero(manifest: SolutionManifest) -> html.Section:
    is_live = manifest.status == "active"
    title = "Live partner workspace" if is_live else "Partner workspace"
    description = (
        "Explore live partner data and use AI-assisted workflows powered by the EULER MCP connection."
        if is_live
        else "This dedicated workspace is reserved for the partner integration and its approved capability surface."
    )
    return html.Section(
        [
            _partner_mark(manifest, compact=True),
            html.Div(
                [
                    html.Div(title, className="workspace-eyebrow"),
                    html.H1(manifest.display_name, className="workspace-title"),
                    html.P(description, className="workspace-lede"),
                ]
            ),
        ],
        className=f"workspace-hero workspace-hero-{manifest.id}",
    )


def build_live_workspace(manifest: SolutionManifest, content, *, actions=None) -> html.Div:
    """Wrap the existing live solution UI in the unified workspace chrome."""
    return html.Div(
        className="partner-workspace-shell partner-workspace-live",
        children=[
            _workspace_header(manifest, actions),
            html.Main(
                [_workspace_hero(manifest), html.Div(content, className="workspace-live-content")],
                className="partner-workspace-content",
            ),
        ],
    )


def build_standby_workspace(manifest: SolutionManifest) -> html.Div:
    """Render an honest, useful landing page for a not-yet-connected partner."""
    capability_cards = [
        html.Div(
            [
                html.Div(tool.name.replace("_", " ").title(), className="standby-capability-title"),
                html.P(tool.description, className="standby-capability-description"),
            ],
            className="standby-capability-card",
        )
        for tool in manifest.declared_tools
    ]
    return html.Div(
        className="partner-workspace-shell partner-workspace-standby",
        children=[
            _workspace_header(manifest, None),
            html.Main(
                [
                    _workspace_hero(manifest),
                    html.Section(
                        [
                            html.Div(
                                [
                                    html.Div("Connection status", className="standby-label"),
                                    html.H2("Ready for activation", className="standby-title"),
                                    html.P(
                                        "The portal route and capability contract are in place. Connect this partner only "
                                        "when its approved credentials and MCP adapter are available.",
                                        className="standby-copy",
                                    ),
                                    html.Div(
                                        "No live data is requested from this workspace yet.",
                                        className="standby-notice",
                                    ),
                                    html.A("Return to partner hub", href="/", className="standby-return-link"),
                                ],
                                className="standby-intro-card",
                            ),
                            html.Div(
                                [
                                    html.Div("Declared capabilities", className="standby-label"),
                                    html.H2("What this workspace will provide", className="standby-title"),
                                    html.Div(capability_cards, className="standby-capability-grid"),
                                ],
                                className="standby-capabilities-panel",
                            ),
                        ],
                        className="standby-layout",
                    ),
                ],
                className="partner-workspace-content",
            ),
        ],
    )
