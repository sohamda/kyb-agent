"""Existing-customer book — used by the nightly re-screening job."""

from __future__ import annotations

from langchain.tools import tool

from tools._data import load


@tool(parse_docstring=True)
def list_customers_for_rescreen() -> dict:
    """List existing onboarded customers and their people, for re-screening.

    Returns each customer's id, legal name, jurisdiction, and the directors and
    beneficial owners on record. Use this in the nightly re-screening job to get
    the parties to screen against the current watchlists.
    """
    customers = [
        {
            "customer_id": c["customer_id"],
            "legal_name": c["legal_name"],
            "jurisdiction": c["jurisdiction"],
            "persons": c["persons"],
        }
        for c in load("customers.json")
    ]
    return {"count": len(customers), "customers": customers}
