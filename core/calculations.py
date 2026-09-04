"""Authoritative monetary and quantity calculation helpers.

Every quantity/price that flows into a line subtotal, Remise, Total
is normalized through :func:`to_decimal` first, so a value may
arrive as a ``Decimal``, ``int``, ``float``, numeric ``str`` (including a
comma decimal separator and thousands separators), empty string, or ``None``
and still be combined without ever performing ``Decimal`` arithmetic with a
raw ``float``.

Float inputs are converted with ``Decimal(str(value))`` - never
``Decimal(value)`` - so the decimal representation round-trips exactly instead
of inheriting the binary floating point approximation. Monetary arithmetic
stays in ``Decimal`` until the final result; floats are only produced for
display by the callers.

If a financial calculation fails the full traceback plus the input values and
their types are logged and the exception is re-raised: a bad calculation must
surface loudly instead of silently showing 0.00.
"""

import logging
import traceback
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from enum import Enum

logger = logging.getLogger(__name__)

class InputState(Enum):
    VALID = "VALID"
    EMPTY = "EMPTY"
    INTERMEDIATE = "INTERMEDIATE"
    INVALID = "INVALID"

_PENNY = Decimal("0.01")


def to_decimal(value):
    """Safely normalize a quantity/monetary input to ``Decimal``.

    Accepts ``Decimal``, ``int``, ``float``, numeric ``str`` (with commas and
    spaces optionally used as separators), empty string, and ``None``.
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        if isinstance(value, str):
            normalized = value.replace(" ", "").replace(",", ".")
        else:
            normalized = str(value)
        return Decimal(normalized or "0")
    except Exception as error:
        logger.error(
            "Invalid monetary/quantity input value=%r type=%s error=%s",
            value, type(value).__name__, error,
        )
        traceback.print_exc()
        raise


def parse_decimal_input(value):
    """Safely parse a raw UI string input into a Decimal and state.

    Returns (InputState, Decimal).

    Handles normal inputs, spaces, commas, empty, and intermediate editing
    states (e.g. "-", ".", ","). Never raises InvalidOperation on intermediate
    or empty inputs.
    """
    if value is None:
        return InputState.EMPTY, Decimal("0")
    if isinstance(value, Decimal):
        return InputState.VALID, value

    # Convert to string if not already
    try:
        text = str(value).strip()
    except (ValueError, TypeError):
        return InputState.INVALID, Decimal("0")

    if not text:
        return InputState.EMPTY, Decimal("0")

    # Intermediate states that shouldn't crash or evaluate to 0 permanently,
    # but the user might just be in the middle of typing.
    intermediate_exact = {"-", "+", ".", ",", "-.", "-,", "+.", "+,"}
    if text in intermediate_exact:
        return InputState.INTERMEDIATE, Decimal("0")
        
    if text.endswith(".") or text.endswith(","):
        prefix = text[:-1].replace(" ", "").replace(",", ".")
        try:
            Decimal(prefix)
            return InputState.INTERMEDIATE, Decimal("0")
        except (InvalidOperation, ValueError, TypeError):
            pass

    # Normalize spaces and commas
    normalized = text.replace(" ", "").replace(",", ".")

    try:
        dec = Decimal(normalized)
        return InputState.VALID, dec
    except (InvalidOperation, ValueError, TypeError):
        return InputState.INVALID, Decimal("0")


def round_money(value):
    """Round a monetary value to two decimal places (project policy)."""
    return to_decimal(value).quantize(_PENNY, rounding=ROUND_HALF_UP)


def calculate_line_subtotal(quantity, unit_price):
    """Line total: ``quantity * unit_price`` at full ``Decimal`` precision."""
    qty = to_decimal(quantity)
    price = to_decimal(unit_price)
    try:
        return qty * price
    except Exception as error:
        logger.error(
            "Line subtotal failed quantity=%r type=%s unit_price=%r type=%s error=%s",
            quantity, type(quantity).__name__,
            unit_price, type(unit_price).__name__, error,
        )
        traceback.print_exc()
        raise


def calculate_operation_totals(raw_subtotal, remise=0):
    """Subtotal / Remise / Total for an operation (no VAT).

    Formulas:
        original_subtotal = sum(quantity * unit_price)
        total             = original_subtotal - remise

    Final monetary values are quantized to two decimal places with
    ``ROUND_HALF_UP``. All values returned are ``Decimal``.
    """
    original = round_money(raw_subtotal)
    discount = round_money(remise)
    try:
        total = round_money(original - discount)
    except Exception as error:
        logger.error(
            "Operation totals failed raw_subtotal=%r type=%s remise=%r "
            "type=%s error=%s",
            raw_subtotal, type(raw_subtotal).__name__,
            remise, type(remise).__name__, error,
        )
        traceback.print_exc()
        raise
    return {
        "original_subtotal": original,
        "remise": discount,
        "total": total,
    }
