"""해석 작업 로직 — 걸기 · 집기 · 돌리기 · 조회 · 권한.

`execute` 는 워커가 부르지만 **요청 안에서도 부를 수 있다**(`JOBS_INLINE`). 시험과 워커 없는
작은 설치가 그 길을 쓴다. 두 길이 같은 함수를 지나므로 「워커에서는 되는데 인라인에서는 안
되는」 차이가 안 생긴다.

## 권한

- **보는 것**은 `open_owner_clause` — 전역 + 열린 부서 + 내 부서. 「우리 조직에 이 형상의 모달
  해석이 있나」 에 답할 수 있어야 같은 해석을 두 번 안 돌린다.
- **거는 것**은 그 부서의 멤버면 된다. 해석은 부서의 일상 업무라 관리자만 걸게 하면 관리자가
  대신 눌러 주는 일이 생기고, 그때 「누가 걸었나」 가 거짓이 된다.
- **재시도**는 건 사람 자신이거나 소유 부서의 관리자(`require_owner_edit`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import ValidationError
from sqlalchemy import Select, func, select, text, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import cleanup, executors
from app.core.doe import DoeFolder, DoePoint, read_folder
from app.core.doe.folder import FolderProblem
from app.core.modes import track_modes
from app.core.spec import RUNNABLE_RECIPES, ModalSpec, StaticSpec, parse_spec
from app.core.stages import (
    STAGES,
    ArtifactSpec,
    StageCanceled,
    StageContext,
    StageFailure,
)
from app.modules.accounts.models import User
from app.modules.simulations.models import (
    FINAL_STATUSES,
    RUNNING_STATUSES,
    Simulation,
    SimulationArtifact,
)
from app.modules.simulations.schemas import (
    ArtifactOut,
    DoeImportOut,
    DoePointPreview,
    DoePreviewOut,
    ModeTrackOut,
    RecipeOut,
    SimulationOut,
    SimulationSummaryOut,
    StageOut,
    StudyOut,
    StudyPointOut,
    StudySummaryOut,
)
from app.modules.workspaces.models import Workspace
from app.shared import extensions
from app.shared.errors import AppError, Forbidden, NotFound, code, describe_validation
from app.shared.permissions import (
    open_owner_clause,
    require_member,
    require_owner_edit,
    workspace_by_slug,
)
from app.shared.text import clean

logger = logging.getLogger(__name__)

#: 입력 형상 상한. STEP 은 조립체면 수백 MB 다 — 첨부(50MB)보다 크게 둔다. 서버가 강제한다.
MAX_INPUT_BYTES = 500 * 1024 * 1024
INPUT_NAME = "input.step"
#: CAD 가 보낸 영역 지문. 구속이 있는 스펙은 이것이 있어야 돈다(`core/regions`).
TOPOLOGY_NAME = "topology.json"
#: 지문 파일의 상한. 면 수천 장이어도 몇 MB 다 — 이보다 크면 다른 것을 올린 것이다.
MAX_TOPOLOGY_BYTES = 20 * 1024 * 1024
CHUNK = 1024 * 1024

#: 워커의 마지막 손길이 이보다 오래됐으면 죽은 것으로 보고 다시 건다. 솔브가 몇 시간이라 해도
#: 단계가 바뀔 때마다 heartbeat 를 찍으므로 이 값은 「한 단계」 의 상한이다.
STALE_AFTER = timedelta(hours=3)
MAX_ATTEMPTS = 2


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# --- 작업 폴더 -----------------------------------------------------------------


def work_root() -> Path:
    root = get_settings().work_dir
    assert root is not None  # config 가 filestore_dir/simulations 로 채운다
    return root


def _new_work_dir(simulation_id: uuid.UUID) -> Path:
    """`<root>/<앞 두 글자>/<id>` — 한 폴더에 수만 개를 두지 않는다(filestore 와 같은 이유)."""
    hex_id = simulation_id.hex
    path = work_root() / hex_id[:2] / hex_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def relative_to_root(path: Path) -> str:
    return str(path.resolve().relative_to(work_root().resolve())).replace("\\", "/")


def resolve_work_path(relative_path: str) -> Path | None:
    """상대 경로 → 실제 파일. 없거나 **뿌리 밖을 가리키면** None(filestore.resolve 와 같은
    이유)."""
    base = work_root().resolve()
    target = (base / relative_path).resolve()
    if not target.is_file() or base not in target.parents:
        return None
    return target


# --- 출력 ------------------------------------------------------------------------


def _artifacts_of(db: Session, simulation_id: uuid.UUID) -> list[SimulationArtifact]:
    return list(
        db.scalars(
            select(SimulationArtifact)
            .where(SimulationArtifact.simulation_id == simulation_id)
            .order_by(SimulationArtifact.created_at, SimulationArtifact.kind)
        )
    )


def _names(db: Session, simulation: Simulation) -> tuple[str | None, str | None]:
    workspace = (
        db.get(Workspace, simulation.owner_workspace_id)
        if simulation.owner_workspace_id
        else None
    )
    requester = (
        db.get(User, simulation.requested_by_id) if simulation.requested_by_id else None
    )
    return (
        workspace.name if workspace else None,
        requester.display_name if requester else None,
    )


def to_summary(db: Session, simulation: Simulation) -> SimulationSummaryOut:
    workspace_name, requester_name = _names(db, simulation)
    return SimulationSummaryOut(
        id=simulation.id,
        name=simulation.name,
        recipe=simulation.recipe,
        status=simulation.status,
        source_kind=simulation.source_kind,
        source_ref=simulation.source_ref,
        source_meta=simulation.source_meta,
        owner_workspace_id=simulation.owner_workspace_id,
        owner_workspace_name=workspace_name,
        requested_by_id=simulation.requested_by_id,
        requested_by_name=requester_name,
        error_code=simulation.error_code,
        summary=simulation.summary,
        created_at=simulation.created_at,
        started_at=simulation.started_at,
        finished_at=simulation.finished_at,
    )


def to_out(db: Session, simulation: Simulation) -> SimulationOut:
    base = to_summary(db, simulation).model_dump()
    return SimulationOut(
        **base,
        spec=simulation.spec,
        stages=[StageOut(**one) for one in simulation.stages],
        error_message=simulation.error_message,
        artifacts=[
            ArtifactOut.model_validate(one) for one in _artifacts_of(db, simulation.id)
        ],
        attempts=simulation.attempts,
        worker_id=simulation.worker_id,
    )


def recipes() -> list[RecipeOut]:
    """화면이 새 작업 폼을 그리는 근거. 스키마는 스펙 모델에서 나온다 — 손으로 적지 않는다."""
    return [
        RecipeOut(
            name="modal",
            runnable="modal" in RUNNABLE_RECIPES,
            schema=ModalSpec.model_json_schema(),
        ),
        RecipeOut(
            name="static",
            runnable="static" in RUNNABLE_RECIPES,
            schema=StaticSpec.model_json_schema(),
        ),
    ]


# --- 조회 ------------------------------------------------------------------------


def _visible(user: User) -> Select[tuple[Simulation]]:
    return select(Simulation).where(
        Simulation.deleted_at.is_(None),
        open_owner_clause(user, Simulation.owner_workspace_id),
    )


def get_visible(db: Session, *, user: User, simulation_id: uuid.UUID) -> Simulation:
    """**없는 것과 못 보는 것을 같게 답한다** — 403 으로 가르면 id 가 존재한다는 사실이
    샌다."""
    found = db.scalar(_visible(user).where(Simulation.id == simulation_id))
    if found is None:
        raise NotFound(code("SIMULATIONS", 5), "해석 작업을 찾을 수 없습니다.")
    return found


def list_visible(
    db: Session,
    *,
    user: User,
    status: str | None,
    workspace_slug: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Simulation], int]:
    query = _visible(user)
    if status:
        query = query.where(Simulation.status == status)
    if workspace_slug:
        query = query.where(
            Simulation.owner_workspace_id == workspace_by_slug(db, workspace_slug).id
        )
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = list(
        db.scalars(query.order_by(Simulation.created_at.desc()).limit(limit).offset(offset))
    )
    return rows, total


def result_json(db: Session, *, user: User, simulation_id: uuid.UUID) -> dict[str, Any]:
    """결과 요약(`result.json`)을 그대로 돌려준다.

    **DB 에 옮겨 담지 않는다.** 모드 목록 · 참여계수는 해석이 낸 파일이 정본이고, 그것을 표로
    복사하면 두 벌이 갈린다 — 그리고 갈린 쪽을 화면이 그린다. 파일이 없으면(아직 안 끝났거나
    옛 작업) 404 가 아니라 **왜 없는지** 를 말한다.
    """
    simulation = get_visible(db, user=user, simulation_id=simulation_id)
    artifact = db.scalar(
        select(SimulationArtifact).where(
            SimulationArtifact.simulation_id == simulation.id,
            SimulationArtifact.kind == "result_json",
        )
    )
    if artifact is None:
        raise NotFound(
            code("SIMULATIONS", 10),
            "결과 요약이 아직 없습니다."
            if simulation.status != "done"
            else "이 작업에는 결과 요약이 없습니다(결과 추출 전에 만들어진 작업입니다).",
            details={"status": simulation.status},
        )
    path = resolve_work_path(artifact.relative_path)
    if path is None:
        raise Forbidden(
            code("SIMULATIONS", 7),
            "결과 요약 파일이 작업 폴더에 없습니다. "
            "작업 폴더(WORK_DIR)가 함께 복구됐는지 확인하세요.",
        )
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def artifact_for_download(
    db: Session, *, user: User, simulation_id: uuid.UUID, artifact_id: uuid.UUID
) -> tuple[SimulationArtifact, Path]:
    get_visible(db, user=user, simulation_id=simulation_id)
    artifact = db.scalar(
        select(SimulationArtifact).where(
            SimulationArtifact.id == artifact_id,
            SimulationArtifact.simulation_id == simulation_id,
        )
    )
    if artifact is None:
        raise NotFound(code("SIMULATIONS", 6), "산출물을 찾을 수 없습니다.")
    path = resolve_work_path(artifact.relative_path)
    if path is None:
        # **조용히 빈 파일을 주지 않는다.** 백업을 DB 만 되돌리면 이 상태가 된다.
        raise Forbidden(
            code("SIMULATIONS", 7),
            "산출물 파일이 작업 폴더에 없습니다. "
            "작업 폴더(WORK_DIR)가 함께 복구됐는지 확인하세요.",
        )
    return artifact, path


# --- 걸기 ------------------------------------------------------------------------


def _initial_stages() -> list[dict[str, Any]]:
    return [{"name": stage, "status": "pending", "detail": ""} for stage in STAGES]


def _save_input(target: Path, stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with target.open("wb") as sink:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            if size > MAX_INPUT_BYTES:
                break
            sink.write(chunk)
    return digest.hexdigest(), size


def _register_artifact(
    db: Session, simulation: Simulation, *, stage: str, spec: ArtifactSpec
) -> None:
    """같은 경로가 이미 있으면 그 행을 갱신한다 — 재시도가 같은 이름으로 다시 쓰기 때문이다."""
    relative = relative_to_root(spec.path)
    existing = db.scalar(
        select(SimulationArtifact).where(
            SimulationArtifact.simulation_id == simulation.id,
            SimulationArtifact.relative_path == relative,
        )
    )
    size = spec.path.stat().st_size
    if existing is not None:
        existing.stage = stage
        existing.kind = spec.kind
        existing.size_bytes = size
        existing.created_at = _now()
        return
    db.add(
        SimulationArtifact(
            simulation_id=simulation.id,
            stage=stage,
            kind=spec.kind,
            filename=spec.path.name,
            relative_path=relative,
            content_type=spec.content_type,
            size_bytes=size,
        )
    )


def create(
    db: Session,
    *,
    user: User,
    spec_raw: dict[str, Any],
    workspace_slug: str | None,
    name: str | None,
    filename: str,
    stream: BinaryIO,
    topology: bytes | None = None,
    source_kind: str = "upload",
    source_ref: str | None = None,
    source_meta: dict[str, Any] | None = None,
) -> Simulation:
    """작업을 건다.

    **스펙 검증은 여기서** — 워커가 집어 들고 나서 실패하면 사람은 「왜」 를 목록에서 찾아야
    한다. 구속이 있는데 영역 지문이 없는 것도 같은 부류라 여기서 막는다: 그대로 보내면
    1분 뒤 모델링 단계에서 같은 말을 듣는다.
    """
    try:
        spec = parse_spec(spec_raw)
    except ValidationError as failure:
        raise AppError(
            code("SIMULATIONS", 1),
            f"스펙이 올바르지 않습니다: {describe_validation(failure.errors())}",
            status=400,
            details={"errors": failure.errors(include_url=False)},
        ) from failure
    if spec.recipe not in RUNNABLE_RECIPES:
        raise AppError(
            code("SIMULATIONS", 2),
            f"「{spec.recipe}」 레시피는 아직 실행할 수 없습니다. "
            f"지금은 {', '.join(RUNNABLE_RECIPES)} 만 됩니다.",
            status=400,
        )

    # **레시피부터 본다.** `static` 은 구속을 필수로 받는 스펙이라 순서가 거꾸로면 「실행기가
    # 없다」 대신 「지문이 없다」 고 답하고, 사람은 지문을 만들어 다시 왔다가 또 거절당한다.
    if getattr(spec, "constraints", None) and topology is None:
        raise AppError(
            code("SIMULATIONS", 11),
            f"구속 조건이 있는 해석은 CAD 가 보낸 {TOPOLOGY_NAME} 이 함께 필요합니다.",
            status=400,
            details={"regions": [one.region for one in spec.constraints]},
        )
    if topology is not None:
        if len(topology) > MAX_TOPOLOGY_BYTES:
            raise AppError(
                code("SIMULATIONS", 12),
                f"영역 지문 파일이 너무 큽니다 (최대 {MAX_TOPOLOGY_BYTES // 1024 // 1024}MB).",
                status=413,
            )
        try:
            parsed = json.loads(topology.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as failure:
            raise AppError(
                code("SIMULATIONS", 13),
                f"영역 지문이 JSON 이 아닙니다: {failure}",
                status=400,
            ) from failure
        if not isinstance(parsed, dict) or "regions" not in parsed:
            raise AppError(
                code("SIMULATIONS", 13),
                "영역 지문에 regions 가 없습니다 — "
                f"CAD 가 낸 {TOPOLOGY_NAME} 인지 확인하세요.",
                status=400,
            )
    if workspace_slug is None:
        if not user.is_system_admin:
            raise Forbidden(
                code("SIMULATIONS", 3),
                "전역 해석 작업은 시스템 관리자만 만들 수 있습니다. 부서를 선택하세요.",
            )
        owner_workspace_id = None
    else:
        workspace = workspace_by_slug(db, workspace_slug)
        require_member(db, workspace=workspace, user=user)
        owner_workspace_id = workspace.id

    simulation = Simulation(
        name=clean(name or filename)[:120] or "이름없음",
        recipe=spec.recipe,
        status="queued",
        spec=spec.model_dump(),
        source_kind=source_kind,
        source_ref=clean(source_ref or filename)[:300],
        source_meta=source_meta or {},
        input_sha256="",
        owner_workspace_id=owner_workspace_id,
        requested_by_id=user.id,
        stages=_initial_stages(),
    )
    db.add(simulation)
    db.flush()

    workdir = _new_work_dir(simulation.id)
    input_path = workdir / INPUT_NAME
    sha256, size = _save_input(input_path, stream)
    if size == 0:
        input_path.unlink(missing_ok=True)
        db.rollback()
        raise AppError(code("SIMULATIONS", 4), "입력 형상이 빈 파일입니다.", status=400)
    if size > MAX_INPUT_BYTES:
        input_path.unlink(missing_ok=True)
        db.rollback()
        raise AppError(
            code("SIMULATIONS", 4),
            f"입력 형상이 너무 큽니다 (최대 {MAX_INPUT_BYTES // 1024 // 1024}MB).",
            status=413,
        )
    spec_path = workdir / "spec.json"
    spec_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    topology_path = workdir / TOPOLOGY_NAME
    if topology is not None:
        topology_path.write_bytes(topology)

    simulation.input_sha256 = sha256
    simulation.work_dir = relative_to_root(workdir)
    _register_artifact(
        db, simulation, stage="input", spec=ArtifactSpec("input_step", input_path)
    )
    _register_artifact(db, simulation, stage="input", spec=ArtifactSpec("spec", spec_path))
    if topology is not None:
        _register_artifact(
            db, simulation, stage="input", spec=ArtifactSpec("topology", topology_path)
        )
    db.commit()
    db.refresh(simulation)

    if get_settings().jobs_inline:
        execute(db, simulation, worker_id="inline")
    return simulation


# --- DOE 폴더 --------------------------------------------------------------------


def _preview_point(point: DoePoint) -> DoePointPreview:
    return DoePointPreview(
        number=point.number,
        params=point.params,
        usable=point.usable,
        skip_reason=point.skip_reason,
    )


def _read_doe(path_text: str) -> DoeFolder:
    """폴더를 읽는다. **경로가 틀린 것과 폴더가 DOE 가 아닌 것을 같은 말로 답하지 않는다.**"""
    try:
        return read_folder(Path(path_text).expanduser())
    except FolderProblem as failure:
        raise AppError(code("SIMULATIONS", 14), str(failure), status=400) from failure


def preview_doe(path_text: str) -> DoePreviewOut:
    """걸기 전에 보여 준다 — 점 몇 개, 변수 무엇, 건너뛸 것 몇 개와 그 이유."""
    doe = _read_doe(path_text)
    return DoePreviewOut(
        path=str(doe.path),
        study_id=doe.study_id,
        name=doe.name,
        factors=doe.factors,
        method=doe.method,
        seed=doe.seed,
        points=[_preview_point(one) for one in doe.points],
        usable=len(doe.usable),
        skipped=len(doe.skipped),
    )


def import_doe(
    db: Session,
    *,
    user: User,
    path_text: str,
    spec_raw: dict[str, Any],
    workspace_slug: str | None,
    numbers: list[int] | None = None,
) -> DoeImportOut:
    """폴더 한 벌 → 해석 작업 N 개.

    **모든 점에 같은 스펙을 쓴다.** 점마다 다른 것은 형상과 영역 지문이고, 물성 · 모드 수 ·
    구속 영역 이름은 스터디 전체에 같다 — 그래야 결과를 견줄 수 있다(그러려고 DOE 를 돌린다).

    걸 수 없는 점은 **걸지 않고 이유를 돌려준다.** 200개를 보내 놓고 「왜 절반이 실패했지」 를
    로그에서 찾게 하지 않는다.
    """
    doe = _read_doe(path_text)
    wanted = set(numbers) if numbers else None
    chosen = [one for one in doe.points if wanted is None or one.number in wanted]
    if not chosen:
        raise AppError(code("SIMULATIONS", 15), "고른 설계점이 폴더에 없습니다.", status=400)

    # **이미 가져온 점은 다시 걸지 않는다.** 폴더를 두 번 가리키는 일은 흔하고(경로를 다시
    # 붙여넣기), 그때 조용히 두 벌이 돌면 Mechanical 라이선스를 두 번 태운다. 다시 돌리려면
    # 그 작업에서 재시도한다.
    already = {
        int(one.source_meta.get("point") or 0)
        for one in db.scalars(
            select(Simulation).where(
                Simulation.deleted_at.is_(None),
                Simulation.source_kind == "doe_point",
                Simulation.source_meta["study_id"].astext == doe.study_id,
            )
        )
    }

    created: list[uuid.UUID] = []
    skipped: list[DoePointPreview] = []
    for point in chosen:
        if not point.usable:
            skipped.append(_preview_point(point))
            continue
        if point.number in already:
            skipped.append(
                DoePointPreview(
                    number=point.number,
                    params=point.params,
                    usable=False,
                    skip_reason=(
                        "이미 가져온 점입니다. 다시 돌리려면 그 작업에서 재시도하세요."
                    ),
                )
            )
            continue
        assert point.step is not None  # usable 이 보장한다
        meta = {
            "study_id": doe.study_id,
            "study_name": doe.name,
            "point": point.number,
            "params": point.params,
            "recipe_digest": point.recipe_digest,
            "folder": str(doe.path),
        }
        label = " · ".join(f"{name} {value:g}" for name, value in point.params.items())
        with point.step.open("rb") as stream:
            simulation = create(
                db,
                user=user,
                spec_raw=spec_raw,
                workspace_slug=workspace_slug,
                name=f"{doe.name} p{point.number:04d}" + (f" ({label})" if label else ""),
                filename=point.step.name,
                stream=stream,
                topology=point.topology.read_bytes() if point.topology else None,
                source_kind="doe_point",
                source_ref=f"{doe.name}/p{point.number:04d}",
                source_meta=meta,
            )
        created.append(simulation.id)
    return DoeImportOut(study_id=doe.study_id, name=doe.name, created=created, skipped=skipped)


# --- 설계점 비교 -----------------------------------------------------------------

#: 비교에 실어 보낼 탄성 모드 수. 전부 실으면 점 200개 x 모드 40개가 한 응답에 들어간다.
COMPARE_MODES = 10


def _study_points(db: Session, user: User, study_id: str) -> list[Simulation]:
    return list(
        db.scalars(
            _visible(user)
            .where(Simulation.source_meta["study_id"].astext == study_id)
            .order_by(Simulation.created_at)
        )
    )


def list_studies(db: Session, *, user: User) -> list[StudySummaryOut]:
    """가져온 DOE 목록. **작업 표에서 모은다** — 스터디를 따로 저장하지 않는다.

    스터디 표를 따로 두면 작업을 지웠을 때 둘이 어긋나고, 그때 어느 쪽이 맞는지 알 수 없다.
    """
    rows = list(
        db.scalars(
            _visible(user)
            .where(Simulation.source_kind == "doe_point")
            .order_by(Simulation.created_at)
        )
    )
    grouped: dict[str, list[Simulation]] = {}
    for one in rows:
        key = str(one.source_meta.get("study_id") or one.source_meta.get("study_name") or "")
        if key:
            grouped.setdefault(key, []).append(one)

    out: list[StudySummaryOut] = []
    for study_id, points in grouped.items():
        first = points[0]
        factors: list[str] = []
        for point in points:
            for name in point.source_meta.get("params") or {}:
                if name not in factors:
                    factors.append(name)
        finished = [one.finished_at for one in points if one.finished_at]
        workspace = (
            db.get(Workspace, first.owner_workspace_id) if first.owner_workspace_id else None
        )
        out.append(
            StudySummaryOut(
                study_id=study_id,
                name=str(first.source_meta.get("study_name") or study_id),
                factors=factors,
                points=len(points),
                done=sum(1 for one in points if one.status == "done"),
                failed=sum(1 for one in points if one.status == "failed"),
                running=sum(1 for one in points if one.status in RUNNING_STATUSES),
                workspace_name=workspace.name if workspace else None,
                created_at=first.created_at,
                finished_at=max(finished) if len(finished) == len(points) else None,
            )
        )
    out.sort(key=lambda one: one.created_at, reverse=True)
    return out


def _elastic_modes(simulation: Simulation) -> list[dict[str, Any]]:
    """그 점의 탄성 모드들. **결과 파일이 정본이다**(요약에는 1차만 있다)."""
    if simulation.status != "done" or simulation.work_dir is None:
        return []
    artifact = db_result_path(simulation)
    if artifact is None:
        return []
    try:
        loaded = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    elastic = [one for one in loaded.get("modes", []) if not one.get("rigid_body")]
    return elastic[:COMPARE_MODES]


def _tracks(
    points: list[Simulation], modes_by_point: dict[int, list[dict[str, Any]]]
) -> tuple[int | None, list[ModeTrackOut]]:
    """설계점 사이에서 **같은 모드를 잇는다.**

    기준은 지문이 있는 첫 점이다. 기준이 없으면(옛 작업 · fake 실행기) 잇지 않는다 — 억지로
    순번으로 이으면 그 선이 거짓말을 한다.
    """

    def signatures(number: int) -> list[list[float]]:
        return [one.get("signature") or [] for one in modes_by_point.get(number, [])]

    numbers = [int(one.source_meta.get("point") or 0) for one in points]
    reference = next((number for number in numbers if any(signatures(number))), None)
    if reference is None:
        return None, []

    base = signatures(reference)
    tracks = [
        ModeTrackOut(reference=index + 1, numbers={reference: index + 1}, confidence={})
        for index in range(len(base))
    ]
    for number in numbers:
        if number == reference:
            continue
        links = track_modes(base, signatures(number))
        for track, link in zip(tracks, links, strict=True):
            track.confidence[number] = link.confidence
            if link.number is not None:
                track.numbers[number] = link.number
    return reference, tracks


def db_result_path(simulation: Simulation) -> Path | None:
    if simulation.work_dir is None:
        return None
    return resolve_work_path(f"{simulation.work_dir}/result.json")


def get_study(db: Session, *, user: User, study_id: str) -> StudyOut:
    points = _study_points(db, user, study_id)
    if not points:
        raise NotFound(code("SIMULATIONS", 16), "그 DOE 를 찾을 수 없습니다.")
    factors: list[str] = []
    for point in points:
        for name in point.source_meta.get("params") or {}:
            if name not in factors:
                factors.append(name)

    modes_by_point = {
        int(one.source_meta.get("point") or 0): _elastic_modes(one) for one in points
    }
    reference, tracks = _tracks(points, modes_by_point)
    return StudyOut(
        study_id=study_id,
        name=str(points[0].source_meta.get("study_name") or study_id),
        factors=factors,
        reference_point=reference,
        tracks=tracks,
        points=[
            StudyPointOut(
                simulation_id=one.id,
                number=int(one.source_meta.get("point") or 0),
                params={
                    name: float(value)
                    for name, value in (one.source_meta.get("params") or {}).items()
                },
                status=one.status,
                error_code=one.error_code,
                first_elastic_hz=(one.summary or {}).get("first_elastic_hz"),
                mass_kg=(one.summary or {}).get("mass_kg"),
                nodes=(one.summary or {}).get("nodes"),
                frequencies=[
                    float(mode["frequency_hz"])
                    for mode in modes_by_point[int(one.source_meta.get("point") or 0)]
                ],
            )
            for one in points
        ],
    )


def retry(db: Session, *, user: User, simulation_id: uuid.UUID) -> Simulation:
    """실패한 작업을 처음부터 다시 건다. 단계별 재시도(솔버만 다시)는 5단계."""
    simulation = get_visible(db, user=user, simulation_id=simulation_id)
    if simulation.requested_by_id != user.id:
        require_owner_edit(
            db,
            user,
            simulation.owner_workspace_id,
            what="해석 작업",
            code_value=code("SIMULATIONS", 8),
        )
    if simulation.status not in ("failed", "canceled"):
        raise AppError(
            code("SIMULATIONS", 9),
            "실패했거나 취소한 작업만 다시 걸 수 있습니다.",
            status=409,
            details={"status": simulation.status},
        )
    simulation.status = "queued"
    simulation.stages = _initial_stages()
    simulation.summary = None
    simulation.error_code = None
    simulation.error_message = None
    simulation.worker_id = None
    simulation.started_at = None
    simulation.finished_at = None
    simulation.heartbeat_at = None
    # **취소 표시를 지운다.** 안 지우면 다시 건 작업이 첫 확인에서 곧바로 멈춘다.
    simulation.cancel_requested_at = None
    # 지난 시도의 산출물 행은 뺀다 — 같은 이름으로 다시 쓰이므로 남기면 목록에 두 벌이 선다.
    # 파일은 그대로다(덮어써진다). 입력(형상 · 스펙)은 남긴다.
    for artifact in _artifacts_of(db, simulation.id):
        if artifact.stage != "input":
            db.delete(artifact)
    db.commit()
    db.refresh(simulation)
    if get_settings().jobs_inline:
        execute(db, simulation, worker_id="inline")
    return simulation


# --- 집기 ------------------------------------------------------------------------


def _cancel_requested(db: Session, simulation_id: uuid.UUID) -> bool:
    """**다른 프로세스가 누른 것을 본다.** 워커는 사람의 화면을 모르고, DB 가 유일한 통로다.

    돌고 있는 행만 다시 읽는다 — 한 단계에 몇 초마다 한 번이라 값싸다.
    """
    db.expire_all()
    found = db.get(Simulation, simulation_id)
    return found is not None and found.cancel_requested_at is not None


def cancel(db: Session, *, user: User, simulation_id: uuid.UUID) -> Simulation:
    """작업을 멈춘다.

    **대기 중이면 곧바로, 돌고 있으면 곧 멈춘다** — 워커가 다음 확인 지점(몇 초)에서 보고
    자식 프로세스를 내린다. 끝난 작업은 되돌릴 것이 없다.
    """
    simulation = get_visible(db, user=user, simulation_id=simulation_id)
    if simulation.requested_by_id != user.id:
        require_owner_edit(
            db,
            user,
            simulation.owner_workspace_id,
            what="해석 작업",
            code_value=code("SIMULATIONS", 8),
        )
    if is_final(simulation.status):
        raise AppError(
            code("SIMULATIONS", 17),
            "이미 끝난 작업입니다.",
            status=409,
            details={"status": simulation.status},
        )

    simulation.cancel_requested_at = _now()
    if simulation.status == "queued":
        # 아직 아무도 안 집었다 — 여기서 끝낸다. 워커를 기다릴 이유가 없다.
        simulation.status = "canceled"
        simulation.finished_at = _now()
        simulation.stages = [
            {**one, "status": "canceled" if one["status"] == "pending" else one["status"]}
            for one in simulation.stages
        ]
    db.commit()
    db.refresh(simulation)
    return simulation


def claim_next(db: Session, worker_id: str) -> Simulation | None:
    """queued 하나를 가져온다. `SKIP LOCKED` — 다른 워커가 잠근 행은 건너뛴다. 이것이 없으면 두
    번째 워커는 첫 워커가 커밋할 때까지 서고, 워커를 늘린 뜻이 없어진다."""
    picked = db.execute(
        text(
            "SELECT id FROM simulations WHERE status = 'queued' AND deleted_at IS NULL "
            "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
        )
    ).scalar()
    if picked is None:
        db.commit()
        return None
    now = _now()
    db.execute(
        update(Simulation)
        .where(Simulation.id == picked)
        .values(
            status="fetching",
            worker_id=worker_id,
            started_at=now,
            heartbeat_at=now,
            attempts=Simulation.attempts + 1,
        )
    )
    db.commit()
    simulation = db.get(Simulation, picked)
    assert simulation is not None
    return simulation


def requeue_stale(db: Session) -> int:
    """워커가 죽어 도는 상태에 갇힌 작업을 되살린다. 시도 한도를 넘긴 것은 `worker_lost` 로
    적는다."""
    cutoff = _now() - STALE_AFTER
    stale = list(
        db.scalars(
            select(Simulation).where(
                Simulation.status.in_(RUNNING_STATUSES), Simulation.heartbeat_at < cutoff
            )
        )
    )
    for simulation in stale:
        if simulation.attempts >= MAX_ATTEMPTS:
            simulation.status = "failed"
            simulation.error_code = "worker_lost"
            simulation.error_message = "워커가 응답하지 않아 중단됐습니다(재시도 한도)."
            simulation.finished_at = _now()
        else:
            simulation.status = "queued"
            simulation.stages = _initial_stages()
            simulation.worker_id = None
            simulation.started_at = None
            simulation.heartbeat_at = None
    db.commit()
    return len(stale)


# --- 돌리기 ----------------------------------------------------------------------


@lru_cache
def default_executor() -> executors.Executor:
    """이 설치가 쓰는 실행기. **워커가 기동할 때 한 번 고른다**(`app/worker.py`)."""
    settings = get_settings()
    return executors.resolve(
        settings.simulation_executor,
        fake_stage_seconds=settings.fake_stage_seconds,
        python=settings.windows_python,
        ansys_version=settings.ansys_version,
        ansys_root=settings.ansys_root,
        solver_processes=settings.solver_processes,
        wrapper=tuple(settings.mechanical_env.split()),
        visual_modes=settings.visual_modes,
    )


def _set_stage(simulation: Simulation, name: str, **changes: Any) -> None:
    # 새 리스트로 갈아 끼운다 — JSONB 는 제자리 변경을 못 알아챈다.
    simulation.stages = [
        {**one, **changes} if one["name"] == name else one for one in simulation.stages
    ]


def execute(
    db: Session,
    simulation: Simulation,
    *,
    worker_id: str,
    executor: executors.Executor | None = None,
) -> Simulation:
    """네 단계를 차례로. **실패도 기록이다** — 어느 단계가 왜 멈췄는지 남기고 뒤는
    `skipped`."""
    runner = executor or default_executor()
    if simulation.status not in RUNNING_STATUSES:
        simulation.worker_id = worker_id
        simulation.started_at = _now()
        simulation.attempts += 1
    if simulation.work_dir is None:
        simulation.work_dir = relative_to_root(_new_work_dir(simulation.id))
    workdir = work_root() / simulation.work_dir
    simulation.stages = _initial_stages()
    simulation.summary = {}
    simulation.error_code = None
    simulation.error_message = None
    db.commit()

    failed_at: str | None = None
    for stage in STAGES:
        if failed_at is not None:
            _set_stage(simulation, stage, status="skipped")
            continue
        simulation.status = stage
        simulation.heartbeat_at = _now()
        _set_stage(simulation, stage, status="running", started_at=_iso(_now()))
        db.commit()

        ctx = StageContext(
            stage=stage, spec=simulation.spec, workdir=workdir, input_name=INPUT_NAME
        )
        try:
            result = runner.run(
                ctx, should_cancel=lambda: _cancel_requested(db, simulation.id)
            )
        except StageCanceled:
            # **실패가 아니다.** 사람이 멈춘 것이라 「남은 일」 에 안 올리고 실패로
            # 세지도 않는다.
            _set_stage(simulation, stage, status="canceled", finished_at=_iso(_now()))
            simulation.status = "canceled"
            simulation.finished_at = _now()
            db.commit()
            logger.info("해석 작업 %s 를 %s 단계에서 취소했습니다", simulation.id, stage)
            db.refresh(simulation)
            return simulation
        except StageFailure as failure:
            failed_at = stage
            simulation.error_code = failure.code
            simulation.error_message = failure.message
            _set_stage(
                simulation,
                stage,
                status="failed",
                finished_at=_iso(_now()),
                error_code=failure.code,
                error_message=failure.message,
            )
            logger.warning(
                "해석 작업 %s 의 %s 실패 [%s]: %s",
                simulation.id,
                stage,
                failure.code,
                failure.message,
            )
        except Exception as failure:
            failed_at = stage
            simulation.error_code = "internal"
            simulation.error_message = f"{type(failure).__name__}: {failure}"
            _set_stage(
                simulation,
                stage,
                status="failed",
                finished_at=_iso(_now()),
                error_code="internal",
                error_message=simulation.error_message,
            )
            logger.exception("해석 작업 %s 의 %s 에서 예외", simulation.id, stage)
        else:
            for spec in result.artifacts:
                _register_artifact(db, simulation, stage=stage, spec=spec)
            simulation.summary = {**(simulation.summary or {}), **result.summary}
            _set_stage(
                simulation,
                stage,
                status="done",
                finished_at=_iso(_now()),
                detail=result.detail,
            )
        db.commit()

    simulation.status = "failed" if failed_at else "done"
    simulation.finished_at = _now()
    simulation.heartbeat_at = _now()
    db.commit()
    db.refresh(simulation)
    return simulation


# --- 정리 -----------------------------------------------------------------------


def _work_dir_of(simulation: Simulation) -> Path | None:
    if simulation.work_dir is None:
        return None
    path = (work_root() / simulation.work_dir).resolve()
    return path if path.is_dir() and work_root().resolve() in path.parents else None


def tidy(db: Session, *, user: User, simulation_id: uuid.UUID) -> dict[str, Any]:
    """중간 파일을 지운다 — **결과는 남는다**(`core/cleanup.py` 의 표).

    **끝난 작업만.** 도는 중에 지우면 그 단계가 읽으려던 파일이 사라진다.
    """
    simulation = get_visible(db, user=user, simulation_id=simulation_id)
    if simulation.requested_by_id != user.id:
        require_owner_edit(
            db,
            user,
            simulation.owner_workspace_id,
            what="해석 작업",
            code_value=code("SIMULATIONS", 8),
        )
    if not is_final(simulation.status):
        raise AppError(
            code("SIMULATIONS", 18),
            "끝난 작업만 정리할 수 있습니다.",
            status=409,
            details={"status": simulation.status},
        )

    workdir = _work_dir_of(simulation)
    if workdir is None:
        return {"bytes_freed": 0, "files": 0}

    done = cleanup.run(workdir)
    removed = {path.name for path in done.files}
    # **사라진 파일의 행을 남기지 않는다.** 「DB 에는 있는데 파일이 없는」 상태는 내려받기에서
    # 403 으로 나타나고, 그것은 백업이 잘못된 것과 구별되지 않는다.
    for artifact in _artifacts_of(db, simulation.id):
        if artifact.filename in removed:
            db.delete(artifact)
    simulation.summary = {
        **(simulation.summary or {}),
        "tidied_bytes": int((simulation.summary or {}).get("tidied_bytes") or 0)
        + done.bytes_freed,
    }
    db.commit()
    return {"bytes_freed": done.bytes_freed, "files": len(done.files)}


def tidy_study(db: Session, *, user: User, study_id: str) -> dict[str, Any]:
    """스터디 하나를 통째로 정리한다. **설계점 200개면 이것이 유일하게 할 만한 길이다.**"""
    points = _study_points(db, user, study_id)
    freed = 0
    files = 0
    for point in points:
        if not is_final(point.status):
            continue
        done = tidy(db, user=user, simulation_id=point.id)
        freed += int(done["bytes_freed"])
        files += int(done["files"])
    return {"bytes_freed": freed, "files": files, "points": len(points)}


# --- 공통 화면에 등록하는 것 ----------------------------------------------------


def stats(db: Session) -> list[extensions.StatItem]:
    total = db.scalar(
        select(func.count()).select_from(Simulation).where(Simulation.deleted_at.is_(None))
    )
    # **작업 폴더가 얼마나 찼는지 보이게 한다.** 한 건이 수십 MB 라 DOE 몇 벌이면 GB 가 된다 —
    # 디스크가 차면 앱만이 아니라 DB 도 함께 멈춘다.
    megabytes = cleanup.folder_bytes(work_root()) // (1024 * 1024)
    return [
        extensions.StatItem(label="해석 작업", count=int(total or 0)),
        extensions.StatItem(label="작업 폴더(MB)", count=int(megabytes)),
    ]


def maintenance(db: Session, viewer: User) -> list[extensions.MaintenanceItem]:
    """홈의 「남은 일」 — 실패한 작업. 사람이 봐야 하는 것은 그것뿐이다(도는 것은 기다리면
    된다)."""
    failed = db.scalar(
        select(func.count())
        .select_from(Simulation)
        .where(
            Simulation.deleted_at.is_(None),
            Simulation.status == "failed",
            open_owner_clause(viewer, Simulation.owner_workspace_id),
        )
    )
    count = int(failed or 0)
    if count == 0:
        return []
    return [
        extensions.MaintenanceItem(
            key="simulations_failed",
            label="실패한 해석 작업",
            count=count,
            link="/simulations?status=failed",
            severity="warning",
        )
    ]


def _move(db: Session, source: uuid.UUID, target: uuid.UUID) -> int:
    done = db.execute(
        update(Simulation)
        .where(Simulation.owner_workspace_id == source)
        .values(owner_workspace_id=target)
    )
    return extensions.rows_changed(done)


def _count_of(db: Session, workspace_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Simulation)
            .where(Simulation.owner_workspace_id == workspace_id)
        )
        or 0
    )


def workspace_content(
    db: Session, workspace_id: uuid.UUID
) -> list[extensions.WorkspaceContent]:
    return [
        extensions.WorkspaceContent(
            kind="simulations",
            label="해석 작업",
            count=_count_of(db, workspace_id),
            move=_move,
        )
    ]


def workspace_reference(
    db: Session, workspace_id: uuid.UUID
) -> list[extensions.WorkspaceReference]:
    """FK 가 RESTRICT 라 DB 가 거부한다 — blocks_delete 를 False 로 두면 화면은 지울 수 있다고
    말하고 서버가 500 을 낸다."""
    return [
        extensions.WorkspaceReference(
            table="simulations",
            label="해석 작업",
            count=_count_of(db, workspace_id),
            blocks_delete=True,
        )
    ]


def is_final(status: str) -> bool:
    return status in FINAL_STATUSES
