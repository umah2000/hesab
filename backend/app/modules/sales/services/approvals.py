"""Supervisor approval on a register (security/permissions.md, note ¹).

The supervisor types their own username and password on the cashier's screen. The
approval is single-use, short-lived and bound to one action on one register; both
the approval and its use are audited. Password failures count towards the
supervisor's lockout exactly like a login.
"""

from __future__ import annotations

import uuid
from datetime import UTC, timedelta

from sqlalchemy.orm import Session

from app.core.db import unit_of_work, utcnow
from app.core.errors import DomainError, PermissionDeniedError
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.iam.services.auth import GENERIC_LOGIN_ERROR, LoginFailedError, check_credentials
from app.modules.sales.models import SalesApproval
from app.modules.sales.schemas import ApprovalIn, ApprovalOut
from app.modules.sales.services.pricing import register_and_warehouse

APPROVAL_TTL = timedelta(minutes=3)
REQUIRED = {
    "line_delete": "sales.invoice.line_delete_after_scan",
    "discount_over_limit": "sales.invoice.discount_over_limit",
    "return": "sales.return.create",
}
LABEL = {
    "line_delete": "حذف ردیف",
    "discount_over_limit": "تخفیف بالاتر از سقف",
    "return": "برگشت از فروش",
}


def grant(actor: Actor, data: ApprovalIn) -> ApprovalOut:
    """Runs its own unit of work: failed attempts must be committed even though we raise."""
    result: ApprovalOut | None = None
    denied = False
    with unit_of_work() as s:
        reg, _ = register_and_warehouse(s, data.cash_register_id, actor.branch_ids)
        user = check_credentials(s, data.username, data.password, purpose="approval")
        if user is not None:
            perms = user.permission_codes
            if REQUIRED[data.action] not in perms or user.id == actor.user_id:
                audit.record(
                    s,
                    "sales.approval_denied",
                    user_id=actor.user_id,
                    branch_id=reg.branch_id,
                    data={"action": data.action, "approver": user.username},
                )
                denied = True
            else:
                a = SalesApproval(
                    action=data.action,
                    cash_register_id=reg.id,
                    requested_by=actor.user_id,
                    approved_by=user.id,
                    expires_at=utcnow() + APPROVAL_TTL,
                )
                s.add(a)
                s.flush()
                audit.record(
                    s,
                    "sales.approval_granted",
                    user_id=user.id,
                    branch_id=reg.branch_id,
                    entity_type="sales_approval",
                    entity_id=a.id,
                    data={"action": data.action, "cashier": actor.username, "register": reg.code},
                )
                result = ApprovalOut(
                    id=a.id,
                    action=a.action,
                    approved_by_name=user.full_name or user.username,
                    expires_at=a.expires_at,
                )
    if denied:
        raise PermissionDeniedError(
            f"این کاربر مجوز تأیید «{LABEL[data.action]}» را ندارد", code="approver_not_allowed"
        )
    if result is None:
        raise LoginFailedError(GENERIC_LOGIN_ERROR)
    return result


def consume(
    s: Session, actor: Actor, approval_id: uuid.UUID | None, action: str, register_id: uuid.UUID
) -> uuid.UUID:
    """Mark the approval used; returns the approver. Raises if missing, used or expired."""
    a = s.get(SalesApproval, approval_id, with_for_update=True) if approval_id else None
    if (
        a is None
        or a.action != action
        or a.cash_register_id != register_id
        or a.requested_by != actor.user_id
    ):
        raise DomainError(f"«{LABEL[action]}» نیازمند تأیید سرپرست است", code="approval_required")
    expires = a.expires_at if a.expires_at.tzinfo else a.expires_at.replace(tzinfo=UTC)
    if a.used_at is not None or expires <= utcnow():
        raise DomainError("تأیید سرپرست منقضی یا قبلاً استفاده شده است", code="approval_expired")
    a.used_at = utcnow()
    return a.approved_by
