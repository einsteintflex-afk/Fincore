"""Ghana-specific helpers: phone numbers, mobile-money networks, Ghana Card, banks."""

from __future__ import annotations

import re

from app.core.errors import ValidationFailed
from app.models.enums import MobileNetwork

# National significant number prefixes (after the leading 0) by network.
# Source: NCA numbering plan; Telecel = former Vodafone Ghana, AT = former AirtelTigo.
NETWORK_PREFIXES: dict[str, MobileNetwork] = {
    "24": MobileNetwork.MTN, "25": MobileNetwork.MTN, "53": MobileNetwork.MTN,
    "54": MobileNetwork.MTN, "55": MobileNetwork.MTN, "59": MobileNetwork.MTN,
    "20": MobileNetwork.TELECEL, "50": MobileNetwork.TELECEL,
    "26": MobileNetwork.AT, "27": MobileNetwork.AT, "56": MobileNetwork.AT, "57": MobileNetwork.AT,
}

NETWORK_NAMES = {
    MobileNetwork.MTN: "MTN Mobile Money",
    MobileNetwork.TELECEL: "Telecel Cash",
    MobileNetwork.AT: "AT Money",
}

GHANA_CARD_RE = re.compile(r"^GHA-\d{9}-\d$")

# Subset of GhIPSS participant banks (bank_code is the platform's internal code).
BANKS: dict[str, str] = {
    "GCB": "GCB Bank",
    "ECO": "Ecobank Ghana",
    "SCB": "Standard Chartered Bank Ghana",
    "ABSA": "Absa Bank Ghana",
    "CAL": "CalBank",
    "FBN": "First Bank Ghana",
    "FID": "Fidelity Bank Ghana",
    "ZEN": "Zenith Bank Ghana",
    "STAN": "Stanbic Bank Ghana",
    "ADB": "Agricultural Development Bank",
    "NIB": "National Investment Bank",
    "UBA": "United Bank for Africa Ghana",
    "ACC": "Access Bank Ghana",
    "SG": "Societe Generale Ghana",
    "PRU": "Prudential Bank",
    "REP": "Republic Bank Ghana",
    "CBG": "Consolidated Bank Ghana",
    "OMNI": "OmniBSIC Bank",
    "UMB": "Universal Merchant Bank",
    "FAB": "First Atlantic Bank",
    "GTB": "Guaranty Trust Bank Ghana",
}


def normalize_msisdn(phone: str) -> str:
    """Return a Ghana mobile number in international format without '+', e.g. ``233241234567``."""
    digits = re.sub(r"[^\d]", "", phone or "")
    if digits.startswith("00233"):
        digits = digits[2:]
    if digits.startswith("233") and len(digits) == 12:
        nsn = digits[3:]
    elif digits.startswith("0") and len(digits) == 10:
        nsn = digits[1:]
    elif len(digits) == 9:
        nsn = digits
    else:
        raise ValidationFailed("Enter a valid Ghana phone number, e.g. 0241234567")
    if nsn[:2] not in NETWORK_PREFIXES:
        raise ValidationFailed("Unrecognised Ghana mobile network prefix")
    return "233" + nsn


def detect_network(phone: str) -> MobileNetwork:
    return NETWORK_PREFIXES[normalize_msisdn(phone)[3:5]]


def local_format(msisdn: str) -> str:
    return "0" + normalize_msisdn(msisdn)[3:]


def validate_ghana_card(number: str) -> str:
    n = number.strip().upper()
    if not GHANA_CARD_RE.match(n):
        raise ValidationFailed("Ghana Card number must look like GHA-123456789-0")
    return n


def validate_bank(bank_code: str, account_number: str) -> tuple[str, str]:
    code = bank_code.upper()
    if code not in BANKS:
        raise ValidationFailed("Unknown bank code")
    acct = re.sub(r"\s", "", account_number)
    if not acct.isdigit() or not 8 <= len(acct) <= 20:
        raise ValidationFailed("Bank account number must be 8-20 digits")
    return code, acct
