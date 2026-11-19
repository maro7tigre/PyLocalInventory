"""Shared Sales workflow state rules."""


FINANCIALLY_ACTIVE_SALE_STATES = frozenset({"confirmed", "finished"})
SALE_STATE_LABELS = {
    "on_hold": "On Hold", "pending": "Pending", "confirmed": "Confirmed", "finished": "Finished",
}


def is_financially_active(state):
    """Only confirmed workflow stages contribute to client debt and payments."""
    return str(state or "").strip().lower() in FINANCIALLY_ACTIVE_SALE_STATES


def sale_state_label(state):
    key = str(state or "pending").strip().lower()
    return SALE_STATE_LABELS.get(key, key.replace("_", " ").title())
