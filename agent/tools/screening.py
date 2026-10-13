"""Watchlist screening: sanctions / PEP name screening and adverse media."""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

from langchain.tools import tool

from tools._data import load

# A hit is reported when the name is at least this similar to a listed name.
MATCH_THRESHOLD = 0.92
CORROBORATED_MATCH_THRESHOLD = 0.75


def _normalize(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    normalized = "".join(char if char.isalnum() else " " for char in without_marks.casefold())
    return " ".join(normalized.split())


def _phonetic_key(name: str) -> str:
    """Return a key using deterministic common romanization substitutions."""
    key = _normalize(name)
    for source, target in (
        ("ow", "ov"),
        ("kh", "h"),
        ("ch", "h"),
        ("ff", "f"),
        ("ph", "f"),
        ("w", "v"),
        ("y", "i"),
        ("j", "i"),
    ):
        key = key.replace(source, target)
    return re.sub(r"([a-z])\1+", r"\1", key)


def _similar(a: str, b: str) -> float:
    normalized_similarity = difflib.SequenceMatcher(
        None, _normalize(a), _normalize(b)
    ).ratio()
    phonetic_similarity = difflib.SequenceMatcher(
        None, _phonetic_key(a), _phonetic_key(b)
    ).ratio()
    return max(normalized_similarity, phonetic_similarity)


def _best_match(name: str, candidates: list[str]) -> float:
    return max((_similar(name, c) for c in candidates), default=0.0)


def _match_basis(
    score: float,
    entry: dict[str, Any],
    dob: str | None,
    nationality: str | None,
) -> str | None:
    if score >= MATCH_THRESHOLD:
        return "name"
    if (
        score >= CORROBORATED_MATCH_THRESHOLD
        and dob is not None
        and nationality is not None
        and entry.get("dob") == dob
        and entry.get("nationality") == nationality
    ):
        return "name_low+dob+nationality"
    return None


def _watchlist() -> list[dict[str, Any]]:
    # The live sanctions list is the base list plus any later additions.
    return load("sanctions.json") + load("sanctions_additions.json")


@tool(parse_docstring=True)
def screen_name(name: str, dob: str | None = None, nationality: str | None = None) -> dict:
    """Screen one person against the sanctions and PEP watchlists.

    Returns strict name matches and lower-similarity candidates only when both
    supplied DOB and nationality exactly match. Each hit includes its match basis
    and listed details for adjudication.

    Args:
        name: Full name of the director or beneficial owner to screen.
        dob: The party's date of birth (YYYY-MM-DD), if known, for adjudication.
        nationality: The party's nationality (ISO code), if known, for adjudication.
    """
    sanctions_hits = []
    for entry in _watchlist():
        names = [entry["name"], *entry.get("aliases", [])]
        score = _best_match(name, names)
        match_basis = _match_basis(score, entry, dob, nationality)
        if match_basis:
            sanctions_hits.append(
                {
                    "entry_id": entry["entry_id"],
                    "name": entry["name"],
                    "aliases": entry.get("aliases", []),
                    "dob": entry.get("dob"),
                    "nationality": entry.get("nationality"),
                    "program": entry.get("program"),
                    "similarity": round(score, 3),
                    "match_basis": match_basis,
                }
            )

    pep_hits = []
    for entry in load("pep.json"):
        names = [entry["name"], *entry.get("aliases", [])]
        score = _best_match(name, names)
        match_basis = _match_basis(score, entry, dob, nationality)
        if match_basis:
            pep_hits.append(
                {
                    "pep_id": entry["pep_id"],
                    "name": entry["name"],
                    "dob": entry.get("dob"),
                    "nationality": entry.get("nationality"),
                    "position": entry.get("position"),
                    "similarity": round(score, 3),
                    "match_basis": match_basis,
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
