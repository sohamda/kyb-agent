"""Corporate-registry tools: company lookup and effective-ownership math."""

from __future__ import annotations

from typing import Any

from langchain.tools import tool

from tools._data import load

UBO_THRESHOLD_PCT = 25.0


def _registry() -> dict[str, Any]:
    return load("registry.json")


def _key(jurisdiction: str, registration_number: str) -> str:
    return f"{jurisdiction}:{registration_number}"


def _parse_ownership(value: Any) -> float:
    # NOTE: parses the stake as a bare float. It ignores the record's
    # ``ownership_unit`` and does not strip a trailing "%". Fractions (0-1) and
    # percent strings ("35%") are therefore handled wrong.
    return float(value)


@tool(parse_docstring=True)
def lookup_company_registry(jurisdiction: str, registration_number: str) -> dict:
    """Look up a company's official record in the corporate registry.

    Returns the registered legal name, status, address, industry, officers and
    the disclosed shareholders. Use it to compare an application against the
    registry and to read directors and shareholders.

    Args:
        jurisdiction: Two-letter jurisdiction code, for example "US", "GB", "DE".
        registration_number: The company registration number exactly as filed.
    """
    record = _registry().get(_key(jurisdiction, registration_number))
    if record is None:
        return {
            "found": False,
            "message": f"No registry record for {jurisdiction}:{registration_number}.",
        }
    return {"found": True, **record}


@tool(parse_docstring=True)
def compute_effective_ownership(jurisdiction: str, registration_number: str) -> dict:
    """Walk the ownership tree and compute each person's effective ownership.

    Follows corporate shareholders recursively down to natural persons, summing
    the product of the stakes along every path. Returns ultimate beneficial
    owners (>= 25%), every reached person, whether any company in the chain
    keeps its shareholders undisclosed, and the jurisdictions of the holding
    companies in the chain.

    Args:
        jurisdiction: Two-letter jurisdiction code of the applying company.
        registration_number: Registration number of the applying company.
    """
    registry = _registry()
    root = _key(jurisdiction, registration_number)
    if root not in registry:
        return {
            "found": False,
            "message": f"No registry record for {jurisdiction}:{registration_number}.",
        }

    persons: dict[tuple[str, str], dict[str, Any]] = {}
    state = {"has_undisclosed": False}
    chain_jurisdictions: set[str] = set()

    def walk(key: str, factor: float) -> None:
        company = registry[key]
        if key != root:
            chain_jurisdictions.add(company["jurisdiction"])
        if not company.get("shareholders_disclosed", True):
            state["has_undisclosed"] = True
            return
        for holder in company["shareholders"]:
            stake = factor * _parse_ownership(holder["ownership"]) / 100
            if holder["type"] == "person":
                person = persons.setdefault(
                    (holder["name"], holder["dob"]),
                    {
                        "name": holder["name"],
                        "dob": holder["dob"],
                        "nationality": holder["nationality"],
                        "effective": 0.0,
                    },
                )
                person["effective"] += stake
            else:
                child = _key(holder["jurisdiction"], holder["registration_number"])
                if child not in registry:
                    state["has_undisclosed"] = True
                    continue
                walk(child, stake)

    walk(root, 1.0)

    resolved = sorted(
        (
            {
                "name": p["name"],
                "dob": p["dob"],
                "nationality": p["nationality"],
                "effective_ownership_pct": round(p["effective"] * 100, 2),
            }
            for p in persons.values()
        ),
        key=lambda p: -p["effective_ownership_pct"],
    )
    ubos = [p for p in resolved if p["effective_ownership_pct"] >= UBO_THRESHOLD_PCT]
    return {
        "found": True,
        "ubos": ubos,
        "all_owners": resolved,
        "has_undisclosed_shareholders": state["has_undisclosed"],
        "chain_jurisdictions": sorted(chain_jurisdictions),
    }
