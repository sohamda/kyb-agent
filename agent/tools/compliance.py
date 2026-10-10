"""Human-approval tool: escalate a confirmed sanctions match for sign-off."""

from __future__ import annotations

from langchain.tools import tool


@tool(parse_docstring=True)
def escalate_to_compliance(
    application_id: str,
    reason: str,
    sanctioned_parties: list[str],
) -> str:
    """Escalate a confirmed sanctions match to a human compliance officer.

    Call this only when screening has confirmed a true sanctions match (the same
    name AND consistent date of birth / nationality). The run pauses for a
    compliance officer to approve or reject before the escalation is recorded.

    Args:
        application_id: The application under review.
        reason: Why this is a confirmed match, citing the screening evidence.
        sanctioned_parties: Names of the parties that matched the sanctions list.
    """
    parties = ", ".join(sanctioned_parties) if sanctioned_parties else "none specified"
    return (
        f"Escalation recorded for {application_id}. "
        f"Confirmed sanctions match: {reason} (parties: {parties})."
    )
