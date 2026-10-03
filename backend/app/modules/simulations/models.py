"""해석 작업(Simulation)과 산출물(SimulationArtifact).

작업 하나 = 입력 형상 + 스펙 → 네 단계 → 산출물들. 상태 기계는 `app/core/stages.py` 의 것:

    queued → fetching → modeling → solving → extracting → done | failed

**DB 가 큐다.** `queued` 행을 워커가 `FOR UPDATE SKIP LOCKED` 로 집어 간다. 별도 큐 서버를 두지
않는 이유: 작업이 시간당 몇십 건이고, 큐 서버는 설치 · 백업 · 장애 지점을 하나 더 만든다
(AutoJigGenerator ADR 0003 과 같은 결정). 워커 수 = Mechanical 라이선스 수.

**지우지 않는다.** 결과로 만든 보고서가 밖에 남아 있다 — `deleted_at` 만 채운다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

#: 단계 이름이 곧 「지금 무엇을 하고 있나」 다. 상태와 단계를 따로 두면 언젠가 어긋난다.
STATUSES = (
    "queued",
    "fetching",
    "modeling",
    "solving",
    "extracting",
    "done",
    "failed",
    "canceled",
)
#: 워커가 붙잡고 있는 상태. 이 상태로 오래 멈춰 있으면 워커가 죽은 것이다(requeue_stale).
RUNNING_STATUSES = ("fetching", "modeling", "solving", "extracting")
#: 끝난 상태. 여기서는 더 안 움직인다.
FINAL_STATUSES = ("done", "failed", "canceled")


class Simulation(Base):
    __tablename__ = "simulations"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120))
    """사람이 붙인 이름. 안 주면 입력 파일 이름 — 목록에서 uuid 로는 아무것도 못 찾는다."""
    recipe: Mapped[str] = mapped_column(String(20), index=True)
    """modal · static … `app/core/spec.py` 의 레시피 이름."""
    status: Mapped[str] = mapped_column(
        String(20), default="queued", server_default="queued", index=True
    )

    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    """검증을 지난 스펙의 **스냅숏**. 나중에 스펙 형식이 바뀌어도 이 작업이 무엇으로 돌았는지는
    여기 남는다."""
    source_kind: Mapped[str] = mapped_column(
        String(20), default="upload", server_default="upload"
    )
    """입력 형상이 어디서 왔나 — upload · part_version · doe_point (뒤 둘은 5단계)."""
    source_ref: Mapped[str] = mapped_column(String(300), default="", server_default="")
    """업로드면 원본 파일 이름, DOE 면 `<스터디 이름>/pNNNN`."""
    source_meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    """이 작업이 **무엇의 결과인가**.

    DOE 면 스터디 id · 이름 · 점 번호 · 그 점에서 바꾼 변수(`params`) · 형상 열쇠
    (`shape_key` — 같은 STEP 을 가리키는 점들은 같은 형상이다) · 조건이 함께 왔는지.

    **CAD 로 되돌려 보내지 않기로 했으므로**(CompCore 0장) 「이 결과가 두께 8 짜리」 라는 것을
    이 플랫폼이 스스로 들고 있어야 한다. 설계점 비교 화면이 이 칸으로 묶는다."""
    input_sha256: Mapped[str] = mapped_column(String(64), index=True)
    """입력 형상의 해시. 같은 형상 + 같은 스펙이면 다시 안 돌리는 멱등성(5단계)의 열쇠."""

    owner_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    """어느 부서의 것인가. NULL 은 전역. 보이는 것은 `open_owner_clause` — 「우리 조직에 이
    모달 해석이 있나」 에 답해야 같은 해석을 두 번 안 돌린다(AGENTS.md)."""
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    work_dir: Mapped[str | None] = mapped_column(String(300), nullable=True)
    """작업 폴더 — `settings.work_dir` 기준 **상대 경로.** 절대경로를 넣으면 서버를 옮기는 날
    전부 틀린 값이 된다."""
    stages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    """단계 기록 `[{name, status, started_at, finished_at, detail, error_code,
    error_message}]`.
    도는 동안 화면이 이것을 폴링한다."""
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """단계들이 알아낸 것을 합친 것 — 절점 수 · 모드 수 · 1차 고유진동수."""
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    """실패 원인 코드(`app/core/stages.py` FailureCode). 코드여야 「라이선스로 몇 건」 을
    센다."""
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """사람이 취소를 누른 시각. **워커는 다른 프로세스라** 이 칸으로만 알 수 있다 — 단계
    사이와 자식 프로세스를 기다리는 동안 이것을 본다. 눌렀다고 곧바로 멈추지는 않는다."""

    worker_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """워커가 마지막으로 이 행을 만진 시각. 단계가 바뀔 때마다 찍는다 — 솔브는 몇 시간이라
    `started_at` 만으로는 「죽었나 오래 걸리나」 를 못 가른다."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class SimulationArtifact(Base):
    """작업이 남긴 파일 하나. 어느 단계가 만들었는지를 안다 — 재시도가 「솔버만 다시」 를 할 때
    모델링 산출물은 그대로 쓴다(5단계)."""

    __tablename__ = "simulation_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    simulation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("simulations.id", ondelete="RESTRICT"),
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20), index=True)
    """`app/core/stages.py` ArtifactKind — input_step · dat · rst · result_json · mode_png …"""
    filename: Mapped[str] = mapped_column(String(255))
    relative_path: Mapped[str] = mapped_column(String(300))
    """`settings.work_dir` 기준 상대 경로."""
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class SimulationWorker(Base):
    """워커 하나 — **살아 있다는 신호**와 무엇을 집는지 · 지금 하는 일.

    워커는 작업을 하는 동안에도(솔브 하나가 몇 시간) 따로 도는 줄에서 15초마다 신호를 적는다.
    신호가 2분 끊기면 그 워커는 죽은 것이고, 잡고 있던 작업은 다른 워커가 되살린다
    (`services.requeue_stale`). CompCore 의 `workers` 표와 같은 계약이다.

    **집는 솔버와 깔린 도구는 워커가 적는다.** `SIMULATION_SOLVERS` 는 워커마다 다른 환경
    파일에서 오고(`worker-<N>.env`), 도구는 워커의 기계 · 이미지에 있다 — API 프로세스가 제
    설정이나 제 `PATH` 로 답하면 그것은 그 워커의 사실이 아니다.
    """

    __tablename__ = "simulation_workers"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    """`호스트:pid` — 작업의 `worker_id` 와 같은 이름."""
    hostname: Mapped[str] = mapped_column(String(120), default="", server_default="")
    pid: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    version: Mapped[str] = mapped_column(String(40), default="", server_default="")
    executor: Mapped[str] = mapped_column(String(40), default="", server_default="")
    """fake · local · windows-bridge — 그 워커가 단계를 어디서 돌리나."""
    solvers: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    """집는 솔버. **비면 전부** 집는다(`SIMULATION_SOLVERS` 를 안 준 워커)."""
    tools: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    """그 워커가 기동 때 찾은 도구 — `{gmsh, ccx, ansys}`(`app/core/toolcheck.py`)."""
    state: Mapped[str] = mapped_column(String(20), default="idle", server_default="idle")
    """idle(기다림) · busy(작업 중) · stopping(끝내는 중) · stopped(멈춤)."""
    current_simulation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("simulations.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class SimulationMeasurement(Base):
    """실측 한 벌 — **센서 자리의 값**(공진 · FRF · 변위 · 변형률)을 작업이나 스터디에 붙인다.

    해석 결과와 견주는 일은 저장하지 않고 **읽을 때 한다**(`app/core/measured.py`) — 결과가
    다시 돌면(재시도 · 수렴 점검) 견준 값도 따라 바뀌어야 하는데, 저장해 두면 옛 결과와 견준
    수가 남는다. 여기에는 사람이 올린 실측만 둔다(기준 단위로 옮긴 줄들).

    **작업 하나 또는 스터디 하나**에 붙는다(둘 중 하나). 스터디에 붙이면 설계점마다 견주어
    「실측에 가장 가까운 설계점」 을 고른다 — 물성 · 감쇠를 훑은 DOE 라면 그것이 곧 차이를
    변수로 설명하는 일이다.
    """

    __tablename__ = "simulation_measurements"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    simulation_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("simulations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    study_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    """스터디는 행이 아니다 — 작업의 `source_meta.study_id`(없으면 이름)와 같은 글자."""
    owner_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(120))
    original_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    """기준 단위(mm · mm/s · mm/s² · 무차원)로 옮긴 실측 줄들."""
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
