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
    source_meta: dict[str, Any]
    """DOE 면 스터디 · 점 번호 · 바꾼 변수. 비교 화면이 이것으로 묶는다."""
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


class DoePointPreview(BaseModel):
    """가져오기 전에 보여 줄 한 줄 — **걸 수 있나, 아니면 왜 못 거나.**"""

    number: int
    params: dict[str, float]
    usable: bool
    skip_reason: str = ""


class DoePreviewOut(BaseModel):
    """폴더를 훑어 본 결과.

    **먼저 보여 주고 나서 건다** — 200개를 잘못 걸면 되돌리기 어렵다.
    """

    path: str
    study_id: str
    name: str
    factors: list[str]
    method: str = ""
    seed: int | None = None
    points: list[DoePointPreview]
    usable: int
    skipped: int


class DoeImportRequest(BaseModel):
    path: str = Field(min_length=1)
    """서버가 볼 수 있는 폴더 경로. **브라우저가 파일을 올리는 것이 아니다** — 설계점 200개면
    STEP 만 수십 MB 이고, 그 폴더는 대개 공유 스토리지에 있다."""
    spec: dict[str, Any]
    """모든 점에 같은 스펙을 쓴다. 물성 · 모드 수 · 구속 영역 이름이 여기 들어간다."""
    workspace_slug: str | None = None
    numbers: list[int] | None = None
    """고른 점만. 비우면 걸 수 있는 전부."""


class DoeImportOut(BaseModel):
    study_id: str
    name: str
    created: list[uuid.UUID]
    skipped: list[DoePointPreview]


class StudySummaryOut(BaseModel):
    """DOE 한 벌 — 목록 한 줄."""

    study_id: str
    name: str
    factors: list[str]
    points: int
    done: int
    failed: int
    running: int
    workspace_name: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class StudyPointOut(BaseModel):
    """설계점 하나 — **바꾼 값과 그 결과를 한 줄에.** 비교는 이 줄들을 견주는 일이다."""

    simulation_id: uuid.UUID
    number: int
    params: dict[str, float]
    status: str
    error_code: str | None = None
    first_elastic_hz: float | None = None
    mass_kg: float | None = None
    nodes: int | None = None
    frequencies: list[float] = Field(default_factory=list)
    """탄성 모드 주파수(앞에서부터). `k` 차 모드로 견주려면 이것이 있어야 한다."""


class StudyOut(BaseModel):
    study_id: str
    name: str
    factors: list[str]
    points: list[StudyPointOut]


class RecipeOut(BaseModel):
    """화면이 새 작업 폼을 그리는 데 쓰는 레시피 목록과 JSON 스키마."""

    name: str
    runnable: bool
    schema_: dict[str, Any] = Field(alias="schema")
    model_config = ConfigDict(populate_by_name=True)
