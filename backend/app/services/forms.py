"""Custom payer questions on payment links (e.g. programme, index number) and receipt verification codes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from datetime import date

from app.core.config import settings
from app.core.errors import ValidationFailed
from app.services.ghana import normalize_msisdn

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalise_fields(fields: list[dict]) -> list[dict]:
    """Give each question a stable key and validate select options."""
    out, keys = [], set()
    for f in fields:
        label = f["label"].strip()
        key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40] or "field"
        base, n = key, 2
        while key in keys:
            key, n = f"{base}_{n}", n + 1
        keys.add(key)
        options = [o.strip() for o in f.get("options") or [] if o.strip()]
        if f.get("type") == "select" and len(options) < 2:
            raise ValidationFailed(f"'{label}' needs at least two options")
        out.append({"key": key, "label": label, "type": f.get("type", "text"), "required": bool(f.get("required", True)),
                    "options": options})
    return out


def validate_answers(fields: list[dict], answers: dict[str, str]) -> list[dict]:
    """Return ``[{label, value, type}]`` in question order, or raise a payer-friendly error."""
    result = []
    for f in fields:
        value = (answers.get(f["key"]) or "").strip()[:200]
        if not value:
            if f["required"]:
                raise ValidationFailed(f"Please fill in: {f['label']}", details={"field": f["key"]})
            continue
        t = f["type"]
        try:
            if t == "phone":
                value = "0" + normalize_msisdn(value)[3:]
            elif t == "email" and not EMAIL_RE.match(value):
                raise ValueError
            elif t == "number" and not re.fullmatch(r"-?\d+(\.\d+)?", value):
                raise ValueError
            elif t == "date":
                date.fromisoformat(value)
            elif t == "select" and value not in f["options"]:
                raise ValueError
        except (ValueError, ValidationFailed) as exc:
            raise ValidationFailed(f"Please check: {f['label']}", details={"field": f["key"]}) from exc
        result.append({"label": f["label"], "value": value, "type": t})
    return result


def receipt_code(reference: str) -> str:
    """Short code printed on receipts; only FinCore can produce it (HMAC with the platform secret)."""
    mac = hmac.new(settings.secret_key.encode(), f"receipt:{reference}".encode(), hashlib.sha256).digest()
    code = base64.b32encode(mac[:6]).decode().rstrip("=")
    return f"{code[:5]}-{code[5:10]}"


def check_receipt_code(reference: str, code: str) -> bool:
    def clean(c: str) -> str:
        return c.strip().upper().replace(" ", "").replace("-", "")
    return hmac.compare_digest(clean(receipt_code(reference)), clean(code))
