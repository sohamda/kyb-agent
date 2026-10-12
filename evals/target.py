"""Eval targets: run the KYB agent over one application and return its decision.

`make_target(profile)` builds the agent **in-process** with `create_deep_agent`,
reusing the project's real tools, subagents, schema, instructions and skills, with
the model wiring for the given profile. `make_deployment_target(url)` runs the same
application against a deployed Agent Server (wired for a later Phase 4 / CI run).

Both return a dict with the KYBDecision fields plus `escalated` (whether the
sanctions-escalation interrupt fired) and a compact `trajectory` for the grounding judge.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

import _env  # noqa: F401  (loads .env + sys.path)
from langchain.agents.structured_output import ProviderStrategy
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from deepagents import create_deep_agent
from models import main_model
from schemas import KYBDecision
from subagents import make_subagents
from tools.compliance import escalate_to_compliance
from tools.customers import list_customers_for_rescreen

_RESUME_APPROVE = {"decisions": [{"type": "approve"}]}


def _system_prompt() -> str:
    """instructions.md + the two skills inlined (no Context Hub in-process)."""
    parts = [(_env.AGENT_DIR / "instructions.md").read_text(encoding="utf-8")]
    for skill in sorted((_env.AGENT_DIR / "skills").glob("*/SKILL.md")):
        parts.append(skill.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)


def _application_message(application: dict) -> str:
    return (
        "Review this business onboarding application and return your KYBDecision.\n\n"
        + json.dumps({"application": application}, indent=2)
    )


def _trajectory(messages: list) -> list[dict]:
    """Compact tool-call / tool-result trail for the grounding judge."""
    traj: list[dict] = []
    for m in messages or []:
        mtype = getattr(m, "type", None) or (m.get("type") if isinstance(m, dict) else None)
        tool_calls = getattr(m, "tool_calls", None) or (
            m.get("tool_calls") if isinstance(m, dict) else None
        )
        content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else None)
        name = getattr(m, "name", None) or (m.get("name") if isinstance(m, dict) else None)
        if tool_calls:
            for tc in tool_calls:
                traj.append({"call": tc.get("name"), "args": tc.get("args")})
        elif mtype == "tool":
            traj.append({"result_of": name, "output": str(content)[:1500]})
    return traj


def _decision_dict(state: dict, escalated: bool) -> dict[str, Any]:
    sr = state.get("structured_response")
    out: dict[str, Any] = {}
    if sr is not None:
        out = sr.model_dump() if hasattr(sr, "model_dump") else dict(sr)
    out["escalated"] = escalated
    out["trajectory"] = _trajectory(state.get("messages", []))
    return out


def make_target(profile_name: str) -> Callable[[dict], dict]:
    """Build an in-process target for the given model profile."""
    graph = create_deep_agent(
        model=main_model(profile_name),
        tools=[escalate_to_compliance, list_customers_for_rescreen],
        subagents=make_subagents(profile_name),
        system_prompt=_system_prompt(),
        response_format=ProviderStrategy(KYBDecision),
        interrupt_on={"escalate_to_compliance": {"allowed_decisions": ["approve", "reject"]}},
        checkpointer=InMemorySaver(),
    )

    def target(inputs: dict) -> dict:
        config = {
            "configurable": {"thread_id": str(uuid.uuid4())},
            "recursion_limit": 150,
        }
        state = graph.invoke(
            {"messages": [{"role": "user", "content": _application_message(inputs["application"])}]},
            config,
        )
        escalated = False
        # Resume through any human-approval interrupts (approve the escalation).
        guard = 0
        while state.get("__interrupt__") and guard < 5:
            escalated = True
            guard += 1
            state = graph.invoke(Command(resume=_RESUME_APPROVE), config)
        return _decision_dict(state, escalated)

    return target


def make_deployment_target(url: str, assistant: str = "kyb-agent") -> Callable[[dict], dict]:
    """Build a target that runs against a deployed Agent Server (Phase 4 / CI)."""
    import os

    from langgraph_sdk import get_sync_client

    # The deployment authenticates callers with a LangSmith workspace API key.
    client = get_sync_client(url=url, api_key=os.environ.get("LANGSMITH_API_KEY"))

    def _interrupts(thread_id: str) -> bool:
        st = client.threads.get_state(thread_id)
        return any(t.get("interrupts") for t in (st.get("tasks") or []))

    def target(inputs: dict) -> dict:
        thread = client.threads.create()
        tid = thread["thread_id"]
        client.runs.wait(
            tid, assistant,
            input={"messages": [{"role": "user", "content": _application_message(inputs["application"])}]},
        )
        escalated = False
        guard = 0
        while _interrupts(tid) and guard < 5:
            escalated = True
            guard += 1
            client.runs.wait(tid, assistant, command={"resume": _RESUME_APPROVE})
        values = client.threads.get_state(tid).get("values", {})
        out = dict(values.get("structured_response") or {})
        out["escalated"] = escalated
        out["trajectory"] = _trajectory(values.get("messages", []))
        return out

    return target
