"""Audit log for every write performed through the API. Detail must never contain PII."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AuditLog, User


def record_audit(
    db: Session,
    *,
    user: User | None,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    detail: dict | None = None,
    request_id: str = "",
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        role=user.role if user else "anonymous",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else "",
        detail=detail or {},
        request_id=request_id,
    )
    db.add(entry)
    db.flush()
    return entry
