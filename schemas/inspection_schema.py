from typing import Optional

from pydantic import BaseModel, Field

from models.enums import ChecklistType, ItemResult, SessionKind, SessionOutcome, SessionStatus
from schemas.common import ORMModel, UserBrief, UTCDateTime, user_brief


class AttachmentOut(ORMModel):
    id: int
    original_filename: str
    content_type: str
    size_bytes: int
    caption: Optional[str] = None
    ticket_id: Optional[int] = None
    repair_id: Optional[int] = None
    inspection_result_id: Optional[int] = None
    created_at: UTCDateTime
    url: str = ""


def attachment_out(att) -> AttachmentOut:
    out = AttachmentOut.model_validate(att)
    out.url = f"/api/v1/uploads/{att.id}"
    return out


class InspectionResultOut(BaseModel):
    id: int
    checklist_type: ChecklistType
    item_name: str
    description: Optional[str] = None
    category: str
    is_mandatory: bool
    allow_not_applicable: bool
    display_order: int
    reference_instructions: Optional[str] = None
    result: ItemResult
    remarks: Optional[str] = None
    inspector: Optional[UserBrief] = None
    inspected_at: Optional[UTCDateTime] = None
    attachments: list[AttachmentOut] = []


class Progress(BaseModel):
    required_total: int
    required_done: int
    percent: int
    failed: int


class InspectionSessionOut(BaseModel):
    id: int
    ticket_id: Optional[int] = None
    repair_id: Optional[int] = None
    kind: SessionKind
    round_number: int
    is_reclean: bool
    status: SessionStatus
    outcome: Optional[SessionOutcome] = None
    inspector: Optional[UserBrief] = None
    started_at: UTCDateTime
    submitted_at: Optional[UTCDateTime] = None
    notes: Optional[str] = None
    progress: Progress
    results: list[InspectionResultOut]


class ResultUpdate(BaseModel):
    result_id: int
    result: ItemResult
    remarks: Optional[str] = Field(default=None, max_length=2000)
    attachment_ids: Optional[list[int]] = None


class ChecklistSaveRequest(BaseModel):
    items: list[ResultUpdate] = []


class EngineeringChecklistSaveRequest(ChecklistSaveRequest):
    diagnosis: Optional[str] = Field(default=None, max_length=5000)
    repair_notes: Optional[str] = Field(default=None, max_length=5000)


def compute_progress(results) -> Progress:
    required = [r for r in results if r.is_mandatory]
    done = [r for r in required if r.result != ItemResult.PENDING]
    failed = sum(1 for r in results if r.result == ItemResult.FAIL)
    total = len(required)
    percent = int(round(100 * len(done) / total)) if total else (100 if results else 0)
    return Progress(required_total=total, required_done=len(done), percent=percent, failed=failed)


def result_out(r) -> InspectionResultOut:
    return InspectionResultOut(
        id=r.id,
        checklist_type=r.checklist_type,
        item_name=r.item_name,
        description=r.description,
        category=r.category,
        is_mandatory=r.is_mandatory,
        allow_not_applicable=r.allow_not_applicable,
        display_order=r.display_order,
        reference_instructions=r.reference_instructions,
        result=r.result,
        remarks=r.remarks,
        inspector=user_brief(r.inspector),
        inspected_at=r.inspected_at,
        attachments=[attachment_out(a) for a in r.attachments],
    )


def session_out(s) -> InspectionSessionOut:
    return InspectionSessionOut(
        id=s.id,
        ticket_id=s.ticket_id,
        repair_id=s.repair_id,
        kind=s.kind,
        round_number=s.round_number,
        is_reclean=s.is_reclean,
        status=s.status,
        outcome=s.outcome,
        inspector=user_brief(s.inspector),
        started_at=s.started_at,
        submitted_at=s.submitted_at,
        notes=s.notes,
        progress=compute_progress(s.results),
        results=[result_out(r) for r in s.results],
    )
