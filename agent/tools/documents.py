"""Document validation: parse a submitted document's dates and expiry."""

from __future__ import annotations

from datetime import date, datetime

from langchain.tools import tool


def _parse_date(value: str) -> date:
    # Dates are parsed in US month-first slash format.
    return datetime.strptime(value, "%m/%d/%Y").date()


@tool(parse_docstring=True)
def check_document(
    doc_type: str,
    holder: str,
    expiry_date: str | None = None,
    issue_date: str | None = None,
    as_of: str | None = None,
) -> dict:
    """Validate a submitted document and report whether it is expired.

    Parses the document's expiry date and compares it to the review date. A
    document whose date cannot be parsed is reported as "unverifiable" and should
    be treated as a document problem.

    Args:
        doc_type: The kind of document, e.g. "passport", "certificate_of_incorporation".
        holder: The person or company the document belongs to.
        expiry_date: The document's expiry date as printed on the document.
        issue_date: The document's issue date as printed, if present.
        as_of: Review date (YYYY-MM-DD). Defaults to today. Pass the application's
            submission date for a deterministic result.
    """
    today = datetime.strptime(as_of, "%Y-%m-%d").date() if as_of else date.today()
    result: dict = {"doc_type": doc_type, "holder": holder}

    if not expiry_date:
        result.update(status="no_expiry", expired=False)
        return result

    try:
        expiry = _parse_date(expiry_date)
    except ValueError:
        result.update(
            status="unverifiable",
            expired=None,
            reason=f"could not parse expiry date {expiry_date!r}",
        )
        return result

    expired = expiry < today
    result.update(
        status="expired" if expired else "valid",
        expired=expired,
        expiry_parsed=expiry.isoformat(),
    )
    return result
