"""Settings → Users: the private dashboard team (at most 15 accounts including the primary administrator)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.common import InviteIn, ReasonIn, RoleIn, UserOut
from app.services import team

router = APIRouter(prefix="/admin/team", tags=["Settings: users (dashboard seats)"])


def _out(u: User) -> dict:
    return {**UserOut.model_validate(u).model_dump(), "deactivated_at": u.deactivated_at}


@router.get("")
def list_team(user: User = Depends(current_user), db: Session = Depends(get_db)):
    team._ensure_manager(user)
    return {"seats": team.seat_summary(db), "users": [_out(u) for u in team.list_team(db)],
            "roles": sorted(team.ASSIGNABLE_ROLES)}


@router.post("/invitations", status_code=201)
def invite(body: InviteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Reserve a seat and create an invitation. The returned link is also emailed; share it privately."""
    invited, link = team.invite(db, user, email=body.email, full_name=body.full_name, role=body.role, phone=body.phone)
    return {"user": _out(invited), "invitation_link": link, "seats": team.seat_summary(db)}


@router.post("/{user_id}/invitation/resend")
def resend(user_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"invitation_link": team.resend_invitation(db, user, user_id)}


@router.post("/{user_id}/deactivate")
def deactivate(user_id: uuid.UUID, body: ReasonIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"user": _out(team.deactivate(db, user, user_id, body.reason)), "seats": team.seat_summary(db)}


@router.post("/{user_id}/activate")
def activate(user_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"user": _out(team.activate(db, user, user_id)), "seats": team.seat_summary(db)}


@router.post("/{user_id}/remove")
def remove(user_id: uuid.UUID, body: ReasonIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"user": _out(team.remove(db, user, user_id, body.reason)), "seats": team.seat_summary(db)}


@router.post("/{user_id}/role")
def change_role(user_id: uuid.UUID, body: RoleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _out(team.change_role(db, user, user_id, body.role))


@router.post("/{user_id}/sessions/revoke")
def revoke_sessions(user_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"revoked": team.revoke_sessions(db, user, user_id)}


@router.get("/{user_id}/activity")
def activity(user_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return team.activity(db, user, user_id)
