import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from core.permissions import require_any
from database.connection import get_db
from models.user import User
from schemas.inspection_schema import AttachmentOut, attachment_out
from services import upload_service

router = APIRouter(prefix="/api/v1/uploads", tags=["Uploads"])


@router.post("", response_model=AttachmentOut, status_code=201)
async def upload(file: UploadFile = File(...), ticket_id: Optional[int] = Form(None), repair_id: Optional[int] = Form(None),
                 caption: Optional[str] = Form(None), user: User = Depends(require_any), db: Session = Depends(get_db)):
    """Upload a JPEG, PNG, WebP or PDF (size limit MAX_UPLOAD_MB). The file type is checked from its content."""
    return attachment_out(await upload_service.save_upload(db, user, file, ticket_id, repair_id, caption))


@router.get("/{attachment_id}")
def download(attachment_id: int, user: User = Depends(require_any), db: Session = Depends(get_db)):
    att, path = upload_service.get_for_download(db, user, attachment_id)
    return FileResponse(path, media_type=att.content_type,
                        headers={"Content-Disposition": f'inline; filename="attachment-{att.id}{os.path.splitext(att.stored_filename)[1]}"',
                                 "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"})
