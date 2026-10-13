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
_NAME_PARTICLES = {"al", "ben", "bin", "ibn", "abu"}
_TRANSLITERATION_EQUIVALENTS = {
    "youssef": "yusuf",
    "muhammad": "mohammed",
    "sergej": "sergei",
    "waldurin": "valdurin",
    "michail": "mikhail",
    "twerdochlebow": "tverdokhlebov",
}


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


def _normalize_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    tokens = re.findall(r"[^\W_]+", unaccented)
    index = 0
    while index < len(tokens) - 1:
        if tokens[index] in _NAME_PARTICLES:
            tokens[index + 1] = tokens[index] + tokens[index + 1]
            del tokens[index]
        else:
            index += 1
    return " ".join(sorted(tokens))


def _transliterate_name(name: str) -> str:
    return " ".join(
        sorted(
            _TRANSLITERATION_EQUIVALENTS.get(token, token)
            for token in _normalize_name(name).split()
        )
    )


def _name_match(name: str, candidate: str) -> tuple[float, str]:
    score = _similar(name, candidate)
    basis = "exact"
    normalized_score = _similar(_normalize_name(name), _normalize_name(candidate))
    if normalized_score > score:
        score = normalized_score
        basis = "normalized"
    transliteration_score = _similar(_transliterate_name(name), _transliterate_name(candidate))
    if transliteration_score > score:
        score = transliteration_score
        basis = "transliteration"
    return score, basis


def _best_match(name: str, candidates: list[str]) -> tuple[float, str]:
    return max(
        (_name_match(name, candidate) for candidate in candidates),
        key=lambda match: match[0],
        default=(0.0, "exact"),
    )


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
        score, match_basis = _best_match(name, names)
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
                    "match_basis": match_basis,
                }
            )

    pep_hits = []
    for entry in load("pep.json"):
        names = [entry["name"], *entry.get("aliases", [])]
        score, match_basis = _best_match(name, names)
        if score >= MATCH_THRESHOLD:
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
