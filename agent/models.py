"""Model profiles — one source of truth for which model each agent uses.

Switch the active profile with the ``KYB_MODEL_PROFILE`` environment variable
(the deployment reads it as a secret; the offline eval sets it per experiment).
A subagent whose profile entry is absent inherits the main agent's model.
"""

from __future__ import annotations

import os

_OPUS = "langsmith:anthropic/claude-opus-5-5"
_SONNET = "langsmith:anthropic/claude-sonnet-5-5"

PROFILES: dict[str, dict] = {
    # All agents on Opus 5.5 — the plan's v1 baseline.
    "opus": {"main": _OPUS, "subagents": {}},
    # Opus on the judgment/high-stakes roles; Sonnet on the mechanical subagents.
    "mixed": {
        "main": _OPUS,
        "subagents": {
            "document-checker": _SONNET,
            "ownership-investigator": _SONNET,
        },
    },
    # All agents on Sonnet 5.5 — the cheapest configuration.
    "sonnet": {
        "main": _SONNET,
        "subagents": {
            "document-checker": _SONNET,
            "ownership-investigator": _SONNET,
            "screening-analyst": _SONNET,
        },
    },
}

DEFAULT_PROFILE = "opus"


def current_profile(name: str | None = None) -> dict:
    """Resolve the active profile: explicit name, else env, else default."""
    key = name or os.getenv("KYB_MODEL_PROFILE") or DEFAULT_PROFILE
    if key not in PROFILES:
        raise ValueError(f"Unknown model profile {key!r}; expected one of {sorted(PROFILES)}.")
    return PROFILES[key]


def profile_name(name: str | None = None) -> str:
    return name or os.getenv("KYB_MODEL_PROFILE") or DEFAULT_PROFILE


def main_model(name: str | None = None) -> str:
    """Model id for the main agent."""
    return current_profile(name)["main"]


def subagent_model(subagent: str, name: str | None = None) -> str | None:
    """Model id for a subagent, or None to inherit the main agent's model."""
    return current_profile(name)["subagents"].get(subagent)
