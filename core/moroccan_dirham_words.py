"""French words for Moroccan dirham amounts."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


_CENT = Decimal("0.01")
_UNITS = (
    "ZÉRO", "UN", "DEUX", "TROIS", "QUATRE", "CINQ", "SIX", "SEPT",
    "HUIT", "NEUF", "DIX", "ONZE", "DOUZE", "TREIZE", "QUATORZE",
    "QUINZE", "SEIZE",
)
_TENS = {
    20: "VINGT",
    30: "TRENTE",
    40: "QUARANTE",
    50: "CINQUANTE",
    60: "SOIXANTE",
}


def amount_to_words(amount: Decimal | int | str | float) -> str:
    """Return a non-negative Moroccan dirham amount in uppercase French words."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount must be a decimal number") from exc

    if not value.is_finite() or value < 0:
        raise ValueError("amount must be a non-negative finite number")

    value = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    dirhams = int(value)
    centimes = int((value - dirhams) * 100)

    result = f"{_number_to_words(dirhams)} {_currency_word(dirhams, 'DIRHAM')}"
    if centimes:
        result += f" ET {_number_to_words(centimes)} {_currency_word(centimes, 'CENTIME')}"
    return result


def _currency_word(amount: int, singular: str) -> str:
    return singular if amount in (0, 1) else f"{singular}S"


def _number_to_words(number: int, before_scale: bool = False) -> str:
    if number < 17:
        return _UNITS[number]
    if number < 20:
        return f"DIX-{_UNITS[number - 10]}"
    if number < 100:
        return _under_hundred(number, before_scale)
    if number < 1_000:
        return _under_thousand(number, before_scale)
    if number < 1_000_000:
        thousands, remainder = divmod(number, 1_000)
        prefix = "MILLE" if thousands == 1 else f"{_number_to_words(thousands, True)} MILLE"
        return prefix if not remainder else f"{prefix} {_number_to_words(remainder)}"

    millions, remainder = divmod(number, 1_000_000)
    scale = "MILLION" if millions == 1 else "MILLIONS"
    prefix = f"{_number_to_words(millions, True)} {scale}"
    return prefix if not remainder else f"{prefix} {_number_to_words(remainder)}"


def _under_hundred(number: int, before_scale: bool) -> str:
    if number < 70:
        tens, unit = divmod(number, 10)
        prefix = _TENS[tens * 10]
        if unit == 0:
            return prefix
        if unit == 1:
            return f"{prefix} ET UN"
        return f"{prefix}-{_UNITS[unit]}"
    if number < 80:
        if number == 71:
            return "SOIXANTE ET ONZE"
        return f"SOIXANTE-{_number_to_words(number - 60)}"
    if number == 80:
        return "QUATRE-VINGT" if before_scale else "QUATRE-VINGTS"
    return f"QUATRE-VINGT-{_number_to_words(number - 80)}"


def _under_thousand(number: int, before_scale: bool) -> str:
    hundreds, remainder = divmod(number, 100)
    if hundreds == 1:
        prefix = "CENT"
    else:
        prefix = f"{_UNITS[hundreds]} CENT"
        if remainder == 0 and not before_scale:
            prefix += "S"
    return prefix if not remainder else f"{prefix} {_number_to_words(remainder, before_scale)}"
