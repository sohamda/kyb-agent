"""Watchlist screening: sanctions / PEP name screening and adverse media."""

from __future__ import annotations

import difflib
from typing import Any

from langchain.tools import tool

from tools._data import load

# A hit is reported when the name is at least this similar to a listed name.
MATCH_THRESHOLD = 0.92


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _best_match(name: str, candidates: list[str]) -> float:
    return max((_similar(name, c) for c in candidates), default=0.0)


def _watchlist() -> list[dict[str, Any]]:
    # The live sanctions list is the base list plus any later additions.
    return load("sanctions.json") + load("sanctions_additions.json")


@tool(parse_docstring=True)
def screen_name(name: str, dob: str | None = None, nationality: str | None = None) -> dict:
    """Screen one person against the sanctions and PEP watchlists.

    Returns any sanctions or PEP entries whose name (or alias) matches the query.
    Each hit includes the listed person's date of birth and nationality so you
    can decide whether it is a true match or a false positive with the same name.

    Args:
        name: Full name of the director or beneficial owner to screen.
        dob: The party's date of birth (YYYY-MM-DD), if known, for adjudication.
        nationality: The party's nationality (ISO code), if known, for adjudication.
    """
    sanctions_hits = []
    for entry in _watchlist():
        names = [entry["name"], *entry.get("aliases", [])]
        score = _best_match(name, names)
        if score >= MATCH_THRESHOLD:
            sanctions_hits.append(
                {
                    "entry_id": entry["entry_id"],
                    "name": entry["name"],
                    "aliases": entry.get("aliases", []),
                    "dob": entry.get("dob"),
                    "nationality": entry.get("nationality"),
                    "program": entry.get("program"),
                    "similarity": round(score, 3),
                }
            )

    pep_hits = []
    for entry in load("pep.json"):
        score = _similar(name, entry["name"])
        if score >= MATCH_THRESHOLD:
            pep_hits.append(
                {
                    "pep_id": entry["pep_id"],
                    "name": entry["name"],
                    "dob": entry.get("dob"),
                    "nationality": entry.get("nationality"),
                    "position": entry.get("position"),
                    "similarity": round(score, 3),
                }
            )

    return {
        "query": {"name": name, "dob": dob, "nationality": nationality},
        "sanctions_hits": sanctions_hits,
        "pep_hits": pep_hits,
    }


@tool(parse_docstring=True)
def search_adverse_media(name: str) -> dict:
    """Search the news corpus for articles mentioning a company or person.

    Returns every article that names the entity. The articles are a mix of
    adverse coverage and neutral background news; read the headline and snippet
    and judge for yourself whether any article is genuinely adverse.

    Args:
        name: Company or person name to search for.
    """
    needle = name.lower()
    articles = [
        {
            "article_id": a["article_id"],
            "published": a["published"],
            "source": a["source"],
            "headline": a["headline"],
            "snippet": a["snippet"],
        }
        for a in load("media.json")
        if any(needle == e.lower() or needle in e.lower() for e in a.get("entities", []))
    ]
    return {"query": name, "articles": articles}
