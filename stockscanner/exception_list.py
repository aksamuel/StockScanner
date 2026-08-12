"""Shared exception-list ordering helpers."""


def sort_exception_rows(rows):
    """Return exception rows sorted by ticker, with blank rows last."""
    return sorted(
        rows,
        key=lambda row: (
            not bool((row.get("Symbol") or "").strip()),
            (row.get("Symbol") or "").strip().casefold(),
        ),
    )
