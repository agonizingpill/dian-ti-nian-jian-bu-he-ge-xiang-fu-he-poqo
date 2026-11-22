"""Weekly leaf-node distribution and sealed weekly report endpoints."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from . import weekly_report
from .auth import current_user, require_roles

router = APIRouter(prefix="/api/weekly-leaf-report", tags=["周叶节点分布"])


class FreezeIn(BaseModel):
    week: str = Field(min_length=1, max_length=10)


@router.get("/model")
def model(user=Depends(current_user)):
    return weekly_report.model_catalog()


@router.get("")
def report(week: str | None = Query(None, max_length=10), user=Depends(current_user)):
    return weekly_report.build_report(week)


@router.post("/snapshot", status_code=201)
def snapshot(payload: FreezeIn, user=Depends(require_roles("supervisor"))):
    return weekly_report.freeze_week(payload.week, user)


@router.get("/snapshot")
def snapshots(user=Depends(current_user)):
    return weekly_report.list_snapshots()
