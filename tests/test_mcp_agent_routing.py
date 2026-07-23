from __future__ import annotations

import unittest
from unittest.mock import patch

from utils import mcp_agent_engine as agent


LIVE_TOOLS = [
    {
        "name": "euler_help",
        "description": "Discover available capabilities.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "partner_artifacts",
        "description": "Read a specific partner's artifacts.",
        "inputSchema": {
            "type": "object",
            "required": ["action", "partner_id"],
            "properties": {
                "action": {"type": "string"},
                "partner_id": {"type": "string"},
            },
        },
    },
]


class _FakeEulerClient:
    instances: list["_FakeEulerClient"] = []

    def __init__(self) -> None:
        self.live_fetch_ok = True
        self.calls: list[tuple[str, dict]] = []
        self.__class__.instances.append(self)

    def list_tools(self):
        return LIVE_TOOLS

    def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        if name == "euler_help":
            return '{"message": "Partner capabilities are available through the live EULER catalog."}'
        raise AssertionError(f"Unexpected tool call: {name}")

    def close(self) -> None:
        return None


class MCPAgentRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeEulerClient.instances.clear()

    def test_generic_partner_question_routes_to_euler_help(self) -> None:
        route = agent._route_intent(
            "Tell me about partners",
            LIVE_TOOLS,
        )
        self.assertEqual(route, ("euler_help", {}))

    def test_picker_prompt_includes_live_input_schema(self) -> None:
        prompt = agent._tools_for_prompt(LIVE_TOOLS)
        self.assertIn('"required":["action","partner_id"]', prompt)

    def test_missing_required_arguments_prevents_artifact_call(self) -> None:
        missing = agent._missing_required_arguments(LIVE_TOOLS[1], {})
        self.assertEqual(missing, ["action", "partner_id"])

    def test_agent_never_calls_artifacts_for_generic_partner_question(self) -> None:
        with patch.object(agent, "EulerMCPClient", _FakeEulerClient), patch.object(
            agent,
            "groq_chat",
            return_value="EULER capability guidance returned.",
        ):
            result = agent.run_euler_agent(
                [{"role": "user", "content": "Tell me about partners"}],
                question="Tell me about partners",
            )

        self.assertEqual(result["error"], "")
        self.assertEqual(_FakeEulerClient.instances[0].calls, [("euler_help", {})])

    def test_missing_artifact_fields_return_an_error_without_an_mcp_call(self) -> None:
        tools_without_help = [LIVE_TOOLS[1]]

        class ArtifactOnlyClient(_FakeEulerClient):
            def list_tools(self):
                return tools_without_help

        with patch.object(agent, "EulerMCPClient", ArtifactOnlyClient), patch.object(
            agent, "groq_chat", return_value="not a tool call"
        ):
            result = agent.run_euler_agent(
                [{"role": "user", "content": "Show partner artifacts"}],
                question="Show partner artifacts",
            )

        self.assertIn("No compatible live EULER tool", result["error"])
        self.assertIn("partner_artifacts", result["answer"])
        self.assertEqual(ArtifactOnlyClient.instances[0].calls, [])

    def test_empty_live_catalog_returns_known_tools_without_calling_any_tool(self) -> None:
        class EmptyCatalogClient(_FakeEulerClient):
            def __init__(self) -> None:
                super().__init__()
                self.live_fetch_ok = False

            def list_tools(self):
                return []

        with patch.object(agent, "EulerMCPClient", EmptyCatalogClient), patch.object(
            agent, "groq_chat", side_effect=AssertionError("LLM must not be called")
        ):
            result = agent.run_euler_agent(
                [{"role": "user", "content": "Tell me about referrals"}],
                question="Tell me about referrals",
            )

        self.assertIn("live EULER tool catalog could not be retrieved", result["answer"])
        self.assertIn("typically supports", result["answer"])
        self.assertEqual(result["tool_results"], [])
        self.assertEqual(EmptyCatalogClient.instances[0].calls, [])

    def test_client_creation_failure_returns_same_honest_catalog_message(self) -> None:
        with patch.object(
            agent,
            "EulerMCPClient",
            side_effect=RuntimeError("No EULER MCP token"),
        ), patch.object(agent, "groq_chat", side_effect=AssertionError("LLM must not be called")):
            result = agent.run_euler_agent(
                [{"role": "user", "content": "What can you do?"}],
                question="What can you do?",
            )

        self.assertIn("No EULER MCP token", result["answer"])
        self.assertIn("typically supports", result["answer"])
        self.assertEqual(result["tool_results"], [])

    def test_failed_tool_summary_names_attempt_and_live_tools(self) -> None:
        answer = agent._summarize_for_human(
            "Tell me about referrals",
            [{"name": "referrals", "error": "permission denied"}],
            model=None,
            temperature=0.2,
            top_p=0.95,
            max_tokens=1200,
            available_tools=["euler_help", "ping"],
        )

        self.assertIn("referrals", answer)
        self.assertIn("euler_help", answer)
        self.assertIn("what can you do?", answer)


if __name__ == "__main__":
    unittest.main()
