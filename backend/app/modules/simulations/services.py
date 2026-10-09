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

import csv
import hashlib
import io
import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO, Literal, cast

from pydantic import ValidationError
from sqlalchemy import Select, and_, delete, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import cleanup, executors, materials, units
from app.core import conditions as condition_model
from app.core import convergence as core_convergence
from app.core import measured as core_measured
from app.core import values as core_values
from app.core.doe import DoeFolder, DoePoint, listing, read_folder, resolve_inside
from app.core.doe.browse import OutsideRoots
from app.core.doe.folder import FolderProblem
from app.core.modes import track_modes
from app.core.spec import (
    RUNNABLE_RECIPES,
    HarmonicSpec,
    ModalSpec,
    StaticSpec,
    parse_spec,
)
from app.core.stages import (
    MIDSURFACE_NAME,
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
    SimulationMeasurement,
    SimulationWorker,
)
from app.modules.simulations.schemas import (
    ArtifactOut,
    CadBodyOut,
    CadMaterialOut,
    ComparisonOut,
    ConditionLine,
    ConditionsOut,
    ConditionsPreviewOut,
    ConvergenceLevelOut,
    ConvergenceLocalSizeOut,
    ConvergenceMetricOut,
    ConvergenceOut,
    DoeEntryOut,
    DoeImportOut,
    DoeListingOut,
    DoePointPreview,
    DoePreviewOut,
    LicenseHolderOut,
    MeasurementOut,
    ModeTrackOut,
    RecipeOut,
    RegionOut,
    SimulationOut,
    SimulationSummaryOut,
    SolverAvailabilityOut,
    SolverQueueOut,
    StageOut,
    StudyMatchOut,
    StudyMeasurementOut,
    StudyOut,
    StudyPointOut,
    StudySummaryOut,
    WorkerJobOut,
    WorkerOut,
    WorkersOut,
    WorkerState,
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
from app.shared.tabular import TabularError, parse_rows
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
#: 워커가 신호를 적는 간격과, 끊겼다고 보는 때. 솔브 하나가 몇 시간이어도 신호는 따로 돈다.
BEAT_EVERY = 15.0
WORKER_LOST_AFTER = timedelta(minutes=2)
#: 서버 화면에 보이는 워커 — 이보다 오래 소식이 없고 멈춘 워커는 목록에서 뺀다.
SHOWN_FOR = timedelta(days=1)
#: 이보다 오래 소식이 없는 워커 줄은 지운다(CompCore 와 같은 7일).
FORGET_AFTER = timedelta(days=7)
#: Ansys 라이선스를 쥐는 단계 — 모델링(Mechanical)과 솔버. 형상 준비 · 추출(DPF)은 안 쥔다.
LICENSED_STATUSES = ("modeling", "solving")
SOLVERS = ("ansys", "calculix")


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
        solver=solver_of(simulation),
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
        conditions=_conditions_of(simulation),
    )


def _conditions_of(simulation: Simulation) -> ConditionsOut:
    """작업 폴더의 점 파일을 찾아 조건 줄로 편다. **못 읽으면 비워 둔다.**"""
    hex_id = simulation.id.hex
    path = work_root() / hex_id[:2] / hex_id / TOPOLOGY_NAME
    if not path.is_file():
        return ConditionsOut()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        recipe = parse_spec(simulation.spec).recipe
    except (OSError, ValueError, ValidationError):
        logger.warning("조건을 읽지 못했습니다 — 화면에는 비워 둡니다", exc_info=True)
        return ConditionsOut()
    return conditions_out(payload, recipe=recipe)


def conditions_out(payload: dict[str, Any], *, recipe: str) -> ConditionsOut:
    """CAD 가 보낸 조건을 화면이 읽을 줄로 편다.

    **반영한 것 · 넘긴 것 · 막은 것**을 그대로 보여 준다 — 조건을 넣었는데 결과가 같을 때,
    그것이 무시된 것인지 원래 그런 것인지 사람이 알 수 있어야 한다.
    """
    try:
        found = condition_model.read(payload, recipe=recipe)
        system = units.declared_in(payload)
    except (ValueError, ValidationError):
        logger.warning("조건을 읽지 못했습니다 — 화면에는 비워 둡니다", exc_info=True)
        return ConditionsOut()

    def faces(region: str) -> str:
        """그 영역이 **면 몇 개**로 풀렸나 — 없으면 빈 글자.

        **면 수가 안 보이면 줄어든 것을 모른다.** CAD 의 선택 규칙 `near` 가 2026-10-02
        (CompCore v0.4.0)부터 「가장 가까운 **하나**」 로 바뀌었다 — 볼트 구멍 넷을 잡던 규칙이
        하나만 잡아도 이름(`fixed_support · bolt_holes`)은 똑같다. 그러면 주파수만 달라지고
        화면은 아무 말도 안 한다.
        """
        group = (payload.get("regions") or {}).get(region)
        if not isinstance(group, list) or not group:
            return ""
        # 선택 그룹은 면 · 엣지 · 점을 담는다 — 지문의 모양이 종류를 말한다(점은 `point`).
        first = group[0] if isinstance(group[0], dict) else {}
        unit = "면" if "centroid" in first else "점" if "point" in first else "자리"
        return f" · {unit} {len(group)}"

    lines: list[ConditionLine] = []
    for frame in found.frames:
        lines.append(
            ConditionLine(
                kind="frame",
                label=f"좌표계 {frame.name}",
                detail=f"원점 {tuple(round(one, 3) for one in frame.origin)}",
            )
        )
    for rule in found.constraints:
        lines.append(
            ConditionLine(
                kind="constraint",
                label=rule.name,
                detail=f"{rule.kind} · {rule.region}{faces(rule.region)}",
            )
        )
    for pair in found.contacts:
        lines.append(
            ConditionLine(
                kind="contact",
                label=pair.name,
                detail=f"{pair.kind} · {pair.source} ↔ {pair.target}",
            )
        )
    for load in found.loads:
        size = f"{load.magnitude:g} {load.unit}" if load.magnitude is not None else ""
        lines.append(
            ConditionLine(
                kind="load",
                label=load.name,
                detail=f"{load.kind} {size}".strip() + faces(load.region),
            )
        )
    for hint in found.mesh_hints:
        parts = [f"요소 {hint.element_size:g}"] if hint.element_size is not None else []
        parts += [
            one
            for one in (_METHOD_WORDS.get(hint.method), _ORDER_WORDS.get(hint.order))
            if one
        ]
        lines.append(
            ConditionLine(kind="mesh", label=f"메시 {hint.region}", detail=" · ".join(parts))
        )
    for one in found.body_settings:
        lines.append(
            ConditionLine(kind="body", label=f"파트 {one.name}", detail=one.describe())
        )
    for note in found.skipped:
        lines.append(
            ConditionLine(kind="load", label=note.what, status="skipped", why=note.why)
        )
    for note in found.refused:
        lines.append(
            ConditionLine(kind="constraint", label=note.what, status="refused", why=note.why)
        )
    return ConditionsOut(
        lines=lines, unit_system=system.key, prestressed=found.prestressed, drives=found.drives
    )


#: 메시 칸의 값 → 사람의 말(조건 줄).
_METHOD_WORDS = {
    "tetrahedrons": "사면체",
    "hex_dominant": "육면체 우세",
    "sweep": "스윕",
    "multizone": "멀티존",
}
_ORDER_WORDS = {"linear": "1차", "quadratic": "2차"}


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


def parse_topology(raw: bytes) -> dict[str, Any]:
    """CAD 점 파일(영역 지문) 한 장을 읽는다 — **작업을 거는 길과 미리보는 길이 같은
    검사**를 한다."""
    if len(raw) > MAX_TOPOLOGY_BYTES:
        raise AppError(
            code("SIMULATIONS", 12),
            f"영역 지문 파일이 너무 큽니다 (최대 {MAX_TOPOLOGY_BYTES // 1024 // 1024}MB).",
            status=413,
        )
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
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
            f"CAD 가 낸 점 파일({TOPOLOGY_NAME})인지 확인하세요.",
            status=400,
        )
    return parsed


