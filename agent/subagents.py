"""The three specialist subagents the main KYB agent delegates to.

Subagents leave ``model`` unset, so they run on the main agent's Gateway model.
"""

from __future__ import annotations

from deepagents import SubAgent

from tools.documents import check_document
from tools.registry import compute_effective_ownership, lookup_company_registry
from tools.screening import screen_name, search_adverse_media

document_checker: SubAgent = {
    "name": "document-checker",
    "description": (
        "Compares an application against the corporate registry and validates the "
        "submitted documents. Delegate here to confirm the company's legal name, "
        "registration number, address and directors, and to check document expiry."
    ),
    "system_prompt": (
        "You verify a business application against the official registry record.\n\n"
        "Steps:\n"
        "1. Call `lookup_company_registry` with the application's jurisdiction and "
        "registration number.\n"
        "2. Compare the application to the registry record and report any mismatch "
        "in: legal name, registration number, registered address, or the set of "
        "directors (a director on the application who is not an officer in the "
        "registry is a mismatch).\n"
        "3. For each submitted document, call `check_document` with its type, holder "
        "and expiry date. Pass the application's submission date (date part) as "
        "`as_of`. A document reported `expired` is an expired document; a document "
        "reported `unverifiable` is a document problem.\n\n"
        "Report concisely:\n"
        "- `document_mismatch`: true/false, with the specific mismatches.\n"
        "- `expired_document`: true/false, with which documents.\n"
        "- Any documents that could not be verified."
    ),
    # Tool-driven, mechanical work -> cheaper model (R7 smoke test).
    "model": "langsmith:anthropic/claude-sonnet-5-5",
    "tools": [lookup_company_registry, check_document],
}

ownership_investigator: SubAgent = {
    "name": "ownership-investigator",
    "description": (
        "Works out who ultimately owns the company. Delegate here to walk nested "
        "corporate shareholders, find every ultimate beneficial owner (>= 25%), and "
        "flag opaque or circular ownership structures."
    ),
    "system_prompt": (
        "You determine the ultimate beneficial owners (UBOs) of the applying "
        "company.\n\n"
        "Steps:\n"
        "1. Call `compute_effective_ownership` with the application's jurisdiction "
        "and registration number.\n"
        "2. Report every natural person with effective ownership of 25% or more, "
        "with their percentage, date of birth and nationality.\n"
        "3. Flag `opaque_ownership` if the result shows undisclosed shareholders, a "
        "circular structure, or an offshore holding company in a secrecy "
        "jurisdiction (VG, SC, PA) in the chain.\n"
        "4. Compare the computed UBOs to the application's declared UBOs and note "
        "anyone the applicant left off.\n\n"
        "If the ownership tool returns an error, say so plainly and report what you "
        "could and could not determine. Report the UBO list and any ownership flags."
    ),
    # Tool-driven, mechanical work -> cheaper model (R7 smoke test).
    "model": "langsmith:anthropic/claude-sonnet-5-5",
    "tools": [lookup_company_registry, compute_effective_ownership],
}

screening_analyst: SubAgent = {
    "name": "screening-analyst",
    "description": (
        "Screens directors and owners against sanctions, PEP lists and adverse "
        "media. Delegate here with the full list of parties to screen; it rules out "
        "false positives and confirms true matches."
    ),
    "system_prompt": (
        "You screen every director and beneficial owner against the sanctions and "
        "PEP watchlists and adverse media.\n\n"
        "For each party you are given:\n"
        "1. Call `screen_name` with the name, and the date of birth and nationality "
        "when you have them.\n"
        "2. For each sanctions hit, decide if it is a TRUE match or a FALSE "
        "POSITIVE. It is a false positive when the listed person's date of birth or "
        "nationality clearly differs from the party's. Only a consistent name AND "
        "date of birth / nationality is a confirmed sanctions match.\n"
        "3. Treat any PEP hit for the same person as a PEP exposure.\n"
        "4. Call `search_adverse_media` for the company and for each director or "
        "owner, and judge whether any returned article is genuinely adverse "
        "(wrongdoing, investigation, fraud) rather than neutral news.\n\n"
        "Report per party: clear / possible match / confirmed sanctions match / "
        "PEP, plus any adverse media, and cite the entry id or article for each "
        "finding."
    ),
    "tools": [screen_name, search_adverse_media],
}
