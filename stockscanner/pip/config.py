from __future__ import annotations

import os


def order_transmission_enabled(environ: dict[str, str] | None = None) -> bool:
    """Fail closed for CI/tests; PIP currently has no order-transmission client."""
    values = os.environ if environ is None else environ
    requested = values.get("PIP_IBKR_ORDER_TRANSMISSION_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    return requested and not values.get("CI") and not values.get("PYTEST_CURRENT_TEST")
