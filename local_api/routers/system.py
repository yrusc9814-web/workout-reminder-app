"""Phase 4.3 — System status router."""

import logging
from fastapi import APIRouter, Request

from ..database import get_db
from ..models import SystemStatusResponse

router = APIRouter(prefix="/api/system", tags=["system"])
logger = logging.getLogger("local_api.system")


@router.get("/status", response_model=SystemStatusResponse)
def get_status(request: Request):
    """Return API version, DB connectivity, and task count."""
    conn = get_db()
    try:
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM tasks")
        count = cursor.fetchone()["cnt"]
        db_connected = True
    except Exception:
        count = 0
        db_connected = False
        logger.exception("DB connectivity check failed")

    return SystemStatusResponse(
        status="ok",
        api_version="4.3.0",
        db_connected=db_connected,
        task_count=count,
    )
