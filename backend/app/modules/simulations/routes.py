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
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core import measured as core_measured
from app.database import get_db
from app.modules.accounts.models import User
from app.modules.simulations import services
from app.modules.simulations.schemas import (
    ConditionsPreviewOut,
    ConvergenceOut,
    ConvergenceRequest,
    DoeImportOut,
    DoeImportRequest,
    DoeListingOut,
    DoePreviewOut,
    MeasurementOut,
    RecipeOut,
    SimulationOut,
    SimulationSummaryOut,
    SolverAvailabilityOut,
    StudyMeasurementOut,
    StudyOut,
    StudySummaryOut,
    WorkersOut,
)
from app.shared.auth import current_user, require_system_admin
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
    midsurface_file: UploadFile | None = File(default=None, alias="midsurface"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SimulationOut:
    """형상(STEP)과, 구속을 걸 거라면 CAD 가 보낸 `topology.json` 을 함께 받는다. 쉘 파트가
    있으면 중간면 형상(`pNNNN_mid.step`)도 받는다."""
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
        midsurface=midsurface_file.file.read() if midsurface_file is not None else None,
    )
    return services.to_out(db, simulation)


@router.get("/workers", response_model=WorkersOut)
def workers(
    _: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> WorkersOut:
    """워커 · 솔버별 줄 · Ansys 라이선스를 쥔 작업 — 서버 화면이 10초마다 묻는다(폴링이라
    접근 로그에 안 남는다).

    **시스템 관리자만.** 워커의 호스트 · 설치 경로가 실린다."""
    return services.workers_overview(db)


@router.get("/solvers", response_model=list[SolverAvailabilityOut])
def solvers(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[SolverAvailabilityOut]:
    """솔버마다 **집을 워커가 살아 있나** — 작업을 거는 화면이 경고에 쓴다. 집을 워커가 없는
    솔버로 걸면 작업은 대기에서 영원히 안 움직이고, 그 사실을 아무도 말해 주지 않는다."""
    return services.solver_availability(db)


@router.get("/measurements/template.csv", include_in_schema=False)
def measurement_template(user: User = Depends(current_user)) -> Response:
    """실측 양식 — 종류 넷(공진 · FRF · 변위 · 변형률)을 한 표에. 장비 파일은 이 모양으로
    옮긴다. BOM 을 붙인다(Excel)."""
    disposition = "attachment; filename=\"measurement.csv\"; filename*=UTF-8''" + quote(
        "실측양식.csv"
    )
    return Response(
        content="\ufeff" + core_measured.TEMPLATE,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


@router.delete("/measurements/{measurement_id}", status_code=204)
def remove_measurement(
    measurement_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """실측을 내린다 — 지우지 않고 `deleted_at` 만 채운다."""
    services.remove_measurement(db, user=user, measurement_id=measurement_id)
    return Response(status_code=204)


@router.get("/studies/{study_id}/measurements", response_model=list[StudyMeasurementOut])
def study_measurements(
    study_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[StudyMeasurementOut]:
    """스터디에 붙은 실측 — 설계점마다 견준 점수와 **가장 가까운 설계점.**"""
    return services.study_measurements(db, user=user, study_id=study_id)


@router.post(
    "/studies/{study_id}/measurements", response_model=StudyMeasurementOut, status_code=201
)
def add_study_measurement(
    study_id: str,
    upload_file: UploadFile = File(alias="file"),
    label: str | None = Form(default=None, max_length=120),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> StudyMeasurementOut:
    """스터디에 실측을 붙인다(CSV · 탭 · JSON)."""
    return services.add_study_measurement(
        db,
        user=user,
        study_id=study_id,
        name=upload_file.filename or "measurement.csv",
        raw=upload_file.file.read(services.MAX_MEASUREMENT_BYTES + 1),
        label=label,
    )


@router.get("/studies", response_model=list[StudySummaryOut])
def list_studies(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[StudySummaryOut]:
    """가져온 DOE 목록. **작업 표에서 모은다** — 스터디를 따로 저장하지 않는다."""
    return services.list_studies(db, user=user)


@router.get("/studies/{study_id}", response_model=StudyOut)
def get_study(
    study_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> StudyOut:
    """설계점마다 **바꾼 값과 그 결과**. 비교 화면이 이것으로 그린다."""
    return services.get_study(db, user=user, study_id=study_id)


@router.get("/studies/{study_id}/export.csv", include_in_schema=False)
def export_study(
    study_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """스터디를 CSV 로 — **화면과 같은 값 · 같은 단위**(mm · MPa · N · Hz).

    BOM 을 붙인다 — 안 붙이면 Excel 이 한글을 깬다. 스키마에 안 싣는다 — 파일을 내려받는
    자리지 데이터를 읽는 자리가 아니다(부서 CSV 와 같은 이유).
    """
    name, text = services.study_csv(db, user=user, study_id=study_id)
    # 파일 이름은 둘로 낸다 — ASCII 는 옛 브라우저용, UTF-8 은 한글 이름용.
    disposition = "attachment; filename=\"study.csv\"; filename*=UTF-8''" + quote(name)
    return Response(
        content="\ufeff" + text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


@router.get("/doe/browse", response_model=DoeListingOut)
def browse_doe(
    path: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DoeListingOut:
    """공용 폴더를 훑는다 — **설정된 뿌리 아래만.** 경로를 안 주면 첫 뿌리부터."""
    return services.browse_doe(path)


@router.post("/conditions/preview", response_model=ConditionsPreviewOut)
def preview_conditions(
    recipe: str | None = Form(default=None),
    topology_file: UploadFile = File(alias="file"),
    user: User = Depends(current_user),
) -> ConditionsPreviewOut:
    """CAD 점 파일 한 장을 **작업을 만들기 전에** 읽어 준다 — 영역 · 물성 · 해석 설정과, 그
    해석 종류에서 조건이 어떻게 다뤄지나. 저장하지 않는다."""
    return services.preview_conditions(
        topology_file.file.read(services.MAX_TOPOLOGY_BYTES + 1), recipe=recipe
    )


@router.get("/doe/preview", response_model=DoePreviewOut)
def preview_doe(
    path: str,
    recipe: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DoePreviewOut:
    """DOE 폴더를 훑어 본다 — **걸기 전에** 점 몇 개, 변수 무엇, 건너뛸 것 몇 개인지.

    폴더는 **서버가 보는 경로**다(공유 스토리지). 브라우저가 파일을 올리는 것이 아니다 —
    설계점 200개면 STEP 만 수십 MB 다.
    """
    return services.preview_doe(path, recipe=recipe)


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
        name=body.name,
    )


@router.get("/doe/point", response_model=ConditionsPreviewOut)
def preview_doe_point(
    path: str,
    number: int,
    recipe: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ConditionsPreviewOut:
    """폴더의 설계점 하나를 읽어 준다 — 새 작업 창이 「설계점 하나 고르기」 에 쓴다(점 파일을
    올렸을 때와 같은 미리보기)."""
    return services.preview_doe_point(path, number, recipe=recipe)


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


@router.get("/{simulation_id}/measurements", response_model=list[MeasurementOut])
def measurements(
    simulation_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[MeasurementOut]:
    """그 작업(과 그 작업의 스터디)에 붙은 실측 — **이 결과와 견준 것**을 함께."""
    return services.measurements_of(db, user=user, simulation_id=simulation_id)


@router.post("/{simulation_id}/measurements", response_model=MeasurementOut, status_code=201)
def add_measurement(
    simulation_id: uuid.UUID,
    upload_file: UploadFile = File(alias="file"),
    label: str | None = Form(default=None, max_length=120),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MeasurementOut:
    """작업에 실측을 붙인다(CSV · 탭 · JSON) — 표 모양은 양식(`/measurements/template.csv`)."""
    return services.add_measurement(
        db,
        user=user,
        simulation_id=simulation_id,
        name=upload_file.filename or "measurement.csv",
        raw=upload_file.file.read(services.MAX_MEASUREMENT_BYTES + 1),
        label=label,
    )


@router.get("/{simulation_id}/convergence", response_model=ConvergenceOut)
def get_convergence(
    simulation_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ConvergenceOut:
    """메시 수렴 — 크기마다 값과 값마다 판정. 원래 작업이나 수준 작업 어느 쪽으로 물어도
    같다."""
    return services.convergence(db, user=user, simulation_id=simulation_id)


@router.post("/{simulation_id}/convergence", response_model=ConvergenceOut, status_code=201)
def request_convergence(
    simulation_id: uuid.UUID,
    body: ConvergenceRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ConvergenceOut:
    """끝난 작업을 **요소 크기만 바꿔** 다시 건다 — 크기마다 작업 하나."""
    return services.request_convergence(
        db, user=user, simulation_id=simulation_id, sizes_mm=body.sizes_mm, solver=body.solver
    )


@router.post("/{simulation_id}/retry", response_model=SimulationOut)
def retry(
    simulation_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SimulationOut:
    return services.to_out(db, services.retry(db, user=user, simulation_id=simulation_id))


@router.post("/studies/{study_id}/tidy")
def tidy_study(
    study_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """DOE 한 벌의 중간 파일을 통째로 정리한다 — 설계점 200개면 이것이 유일한 길이다."""
    return services.tidy_study(db, user=user, study_id=study_id)


@router.post("/{simulation_id}/tidy")
def tidy(
    simulation_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """중간 파일(`.mechdb` · `.rst` · 솔버 scratch)을 지운다. **결과는 남는다.**"""
    return services.tidy(db, user=user, simulation_id=simulation_id)


@router.post("/{simulation_id}/cancel", response_model=SimulationOut)
def cancel(
    simulation_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SimulationOut:
    """작업을 멈춘다. **대기 중이면 곧바로, 돌고 있으면 곧**(워커가 몇 초 안에 본다)."""
    return services.to_out(db, services.cancel(db, user=user, simulation_id=simulation_id))


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
