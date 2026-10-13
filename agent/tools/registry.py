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


def _parse_ownership(value: Any, unit: str = "percent") -> float:
    if isinstance(value, str):
        value = value.strip()
        if value.endswith("%"):
            value = value[:-1].strip()
    ownership = float(value)
    return ownership * 100 if unit == "fraction" else ownership


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
    state = {"has_undisclosed": False, "unparseable_stakes": []}
    chain_jurisdictions: set[str] = set()

    def walk(key: str, factor: float) -> None:
        company = registry[key]
        if key != root:
            chain_jurisdictions.add(company["jurisdiction"])
        if not company.get("shareholders_disclosed", True):
            state["has_undisclosed"] = True
            return
        unit = company.get("ownership_unit", "percent")
        for holder in company["shareholders"]:
            try:
                ownership = _parse_ownership(holder["ownership"], unit)
            except (TypeError, ValueError) as error:
                state["unparseable_stakes"].append(
                    {
                        "company": key,
                        "holder": holder.get("name"),
                        "ownership": holder.get("ownership"),
                        "ownership_unit": unit,
                        "error": str(error),
                    }
                )
                continue
            stake = factor * ownership / 100
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
    result = {
        "found": True,
        "ubos": ubos,
        "all_owners": resolved,
        "has_undisclosed_shareholders": state["has_undisclosed"],
        "chain_jurisdictions": sorted(chain_jurisdictions),
        "unparseable_stakes": state["unparseable_stakes"],
    }
    if state["unparseable_stakes"]:
        result["error"] = "Some ownership stakes could not be parsed; ownership may be incomplete."
    return result
