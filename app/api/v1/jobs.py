"""Read-only ingestion-job status endpoint, scoped to the job creator."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.models import IngestionJob, User
from app.db.session import get_db

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}")
def get_job_status(
    job_id: uuid.UUID,
    session: Session = Depends(get_db),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, str | None]:
    """Return status only for jobs created by the authenticated user."""
    job = session.get(IngestionJob, job_id)
    if job is None or job.created_by != user.user_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": "The requested job is unavailable."},
        )
    return {
        "job_id": str(job.job_id),
        "job_type": job.job_type,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error_summary": job.error_summary,
    }
