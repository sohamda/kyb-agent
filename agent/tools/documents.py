"""Document validation: parse a submitted document's dates and expiry."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from langchain.tools import tool


def _parse_date(
    value: str, date_format: Literal["MDY", "DMY"] | None = None
) -> date | tuple[date, date]:
    for date_pattern in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, date_pattern).date()
        except ValueError:
            pass

    if "/" not in value:
        raise ValueError(f"unsupported date format: {value!r}")

    patterns = {
        "MDY": "%m/%d/%Y",
        "DMY": "%d/%m/%Y",
    }
    if date_format is not None:
        return datetime.strptime(value, patterns[date_format]).date()

    candidates = {}
    for format_name, date_pattern in patterns.items():
        try:
            candidates[format_name] = datetime.strptime(value, date_pattern).date()
        except ValueError:
            pass

    if not candidates:
        raise ValueError(f"could not parse date: {value!r}")
    if len(candidates) == 1 or len(set(candidates.values())) == 1:
        return next(iter(candidates.values()))
    return candidates["MDY"], candidates["DMY"]


@tool
def check_document(
    doc_type: str,
    holder: str,
    expiry_date: str | None = None,
    issue_date: str | None = None,
    as_of: str | None = None,
    date_format: Literal["MDY", "DMY"] | None = None,
) -> dict:
    """Validate expiry dates; date_format selects MDY or DMY for slash dates."""
    today = datetime.strptime(as_of, "%Y-%m-%d").date() if as_of else date.today()
    result: dict = {"doc_type": doc_type, "holder": holder}

    if not expiry_date:
        result.update(status="no_expiry", expired=False)
        return result

    try:
        expiry = _parse_date(expiry_date, date_format)
    except ValueError:
        result.update(
            status="unverifiable",
            expired=None,
            reason=f"could not parse expiry date {expiry_date!r}",
        )
        return result

    if isinstance(expiry, tuple):
        result.update(
            status="ambiguous",
            expired=None,
            expiry_candidates={
                "MDY": expiry[0].isoformat(),
                "DMY": expiry[1].isoformat(),
            },
        )
        return result

    expired = expiry < today
    result.update(
        status="expired" if expired else "valid",
        expired=expired,
        expiry_parsed=expiry.isoformat(),
    )
    return result