def _parsed_spec(spec_raw: dict[str, Any]) -> ModalSpec | StaticSpec | HarmonicSpec:
    try:
        return parse_spec(spec_raw)
    except ValidationError as failure:
        raise AppError(
            code("SIMULATIONS", 1),
            f"스펙이 올바르지 않습니다: {describe_validation(failure.errors())}",
            status=400,
            # `json()` 을 거친다 — 검증기가 던진 예외(`ctx.error`)가 글자로 바뀐다.
            details={"errors": json.loads(failure.json(include_url=False))},
        ) from failure


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
    midsurface: bytes | None = None,
    source_kind: str = "upload",
    source_ref: str | None = None,
    source_meta: dict[str, Any] | None = None,
) -> Simulation:
    """작업을 건다.

    **스펙 검증은 여기서** — 워커가 집어 들고 나서 실패하면 사람은 「왜」 를 목록에서 찾아야
    한다. 구속이 있는데 영역 지문이 없는 것도 같은 부류라 여기서 막는다: 그대로 보내면
    1분 뒤 모델링 단계에서 같은 말을 듣는다.
    """
    spec = _parsed_spec(spec_raw)
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
    payload = parse_topology(topology) if topology is not None else None
    gap = material_gap(spec, payload)
    if gap:
        raise AppError(code("SIMULATIONS", 28), gap, status=400)
    blocked = conditions_gap(spec, payload)
    if blocked:
        raise AppError(code("SIMULATIONS", 30), blocked, status=400)
    missing_mid = midsurface_gap(payload, has_midsurface=bool(midsurface))
    if missing_mid:
        # 만들 때 말한다 — 걸어 두면 모델링에서 멈춘다.
        raise AppError(code("SIMULATIONS", 29), missing_mid, status=400)
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
        spec=_stored_spec(spec),
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
    spec_path.write_text(
        json.dumps(_stored_spec(spec), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    topology_path = workdir / TOPOLOGY_NAME
    if topology is not None:
        topology_path.write_bytes(topology)
    mid_path = workdir / MIDSURFACE_NAME
    if midsurface:
        mid_path.write_bytes(midsurface)

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
    if midsurface:
        _register_artifact(
            db, simulation, stage="input", spec=ArtifactSpec("input_mid_step", mid_path)
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


def doe_roots() -> list[Path]:
    """공용 폴더 뿌리 — **푼 경로로** 준다. 탐색은 고른 경로를 늘 풀어(`resolve`) 돌려주는데
    뿌리만 적힌 그대로(심볼릭 링크 · 상대 경로)면 화면이 경로를 뿌리로 못 알아봐 경로 마디가
    통째로 한 덩어리가 됐다(2026-10-05 리뷰)."""
    return [one.resolve() for one in get_settings().doe_root_paths]


def _inside_roots(path_text: str | None) -> Path:
    """공용 폴더 안의 경로로 푼다.

    **아무 경로나 받지 않는다** — 그 칸이 서버의 모든 폴더를 여는 문이 된다(`datasource_dir`
    와 같은 규칙). 설정이 비어 있는 것과 밖을 가리킨 것을 **다른 말로** 답한다: 앞은 관리자가
    `.env` 를 고칠 일이고, 뒤는 사람이 다른 폴더를 고를 일이다.
    """
    roots = doe_roots()
    if not roots:
        raise AppError(
            code("SIMULATIONS", 19),
            "DOE 공용 폴더가 설정돼 있지 않습니다. "
            "관리자가 .env 의 DOE_ROOTS 를 정해야 합니다.",
            status=409,
        )
    try:
        return resolve_inside(roots, path_text)
    except OutsideRoots as failure:
        raise AppError(
            code("SIMULATIONS", 20),
            str(failure),
            status=400,
            details={"roots": [str(one) for one in roots]},
        ) from failure


def browse_doe(path_text: str | None) -> DoeListingOut:
    """공용 폴더를 훑는다 — **탐색기처럼.** 경로를 외워서 치게 하지 않는다."""
    target = _inside_roots(path_text)
    try:
        found = listing(doe_roots(), str(target))
    except FileNotFoundError as failure:
        raise AppError(code("SIMULATIONS", 21), str(failure), status=404) from failure
    return DoeListingOut(
        path=found.path,
        parent=found.parent,
        entries=[
            DoeEntryOut(
                name=one.name,
                path=one.path,
                is_study=one.is_study,
                modified_at=one.modified_at,
            )
            for one in found.entries
        ],
        truncated=found.truncated,
        is_study=found.is_study,
        roots=[str(one) for one in doe_roots()],
    )


def _read_doe(path_text: str) -> DoeFolder:
    """폴더를 읽는다. **경로가 틀린 것과 폴더가 DOE 가 아닌 것을 같은 말로 답하지 않는다.**"""
    target = _inside_roots(path_text)
    try:
        return read_folder(target)
    except FolderProblem as failure:
        raise AppError(code("SIMULATIONS", 14), str(failure), status=400) from failure


def preview_doe_point(
    path_text: str, number: int, *, recipe: str | None = None
) -> ConditionsPreviewOut:
    """폴더의 **설계점 하나**를 새 작업 창이 올린 점 파일처럼 읽어 준다 — 파트 · 재료 · 조건.
    같은 코드(`preview_conditions`)를 지나므로 두 창이 같은 것을 보인다."""
    doe = _read_doe(path_text)
    point = next((one for one in doe.points if one.number == number), None)
    if point is None:
        raise AppError(code("SIMULATIONS", 15), "고른 설계점이 폴더에 없습니다.", status=400)
    if point.point_file is None:
        raise AppError(
            code("SIMULATIONS", 15),
            f"설계점 p{number:04d} 에 점 파일이 없습니다 — "
            f"{point.skip_reason or 'CAD 폴더를 보세요'}",
            status=400,
        )
    return preview_conditions(point.point_file.read_bytes(), recipe=recipe)


def preview_doe(path_text: str, *, recipe: str | None = None) -> DoePreviewOut:
    """걸기 전에 보여 준다 — 점 몇 개, 변수 무엇, 건너뛸 것 몇 개와 그 이유, 그리고 **첫 점의
    조건이 그 해석 종류에서 어떻게 다뤄지나**(반영 · 넘김 · 막음)."""
    doe = _read_doe(path_text)
    analysis = _doe_analysis(doe)
    payload = _first_payload(doe)
    wanted = recipe if recipe in RUNNABLE_RECIPES else (analysis.recipe or "modal")
    return DoePreviewOut(
        conditions=conditions_out(payload, recipe=wanted) if payload is not None else None,
        path=str(doe.path),
        study_id=doe.study_id,
        name=doe.name,
        factors=doe.factors,
        single=doe.single,
        method=doe.method,
        seed=doe.seed,
        points=[_preview_point(one) for one in doe.points],
        usable=len(doe.usable),
        skipped=len(doe.skipped),
        materials=_doe_materials(doe),
        suggested_modes=analysis.modes,
        suggested_recipe=analysis.recipe,
        suggested_element_size_mm=analysis.element_size_mm,
        suggested_order=analysis.order,
        suggested_large_deflection=analysis.large_deflection,
    )


@dataclass(frozen=True)
class _DoeAnalysis:
    """CAD 가 적어 보낸 해석 설정 — **미리 채우고 사람이 고친다.**"""

    recipe: str | None = None
    modes: int | None = None
    element_size_mm: float | None = None
    order: str | None = None
    """「전체」 요소 차수(`linear` · `quadratic`) — 적혀 있을 때만."""
    large_deflection: bool | None = None
    """정적의 큰 변형 — CompCore 는 정적이면 늘 적는다(`statics.static_plan`)."""


def _analysis_of(payload: dict[str, Any]) -> _DoeAnalysis:
    """점 파일 한 장에서 CAD 가 적은 해석 설정을 읽는다.

    **해석 종류는 `conditions.analysis.type` 이다** — `study.json` 의 `recipe` 는 형상
    레시피(상자 · 구멍 노드)라 해석과 상관이 없다. 적혀 있지 않으면 비워 둔다: 조건 읽기는 없을
    때 모달로 채우는데, 그것을 「CAD 가 모달이라 했다」 로 보여 주면 거짓이다.

    요소 크기는 「전체」 힌트를 **mm 로 옮겨** 낸다(SI 폴더면 m 로 온다) — CalculiX 모델링이
    같은 셈을 한다(`calculix/build.py` 의 `_global_size`).
    """
    try:
        system = units.declared_in(payload)
        given = condition_model.read(payload)
    except ValueError:
        return _DoeAnalysis()
    block = payload.get("conditions")
    declared = block.get("analysis") if isinstance(block, dict) else None
    kind = declared.get("type") if isinstance(declared, dict) else None
    hint = given.whole_mesh
    whole = hint.element_size if hint is not None else None
    return _DoeAnalysis(
        recipe=kind if kind in RUNNABLE_RECIPES else None,
        modes=given.analysis.modes,
        element_size_mm=round(whole * system.length_mm, 6) if whole is not None else None,
        order=hint.order if hint is not None and hint.order else None,
        large_deflection=given.analysis.large_deflection,
    )


def _first_payload(doe: DoeFolder) -> dict[str, Any] | None:
    """조건이 든 첫 점의 파일 — 스터디 전체에 같은 것(해석 설정 · 조건 모양)을 여기서
    읽는다."""
    for point in doe.usable:
        if point.point_file is None or not point.has_conditions:
            continue
        try:
            loaded = json.loads(point.point_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return loaded if isinstance(loaded, dict) else None
    return None


def _doe_analysis(doe: DoeFolder) -> _DoeAnalysis:
    """첫 점에서 읽는다(스터디 전체에 같다)."""
    payload = _first_payload(doe)
    return _analysis_of(payload) if payload is not None else _DoeAnalysis()


def preview_conditions(raw: bytes, *, recipe: str | None) -> ConditionsPreviewOut:
    """CAD 점 파일 한 장을 **작업을 만들기 전에** 읽어 준다 — 영역 · 바디 · 물성 · 해석 설정과,
    그 해석 종류에서 조건이 어떻게 다뤄지나. 화면이 파일을 따로 해석하지 않는다(두 벌이 되면
    언젠가 갈린다 — 작업을 거는 길과 같은 코드를 지난다)."""
    payload = parse_topology(raw)
    analysis = _analysis_of(payload)
    wanted = recipe if recipe in RUNNABLE_RECIPES else (analysis.recipe or "modal")
    regions: list[RegionOut] = []
    for name, group in (payload.get("regions") or {}).items():
        rows = group if isinstance(group, list) else []
        first = rows[0] if rows and isinstance(rows[0], dict) else {}
        kind: Literal["face", "point", "other"] = (
            "point" if "point" in first else "face" if "centroid" in first else "other"
        )
        regions.append(RegionOut(name=str(name), count=len(rows), kind=kind))
    found: list[materials.Material] = []
    problem = ""
    try:
        found = materials.read(payload, units.declared_in(payload))
    except ValueError as failure:
        problem = str(failure)
    names = materials.body_names(payload)
    settings = {one.name: one for one in condition_model.read(payload).body_settings}
    off = {name for name, one in settings.items() if one.suppressed}
    on_body = (
        materials.assigned(found, [one for one in names if one not in off]) if found else {}
    )
    unresolved = payload.get("unresolved")
    return ConditionsPreviewOut(
        recipe=wanted,
        regions=regions,
        unresolved=[str(one) for one in unresolved] if isinstance(unresolved, list) else [],
        bodies=[
            CadBodyOut(
                name=name,
                volume_mm3=_volume_of(payload, name),
                material=chosen.name if (chosen := on_body.get(name)) else None,
                suppressed=name in off,
                shell=name in settings and settings[name].shell and name not in off,
                setting=settings[name].describe() if name in settings else "",
            )
            for name in names
        ],
        materials=[
            CadMaterialOut(
                name=one.name,
                bodies=list(one.bodies),
                youngs_modulus_gpa=round(one.youngs_modulus_pa / 1e9, 6),
                poisson_ratio=one.poisson_ratio,
                density_kg_m3=round(one.density_kg_m3, 6),
            )
            for one in found
        ],
        material_error=problem,
        suggested_recipe=analysis.recipe,
        suggested_modes=analysis.modes,
        suggested_element_size_mm=analysis.element_size_mm,
        suggested_order=analysis.order,
        suggested_large_deflection=analysis.large_deflection,
        conditions=conditions_out(payload, recipe=wanted),
    )


def _volume_of(payload: dict[str, Any], name: str) -> float | None:
    for one in payload.get("bodies") or []:
        if isinstance(one, dict) and str(one.get("name") or "").strip() == name:
            volume = one.get("volume")
            return float(volume) if isinstance(volume, int | float) else None
    return None


def _stored_spec(spec: ModalSpec | StaticSpec | HarmonicSpec) -> dict[str, Any]:
    """저장할 스펙 — **새 칸이 기본값이면 적지 않는다.** 스펙은 모르는 칸을 거절하므로
    (`extra="forbid"`), 무중단 갱신(B 먼저 그다음 A — README_OPERATOR) 중 새 서버가 만든 작업을
    옛 워커가 집으면 칸 하나 때문에 실패한다. 기본값이면 칸이 없어도 뜻이 같다."""
    stored: dict[str, Any] = spec.model_dump()
    mesh = stored.get("mesh")
    if isinstance(mesh, dict) and mesh.get("local_scale") == 1.0:
        del mesh["local_scale"]
    # 「큰 변형」 을 비웠으면(CAD 를 따른다) 적지 않는다 — 옛 워커는 `null` 을 참 · 거짓으로
    # 못 읽고, 칸이 없으면 끈 것으로 읽는다(그때까지의 뜻 그대로).
    if "large_deflection" in stored and stored["large_deflection"] is None:
        del stored["large_deflection"]
    return stored


def midsurface_gap(payload: dict[str, Any] | None, *, has_midsurface: bool) -> str:
    """쉘 파트가 있는데 중간면 형상이 없으면 그 까닭 한 줄. **쉘 파트는 중간면으로 푼다** —
    없으면 모델링이 멈춘다."""
    shells = condition_model.read(payload).shells if payload else {}
    if not shells or has_midsurface:
        return ""
    return (
        f"쉘 파트({' · '.join(sorted(shells))})가 있습니다 — CAD 가 낸 중간면 형상"
        "(pNNNN_mid.step)을 함께 올려야 합니다."
    )


def material_gap(
    spec: ModalSpec | StaticSpec | HarmonicSpec, payload: dict[str, Any] | None
) -> str | None:
    """물성이 빠지는 자리가 있나 — 있으면 까닭, 없으면 `None`.

    **작업을 만들 때 막는다.** 그대로 두면 워커가 집어 들고 모델링에서야 같은 말을 한다 —
    DOE 200점이면 200번. 규칙은 모델링과 같다(`materials.assigned`).
    """
    if spec.material_from == "spec":
        return None  # 스펙 검증이 `material` 이 있는지 봤다.
    found: list[materials.Material] = []
    if payload:
        try:
            found = materials.read(payload, units.declared_in(payload))
        except ValueError as failure:
            return f"CAD 가 보낸 물성을 읽지 못했습니다: {failure}"
    if not found:
        if spec.material is not None:
            return None
        return (
            "CAD 점 파일에 물성이 없습니다 — CompCore 에서 재료를 지정한 뒤 다시 내보내세요."
            if payload
            else "물성이 없습니다 — CompCore 가 내보낸 CAD 점 파일이 함께 있어야 합니다."
        )
    # **해석에서 뺀 파트는 물성이 없어도 된다** — 메시에도 안 나온다.
    off = condition_model.read(payload).suppressed
    missing = materials.uncovered(
        found, [one for one in materials.body_names(payload) if one not in off]
    )
    if missing:
        return (
            f"CAD 가 재료를 지정하지 않은 파트가 있습니다: {', '.join(missing)} — "
            "CompCore 에서 재료를 지정하세요."
        )
    return None


def conditions_gap(
    spec: ModalSpec | StaticSpec | HarmonicSpec, payload: dict[str, Any] | None
) -> str | None:
    """CAD 가 보낸 조건 중 못 거는 것이 있나 — 있으면 까닭, 없으면 `None`.

    **작업을 만들 때 막는다.** 모델링은 「막음」 이 하나라도 있으면 멈춘다
    (`_declared_conditions`) — 구속이 빠지면 모드가 통째로 달라지는데 그 사실은 고유진동수를
    보고도 모른다. 그대로 두면 워커가 집어 들고 모델링에서야 같은 말을 한다(DOE 200점이면
    200번). 규칙은 모델링과 같다: 사람이 「내 스펙으로」 를 골랐으면(`conditions_from="spec"`)
    CAD 조건을 안 읽는다.
    """
    if spec.conditions_from == "spec" or not payload:
        return None
    given = condition_model.read(payload, recipe=spec.recipe)
    refused = given.refused
    if refused:
        return (
            "CAD 가 보낸 조건 중 걸 수 없는 것이 있습니다: "
            + " · ".join(f"{one.what} — {one.why}" for one in refused)
            + " (CAD 조건 없이 돌리려면 「CAD 가 보낸 조건 사용」 을 끄고 고정할 면을 "
            "고릅니다)"
        )
    if spec.solver == "calculix":
        from app.core.calculix import deck as calculix_deck

        # **솔버가 못 거는 종류도 만들 때 막는다** — 조건 층은 솔버를 모르고(두 솔버가
        # 같은 것을 읽는다), CalculiX 의 능력표는 덱 쪽에 있다.
        cannot = calculix_deck.unsupported(given)
        if cannot:
            return (
                "CalculiX 로는 아직 못 거는 조건이 있습니다: "
                + " · ".join(cannot)
                + " — 솔버를 ansys 로 바꾸세요."
            )
    return None


def _doe_materials(doe: DoeFolder) -> list[str]:
    """폴더가 함께 보낸 재료 이름 — 훑어볼 때 보여 준다.

    **못 읽는 물성은 여기서 조용히 뺀다.** 미리보기는 「이 폴더에 무엇이 있나」 를 말하는
    자리고, 값을 읽어 세우는 일은 모델링 단계가 한다(그때는 실패한다). 훑어보기가 오류로
    죽으면 사람은 폴더를 고를 수조차 없다.
    """
    names: list[str] = []
    for point in doe.usable:
        if point.point_file is None or not point.has_conditions:
            continue
        try:
            payload = json.loads(point.point_file.read_text(encoding="utf-8"))
            system = units.declared_in(payload)
            found = materials.read(payload, system)
        except (OSError, ValueError):
            continue
        names.extend(one.name for one in found)
    # 설계점마다 같은 재료가 되풀이된다 — 순서를 지키며 한 번씩만.
    return list(dict.fromkeys(names))


def import_doe(
    db: Session,
    *,
    user: User,
    path_text: str,
    spec_raw: dict[str, Any],
    workspace_slug: str | None,
    numbers: list[int] | None = None,
    name: str | None = None,
) -> DoeImportOut:
    """폴더 한 벌 → 해석 작업 N 개.

    **모든 점에 같은 스펙을 쓴다.** 점마다 다른 것은 형상과 영역 지문이고, 물성 · 모드 수 ·
    구속 영역 이름은 스터디 전체에 같다 — 그래야 결과를 견줄 수 있다(그러려고 DOE 를 돌린다).

    걸 수 없는 점은 **걸지 않고 이유를 돌려준다.** 200개를 보내 놓고 「왜 절반이 실패했지」 를
    로그에서 찾게 하지 않는다.
    """
    doe = _read_doe(path_text)
    spec = _parsed_spec(spec_raw)
    wanted = set(numbers) if numbers else None
    chosen = [one for one in doe.points if wanted is None or one.number in wanted]
    if not chosen:
        raise AppError(code("SIMULATIONS", 15), "고른 설계점이 폴더에 없습니다.", status=400)

    # **이미 가져온 점은 다시 걸지 않는다.** 폴더를 두 번 가리키는 일은 흔하고(경로를 다시
    # 붙여넣기), 그때 조용히 두 벌이 돌면 Mechanical 라이선스를 두 번 태운다. 다시 돌리려면
    # 그 작업에서 재시도한다.
    #
    # **단, 앞선 작업이 실패 · 취소면 다시 가져온다.** 재시도는 가져올 때 복사한 옛 점 파일을
    # 그대로 쓰므로, CompCore 가 고쳐 다시 내보낸 폴더(2026-10-05 「솔버 덱 함께」 — 엣지
    # 지문을 면으로)를 쓸 길이 이것뿐이다. 옛 작업은 지우지 않고 기록으로 남기고, 새 작업이
    # 그것을 가리킨다(`source_meta.previous`). 스터디는 점마다 마지막 작업으로 견준다
    # (`_latest_per_point`).
    already: set[int] = set()
    earlier: dict[int, list[Simulation]] = {}
    for one in db.scalars(
        select(Simulation)
        .where(
            Simulation.deleted_at.is_(None),
            Simulation.source_kind.in_(("doe_point", "design")),
            Simulation.source_meta["study_id"].astext == doe.study_id,
        )
        .order_by(Simulation.created_at)
    ):
        number = int(one.source_meta.get("point") or 0)
        if one.status in RETRYABLE_BY_IMPORT:
            earlier.setdefault(number, []).append(one)
        else:
            already.add(number)

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
        topology = point.point_file.read_bytes() if point.point_file else None
        # **물성이 빠지거나 못 거는 조건이 있는 점은 걸지 않는다** — 재료를 훑는 DOE 는 점마다
        # 붙는 재료가 다르고, 걸어 봐야 모델링에서 멈춘다.
        payload = parse_topology(topology) if topology is not None else None
        # **중간면도 여기서 본다** — `create` 가 점마다 커밋하므로, 여기서 안 거르면 앞 점들은
        # 만들어지고 이 점에서 400 이 나 요약도 못 받는다(다시 가져오면 「이미 가져온 점」
        # 이다).
        gap = (
            material_gap(spec, payload)
            or conditions_gap(spec, payload)
            or midsurface_gap(payload, has_midsurface=point.mid_step is not None)
        )
        if gap:
            skipped.append(
                DoePointPreview(
                    number=point.number, params=point.params, usable=False, skip_reason=gap
                )
            )
            continue
        meta = {
            "study_id": doe.study_id,
            "study_name": doe.name,
            "point": point.number,
            "params": point.params,
            # **같은 STEP 을 가리키는 점들은 같은 형상이다**(CompCore 2026-09-24 계약).
            # 조건만 훑는 DOE 는 형상 한 벌을 나눠 쓰므로, 이 값이 같으면 모델링 · 메시를
            # 다시 할 이유가 없다.
            "shape_key": point.shape_key,
            "has_conditions": point.has_conditions,
            # **CAD 가 선언한 계**. 모델링이 이 계로 세션을 세운다(2026-09-24 결정) — 비어
            # 있으면 선언이 없었고, 그때는 SI 다.
            "unit_system": point.unit_system,
            "folder": str(doe.path),
        }
        if point.number in earlier:
            # 앞선 시도(실패 · 취소) — 왜 다시 가져왔는지 그 작업에서 읽는다.
            meta["previous"] = [str(one.id) for one in earlier[point.number]]
        label = " · ".join(
            f"{name} {value:g}" if isinstance(value, float) else f"{name} {value}"
            for name, value in point.params.items()
        )
        with point.step.open("rb") as stream:
            simulation = create(
                db,
                user=user,
                spec_raw=spec_raw,
                workspace_slug=workspace_slug,
                # 이름을 줬으면 그것(설계점 하나를 고른 새 작업 창), 설계 하나면 폴더 이름.
                name=(name or "").strip()
                or (
                    doe.name
                    if doe.single
                    else f"{doe.name} p{point.number:04d}" + (f" ({label})" if label else "")
                ),
                filename=point.step.name,
                stream=stream,
                # 점 파일 하나에 영역 · 바디 · 조건이 다 있다. 작업 폴더에는 지금 이름
                # (`topology.json`)으로 둔다 — 모델링이 `regions` 를 읽는 자리라 그대로 맞는다.
                topology=topology,
                midsurface=point.mid_step.read_bytes() if point.mid_step else None,
                # **설계 하나는 스터디가 아니다** — 비교 · 스터디 목록에 섞이지 않게 가른다.
                source_kind="design" if doe.single else "doe_point",
                source_ref=f"{doe.name}/p{point.number:04d}",
                source_meta=meta,
            )
        created.append(simulation.id)
        if point.number in earlier:
            # **옛 시도에는 대신한 작업을 적는다** — 안 적으면 홈의 「실패한 해석 작업」 에
            # 영영 남고, 누가 옛 시도를 재시도하면 옛 점 파일로 다시 돌아 새 작업을 가린다.
            for old in earlier[point.number]:
                old.source_meta = {
                    **(old.source_meta or {}),
                    "superseded_by": str(simulation.id),
                }
            db.commit()
    return DoeImportOut(study_id=doe.study_id, name=doe.name, created=created, skipped=skipped)


# --- 설계점 비교 -----------------------------------------------------------------

#: 비교에 실어 보낼 탄성 모드 수. 전부 실으면 점 200개 x 모드 40개가 한 응답에 들어간다.
COMPARE_MODES = 10


#: 이 상태의 작업이 있는 점은 다시 가져올 수 있다 — 재시도는 옛 점 파일을 그대로 쓴다.
RETRYABLE_BY_IMPORT = ("failed", "canceled")


def _latest_per_point(rows: list[Simulation]) -> list[Simulation]:
    """점마다 **마지막 작업** — 실패 · 취소한 점을 다시 가져오면 한 점에 작업이 둘이 된다.

    둘을 다 세면 표에 같은 점이 두 줄 나오고, 결과를 점 번호로 모으는 자리에서는 옛 실패 줄에
    새 결과가 붙는다. `rows` 는 만든 순서여야 한다 — 점의 자리는 처음 나온 순서 그대로 둔다.
    """
    latest: dict[int, Simulation] = {}
    for one in rows:
        latest[int(one.source_meta.get("point") or 0)] = one
    return list(latest.values())


def _study_points(
    db: Session, user: User, study_id: str, *, every: bool = False
) -> list[Simulation]:
    """그 스터디의 점들. **목록과 같은 열쇠로 모은다** — `study_id` 가 없는 옛 가져오기는
    목록이 `study_name` 으로 묶으므로 여기서도 그렇게 찾는다. 안 그러면 목록에는 있는데 상세는
    404 다.

    점마다 마지막 작업만 준다(`_latest_per_point`). `every` 면 다시 가져오기 전의 시도까지 —
    정리(중간 파일 지우기)는 그것들도 대상이다."""
    rows = list(
        db.scalars(
            _visible(user)
            .where(
                Simulation.source_kind == "doe_point",
                or_(
                    Simulation.source_meta["study_id"].astext == study_id,
                    and_(
                        Simulation.source_meta["study_id"].astext.is_(None),
                        Simulation.source_meta["study_name"].astext == study_id,
                    ),
                ),
            )
            .order_by(Simulation.created_at)
        )
    )
    return rows if every else _latest_per_point(rows)


def solver_of(simulation: Simulation) -> str:
    """그 작업의 솔버. 칸이 없는 옛 작업은 Ansys 다(`claim_next` 의 `COALESCE` 와 같다)."""
    return str((simulation.spec or {}).get("solver") or "ansys")


def _most(values: list[str], default: str) -> str:
    return Counter(values).most_common(1)[0][0] if values else default


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
    for study_id, every in grouped.items():
        points = _latest_per_point(every)
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
                recipe=_most([one.recipe for one in points], "modal"),
                solvers=list(dict.fromkeys(solver_of(one) for one in points)),
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


def result_of(simulation: Simulation) -> dict[str, Any]:
    """그 작업의 결과 파일. **결과 파일이 정본이다**(요약에는 몇 칸만 있다). 끝나지 않았거나
    못 읽으면 빈 것 — 비교 화면은 그 점을 빈칸으로 둔다."""
    if simulation.status != "done" or simulation.work_dir is None:
        return {}
    artifact = db_result_path(simulation)
    if artifact is None:
        return {}
    try:
        loaded = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


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

    # **결과 파일은 점마다 한 번만 연다** — 모드 잇기와 정적 · 조화 값이 같은 파일에서 나온다.
    results = {int(one.source_meta.get("point") or 0): result_of(one) for one in points}
    modes_by_point = {
        number: core_values.elastic_modes(loaded)[:COMPARE_MODES]
        for number, loaded in results.items()
    }
    reference, tracks = _tracks(points, modes_by_point)
    return StudyOut(
        study_id=study_id,
        name=str(points[0].source_meta.get("study_name") or study_id),
        factors=factors,
        recipe=_most([one.recipe for one in points], "modal"),
        solvers=list(dict.fromkeys(solver_of(one) for one in points)),
        reference_point=reference,
        tracks=tracks,
        points=[
            _study_point(one, results[int(one.source_meta.get("point") or 0)])
            for one in points
        ],
    )


def _study_point(simulation: Simulation, loaded: dict[str, Any]) -> StudyPointOut:
    number = int(simulation.source_meta.get("point") or 0)
    summary = simulation.summary or {}
    found = core_values.read(loaded) if loaded else None
    return StudyPointOut(
        simulation_id=simulation.id,
        number=number,
        # **숫자로 못 읽는 값도 그대로 낸다**(재료 이름 같은 것). 버리면 두 설계점이 화면에서
        # 똑같아 보이고, 사람은 왜 결과가 다른지 알 수 없다.
        params=dict(simulation.source_meta.get("params") or {}),
        status=simulation.status,
        error_code=simulation.error_code,
        recipe=simulation.recipe,
        solver=solver_of(simulation),
        first_elastic_hz=summary.get("first_elastic_hz"),
        mass_kg=summary.get("mass_kg"),
        nodes=summary.get("nodes"),
        frequencies=[
            float(mode["frequency_hz"])
            for mode in core_values.elastic_modes(loaded)[:COMPARE_MODES]
        ],
        max_displacement_mm=found.max_displacement_mm if found else None,
        max_von_mises_mpa=found.max_von_mises_mpa if found else None,
        peak_hz=found.peak_hz if found else None,
        peak_displacement_mm=found.peak_displacement_mm if found else None,
        reactions_n=found.reactions_n if found else {},
        probes_mm=found.probes_mm if found else {},
        probe_vectors_mm=found.probe_vectors_mm if found else {},
        probe_peaks_hz=found.probe_peaks_hz if found else {},
        relative_mm=found.relative_mm if found else {},
    )


# --- CSV ---------------------------------------------------------------------


def _number(value: float | None, digits: int = 6) -> str:
    """CSV 칸 하나. **없는 값은 빈칸** — 0 으로 적으면 「0 이었다」 로 읽힌다."""
    if value is None:
        return ""
    return f"{value:.{digits}g}"


def _keys_in(points: list[StudyPointOut], pick: Any) -> list[str]:
    """점들에 나온 이름(영역 · 측정점)을 **처음 나온 순서**로."""
    seen: dict[str, None] = {}
    for one in points:
        for name in pick(one):
            seen.setdefault(str(name), None)
    return list(seen)


def study_table(study: StudyOut) -> tuple[list[str], list[list[str]]]:
    """스터디 → CSV 머리와 줄. **화면과 같은 값**(`StudyOut`)에서 만든다 — 두 길이 따로
    계산하면 언젠가 갈리고, 그때 화면과 엑셀이 다른 말을 한다.

    단위는 머리에 붙인다(늘 mm · MPa · N · Hz). 모드는 **형상으로 이은 열**만 낸다 — 이은 것이
    없으면(지문 없는 작업) 그 점의 k 번째 탄성 모드를 「순번」 이라고 밝혀 적는다.
    """
    points = study.points
    head = ["설계점", *study.factors, "상태", "해석 종류", "솔버"]
    picks: list[Any] = []

    if study.recipe == "static":
        head += ["최대 변형 (mm)", "최대 상당응력 (MPa)"]
        picks += [lambda one: one.max_displacement_mm, lambda one: one.max_von_mises_mpa]
        for region in _keys_in(points, lambda one: one.reactions_n):
            for axis, label in enumerate(("Fx", "Fy", "Fz")):
                head.append(f"반력 {region} {label} (N)")
                picks.append(
                    lambda one, r=region, a=axis: (one.reactions_n.get(r) or [None] * 3)[a]
                )
            head.append(f"반력 {region} 크기 (N)")
            picks.append(
                lambda one, r=region: (
                    sum(value**2 for value in one.reactions_n[r]) ** 0.5
                    if r in one.reactions_n
                    else None
                )
            )
        for name in _keys_in(points, lambda one: one.probes_mm):
            head.append(f"측정점 {name} 변위 (mm)")
            picks.append(lambda one, n=name: one.probes_mm.get(n))
            for axis, label in enumerate(("X", "Y", "Z")):
                head.append(f"측정점 {name} {label} (mm)")
                picks.append(
                    lambda one, n=name, a=axis: (one.probe_vectors_mm.get(n) or [None] * 3)[a]
                )
        for pair in _keys_in(points, lambda one: one.relative_mm):
            for axis, label in enumerate(("X", "Y", "Z")):
                head.append(f"상대 변위 {pair} {label} (mm)")
                picks.append(
                    lambda one, n=pair, a=axis: (one.relative_mm.get(n) or [None] * 3)[a]
                )
    elif study.recipe == "harmonic":
        head += ["봉우리 주파수 (Hz)", "봉우리 변위 (mm)"]
        picks += [lambda one: one.peak_hz, lambda one: one.peak_displacement_mm]
        for name in _keys_in(points, lambda one: one.probes_mm):
            head += [f"측정점 {name} 봉우리 주파수 (Hz)", f"측정점 {name} 봉우리 진폭 (mm)"]
            picks += [
                lambda one, n=name: one.probe_peaks_hz.get(n),
                lambda one, n=name: one.probes_mm.get(n),
            ]
    else:
        head.append("1차 고유진동수 (Hz)")
        picks.append(lambda one: one.first_elastic_hz)
        if study.tracks:
            base = f"p{(study.reference_point or 0):04d}"
            for track in study.tracks:
                head.append(f"모드 {track.reference}차 (Hz · 기준 {base} 에서 형상으로 이음)")
                picks.append(
                    lambda one, t=track: (
                        one.frequencies[t.numbers[one.number] - 1]
                        if one.number in t.numbers
                        and t.numbers[one.number] - 1 < len(one.frequencies)
                        else None
                    )
                )
        else:
            for index in range(max((len(one.frequencies) for one in points), default=0)):
                head.append(f"탄성 {index + 1}번째 (Hz · 순번 — 같은 모드라는 보장이 없다)")
                picks.append(
                    lambda one, i=index: (
                        one.frequencies[i] if i < len(one.frequencies) else None
                    )
                )
    # 끝의 세 칸은 레시피와 무관하다 — 아래 줄도 같은 순서로 채운다.
    head += ["질량 (kg)", "절점", "작업 ID"]

    rows: list[list[str]] = []
    for one in points:
        line = [f"p{one.number:04d}"]
        line += [str(one.params.get(factor, "")) for factor in study.factors]
        line += [
            one.status,
            study.recipe if one.recipe == study.recipe else one.recipe,
            one.solver,
        ]
        line += [_number(pick(one)) for pick in picks]
        line += [
            _number(one.mass_kg),
            "" if one.nodes is None else str(one.nodes),
            str(one.simulation_id),
        ]
        rows.append(line)
    return head, rows


def study_csv(db: Session, *, user: User, study_id: str) -> tuple[str, str]:
    """스터디를 CSV 로 — `(파일 이름, 본문)`. 화면과 같은 권한 · 같은 값이다."""
    study = get_study(db, user=user, study_id=study_id)
    head, rows = study_table(study)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(head)
    writer.writerows(rows)
    return f"{study.name}.csv", buffer.getvalue()


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
    replaced = (simulation.source_meta or {}).get("superseded_by")
    if replaced:
        # **다시 가져온 점의 옛 시도는 다시 걸지 않는다** — 옛 점 파일로 돌아 새 작업을 가린다
        # (스터디는 점마다 마지막 작업을 본다).
        raise AppError(
            code("SIMULATIONS", 31),
            "이 점은 다시 가져왔습니다 — 새로 만든 작업에서 다시 실행하세요.",
            status=409,
            details={"superseded_by": replaced},
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


def _still_mine(db: Session, simulation_id: uuid.UUID, worker_id: str) -> bool:
    """**아직 내 작업인가.** 신호가 끊긴 사이(DB 가 몇 분 끊겼다 돌아온 때) 다른 워커가 이
    작업을 되살려 집어 갔으면 손을 뗀다 — 안 그러면 두 워커가 같은 작업에 결과를 덮어쓴다."""
    owner = db.scalar(select(Simulation.worker_id).where(Simulation.id == simulation_id))
    return owner == worker_id


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


def claim_next(
    db: Session, worker_id: str, *, solvers: tuple[str, ...] | None = None
) -> Simulation | None:
    """queued 하나를 가져온다. `SKIP LOCKED` — 다른 워커가 잠근 행은 건너뛴다. 이것이 없으면 두
    번째 워커는 첫 워커가 커밋할 때까지 서고, 워커를 늘린 뜻이 없어진다.

    `solvers` 를 주면 **그 솔버의 작업만** 집는다. 쓰는 곳은 하나다: **Ansys 는 노드락
    라이선스가 하나라 워커도 하나여야 하고, CalculiX 는 라이선스가 없어 코어 수만큼 띄울 수
    있다.** 그래서 운영은 「Ansys 워커 하나 + CalculiX 워커 N개」 로 띄운다. 구분이 없으면
    CalculiX 를 늘리려고 워커를 늘렸다가 **Ansys 작업이 라이선스 오류로 실패한다.**

    솔버 칸이 없는 옛 작업은 `ansys` 로 본다 — 칸이 생기기 전에는 Ansys 로 풀었다(기본값이
    CalculiX 로 바뀐 뒤에도 같다 — `spec.parse_stored_spec`).
    """
    where = "status = 'queued' AND deleted_at IS NULL"
    params: dict[str, Any] = {}
    if solvers is not None:
        where += " AND COALESCE(spec->>'solver', 'ansys') = ANY(:solvers)"
        params["solvers"] = list(solvers)
    picked = db.execute(
        text(
            f"SELECT id FROM simulations WHERE {where} "
            "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
        ),
        params,
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
    적는다.

    죽은 것을 아는 길은 둘이다 — 그 워커의 **신호가 끊겼거나**(`simulation_workers`, 2분),
    신호를 안 적는 워커(옛 워커 · 인라인)면 **단계가 너무 오래 멈췄거나**(3시간). 앞의 길이
    없으면 죽은 워커의 작업이 3시간 동안 「도는 중」 으로 보인다. 취소를 요청받은 채 죽었으면
    되살리지 않고 취소로 끝낸다 — 되살리면 사람이 멈춘 작업이 다시 돈다.
    """
    now = _now()
    lost = set(
        db.scalars(
            select(SimulationWorker.id).where(
                SimulationWorker.last_seen_at < now - WORKER_LOST_AFTER,
                SimulationWorker.state != "stopped",
            )
        )
    )
    seen = set(db.scalars(select(SimulationWorker.id)))
    # **세션이 들고 있던 사본을 믿지 않는다** — 취소는 다른 요청이 적는다. 묵은 사본으로
    # 판정하면 사람이 멈춘 작업을 되살린다.
    running = db.scalars(
        select(Simulation)
        .where(Simulation.status.in_(RUNNING_STATUSES))
        .execution_options(populate_existing=True)
    )
    stale = [
        one
        for one in running
        if one.worker_id in lost
        or (
            one.worker_id not in seen
            and one.heartbeat_at is not None
            and one.heartbeat_at < now - STALE_AFTER
        )
    ]
    for simulation in stale:
        if simulation.cancel_requested_at is not None:
            simulation.status = "canceled"
            simulation.error_message = "취소를 요청받은 채 워커가 멈췄습니다."
            simulation.finished_at = now
        elif simulation.attempts >= MAX_ATTEMPTS:
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


# --- 메시 수렴 ---------------------------------------------------------------------

#: 수준(작업) 수 상한 — 원래 작업 + 새 크기 넷. 그 너머는 정련보다 다른 원인을 볼 때다.
MAX_LEVELS = 5
#: 원래 대비 크기 비율의 범위 — `ConvergenceRequest` 의 비율 검사와 같다. 아래 한도는 열 배
#: 촘촘하게(요소 수로 천 배)다 — 그 너머는 정련이 아니라 다른 해석이고, 배율이 반올림에서
#: 0 이 된다.
MIN_RATIO = 0.1
MAX_RATIO = 2.0
#: 판정 문턱(상대). 주파수는 좁게, 크기는 조금 넓게 — 실측과 견주는 자릿수에 맞춘다.
FREQUENCY_TOLERANCE = 0.01
SIZE_TOLERANCE = 0.02


def _original_of(db: Session, user: User, simulation: Simulation) -> Simulation:
    """수렴 묶음의 **원래 작업** — 수준 작업을 가리켜도 원래 것으로 간다."""
    parent = (simulation.source_meta or {}).get("convergence_of")
    if simulation.source_kind == "mesh_check" and parent:
        return get_visible(db, user=user, simulation_id=uuid.UUID(str(parent)))
    return simulation


def _levels_of(db: Session, user: User, original: Simulation) -> list[Simulation]:
    rows = list(
        db.scalars(
            _visible(user).where(
                Simulation.source_kind == "mesh_check",
                Simulation.source_meta["convergence_of"].astext == str(original.id),
            )
        )
    )
    return [original, *rows]


def _size_of(simulation: Simulation) -> float | None:
    """그 작업이 쓴 전역 요소 크기(mm) — 모델링 요약이 정본, 없으면 스펙."""
    found = (simulation.summary or {}).get("element_size_mm")
    if isinstance(found, int | float):
        return float(found)
    asked = ((simulation.spec or {}).get("mesh") or {}).get("element_size_mm")
    return float(asked) if isinstance(asked, int | float) else None


def request_convergence(
    db: Session,
    *,
    user: User,
    simulation_id: uuid.UUID,
    solver: str | None,
    ratios: list[float] | None = None,
    sizes_mm: list[float] | None = None,
) -> ConvergenceOut:
    """끝난 작업을 **요소 크기만 바꿔** 다시 건다 — 수준마다 작업 하나.

    **비율이 기본이다**(`ratios` — 원래 대비 0.7 · 0.5). 전체 크기와 CAD 가 크기를 적은 파트
    · 면이 모두 그 비율로 줄어든다. 원래 작업의 전체 크기를 모르면(Ansys 를 크기 없이 —
    Mechanical 기본값으로 — 풀었다) 곱할 기준이 없어 거절한다: 짐작한 크기로 풀면 원래보다
    성기게 풀릴 수도 있다(박스는 육면체로 메시돼 사면체 기준 짐작이 두 배 어긋난다).

    작업 셋으로 두는 까닭: 상태 기계 · 단계 파일 · 재시도 · 취소 · 정리가 작업 단위로 이미
    되고, CalculiX 워커 여럿이 크기들을 **동시에** 푼다. 한 작업 안에서 크기를 돌리면 그 전부를
    새로 뚫어야 하고 한 워커가 직렬로 푼다.
    """
    original = _original_of(db, user, get_visible(db, user=user, simulation_id=simulation_id))
    if original.status != "done":
        raise AppError(
            code("SIMULATIONS", 22),
            "끝난 작업에서만 메시 수렴을 점검할 수 있습니다 — 기준이 될 결과가 있어야 합니다.",
            status=409,
            details={"status": original.status},
        )
    existing = _levels_of(db, user, original)
    base = _size_of(original)
    if ratios is not None:
        if base is None:
            raise AppError(
                code("SIMULATIONS", 23),
                "원래 작업의 전체 요소 크기를 모릅니다 — Ansys 기본 크기로 풀린 작업이라 "
                "비율을 곱할 기준이 없습니다. 전체 요소 크기를 정해 다시 실행한 뒤 "
                "점검하세요.",
                status=400,
            )
        sizes_mm = [base * one for one in ratios]
    asked = {round(float(one), 6) for one in sizes_mm or [] if one > 0}
    if not asked:
        raise AppError(code("SIMULATIONS", 23), "요소 크기는 0 보다 커야 합니다.", status=400)
    # 크기는 6자리로 반올림했다 — 원래 크기가 더 긴 소수면 비율 2 가 2.0000001 로 읽힌다.
    if base and any(one / base > MAX_RATIO + 1e-6 for one in asked):
        # **옛 방식(`sizes_mm`)도 비율과 같은 한도다** — 크기에서 나온 배율이 스펙 칸의 한도를
        # 넘으면 만들 때 속 칸(`mesh.local_scale`) 이름으로 거절돼 사람이 까닭을 못 읽었다
        # (2026-10-05 리뷰). 원래보다 두 배 넘게 성긴 수준은 수렴 판정에 보탬이 안 된다.
        raise AppError(
            code("SIMULATIONS", 23),
            f"원래 크기({base:g} mm)의 {MAX_RATIO:g}배보다 큰 크기는 점검하지 않습니다 — "
            "수렴은 촘촘하게 줄여 가며 봅니다.",
            status=400,
            details={"base_size_mm": base, "max_ratio": MAX_RATIO},
        )
    if base and any(one / base < MIN_RATIO - 1e-6 for one in asked):
        raise AppError(
            code("SIMULATIONS", 23),
            f"원래 크기({base:g} mm)의 {MIN_RATIO:g}배보다 작은 크기는 점검하지 않습니다 — "
            "요소 수가 천 배를 넘습니다.",
            status=400,
            details={"base_size_mm": base, "min_ratio": MIN_RATIO},
        )
    if solver and solver != solver_of(original) and base is not None:
        # **솔버를 바꾸면 원래 크기도 그 솔버로 다시 푼다** — 원래 작업은 다른 솔버라 판정에서
        # 빠지므로, 안 그러면 그 솔버의 수준이 하나 모자라 차수를 못 잰다.
        asked.add(round(base, 6))
    # **비례 정련 전에 만든 수준은 「푼 크기」 로 치지 않는다** — CAD 파트 · 면 크기를 그대로
    # 둔 수준이라, 같은 크기를 비례로 다시 풀 수 있어야 판정이 고르게 된다(새 수준이 옛 것을
    # 대신한다 — `convergence`). 줄일 CAD 크기가 없으면 둘은 같은 수준이다.
    uneven_matters = base is not None and bool(_cad_local_sizes(original))
    taken = {
        (round(size, 6), solver_of(one))
        for one in existing
        if (size := _size_of(one)) is not None
        and (not uneven_matters or _proportional(one, base))
    }
    wanted = sorted(
        (size for size in asked if (size, solver or solver_of(original)) not in taken),
        reverse=True,
    )
    if not wanted:
        raise AppError(
            code("SIMULATIONS", 23),
            "그 크기들은 이미 풀었습니다 — 다른 크기를 주세요.",
            status=400,
        )
    if len(existing) + len(wanted) > MAX_LEVELS:
        raise AppError(
            code("SIMULATIONS", 23),
            f"수준은 원래 작업을 포함해 {MAX_LEVELS}개까지입니다 — 지금 {len(existing)}개가 "
            "있습니다.",
            status=400,
        )
    source = (
        resolve_work_path(f"{original.work_dir}/{INPUT_NAME}") if original.work_dir else None
    )
    if source is None or not source.is_file():
        raise Forbidden(
            code("SIMULATIONS", 24),
            "원래 작업의 입력 형상 파일이 없습니다 — 다시 걸 수 없습니다.",
        )
    topology_path = resolve_work_path(f"{original.work_dir}/{TOPOLOGY_NAME}")
    topology = (
        topology_path.read_bytes()
        if topology_path is not None and topology_path.is_file()
        else None
    )
    # **쉘 파트가 있으면 중간면도 함께 옮긴다** — 빠뜨리면 만들 때 SIMULATIONS-0029 로 막힌다
    # (2026-10-05, 조건_강체지그_쉘브래킷: 형상 · 점 파일만 옮겨서 점검 자체가 안 걸렸다).
    mid_path = resolve_work_path(f"{original.work_dir}/{MIDSURFACE_NAME}")
    midsurface = mid_path.read_bytes() if mid_path is not None and mid_path.is_file() else None
    workspace = (
        db.get(Workspace, original.owner_workspace_id) if original.owner_workspace_id else None
    )
    for size in wanted:
        spec = dict(original.spec or {})
        # 칸이 없는 옛 작업이면 원래 솔버(Ansys)를 적어 둔다 — 안 그러면 새 기본값
        # (CalculiX)으로 만들어져 「원래 작업의 솔버로」 가 깨진다.
        spec.setdefault("solver", solver_of(original))
        spec["mesh"] = {**(spec.get("mesh") or {}), "element_size_mm": size}
        if base:
            # **비례 정련** — CAD 가 크기를 적은 파트 · 면도 전체 크기와 같은 비율로 줄인다.
            # 안 그러면 그 자리는 그대로라 정련이 고르지 않다. 원래 크기를 모르면(옛 방식
            # `sizes_mm` 에서만 온다) 비율을 못 정하므로 CAD 값 그대로 둔다.
            spec["mesh"]["local_scale"] = round(size / base, 6)
        if solver:
            spec["solver"] = solver
        with source.open("rb") as stream:
            create(
                db,
                user=user,
                spec_raw=spec,
                workspace_slug=workspace.slug if workspace else None,
                name=f"{original.name} · 메시 {size:g} mm",
                filename=INPUT_NAME,
                stream=stream,
                topology=topology,
                midsurface=midsurface,
                source_kind="mesh_check",
                source_ref=f"{original.id}",
                source_meta={
                    "convergence_of": str(original.id),
                    "element_size_mm": size,
                    # 원래 작업이 DOE 점이면 그 자리를 함께 적어 둔다 — 「어느 설계점의
                    # 점검인가」.
                    **{
                        key: original.source_meta[key]
                        for key in ("study_id", "study_name", "point", "params")
                        if key in (original.source_meta or {})
                    },
                },
            )
    return convergence(db, user=user, simulation_id=original.id)


def _convergence_metrics(
    recipe: str, found: list[core_values.Values | None]
) -> list[tuple[str, str, str, float, list[float | None], bool]]:
    """`(열쇠, 이름, 단위, 문턱, 수준별 값, 특이점일 수 있나)` — 레시피마다 견줄 값."""

    def take(pick: Any) -> list[float | None]:
        return [pick(one) if one is not None else None for one in found]

    def names(pick: Any) -> list[str]:
        seen: dict[str, None] = {}
        for one in found:
            if one is not None:
                for name in pick(one):
                    seen.setdefault(str(name), None)
        return list(seen)

    if recipe == "modal":
        return [
            (
                "first_elastic_hz",
                "1차 고유진동수",
                "Hz",
                FREQUENCY_TOLERANCE,
                take(lambda one: one.first_elastic_hz),
                False,
            )
        ]
    if recipe == "harmonic":
        made = [
            (
                "peak_hz",
                "봉우리 주파수",
                "Hz",
                FREQUENCY_TOLERANCE,
                take(lambda one: one.peak_hz),
                False,
            ),
            (
                "peak_mm",
                "봉우리 변위",
                "mm",
                SIZE_TOLERANCE,
                take(lambda one: one.peak_displacement_mm),
                False,
            ),
        ]
        for name in names(lambda one: one.probes_mm):
            made.append(
                (
                    f"probe:{name}",
                    f"측정점 {name} 봉우리 진폭",
                    "mm",
                    SIZE_TOLERANCE,
                    take(lambda one, n=name: one.probes_mm.get(n)),
                    False,
                )
            )
        return made
    made = [
        (
            "max_mm",
            "최대 변형",
            "mm",
            SIZE_TOLERANCE,
            take(lambda one: one.max_displacement_mm),
            False,
        ),
        (
            "max_mpa",
            "최대 상당응력",
            "MPa",
            SIZE_TOLERANCE,
            take(lambda one: one.max_von_mises_mpa),
            True,
        ),
    ]
    for region in names(lambda one: one.reactions_n):
        made.append(
            (
                f"reaction:{region}",
                f"반력 {region}",
                "N",
                SIZE_TOLERANCE,
                take(
                    lambda one, r=region: (
                        sum(value**2 for value in one.reactions_n[r]) ** 0.5
                        if r in one.reactions_n
                        else None
                    )
                ),
                False,
            )
        )
    for name in names(lambda one: one.probes_mm):
        made.append(
            (
                f"probe:{name}",
                f"측정점 {name} 변위",
                "mm",
                SIZE_TOLERANCE,
                take(lambda one, n=name: one.probes_mm.get(n)),
                False,
            )
        )
    return made


def convergence(db: Session, *, user: User, simulation_id: uuid.UUID) -> ConvergenceOut:
    """수렴 묶음 — 수준(크기)마다 값과, 값마다 판정. 원래 작업이나 수준 작업 어느 쪽으로 물어도
    같은 답이다."""
    original = _original_of(db, user, get_visible(db, user=user, simulation_id=simulation_id))
    rows = _levels_of(db, user, original)
    notes: list[str] = []
    # **솔버가 섞이면 한 솔버의 수준끼리만 판정한다** — 두 솔버의 차이(몇 %)가 메시 차이로
    # 읽힌다. 수준이 많은 솔버를 고르고, 같으면 원래 작업의 솔버다.
    counts = Counter(solver_of(one) for one in rows)
    solver = max(counts, key=lambda name: (counts[name], name == solver_of(original)))
    if len(counts) > 1:
        notes.append(
            f"솔버가 섞여 있습니다 — {solver} 로 푼 수준끼리만 판정합니다"
            "(두 솔버의 값은 몇 % 갈립니다)."
        )
    rows = [one for one in rows if solver_of(one) == solver]
    base_size = _size_of(original)
    local = _cad_local_sizes(original)
    if local and base_size is not None:
        # 같은 크기를 비례로 다시 풀었으면 그 크기의 옛 수준(CAD 크기를 그대로 둔)은
        # 판정에서 뺀다.
        redone = {
            round(size, 6)
            for one in rows
            if one.source_kind == "mesh_check"
            and _proportional(one, base_size)
            and (size := _size_of(one)) is not None
        }
        rows = [
            one
            for one in rows
            if not (
                one.source_kind == "mesh_check"
                and not _proportional(one, base_size)
                and (size := _size_of(one)) is not None
                and round(size, 6) in redone
            )
        ]

    loaded = [result_of(one) for one in rows]
    found = [core_values.read(one) if one else None for one in loaded]
    levels = [
        ConvergenceLevelOut(
            simulation_id=one.id,
            element_size_mm=_size_of(one),
            nodes=(values.nodes if values is not None and values.nodes else None)
            or (one.summary or {}).get("nodes"),
            status=one.status,
            solver=solver_of(one),
            is_original=one is original,
            local_scale=float(((one.spec or {}).get("mesh") or {}).get("local_scale") or 1.0),
            ratio=(
                1.0
                if one is original
                else round(size / base_size, 6)
                if (size := _size_of(one)) is not None and base_size
                else None
            ),
        )
        for one, values in zip(rows, found, strict=True)
    ]
    order = sorted(range(len(levels)), key=lambda index: levels[index].nodes or 0)
    levels = [levels[index] for index in order]
    found = [found[index] for index in order]

    metrics: list[ConvergenceMetricOut] = []
    for key, label, unit, tolerance, values, singular in _convergence_metrics(
        original.recipe, found
    ):
        pairs = [
            (level.nodes, value)
            for level, value in zip(levels, values, strict=True)
            if level.nodes and value is not None
        ]
        verdict = core_convergence.judge(pairs, tolerance=tolerance)
        note = ""
        if singular and verdict.status in ("diverging", "not_converged", "oscillating"):
            note = (
                "첨두응력은 구속 모서리 · 날카로운 모서리의 특이점에 있으면 메시를 줄일수록 "
                "커집니다 — 이 값으로 판단하지 말고 측정점 · 변형을 봅니다."
            )
        metrics.append(
            ConvergenceMetricOut(
                key=key,
                label=label,
                unit=unit,
                values=values,
                status=verdict.status,
                tolerance_pct=round(tolerance * 100, 3),
                change_pct=round(verdict.change * 100, 4)
                if verdict.change is not None
                else None,
                order=round(verdict.order, 3) if verdict.order is not None else None,
                gci_pct=round(verdict.gci * 100, 4) if verdict.gci is not None else None,
                extrapolated=verdict.extrapolated,
                note=note,
            )
        )
    if solver == "calculix" and any((one.summary or {}).get("contact_pairs") for one in rows):
        notes.append(
            "CalculiX 의 비선형 접촉은 접촉 강성이 요소 크기를 따라갑니다 — 크기를 바꾸면 "
            "메시와 접촉 모델이 함께 바뀐 결과입니다."
        )
    checks = [one for one in rows if one.source_kind == "mesh_check"]
    if local and checks:
        even = all(_proportional(one, base_size) for one in checks)
        if even:
            notes.append(
                f"CAD 가 요소 크기를 적은 자리({' · '.join(one.name for one in local)})도 "
                "전체 크기와 같은 비율로 "
                "줄였습니다(비례 정련)."
            )
        else:
            # 비례 정련 전에 만든 수준이 섞였다 — 그 수준은 CAD 크기를 그대로 두었다.
            notes.append(
                f"CAD 가 요소 크기를 적은 자리({' · '.join(one.name for one in local)})를 "
                "그대로 둔 수준이 "
                "있습니다(비례 정련 전에 만든 수준) — 정련이 고르지 않습니다. 새로 점검하는 "
                "크기부터는 같은 비율로 줄입니다."
            )
    return ConvergenceOut(
        original_id=original.id,
        recipe=original.recipe,
        base_size_mm=_size_of(original),
        levels=levels,
        metrics=metrics,
        notes=notes,
        local_sizes=local,
    )


def _proportional(simulation: Simulation, base: float | None) -> bool:
    """그 수준의 CAD 파트 · 면 배율이 정말 「이 수준의 크기 / 원래 크기」 인가 — 비례 정련으로
    푼 수준인가. 칸이 없으면 1 이다(기본값은 저장하지 않는다 — `_stored_spec`). 비례 정련 전에
    만든 수준은 칸이 없어 원래 크기가 아니면 어긋난다."""
    scale = ((simulation.spec or {}).get("mesh") or {}).get("local_scale", 1.0)
    size = _size_of(simulation)
    return (
        base is not None
        and size is not None
        and isinstance(scale, int | float)
        and abs(float(scale) - size / base) < 1e-5
    )


def _cad_local_sizes(original: Simulation) -> list[ConvergenceLocalSizeOut]:
    """원래 작업에서 CAD 가 크기를 적은 파트 · 면. **CAD 조건을 끄고 푼 작업에는 없다** —
    빌더가 점 파일을 아예 안 읽는다(`conditions_from="spec"`). 보이면 쓰지도 않은 크기를
    줄였다고 읽힌다."""
    if (original.spec or {}).get("conditions_from", "cad") != "cad":
        return []
    return _local_sizes(_topology_payload(original))


def _local_sizes(payload: dict[str, Any]) -> list[ConvergenceLocalSizeOut]:
    """CAD 가 요소 크기를 적은 자리 — 파트(파트별 설정)와 면(국부 메시). 「전체」 는 아니다.

    크기는 mm 로 바꿔 준다 — CAD 는 선언한 계의 길이로 적는다(SI 폴더면 m).
    """
    if not payload:
        return []
    declared = condition_model.read(payload)
    try:
        mm = units.declared_in(payload).length_mm
    except ValueError:
        mm = 1.0
    found: dict[str, ConvergenceLocalSizeOut] = {}
    for one in declared.body_settings:
        if one.element_size is not None and not one.suppressed:
            found[one.name] = ConvergenceLocalSizeOut(
                name=one.name, kind="part", size_mm=round(one.element_size * mm, 6)
            )
    for hint in declared.mesh_hints:
        if hint.element_size is not None and not hint.whole and hint.region not in found:
            found[hint.region] = ConvergenceLocalSizeOut(
                name=hint.region, kind="face", size_mm=round(hint.element_size * mm, 6)
            )
    return sorted(found.values(), key=lambda one: (one.kind != "part", one.name))


def _topology_payload(simulation: Simulation) -> dict[str, Any]:
    path = (
        resolve_work_path(f"{simulation.work_dir}/{TOPOLOGY_NAME}")
        if simulation.work_dir
        else None
    )
    if path is None or not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


# --- 실측 -------------------------------------------------------------------------

#: 실측 파일 상한 — FRF 수천 점 x 측정점 몇 개면 수백 KB 다.
MAX_MEASUREMENT_BYTES = 5 * 1024 * 1024


def _youngs_of(simulation: Simulation) -> float | None:
    """그 작업이 **실제로 쓴** 영률(GPa) — 모델링 요약(CAD 물성)이 먼저, 없으면 스펙.

    바디마다 재료가 다르면 하나로 줄일 수 없다 — 그때는 영률을 제안하지 않는다."""
    summary = simulation.summary or {}
    if isinstance(summary.get("youngs_modulus_gpa"), int | float):
        return float(summary["youngs_modulus_gpa"])
    if summary.get("material_bodies"):
        return None
    material = (simulation.spec or {}).get("material") or {}
    value = material.get("youngs_modulus_gpa")
    return float(value) if isinstance(value, int | float) else None


def _force_driven(simulation: Simulation) -> bool:
    """힘으로 건 모델인가 — **변위로 당긴 구속이 있으면 아니다**(그때 변위는 1/E 를 안
    따른다)."""
    given = condition_model.read(_topology_payload(simulation), recipe=simulation.recipe)
    return not any(rule.kind == "displacement" for rule in given.constraints)


def _compare(simulation: Simulation, rows: list[dict[str, Any]]) -> ComparisonOut | None:
    loaded = result_of(simulation)
    if not loaded:
        return None
    return ComparisonOut.model_validate(
        core_measured.compare(
            loaded,
            rows,
            youngs_gpa=_youngs_of(simulation),
            force_driven=_force_driven(simulation),
        )
    )


def _measurement_out(
    db: Session, row: SimulationMeasurement, comparison: ComparisonOut | None = None
) -> MeasurementOut:
    author = db.get(User, row.created_by_id) if row.created_by_id else None
    return MeasurementOut(
        id=row.id,
        label=row.label,
        original_name=row.original_name,
        simulation_id=row.simulation_id,
        study_id=row.study_id,
        kinds=list(dict.fromkeys(str(one["kind"]) for one in row.rows)),
        probes=list(dict.fromkeys(str(one["probe"]) for one in row.rows if one.get("probe"))),
        rows=len(row.rows),
        created_at=row.created_at,
        created_by_name=author.display_name if author else None,
        comparison=comparison,
    )


def _read_measurement(name: str, raw: bytes) -> list[dict[str, Any]]:
    if not raw.strip():
        raise AppError(code("SIMULATIONS", 25), "실측 파일이 비었습니다.", status=400)
    if len(raw) > MAX_MEASUREMENT_BYTES:
        raise AppError(
            code("SIMULATIONS", 25),
            f"실측 파일이 너무 큽니다 (최대 {MAX_MEASUREMENT_BYTES // 1024 // 1024}MB).",
            status=413,
        )
    try:
        table = parse_rows(name, raw)
    except (TabularError, UnicodeDecodeError) as failure:
        raise AppError(
            code("SIMULATIONS", 25), f"실측 표를 읽지 못했습니다: {failure}", status=400
        ) from failure
    rows, errors = core_measured.parse(table)
    if errors:
        # **줄 번호와 함께 전부** 돌려준다 — 하나 고치고 또 올려 다음 것을 알게 하지 않는다.
        raise AppError(
            code("SIMULATIONS", 25),
            f"실측 표에 고칠 곳이 {len(errors)}개 있습니다: {errors[0]}",
            status=400,
            details={"errors": errors[:50]},
        )
    return rows


def _save_measurement(
    db: Session,
    *,
    user: User,
    workspace_id: uuid.UUID | None,
    rows: list[dict[str, Any]],
    label: str | None,
    original_name: str,
    simulation_id: uuid.UUID | None = None,
    study_id: str | None = None,
) -> SimulationMeasurement:
    """**거는 사람과 같은 규칙** — 그 부서의 멤버(전역은 시스템 관리자)."""
    if workspace_id is None:
        if not user.is_system_admin:
            raise Forbidden(
                code("SIMULATIONS", 26), "전역 작업의 실측은 시스템 관리자만 올릴 수 있습니다."
            )
    else:
        workspace = db.get(Workspace, workspace_id)
        if workspace is None:
            raise NotFound(code("SIMULATIONS", 26), "작업의 부서를 찾을 수 없습니다.")
        require_member(db, workspace=workspace, user=user)
    row = SimulationMeasurement(
        simulation_id=simulation_id,
        study_id=study_id,
        owner_workspace_id=workspace_id,
        label=clean(label or original_name)[:120] or "실측",
        original_name=clean(original_name)[:255],
        rows=rows,
        created_by_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_measurement(
    db: Session,
    *,
    user: User,
    simulation_id: uuid.UUID,
    name: str,
    raw: bytes,
    label: str | None,
) -> MeasurementOut:
    """작업 하나에 실측을 붙인다 — 올린 즉시 그 결과와 견준 것을 돌려준다."""
    simulation = get_visible(db, user=user, simulation_id=simulation_id)
    rows = _read_measurement(name, raw)
    row = _save_measurement(
        db,
        user=user,
        workspace_id=simulation.owner_workspace_id,
        rows=rows,
        label=label,
        original_name=name,
        simulation_id=simulation.id,
    )
    return _measurement_out(db, row, _compare(simulation, rows))


def _study_key(simulation: Simulation) -> str | None:
    meta = simulation.source_meta or {}
    if simulation.source_kind != "doe_point":
        return None
    key = meta.get("study_id") or meta.get("study_name")
    return str(key) if key else None


def measurements_of(
    db: Session, *, user: User, simulation_id: uuid.UUID
) -> list[MeasurementOut]:
    """그 작업에 붙은 실측과 **그 작업의 스터디에 붙은 실측** — 둘 다 이 결과와 견준다."""
    simulation = get_visible(db, user=user, simulation_id=simulation_id)
    key = _study_key(simulation)
    scope = [SimulationMeasurement.simulation_id == simulation.id]
    if key is not None:
        scope.append(SimulationMeasurement.study_id == key)
    rows = db.scalars(
        select(SimulationMeasurement)
        .where(SimulationMeasurement.deleted_at.is_(None), or_(*scope))
        .order_by(SimulationMeasurement.created_at.desc())
        .limit(50)
    )
    return [_measurement_out(db, row, _compare(simulation, row.rows)) for row in rows]


def _study_measurement_out(
    db: Session, row: SimulationMeasurement, points: list[Simulation]
) -> StudyMeasurementOut:
    """설계점마다 견주고 **가장 가까운 점**을 고른다 — 물성 · 감쇠를 훑은 DOE 면 그 값이
    실측과의 차이를 설명한다."""
    scored: list[StudyMatchOut] = []
    for point in points:
        comparison = _compare(point, row.rows) if point.status == "done" else None
        scored.append(
            StudyMatchOut(
                simulation_id=point.id,
                number=int(point.source_meta.get("point") or 0),
                params=dict(point.source_meta.get("params") or {}),
                status=point.status,
                score_pct=comparison.score_pct if comparison is not None else None,
            )
        )
    ranked = [one for one in scored if one.score_pct is not None]
    best = min(ranked, key=lambda one: one.score_pct or 0.0) if ranked else None
    if best is None:
        explanation = (
            "견줄 수 있는 설계점이 없습니다 — 끝난 점이 없거나 종류가 레시피와 다릅니다."
        )
    else:
        values = " · ".join(f"{name} {value}" for name, value in best.params.items())
        explanation = (
            f"실측에 가장 가까운 설계점은 p{best.number:04d}({values}) — 평균 차이 "
            f"{best.score_pct:.2f}% 입니다."
        )
    base = _measurement_out(db, row)
    return StudyMeasurementOut(
        **base.model_dump(),
        points=scored,
        best_point=best.number if best is not None else None,
        explanation=explanation,
    )


def add_study_measurement(
    db: Session, *, user: User, study_id: str, name: str, raw: bytes, label: str | None
) -> StudyMeasurementOut:
    """스터디에 실측을 붙인다 — 설계점마다 견준 점수를 돌려준다."""
    points = _study_points(db, user, study_id)
    if not points:
        raise NotFound(code("SIMULATIONS", 16), "그 DOE 를 찾을 수 없습니다.")
    rows = _read_measurement(name, raw)
    row = _save_measurement(
        db,
        user=user,
        workspace_id=points[0].owner_workspace_id,
        rows=rows,
        label=label,
        original_name=name,
        study_id=study_id,
    )
    return _study_measurement_out(db, row, points)


def study_measurements(db: Session, *, user: User, study_id: str) -> list[StudyMeasurementOut]:
    points = _study_points(db, user, study_id)
    if not points:
        raise NotFound(code("SIMULATIONS", 16), "그 DOE 를 찾을 수 없습니다.")
    rows = db.scalars(
        select(SimulationMeasurement)
        .where(
            SimulationMeasurement.deleted_at.is_(None),
            SimulationMeasurement.study_id == study_id,
        )
        .order_by(SimulationMeasurement.created_at.desc())
        .limit(20)
    )
    return [_study_measurement_out(db, row, points) for row in rows]


def remove_measurement(db: Session, *, user: User, measurement_id: uuid.UUID) -> None:
    """실측을 내린다 — **지우지 않고 `deleted_at` 만 채운다.** 올린 사람이거나 그 부서의
    관리자."""
    row = db.get(SimulationMeasurement, measurement_id)
    if row is None or row.deleted_at is not None:
        raise NotFound(code("SIMULATIONS", 27), "그 실측을 찾을 수 없습니다.")
    if row.created_by_id != user.id:
        require_owner_edit(
            db, user, row.owner_workspace_id, what="실측", code_value=code("SIMULATIONS", 27)
        )
    row.deleted_at = _now()
    db.commit()


# --- 워커 신호 -----------------------------------------------------------------------


def beat(
    db: Session,
    worker_id: str,
    *,
    state: str,
    current_simulation_id: uuid.UUID | None = None,
    hostname: str = "",
    pid: int = 0,
    version: str = "",
    executor: str = "",
    solvers: list[str] | None = None,
    tools: dict[str, Any] | None = None,
) -> None:
    """워커가 살아 있다고 적는다 — 없으면 줄을 만든다. 기동 때 정한 것(실행기 · 솔버 · 도구)은
    처음 한 번 적고, 뒤의 신호는 상태 · 지금 작업 · 시각만 바꾼다."""
    row = db.get(SimulationWorker, worker_id)
    if row is None:
        # **새 워커가 뜰 때 오래된 줄을 치운다.** 워커 id 가 호스트:PID 라 뜰 때마다 줄이 새로
        # 생기는데 지우는 곳이 없어 4일에 119줄이 쌓였다(CompCore 가 알려 줬다, 2026-10-07).
        db.execute(
            delete(SimulationWorker).where(
                SimulationWorker.last_seen_at < _now() - FORGET_AFTER
            )
        )
        row = SimulationWorker(
            id=worker_id,
            hostname=hostname,
            pid=pid,
            version=version,
            executor=executor,
            solvers=list(solvers or []),
            tools=dict(tools or {}),
        )
        db.add(row)
    row.state = state
    row.current_simulation_id = current_simulation_id
    row.last_seen_at = _now()
    db.commit()


def _alive(row: SimulationWorker, now: datetime) -> bool:
    return row.state != "stopped" and now - row.last_seen_at <= WORKER_LOST_AFTER


def _takes(row: SimulationWorker, solver: str) -> bool:
    """이 워커가 그 솔버를 집나 — **비어 있으면 전부.**"""
    return not row.solvers or solver in row.solvers


def _queue_counts(db: Session) -> dict[tuple[str, str], int]:
    """(솔버, 상태) → 건수. 솔버 칸이 없는 옛 작업은 Ansys 다(`claim_next` 와 같다)."""
    solver = func.coalesce(Simulation.spec["solver"].astext, "ansys")
    rows = db.execute(
        select(solver, Simulation.status, func.count())
        .where(
            Simulation.deleted_at.is_(None),
            Simulation.status.in_(("queued", *RUNNING_STATUSES)),
        )
        .group_by(solver, Simulation.status)
    ).all()
    counts: dict[tuple[str, str], int] = {}
    for name, status, many in rows:
        group = "queued" if status == "queued" else "running"
        counts[(str(name), group)] = counts.get((str(name), group), 0) + int(many)
    return counts


def _oldest_queued(db: Session) -> dict[str, datetime]:
    solver = func.coalesce(Simulation.spec["solver"].astext, "ansys")
    return {
        str(name): oldest
        for name, oldest in db.execute(
            select(solver, func.min(Simulation.created_at))
            .where(Simulation.deleted_at.is_(None), Simulation.status == "queued")
            .group_by(solver)
        ).all()
    }


def workers_overview(db: Session) -> WorkersOut:
    """서버 화면의 「워커 · 솔버」 — 워커마다 상태 · 집는 솔버 · 깔린 도구 · 하는 일, 솔버마다
    줄(대기 · 도는 것 · 집을 워커), 그리고 **지금 Ansys 라이선스를 쥐었을 작업**."""
    now = _now()
    rows = list(
        db.scalars(
            select(SimulationWorker)
            .where(
                (SimulationWorker.last_seen_at > now - SHOWN_FOR)
                | (SimulationWorker.state != "stopped")
            )
            .order_by(SimulationWorker.started_at.desc())
        )
    )
    workers: list[WorkerOut] = []
    for row in rows:
        silent = (now - row.last_seen_at).total_seconds()
        # **끊긴 것은 서버가 판정한다** — 죽은 워커는 「죽었다」 고 적을 수 없다.
        state = cast(
            WorkerState,
            "lost"
            if row.state != "stopped" and silent > WORKER_LOST_AFTER.total_seconds()
            else row.state,
        )
        job = (
            db.get(Simulation, row.current_simulation_id)
            if row.current_simulation_id and state in ("busy", "stopping")
            else None
        )
        workers.append(
            WorkerOut(
                id=row.id,
                hostname=row.hostname,
                pid=row.pid,
                version=row.version,
                executor=row.executor,
                solvers=list(row.solvers or []),
                tools=dict(row.tools or {}),
                state=state,
                started_at=row.started_at,
                last_seen_at=row.last_seen_at,
                silent_seconds=round(silent, 1),
                job=(
                    WorkerJobOut(
                        id=job.id,
                        name=job.name,
                        status=job.status,
                        recipe=job.recipe,
                        solver=solver_of(job),
                        started_at=job.started_at,
                        cancelling=job.cancel_requested_at is not None,
                    )
                    if job is not None
                    else None
                ),
            )
        )

    counts = _queue_counts(db)
    oldest = _oldest_queued(db)
    living = [row for row in rows if _alive(row, now)]
    names = list(dict.fromkeys([*SOLVERS, *(name for name, _ in counts)]))
    queues = [
        SolverQueueOut(
            solver=name,
            queued=counts.get((name, "queued"), 0),
            running=counts.get((name, "running"), 0),
            oldest_queued_seconds=(
                round((now - oldest[name]).total_seconds(), 1) if name in oldest else None
            ),
            workers_alive=sum(1 for row in living if _takes(row, name)),
        )
        for name in names
    ]
    holders = [
        LicenseHolderOut(
            simulation_id=one.id,
            name=one.name,
            status=one.status,
            worker_id=one.worker_id,
            started_at=one.started_at,
        )
        for one in db.scalars(
            select(Simulation)
            .where(
                Simulation.deleted_at.is_(None),
                Simulation.status.in_(LICENSED_STATUSES),
                func.coalesce(Simulation.spec["solver"].astext, "ansys") == "ansys",
            )
            .order_by(Simulation.started_at)
        )
    ]
    return WorkersOut(
        workers=workers,
        queues=queues,
        license_holders=holders,
        alive=len(living),
    )


def solver_availability(db: Session) -> list[SolverAvailabilityOut]:
    """솔버마다 **집을 워커가 살아 있나** — 작업을 거는 화면이 경고에 쓴다.

    신호를 적는 워커가 하나도 없으면(옛 워커 · 인라인 설치) 알 수 없다 — 그때는 화면이
    경고하지 않게 `workers_alive` 를 -1 로 둔다. 「모른다」 를 「없다」 로 말하면 멀쩡한
    설치에서 사람을 놀라게 한다.
    """
    now = _now()
    rows = list(db.scalars(select(SimulationWorker)))
    counts = _queue_counts(db)
    known = bool(rows) and not get_settings().jobs_inline
    living = [row for row in rows if _alive(row, now)]
    return [
        SolverAvailabilityOut(
            solver=name,
            workers_alive=sum(1 for row in living if _takes(row, name)) if known else -1,
            queued=counts.get((name, "queued"), 0),
        )
        for name in SOLVERS
    ]


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
        # **형상 캐시는 작업 폴더들과 나란히 둔다** — 설계점마다 폴더가 다르므로 같은 형상을
        # 나눠 쓰려면 한 자리여야 한다. 지우면 다음 작업이 다시 만든다(덤이다).
        shape_cache=work_root() / ".shape-cache",
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
                ctx,
                should_cancel=lambda: (
                    _cancel_requested(db, simulation.id)
                    or not _still_mine(db, simulation.id, worker_id)
                ),
            )
        except StageCanceled:
            if not _still_mine(db, simulation.id, worker_id):
                # **다른 워커가 되살려 집어 갔다** — 아무것도 쓰지 않고 손을 뗀다.
                db.rollback()
                logger.warning(
                    "해석 작업 %s 를 다른 워커가 되살렸습니다 — 손을 뗍니다", simulation.id
                )
                return simulation
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
        if not _still_mine(db, simulation.id, worker_id):
            # 단계가 끝나는 사이 다른 워커가 집어 갔다 — 그 워커의 기록을 덮지 않는다.
            db.rollback()
            logger.warning(
                "해석 작업 %s 를 다른 워커가 되살렸습니다 — 손을 뗍니다", simulation.id
            )
            return simulation
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
    points = _study_points(db, user, study_id, every=True)
    freed = 0
    files = 0
    for point in points:
        if not is_final(point.status):
            continue
        done = tidy(db, user=user, simulation_id=point.id)
        freed += int(done["bytes_freed"])
        files += int(done["files"])
    # 정리는 다시 가져오기 전의 시도까지 하지만, 세는 것은 설계점이다 — 한 점의 두 시도를
    # 두 점으로 말하면 화면의 「설계점 N개」 가 스터디 표와 어긋난다.
    return {"bytes_freed": freed, "files": files, "points": len(_latest_per_point(points))}


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
            # 다시 가져와 대신한 작업이 있는 옛 시도는 「남은 일」 이 아니다.
            Simulation.source_meta["superseded_by"].astext.is_(None),
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
