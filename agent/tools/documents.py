"""Document validation: parse a submitted document's dates and expiry."""

from __future__ import annotations

import re
from datetime import date, datetime

from langchain.tools import tool


_DATE_ORDER_BY_REGION = {"US": "MDY", "GB": "DMY", "DE": "DMY"}


def _parse_date(
    value: str,
    date_order: str | None = None,
    locale: str | None = None,
    jurisdiction: str | None = None,
) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass

    match = re.fullmatch(r"(\d{1,2})([./-])(\d{1,2})\2(\d{4})", value)
    if not match:
        raise ValueError("unsupported date format")

    first, second, year = int(match[1]), int(match[3]), int(match[4])
    if date_order is not None:
        order = date_order.upper()
        if order not in {"MDY", "DMY"}:
            raise ValueError("date_order must be 'MDY' or 'DMY'")
    else:
        region = locale.replace("_", "-").split("-")[-1].upper() if locale else ""
        order = _DATE_ORDER_BY_REGION.get(region)
        if order is None and jurisdiction:
            order = _DATE_ORDER_BY_REGION.get(jurisdiction.upper())

    if order is None:
        if first == second and first <= 12:
            order = "MDY"
        elif first > 12 and second <= 12:
            order = "DMY"
        elif second > 12 and first <= 12:
            order = "MDY"
        elif first > 12 and second > 12:
            raise ValueError(f"invalid expiry date {value!r}")
        else:
            raise ValueError(
                f"ambiguous date {value!r}; provide date_order, locale, or jurisdiction"
            )

    month, day = (first, second) if order == "MDY" else (second, first)
    return date(year, month, day)


@tool
def check_document(
    doc_type: str,
    holder: str,
    expiry_date: str | None = None,
    issue_date: str | None = None,
    as_of: str | None = None,
    date_order: str | None = None,
    locale: str | None = None,
    jurisdiction: str | None = None,
) -> dict:
    """Check expiry dates using ISO YYYY-MM-DD or localized slash, dot, or hyphen dates ordered by date_order, locale, or a configured jurisdiction mapping."""
    today = datetime.strptime(as_of, "%Y-%m-%d").date() if as_of else date.today()
    result: dict = {"doc_type": doc_type, "holder": holder}

    if not expiry_date:
        result.update(status="no_expiry", expired=False)
        return result

    try:
        expiry = _parse_date(expiry_date, date_order, locale, jurisdiction)
    except ValueError as error:
        result.update(
            status="unverifiable",
            expired=None,
            reason=str(error),
        )
        return result

    expired = expiry < today
    result.update(
        status="expired" if expired else "valid",
        expired=expired,
        expiry_parsed=expiry.isoformat(),
    )
    return result
