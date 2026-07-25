"""Tests for OrchestratorAgent structured mode."""

from __future__ import annotations

import pytest

from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.types import ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool, ToolSpec

# -- Mocks -------------------------------------------------------------------


class _MockEngine(InferenceEngine):
    """Engine that returns pre-scripted responses."""

    engine_id = "mock"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_idx = 0

    def generate(self, messages, **kwargs) -> dict:
        if self._call_idx < len(self._responses):
            content = self._responses[self._call_idx]
            self._call_idx += 1
        else:
            content = "FINAL_ANSWER: fallback"
        return {"content": content}

    def stream(self, messages, **kwargs):
        raise NotImplementedError

    def list_models(self):
        return []

    def health(self) -> bool:
        return True


class _MockTool(BaseTool):
    tool_id = "calculator"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculator",
            description="A calculator",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                },
            },
        )

    def execute(self, **params) -> ToolResult:
        expr = params.get("expression", "")
        return ToolResult(tool_name="calculator", content=str(expr), success=True)


class _FileReadLikeTool(BaseTool):
    """Small test double with one required and one optional parameter."""

    tool_id = "file_read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="file_read",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["path"],
            },
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="file_read",
            content=params.get("path", ""),
            success=True,
        )


class _AmbiguousTool(BaseTool):
    """Test double whose bare input cannot map to one parameter safely."""

    tool_id = "copy"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="copy",
            description="Copy a value",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                },
                "required": ["source", "destination"],
            },
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(tool_name="copy", content="copied", success=True)


# -- Tests -------------------------------------------------------------------


class TestStructuredMode:
    def test_thought_tool_input_then_final_answer(self):
        """Test full structured loop: TOOL call -> FINAL_ANSWER."""
        engine = _MockEngine(
            [
                "THOUGHT: I need to calculate\nTOOL: calculator\nINPUT: 2+2",
                "THOUGHT: Got result\nFINAL_ANSWER: 4",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_MockTool()],
            mode="structured",
        )
        result = agent.run("What is 2+2?")
        assert result.content == "4"
        assert result.turns == 2
        assert len(result.tool_results) == 1
        assert result.tool_results[0].success is True
        assert result.tool_results[0].content == "2+2"

    @pytest.mark.parametrize(
        "raw_input",
        [
            "notes/today.md",
            '"notes/today.md"',
            '{"path": "notes/today.md"}',
        ],
    )
    def test_single_required_parameter_accepts_string_input(self, raw_input):
        """Structured input maps unambiguous strings to the required field."""
        engine = _MockEngine(
            [
                f"TOOL: file_read\nINPUT: {raw_input}",
                "FINAL_ANSWER: done",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_FileReadLikeTool()],
            mode="structured",
        )

        result = agent.run("Read my notes")

        assert result.tool_results[0].success is True
        assert result.tool_results[0].content == "notes/today.md"

    def test_multiple_required_parameters_do_not_guess_string_mapping(self):
        """Ambiguous bare input remains invalid instead of choosing a field."""
        engine = _MockEngine(
            [
                "TOOL: copy\nINPUT: notes/today.md",
                "FINAL_ANSWER: done",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_AmbiguousTool()],
            mode="structured",
        )

        result = agent.run("Copy my notes")

        assert result.tool_results[0].success is False
        assert "Invalid arguments JSON" in result.tool_results[0].content

    def test_direct_final_answer(self):
        """Test that FINAL_ANSWER on first turn works."""
        engine = _MockEngine(
            [
                "THOUGHT: Easy\nFINAL_ANSWER: Paris",
            ]
        )
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_MockTool()],
            mode="structured",
        )
        result = agent.run("Capital of France?")
        assert result.content == "Paris"
        assert result.turns == 1
        assert len(result.tool_results) == 0

    def test_no_tool_no_final_treats_as_answer(self):
        """If neither TOOL nor FINAL_ANSWER found, treat content as answer."""
        engine = _MockEngine(["Just a plain response with no format"])
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_MockTool()],
            mode="structured",
        )
        result = agent.run("Hello")
        assert result.content == "Just a plain response with no format"
        assert result.turns == 1

    def test_max_turns(self):
        """Test that max_turns terminates the loop."""
        # Always returns a tool call, never a final answer
        responses = [
            "THOUGHT: calc\nTOOL: calculator\nINPUT: 1+1",
        ] * 5
        engine = _MockEngine(responses)
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_MockTool()],
            mode="structured",
            max_turns=3,
        )
        result = agent.run("loop forever")
        assert result.turns == 3
        assert result.metadata.get("max_turns_exceeded") is True

    def test_custom_system_prompt(self):
        """Test that custom system_prompt is used."""
        engine = _MockEngine(["FINAL_ANSWER: ok"])
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
            tools=[_MockTool()],
            mode="structured",
            system_prompt="Custom prompt here",
        )
        result = agent.run("test")
        assert result.content == "ok"


class TestFunctionCallingModeUnchanged:
    """Ensure function_calling mode still works as before."""

    def test_default_mode(self):
        engine = _MockEngine(["Hello back"])
        agent = OrchestratorAgent(
            engine=engine,
            model="test",
        )
        # Default mode should be function_calling
        assert agent._mode == "function_calling"
        result = agent.run("Hello")
        assert result.content == "Hello back"


class TestParseStructuredResponse:
    def test_parse_thought_tool_input(self):
        parsed = OrchestratorAgent._parse_structured_response(
            "THOUGHT: reasoning\nTOOL: calculator\nINPUT: 2+2"
        )
        assert parsed["thought"] == "reasoning"
        assert parsed["tool"] == "calculator"
        assert parsed["input"] == "2+2"
        assert parsed["final_answer"] == ""

    def test_parse_final_answer(self):
        parsed = OrchestratorAgent._parse_structured_response(
            "THOUGHT: done\nFINAL_ANSWER: 42"
        )
        assert parsed["final_answer"] == "42"
        assert parsed["thought"] == "done"

    def test_parse_empty(self):
        parsed = OrchestratorAgent._parse_structured_response("")
        assert parsed["thought"] == ""
        assert parsed["tool"] == ""
        assert parsed["final_answer"] == ""
