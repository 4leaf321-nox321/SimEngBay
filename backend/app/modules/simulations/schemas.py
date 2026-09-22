"""해석 작업 API 형태."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StageOut(BaseModel):
    name: str
    status: str
    """pending · running · done · failed · skipped"""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    detail: str = ""
    error_code: str | None = None
    error_message: str | None = None


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stage: str
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class SimulationSummaryOut(BaseModel):
    """목록 한 줄. 스펙 · 단계 · 산출물은 싣지 않는다 — 50줄에 그것까지 실으면 목록이
    무겁다."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    recipe: str
    status: str
    source_kind: str
    source_ref: str
    owner_workspace_id: uuid.UUID | None
    owner_workspace_name: str | None
    requested_by_id: uuid.UUID | None
    requested_by_name: str | None
    error_code: str | None
    summary: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SimulationOut(SimulationSummaryOut):
    spec: dict[str, Any]
    stages: list[StageOut]
    error_message: str | None
    artifacts: list[ArtifactOut]
    attempts: int
    worker_id: str | None


class SimulationCreateForm(BaseModel):
    """multipart 의 글자 칸들. 파일은 따로 온다(`file`)."""

    spec: dict[str, Any]
    """`app/core/spec.py` 의 JobSpec — 라우트가 JSON 문자열로 받아 여기 넣는다."""
    workspace_slug: str | None = None
    name: str | None = Field(default=None, max_length=120)


class RecipeOut(BaseModel):
    """화면이 새 작업 폼을 그리는 데 쓰는 레시피 목록과 JSON 스키마."""

    name: str
    runnable: bool
    schema_: dict[str, Any] = Field(alias="schema")
    model_config = ConfigDict(populate_by_name=True)
