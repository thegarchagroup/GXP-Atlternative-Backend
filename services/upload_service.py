import os
import uuid
from typing import Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from core.config import settings
from core.exceptions import ForbiddenError, NotFoundError, ValidationFailedError
from models.enums import Department, Role, SessionKind
from models.inspection import Attachment, AttachmentFile
from models.user import User
from repositories import turnover_repository
from services import audit_service
from services import turnover_service as wf

ALLOWED = {
    "image/jpeg": (".jpg", [b"\xff\xd8\xff"]),
    "image/png": (".png", [b"\x89PNG\r\n\x1a\n"]),
    "image/webp": (".webp", [b"RIFF"]),
    "application/pdf": (".pdf", [b"%PDF-"]),
}


def _sniff(head: bytes) -> Optional[str]:
    for ctype, (_, sigs) in ALLOWED.items():
        if any(head.startswith(sig) for sig in sigs):
            if ctype == "image/webp" and head[8:12] != b"WEBP":
                continue
            return ctype
    return None


def _can_touch_ticket(user: User, ticket) -> bool:
    if user.department == Department.FRONT_DESK:
        return True
    if user.department == Department.HOUSEKEEPING:
        return ticket.assigned_housekeeper_id == user.id
    if user.department == Department.ENGINEERING:
        return any(r.assigned_engineer_id == user.id for r in ticket.repairs)
    return False


async def save_upload(db: Session, user: User, file: UploadFile, ticket_id: Optional[int], repair_id: Optional[int],
                      caption: Optional[str]) -> Attachment:
    ticket = None
    if repair_id is not None:
        repair = turnover_repository.get_repair(db, repair_id)
        if not repair:
            raise NotFoundError("Repair request not found.")
        ticket = repair.ticket
        if ticket_id is not None and ticket_id != ticket.id:
            raise ValidationFailedError("Repair does not belong to that ticket.")
    elif ticket_id is not None:
        ticket = wf.get_ticket(db, ticket_id)
    if ticket is not None and not _can_touch_ticket(user, ticket):
        raise ForbiddenError("You cannot upload files to this ticket.")
    if repair_id is not None and ticket is None and not (
            user.department == Department.FRONT_DESK or repair.assigned_engineer_id == user.id):
        raise ForbiddenError("You cannot upload files to this repair.")

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValidationFailedError(f"File is larger than {settings.MAX_UPLOAD_MB} MB.", code="FILE_TOO_LARGE")
    if not data:
        raise ValidationFailedError("File is empty.", code="FILE_EMPTY")
    ctype = _sniff(data[:16])
    if ctype is None:
        raise ValidationFailedError("Only JPEG, PNG, WebP images and PDF files are allowed.", code="FILE_TYPE")

    stored = f"{uuid.uuid4().hex}{ALLOWED[ctype][0]}"
    original = os.path.basename(file.filename or "upload")[:255]
    att = Attachment(original_filename=original, stored_filename=stored, content_type=ctype, size_bytes=len(data),
                     uploaded_by_id=user.id, ticket_id=ticket.id if ticket else None, repair_id=repair_id,
                     caption=(caption or None))
    att.file = AttachmentFile(data=data)
    db.add(att)
    db.flush()
    audit_service.log(db, actor=user, action="ATTACHMENT_UPLOADED", entity_type="attachment", entity_id=att.id,
                      ticket_id=att.ticket_id, repair_id=repair_id, message=f"Uploaded {original}")
    db.commit()
    return att


def get_for_download(db: Session, user: User, attachment_id: int) -> tuple[Attachment, bytes]:
    att = db.get(Attachment, attachment_id)
    if not att:
        raise NotFoundError("File not found.")
    allowed = (user.department == Department.FRONT_DESK or att.uploaded_by_id == user.id
               or user.role in (Role.HK_SUPERVISOR, Role.ENG_SUPERVISOR))
    if not allowed and not att.ticket_id and att.repair_id and user.department == Department.ENGINEERING:
        allowed = True
    if not allowed and att.ticket_id:
        ticket = wf.get_ticket(db, att.ticket_id)
        if user.department == Department.ENGINEERING:
            allowed = len(ticket.repairs) > 0
        elif user.department == Department.HOUSEKEEPING:
            allowed = wf.can_view_ticket(user, ticket)
    if not allowed:
        raise ForbiddenError("You cannot view this file.")
    if att.file is not None:
        return att, att.file.data
    # Older uploads saved on disk before files moved into the database
    path = os.path.join(settings.UPLOAD_DIR, att.stored_filename)
    if os.path.isfile(path):
        with open(path, "rb") as fh:
            return att, fh.read()
    raise NotFoundError("This file is not in the database, and the original upload is not on this computer.",
                        code="FILE_MISSING")


def import_files_from_disk(db: Session) -> tuple[int, int]:
    """Copy uploads saved as files (older versions) into the database. Safe to run repeatedly:
    only attachments that have no stored bytes yet are touched, and files on disk are left in place.
    Returns (imported, still_missing)."""
    from sqlalchemy import select

    pending = list(db.scalars(select(Attachment).outerjoin(AttachmentFile, AttachmentFile.attachment_id == Attachment.id)
                              .where(AttachmentFile.attachment_id.is_(None))).unique().all())
    imported = missing = 0
    for att in pending:
        path = os.path.join(settings.UPLOAD_DIR, att.stored_filename)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                att.file = AttachmentFile(data=fh.read())
            imported += 1
            db.commit()  # one at a time keeps each write small over a remote connection
        else:
            missing += 1
    return imported, missing
