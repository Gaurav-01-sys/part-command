"""Explicit solution registries.

Use ``build_primary_registry`` in the live portal. ``build_full_registry`` is
reserved for settings, diagnostics, and future activation workflows; it lazy-
loads standby modules so they cannot affect the EULER-first application path.
"""

from __future__ import annotations

from typing import Iterable

from .contracts import PartnerSolution


class SolutionRegistry:
    def __init__(self, solutions: Iterable[PartnerSolution] = ()) -> None:
        self._solutions: dict[str, PartnerSolution] = {}
        for solution in solutions:
            self.register(solution)

    def register(self, solution: PartnerSolution) -> None:
        solution_id = solution.manifest.id
        if solution_id in self._solutions:
            raise ValueError(f"Duplicate partner solution: {solution_id}")
        self._solutions[solution_id] = solution

    def get(self, solution_id: str) -> PartnerSolution:
        try:
            return self._solutions[solution_id]
        except KeyError as exc:
            raise KeyError(f"Unknown partner solution: {solution_id}") from exc

    def ids(self) -> tuple[str, ...]:
        return tuple(self._solutions)

    def manifests(self):
        return tuple(solution.manifest for solution in self._solutions.values())


def build_primary_registry() -> SolutionRegistry:
    """Build the registry used by ``dash_app.py``: EULER only."""

    from .euler import build_euler_solution

    return SolutionRegistry([build_euler_solution()])


def build_full_registry() -> SolutionRegistry:
    """Build the EULER + standby catalog for explicit diagnostics/settings use."""

    from .databricks import build_solution as build_databricks
    from .euler import build_euler_solution
    from .microsoft import build_solution as build_microsoft
    from .snowflake import build_solution as build_snowflake

    return SolutionRegistry(
        [
            build_euler_solution(),
            build_databricks(),
            build_snowflake(),
            build_microsoft(),
        ]
    )
