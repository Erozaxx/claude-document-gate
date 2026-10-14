"""Local, conservative regex pseudonymization; NOT a complete PII guardrail.

The regexes prefer redacting plausible sensitive identifiers over requiring
checksums (which deliberately fails for some sample/test data).

Real processing passes a secret key so deterministic markers are HMAC based,
not dictionary-attackable truncated hashes of small phone-number spaces.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re

# Increment for any change to the redaction semantics: prevents old cached
# files from being treated as newly sanitized without reprocessing.
SANITIZER_VERSION = 3

# ISO 13616 national IBAN lengths (including non-EU participants). Deliberately
# use the structural lengths rather than checksum validity for DLP purposes.
IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20,
    "BE": 16, "BG": 22, "BH": 22, "BI": 27, "BR": 29, "BY": 28,
    "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DJ": 27,
    "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18,
    "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18,
    "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22, "IL": 23,
    "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20,
    "LB": 28, "LC": 32, "LI": 21, "LT": 20, "LU": 20, "LV": 21,
    "LY": 25, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MN": 20,
    "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15, "PK": 24,
    "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22,
    "SA": 24, "SC": 31, "SD": 18, "SE": 24, "SI": 19, "SK": 24,
    "SM": 27, "SO": 23, "ST": 25, "SV": 28, "TL": 23, "TN": 24,
    "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20,
}

# By matching the expected national length we avoid cutting off a short piece
# of a longer string, or swallowing a merchant name after a spaced IBAN.
_iban_alternatives = "|".join(
    rf"{country}[0-9]{{2}}(?:[ \t]*[A-Z0-9]){{{length - 4}}}"
    for country, length in IBAN_LENGTHS.items()
)
IBAN_PATTERN = re.compile(
    rf"(?<![A-Z0-9])(?:{_iban_alternatives})(?![A-Z0-9])", re.IGNORECASE
)

PHONE_INTL_PATTERN = re.compile(
    # Examples: +420 731 456 789, 00420-731-456-789, +44 (20) 1234 5678
    r"(?<![A-Z0-9+])(?:\+|00)[1-9][0-9]{0,2}(?:[ \t().-]*[0-9]){6,12}(?![A-Z0-9])",
    re.IGNORECASE,
)
PHONE_CZ_PATTERN = re.compile(
    # 9-digit Czech numbers, including 731456789, 731 456 789 or 222-333-444.
    r"(?<![A-Z0-9+])(?:[2-9][0-9]{2})(?:[ \t.-]?[0-9]{3}){2}(?![A-Z0-9]|\.[0-9])",
    re.IGNORECASE,
)

PATTERNS = (
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # Sensitive bank IDs before phones: the latter can occur inside grouping.
    ("IBAN", IBAN_PATTERN),
    ("IPV4", re.compile(r"(?<![A-Za-z0-9_.])(?:\d{1,3}\.){3}\d{1,3}(?![A-Za-z0-9_.])")),
    ("PHONE", PHONE_INTL_PATTERN),
    ("PHONE", PHONE_CZ_PATTERN),
    ("CZ_RC", re.compile(r"(?<!\d)\d{6}/?\d{3,4}(?!\d)")),
    ("BEARER", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_\-\.~=+/]{10,}")),
    ("API_KEY", re.compile(r"(?i)\b(?:sk-ant-[\w\-]{10,}|sk-[\w\-]{15,}|gh[pousr]_[\w]{20,}|AKIA[A-Z0-9]{16})\b")),
)


def _valid(kind: str, value: str) -> bool:
    if kind == "IPV4":
        try:
            return isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
        except ValueError:
            return False
    if kind == "PHONE":
        digits = re.sub(r"\D", "", value)
        if value.startswith("00"):
            digits = digits[2:]
        return (8 <= len(digits) <= 15) if value.startswith(("+", "00")) else len(digits) == 9
    if kind == "IBAN":
        compact = re.sub(r"[ \t]", "", value).upper()
        return len(compact) == IBAN_LENGTHS.get(compact[:2])
    return True


def _canonical(kind: str, value: str) -> str:
    if kind == "IBAN":
        return re.sub(r"[ \t]", "", value).upper()
    if kind == "PHONE":
        digits = re.sub(r"\D", "", value)
        if value.startswith("00"):
            digits = digits[2:]
        if not value.startswith(("+", "00")) and len(digits) == 9:
            digits = "420" + digits
        return "+" + digits
    return value


def sanitize(text: str, *, key: bytes | None = None) -> tuple[str, dict[str, int]]:
    """Return redacted text and per-type counts.

    Callers handling real data should supply a private, persistent HMAC key.
    Keyless mode is retained for standalone testing (not privacy-safe against
    brute-force of phone-number/IBAN dictionaries).
    """
    counts: dict[str, int] = {}
    for kind, pattern in PATTERNS:
        def repl(match: re.Match[str]) -> str:
            value = match.group(0)
            if not _valid(kind, value):
                return value
            counts[kind] = counts.get(kind, 0) + 1
            canonical = f"{kind}:{_canonical(kind, value)}".encode("utf-8")
            if key is not None:
                digest = hmac.new(key, canonical, hashlib.sha256).hexdigest()
            else:
                digest = hashlib.sha256(canonical).hexdigest()
            return f"[REDACTED_{kind}_{digest[:10]}]"
        text = pattern.sub(repl, text)
    return text, counts
