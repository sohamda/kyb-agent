import unittest
from pathlib import Path

from subagents import _with_tool_error_result, make_subagents
from tools.registry import compute_effective_ownership


class SubagentToolErrorTests(unittest.TestCase):
    def test_unexpected_tool_exception_returns_error_result(self):
        def fail(jurisdiction, registration_number):
            raise RecursionError("maximum recursion depth exceeded")

        failing_tool = compute_effective_ownership.model_copy(update={"func": fail})
        safe_tool = _with_tool_error_result(failing_tool)

        result = safe_tool.invoke(
            {"jurisdiction": "US", "registration_number": "A"}
        )

        self.assertEqual(
            result,
            {
                "error": "compute_effective_ownership failed: RecursionError: "
                "maximum recursion depth exceeded"
            },
        )

    def test_subagents_receive_safe_tools_and_edd_fallback_instructions(self):
        subagents = make_subagents()
        ownership_investigator = next(
            subagent
            for subagent in subagents
            if subagent["name"] == "ownership-investigator"
        )

        self.assertIn(
            "If the ownership tool returns an error",
            ownership_investigator["system_prompt"],
        )
        self.assertIn(
            "`has_circular_ownership` is true",
            ownership_investigator["system_prompt"],
        )
        self.assertTrue(
            all(tool.func.__name__ == "safe_func" for tool in ownership_investigator["tools"])
        )
        agent_dir = Path(__file__).parents[1]
        self.assertIn("lean toward EDD", (agent_dir / "instructions.md").read_text())
        self.assertIn(
            "Any EDD flag is present",
            (agent_dir / "skills/risk-rating/SKILL.md").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
