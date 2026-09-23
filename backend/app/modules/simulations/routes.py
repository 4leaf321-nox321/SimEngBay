"""해석 작업 라우터 — 걸기 · 목록 · 상세 · 상태 폴링 · 산출물 · 재시도.

`POST /simulations` 는 multipart 다 — 형상 파일과 스펙(JSON 문자열)이 한 요청에 온다. 오케스트
(PAT, `simulations:write`)와 화면이 같은 경로를 쓴다.

`GET /simulations/{id}/status` 는 **폴링용**이다. 상세와 같은 것을 돌려주지만 접근 로그에 안
(`shared/access_log.py` `_SKIP`) — 안 그러면 로그가 2초마다 한 줄씩 그것으로 찬다.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.accounts.models import User
from app.modules.simulations import services
from app.modules.simulations.schemas import (
    DoeImportOut,
    DoeImportRequest,
    DoePreviewOut,
    RecipeOut,
    SimulationOut,
    SimulationSummaryOut,
)
from app.shared.auth import current_user
from app.shared.errors import AppError, code
from app.shared.pagination import Page, clamp_limit

router = APIRouter(prefix="/simulations", tags=["simulations"])


@router.get("/recipes", response_model=list[RecipeOut])
def recipes(user: User = Depends(current_user)) -> list[RecipeOut]:
    """레시피 목록과 각 스펙의 JSON 스키마. 화면이 폼을 그리는 근거다."""
    return services.recipes()


@router.post("", response_model=SimulationOut, status_code=201)
def create(
    spec: str = Form(description="JobSpec JSON (app/core/spec.py)"),
    workspace_slug: str | None = Form(default=None),
    name: str | None = Form(default=None, max_length=120),
    upload_file: UploadFile = File(alias="file"),
    topology_file: UploadFile | None = File(default=None, alias="topology"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SimulationOut:
    """형상(STEP)과, 구속을 걸 거라면 CAD 가 보낸 `topology.json` 을 함께 받는다."""
    try:
        spec_raw: Any = json.loads(spec)
    except json.JSONDecodeError as failure:
        raise AppError(
            code("SIMULATIONS", 1), f"스펙이 JSON 이 아닙니다: {failure.msg}", status=400
        ) from failure
    if not isinstance(spec_raw, dict):
        raise AppError(code("SIMULATIONS", 1), "스펙은 JSON 객체여야 합니다.", status=400)
    simulation = services.create(
        db,
        user=user,
        spec_raw=spec_raw,
        workspace_slug=workspace_slug,
        name=name,
        filename=upload_file.filename or "input.step",
        stream=upload_file.file,
        topology=topology_file.file.read() if topology_file is not None else None,
    )
    return services.to_out(db, simulation)


@router.get("/doe/preview", response_model=DoePreviewOut)
def preview_doe(
    path: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DoePreviewOut:
    """DOE 폴더를 훑어 본다 — **걸기 전에** 점 몇 개, 변수 무엇, 건너뛸 것 몇 개인지.

    폴더는 **서버가 보는 경로**다(공유 스토리지). 브라우저가 파일을 올리는 것이 아니다 —
    설계점 200개면 STEP 만 수십 MB 다.
    """
    return services.preview_doe(path)


@router.post("/doe/import", response_model=DoeImportOut, status_code=201)
def import_doe(
    body: DoeImportRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DoeImportOut:
    """폴더 한 벌을 해석 작업 N 개로. 걸 수 없는 점은 **이유와 함께** 돌려준다."""
    return services.import_doe(
        db,
        user=user,
        path_text=body.path,
        spec_raw=body.spec,
        workspace_slug=body.workspace_slug,
        numbers=body.numbers,
    )


@router.get("", response_model=Page[SimulationSummaryOut])
def list_simulations(
    status: str | None = None,
    workspace_slug: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[SimulationSummaryOut]:
    size = clamp_limit(limit)
    rows, total = services.list_visible(
        db,
        user=user,
        status=status,
        workspace_slug=workspace_slug,
        limit=size,
        offset=max(0, offset),
    )
    return Page(
        items=[services.to_summary(db, one) for one in rows],
        total=total,
        limit=size,
        offset=max(0, offset),
    )


@router.get("/{simulation_id}", response_model=SimulationOut)
def get_one(
    simulation_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SimulationOut:
    return services.to_out(
        db, services.get_visible(db, user=user, simulation_id=simulation_id)
    )


@router.get("/{simulation_id}/status", response_model=SimulationOut)
def poll_status(
    simulation_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SimulationOut:
    """상세와 같다. **폴링이 쓰는 경로라 접근 로그에 안 남는다.**"""
    return services.to_out(
        db, services.get_visible(db, user=user, simulation_id=simulation_id)
    )


@router.get("/{simulation_id}/result")
def get_result(
    simulation_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """`result.json` 그대로 — 모드 목록 · 단위계 · 참여계수 · 모드 형상 파일 이름.

    **모양을 스키마로 굳히지 않는다.** 레시피마다 다르고(모달 · 정적), 해석이 낸 파일이
    정본이다. 화면은 필요한 칸만 읽는다.
    """
    return services.result_json(db, user=user, simulation_id=simulation_id)


@router.post("/{simulation_id}/retry", response_model=SimulationOut)
def retry(
    simulation_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SimulationOut:
    return services.to_out(db, services.retry(db, user=user, simulation_id=simulation_id))


@router.get("/{simulation_id}/artifacts/{artifact_id}/content", include_in_schema=False)
def download_artifact(
    simulation_id: uuid.UUID,
    artifact_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """**스키마에 안 싣는다** — 파일 응답이 생성 타입에 끼면 `unknown` 이 되고 화면은 그것을
    통과한다(files 와 같은 이유)."""
    artifact, path = services.artifact_for_download(
        db, user=user, simulation_id=simulation_id, artifact_id=artifact_id
    )
    disposition = "attachment; filename=\"download\"; filename*=UTF-8''" + quote(
        artifact.filename
    )
    return FileResponse(
        path, media_type=artifact.content_type, headers={"Content-Disposition": disposition}
    )
