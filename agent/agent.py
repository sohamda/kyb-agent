"""KYB onboarding agent — a Managed Deep Agent deployed on LangSmith Cloud.

The main agent plans the review, delegates to three specialist subagents,
applies the risk-rating and EDD-trigger skills, escalates confirmed sanctions
matches for human approval, and returns a structured ``KYBDecision``.
"""

from langchain.agents.structured_output import ProviderStrategy
from managed_deepagents import define_deep_agent

from models import main_model
from schemas import KYBDecision
from subagents import make_subagents
from tools.compliance import escalate_to_compliance
from tools.customers import list_customers_for_rescreen

agent = define_deep_agent(
    name="kyb-agent",
    # Model comes from the active profile (KYB_MODEL_PROFILE); default is all-Opus.
    # All calls route through the LLM Gateway. See models.py.
    model=main_model(),
    subagents=make_subagents(),
    tools=[escalate_to_compliance, list_customers_for_rescreen],
    # Pause for a compliance officer to approve or reject the escalation.
    interrupt_on={
        "escalate_to_compliance": {"allowed_decisions": ["approve", "reject"]},
    },
    # Native (provider) structured output. Opus/Sonnet 5.5 reject the forced
    # `tool_choice` that the default ToolStrategy uses via the Gateway (see R8).
    response_format=ProviderStrategy(KYBDecision),
)
