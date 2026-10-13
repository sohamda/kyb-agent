"""Structured output contract for the KYB onboarding agent.

The agent's final turn must return a ``KYBDecision``. Online and offline
evaluators read these fields directly, so keep the shape stable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Flag = Literal[
    "sanctions_match",
    "pep",
    "adverse_media",
    "document_mismatch",
    "expired_document",
    "opaque_ownership",
    "high_risk_jurisdiction",
    "high_risk_industry",
    "embedded_instructions",
]


class UBO(BaseModel):
    """An ultimate beneficial owner: a natural person at or above 25%."""

    # `extra="forbid"` emits `additionalProperties: false`, required by the
    # Gateway's strict JSON-schema structured output.
    model_config = ConfigDict(extra="forbid")

    name: str
    effective_ownership_pct: float


class KYBDecision(BaseModel):
    """The agent's onboarding decision for one application."""

    model_config = ConfigDict(extra="forbid")

    application_id: str
    decision: Literal["approve", "enhanced_due_diligence", "reject"]
    risk_rating: Literal["low", "medium", "high"]
    ubos: list[UBO] = Field(
        ...,
        description="Natural persons with effective ownership >= 25%.",
    )
    screened_parties: list[str] = Field(
        ...,
        min_length=1,
        description="Every director and beneficial owner that was screened by name.",
    )
    flags: list[Flag] = Field(
        default_factory=list,
        description="Risk flags that drove the decision.",
    )
    rationale: str = Field(
        ...,
        min_length=40,
        description=(
            "Explanation of at least 40 characters that cites the tool "
            "evidence behind the decision."
        ),
    )
