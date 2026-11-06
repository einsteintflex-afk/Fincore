from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.context import client_ip_var, request_id_var
from app.models.ops import AuditLog


def audit(db: Session, action: str, *, actor_id: uuid.UUID | None = None, actor_type: str = "user",
          target_type: str | None = None, target_id: Any = None, details: dict | None = None) -> AuditLog:
    """Append an audit record to the current DB transaction (committed with the business change)."""
    entry = AuditLog(
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        ip_address=client_ip_var.get(),
        request_id=request_id_var.get(),
        details=_jsonable(details or {}),
    )
    db.add(entry)
    return entry


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
