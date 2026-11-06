"""Money helpers. All monetary values are ``decimal.Decimal`` – never float."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.errors import ValidationFailed

# ISO-4217 code -> number of minor-unit digits.
CURRENCY_EXPONENTS: dict[str, int] = {
    "GHS": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "NGN": 2,
    "KES": 2,
    "XOF": 0,
}

ZERO = Decimal("0")


def exponent(currency: str) -> int:
    try:
        return CURRENCY_EXPONENTS[currency]
    except KeyError as exc:
        raise ValidationFailed(f"Unsupported currency: {currency}") from exc


def quantum(currency: str) -> Decimal:
    return Decimal(1).scaleb(-exponent(currency))


def to_decimal(value: object) -> Decimal:
    if isinstance(value, float):
        raise TypeError("float is not allowed for money; pass str or Decimal")
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationFailed(f"Invalid amount: {value!r}") from exc


def round_money(value: object, currency: str) -> Decimal:
    """Round half-up to the currency's minor unit (used for computed amounts such as fees)."""
    return to_decimal(value).quantize(quantum(currency), rounding=ROUND_HALF_UP)


def validate_amount(value: object, currency: str, *, allow_zero: bool = False) -> Decimal:
    """Validate a user-supplied amount: positive, finite and no more precision than the currency allows."""
    d = to_decimal(value)
    if not d.is_finite():
        raise ValidationFailed("Amount must be finite")
    if d < 0 or (d == 0 and not allow_zero):
        raise ValidationFailed("Amount must be greater than zero")
    if d != d.quantize(quantum(currency)):
        raise ValidationFailed(f"{currency} amounts allow at most {exponent(currency)} decimal places")
    if d > Decimal("1000000000000"):
        raise ValidationFailed("Amount too large")
    return d.quantize(quantum(currency))


def fmt(value: Decimal, currency: str) -> str:
    return f"{currency} {round_money(value, currency):,}"
