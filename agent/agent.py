"""KYB onboarding agent — a Managed Deep Agent deployed on LangSmith Cloud.

The main agent plans the review, delegates to three specialist subagents,
applies the risk-rating and EDD-trigger skills, escalates confirmed sanctions
matches for human approval, and returns a structured ``KYBDecision``.
"""

from langchain.agents.structured_output import ProviderStrategy
from managed_deepagents import define_deep_agent

from schemas import KYBDecision
from subagents import document_checker, ownership_investigator, screening_analyst
from tools.compliance import escalate_to_compliance
from tools.customers import list_customers_for_rescreen

agent = define_deep_agent(
    name="kyb-agent",
    # Routed through LLM Gateway. Comparison model: langsmith:anthropic/claude-sonnet-5-5
    model="langsmith:anthropic/claude-opus-5-5",
    subagents=[document_checker, ownership_investigator, screening_analyst],
    tools=[escalate_to_compliance, list_customers_for_rescreen],
    # Pause for a compliance officer to approve or reject the escalation.
    interrupt_on={
        "escalate_to_compliance": {"allowed_decisions": ["approve", "reject"]},
    },
    # Native (provider) structured output. Opus/Sonnet 5.5 reject the forced
    # `tool_choice` that the default ToolStrategy uses via the Gateway (see R8).
    response_format=ProviderStrategy(KYBDecision),
)
