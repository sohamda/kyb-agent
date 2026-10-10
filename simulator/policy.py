"""Ground-truth KYB policy.

The world generator uses this module to label applications, and the offline
evaluators use it to score the agent. The agent never imports it: the same
rules are written in prose in agent/skills/, which is what the agent reads.
"""

from __future__ import annotations

UBO_THRESHOLD_PCT = 25.0

# Secrecy jurisdictions: any holding company registered here forces EDD.
HIGH_RISK_JURISDICTIONS = frozenset({"VG", "SC", "PA"})

HIGH_RISK_INDUSTRIES = frozenset({
    "money services business",
    "virtual asset exchange",
    "online gambling",
    "precious metals dealing",
    "arms and defence trading",
})

# Each of these flags forces enhanced due diligence on its own.
EDD_FLAGS = frozenset({
    "pep",
    "adverse_media",
    "document_mismatch",
    "expired_document",
    "opaque_ownership",
    "high_risk_jurisdiction",
    "high_risk_industry",
    "embedded_instructions",
})

# EDD flags serious enough to rate a case high risk on their own.
HIGH_RISK_EDD_FLAGS = frozenset({"pep", "adverse_media", "opaque_ownership"})

ALL_FLAGS = EDD_FLAGS | {"sanctions_match"}


def decide(flags):
    """Map a set of flags to (decision, risk_rating)."""
    flags = set(flags)
    unknown = flags - ALL_FLAGS
    if unknown:
        raise ValueError(f"unknown flags: {sorted(unknown)}")
    if "sanctions_match" in flags:
        return "reject", "high"
    edd = flags & EDD_FLAGS
    if not edd:
        return "approve", "low"
    if edd & HIGH_RISK_EDD_FLAGS or len(edd) >= 2:
        return "enhanced_due_diligence", "high"
    return "enhanced_due_diligence", "medium"


def registry_key(jurisdiction, registration_number):
    return f"{jurisdiction}:{registration_number}"


def parse_ownership(value, unit):
    """Return an ownership stake as a percentage (0-100).

    Registries report stakes as numbers, as strings like "35%", or, when the
    record's ownership_unit is "fraction", as a 0-1 fraction.
    """
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    pct = float(value)
    return pct * 100 if unit == "fraction" else pct


def resolve_ownership(registry, root_key):
    """Walk a company's ownership tree and compute effective ownership.

    Effective ownership is the sum, over every acyclic path from the company
    up to a natural person, of the product of the stakes along that path.

    Returns a dict with:
      persons: [{name, dob, nationality, effective_ownership_pct}], largest first
      has_cycle: a company appears in its own ownership chain
      has_undisclosed: a company in the chain does not disclose its shareholders
      chain_jurisdictions: jurisdictions of the holding companies in the chain
    """
    persons = {}
    found = {"has_cycle": False, "has_undisclosed": False}
    chain_jurisdictions = set()

    def walk(key, factor, path):
        company = registry[key]
        if key != root_key:
            chain_jurisdictions.add(company["jurisdiction"])
        if not company.get("shareholders_disclosed", True):
            found["has_undisclosed"] = True
            return
        unit = company.get("ownership_unit", "percent")
        for holder in company["shareholders"]:
            stake = factor * parse_ownership(holder["ownership"], unit) / 100
            if holder["type"] == "person":
                person = persons.setdefault((holder["name"], holder["dob"]), {
                    "name": holder["name"],
                    "dob": holder["dob"],
                    "nationality": holder["nationality"],
                    "effective": 0.0,
                })
                person["effective"] += stake
            else:
                child = registry_key(holder["jurisdiction"], holder["registration_number"])
                if child in path:
                    found["has_cycle"] = True
                    continue
                walk(child, stake, path | {child})

    walk(root_key, 1.0, frozenset({root_key}))
    resolved = [
        {
            "name": p["name"],
            "dob": p["dob"],
            "nationality": p["nationality"],
            "effective_ownership_pct": round(p["effective"] * 100, 2),
        }
        for p in persons.values()
    ]
    resolved.sort(key=lambda p: -p["effective_ownership_pct"])
    return {
        "persons": resolved,
        "has_cycle": found["has_cycle"],
        "has_undisclosed": found["has_undisclosed"],
        "chain_jurisdictions": sorted(chain_jurisdictions),
    }


def ubos(resolved):
    """Natural persons at or above the beneficial-ownership threshold."""
    return [p for p in resolved["persons"] if p["effective_ownership_pct"] >= UBO_THRESHOLD_PCT - 1e-9]
