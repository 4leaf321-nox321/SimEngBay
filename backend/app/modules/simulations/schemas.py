"""해석 작업 API 형태."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

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


class ConditionLine(BaseModel):
    """CAD 가 보낸 조건 한 줄 — **반영하나 안 하나**를 화면이 그대로 읽는다."""

    kind: str
    """`constraint` · `contact` · `load` · `mesh` · `frame` · `analysis`."""
    label: str
    detail: str = ""
    status: Literal["applied", "skipped", "refused"] = "applied"
    why: str = ""
    """넘기거나 막은 까닭 — 비어 있으면 반영한 것이다."""


class ConditionsOut(BaseModel):
    """작업 하나에 딸린 조건 전부.

    **없으면 `lines` 가 비어 있다** — 사람이 준 스펙으로 돈 것이다.
    """

    lines: list[ConditionLine] = []
    unit_system: str = ""
    prestressed: bool = False


class SimulationOut(SimulationSummaryOut):
    spec: dict[str, Any]
    stages: list[StageOut]
    error_message: str | None
    artifacts: list[ArtifactOut]
    attempts: int
    worker_id: str | None
    conditions: ConditionsOut = ConditionsOut()
    """CAD 가 보낸 조건과 **우리가 그것을 어떻게 다뤘나**. 조용히 무시하지 않으려고 싣는다."""


class SimulationCreateForm(BaseModel):
    """multipart 의 글자 칸들. 파일은 따로 온다(`file`)."""

    spec: dict[str, Any]
    """`app/core/spec.py` 의 JobSpec — 라우트가 JSON 문자열로 받아 여기 넣는다."""
    workspace_slug: str | None = None
    name: str | None = Field(default=None, max_length=120)


class DoePointPreview(BaseModel):
    """가져오기 전에 보여 줄 한 줄 — **걸 수 있나, 아니면 왜 못 거나.**"""

    number: int
    params: dict[str, float | str]
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
    suggested_modes: int | None = None
    """CAD 가 적어 보낸 모드 수 — 화면이 **미리 채우고 사람이 고친다.**

    조용히 쓰면 그쪽 기본값(6)이 우리 기본값(10)을 말없이 덮는다. 보여 주고 고르게 한다."""
    materials: list[str] = []
    """CAD 가 함께 보낸 재료 이름들. 비어 있으면 물성은 사람이 넣어야 한다 — 화면이 그 차이를
    말해 주지 않으면, 재료를 훑는 DOE 가 **이름만 다른 결과**로 돌아도 아무도 모른다."""
    suggested_recipe: str | None = None
    """CAD 가 적은 해석 종류(`modal` · `static` · `harmonic`). 화면이 레시피를 미리 고른다 —
    모달로 못 박아 두면 전단 이음 같은 정적 DOE 가 하중을 건너뛴 채 모달로 돈다."""
    suggested_element_size_mm: float | None = None
    """CAD 가 「전체」 로 적은 요소 크기(mm). **CalculiX 는 이것이나 사람이 준 값이 있어야
    돈다** — 둘 다 없으면 설계점마다 메시 단계에서 멈춘다."""


class DoeEntryOut(BaseModel):
    """탐색기의 한 줄."""

    name: str
    path: str
    is_study: bool
    """`manifest.csv` 가 있나 — **가져올 수 있는 폴더인가.**"""
    modified_at: datetime | None = None


class DoeListingOut(BaseModel):
    path: str
    parent: str | None = None
    """한 칸 위. **뿌리 밖으로는 못 올라간다** — 그때는 없다."""
    entries: list[DoeEntryOut]
    truncated: bool = False
    is_study: bool = False
    roots: list[str] = Field(default_factory=list)
    """설정된 공용 폴더들. 화면이 뿌리를 고르는 데 쓴다."""


class DoeImportRequest(BaseModel):
    path: str = Field(min_length=1)
    """가져올 폴더. **공용 폴더(DOE_ROOTS) 아래여야 한다.**

    브라우저가 파일을 올리는 것이 아니다 — 설계점 200개면 STEP 만 수십 MB 이고, 그 폴더는
    대개 공유 스토리지에 있다. 사람은 화면의 탐색기에서 고른다."""
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
    recipe: str = "modal"
    """가장 많은 점의 해석 종류. 한 스터디는 한 스펙으로 가져오므로 보통 하나다."""
    solvers: list[str] = Field(default_factory=list)
    """점들이 쓴 솔버. **둘이면 섞인 것이다** — 그 차이(몇 %)가 변수의 효과로 읽힐 수 있다."""
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
    params: dict[str, float | str]
    """바꾼 값. **숫자만이 아니다** — 재료처럼 고르는 인자가 온다."""
    status: str
    error_code: str | None = None
    recipe: str = "modal"
    solver: str = "ansys"
    first_elastic_hz: float | None = None
    mass_kg: float | None = None
    nodes: int | None = None
    frequencies: list[float] = Field(default_factory=list)
    """탄성 모드 주파수(앞에서부터). `k` 차 모드로 견주려면 이것이 있어야 한다."""
    # --- 정적 · 조화 — **늘 mm · MPa · N · Hz**(`app/core/values.py` 가 맞춘다). 결과 파일의
    # 단위가 솔버마다 달라서(Ansys 를 SI 로 돌리면 m · Pa) 여기서 맞추지 않으면 1000배 차이가
    # 숫자로만 보인다.
    max_displacement_mm: float | None = None
    max_von_mises_mpa: float | None = None
    peak_hz: float | None = None
    peak_displacement_mm: float | None = None
    reactions_n: dict[str, list[float]] = Field(default_factory=dict)
    """변위를 준 영역 → 반력 합 `[Fx, Fy, Fz]`(N)."""
    probes_mm: dict[str, float] = Field(default_factory=dict)
    """측정점 → 값(mm). 정적은 변위 크기, 조화는 **그 자리 곡선의 봉우리** 진폭."""
    probe_vectors_mm: dict[str, list[float]] = Field(default_factory=dict)
    """정적 — 측정점 → 변위 성분(mm). 같은 자리 두 바디의 차가 미끄럼이다."""
    probe_peaks_hz: dict[str, float] = Field(default_factory=dict)
    """조화 — 측정점 → 그 자리 곡선의 봉우리 주파수(Hz)."""
    relative_mm: dict[str, list[float]] = Field(default_factory=dict)
    """정적 — 같은 자리 · 다른 바디의 두 측정점 「A - B」 → 변위 차(mm). 전단 이음의 미끄럼."""


class ModeTrackOut(BaseModel):
    """기준 설계점의 모드 하나가 다른 점들에서 몇 번 모드인가.

    **순번으로 견주지 않는다.** 치수가 바뀌면 모드 순서가 뒤바뀌고(mode crossing), 그때
    「2차 대 두께」 는 서로 다른 모드를 이은 선이 된다.
    """

    reference: int
    """기준 설계점에서의 탄성 모드 번호(1차 · 2차 …)."""
    numbers: dict[int, int]
    """설계점 번호 → 그 점에서의 모드 번호. 못 이은 점은 빠진다."""
    confidence: dict[int, float]
    """설계점 번호 → MAC(0~1). 못 이었으면 가장 높았던 값."""


class StudyOut(BaseModel):
    study_id: str
    name: str
    factors: list[str]
    recipe: str = "modal"
    """가장 많은 점의 해석 종류 — 화면이 이것으로 비교 화면을 가른다."""
    solvers: list[str] = Field(default_factory=list)
    """점들이 쓴 솔버. 둘이면 섞인 것이다."""
    points: list[StudyPointOut]
    reference_point: int | None = None
    """모드를 잇는 기준이 된 설계점. 지문이 있는 첫 점이다."""
    tracks: list[ModeTrackOut] = Field(default_factory=list)


class RecipeOut(BaseModel):
    """화면이 새 작업 폼을 그리는 데 쓰는 레시피 목록과 JSON 스키마."""

    name: str
    runnable: bool
    schema_: dict[str, Any] = Field(alias="schema")
    model_config = ConfigDict(populate_by_name=True)


# --- 워커 · 솔버 -------------------------------------------------------------------


class WorkerJobOut(BaseModel):
    """워커가 지금 붙든 작업."""

    id: uuid.UUID
    name: str
    status: str
    recipe: str
    solver: str
    started_at: datetime | None = None
    cancelling: bool = False


WorkerState = Literal["idle", "busy", "stopping", "stopped", "lost"]


class WorkerOut(BaseModel):
    """워커 하나 — 살아 있나 · 무엇을 집나 · 무엇이 깔렸나 · 지금 무엇을 하나."""

    id: str
    hostname: str
    pid: int
    version: str
    executor: str
    solvers: list[str]
    """집는 솔버. **비면 전부.**"""
    tools: dict[str, Any]
    """그 워커가 기동 때 찾은 도구 `{gmsh, ccx, ansys}`."""
    state: WorkerState
    """`lost` 는 신호가 끊긴 것 — 워커가 적은 값이 아니라 서버가 판정한다."""
    started_at: datetime
    last_seen_at: datetime
    silent_seconds: float
    job: WorkerJobOut | None = None


class SolverQueueOut(BaseModel):
    """솔버 하나의 줄 — **기다리는 작업이 있는데 집을 워커가 없으면** 영원히 안 움직인다."""

    solver: str
    queued: int
    running: int
    oldest_queued_seconds: float | None = None
    workers_alive: int
    """이 솔버를 집는 살아 있는 워커 수(「전부」 를 집는 워커 포함)."""


class LicenseHolderOut(BaseModel):
    """Ansys 라이선스를 쥐고 있을 작업 — **모델링(Mechanical) · 솔버 단계**."""

    simulation_id: uuid.UUID
    name: str
    status: str
    worker_id: str | None = None
    started_at: datetime | None = None


class WorkersOut(BaseModel):
    """서버 화면의 「워커 · 솔버」 — 워커 · 솔버별 줄 · 라이선스를 쥔 작업."""

    workers: list[WorkerOut]
    queues: list[SolverQueueOut]
    license_holders: list[LicenseHolderOut]
    """**해석 작업 기준**이다 — 사람이 따로 연 Mechanical 이나 다른 플랫폼이 쥔 것은 못
    본다."""
    alive: int


class SolverAvailabilityOut(BaseModel):
    """솔버 하나를 지금 쓸 수 있나 — 작업을 거는 화면이 묻는다(관리자가 아니어도)."""

    solver: str
    workers_alive: int
    queued: int


# --- 메시 수렴 ----------------------------------------------------------------------


class ConvergenceRequest(BaseModel):
    """같은 설계점을 **요소 크기만 바꿔** 다시 푼다 — 크기마다 작업 하나."""

    sizes_mm: list[float] = Field(min_length=1, max_length=4)
    """새로 풀 전역 요소 크기들(mm). 원래 작업의 크기는 넣지 않아도 한 수준으로 들어간다."""
    solver: Literal["ansys", "calculix"] | None = None
    """비우면 원래 작업의 솔버. **솔버를 바꾸면 그 차이(몇 %)가 메시 차이로 읽힌다** — 그래서
    판정은 한 솔버의 수준끼리만 하고, 원래 크기도 그 솔버로 다시 푼다(CalculiX 로 점검하면
    Ansys 라이선스를 쓰지 않는다)."""


class ConvergenceLevelOut(BaseModel):
    """수준 하나 = 요소 크기 하나 = 작업 하나."""

    simulation_id: uuid.UUID
    element_size_mm: float | None = None
    nodes: int | None = None
    status: str
    solver: str
    is_original: bool = False


ConvergenceStatus = Literal[
    "converged", "not_converged", "oscillating", "diverging", "insufficient"
]


class ConvergenceMetricOut(BaseModel):
    """견준 값 하나와 그 판정(`app/core/convergence.py`)."""

    key: str
    label: str
    unit: str
    values: list[float | None]
    """`levels` 와 같은 순서."""
    status: ConvergenceStatus
    tolerance_pct: float
    change_pct: float | None = None
    """가장 촘촘한 두 수준의 상대 변화(%)."""
    order: float | None = None
    """관측 수렴 차수 — 수준이 셋 이상이어야 잰다."""
    gci_pct: float | None = None
    """격자 수렴 지수(%) — 가장 촘촘한 메시의 값이 무한히 촘촘한 값과 얼마나 다를 수 있나."""
    extrapolated: float | None = None
    note: str = ""


class ConvergenceOut(BaseModel):
    original_id: uuid.UUID
    recipe: str
    base_size_mm: float | None = None
    """원래 작업이 실제로 쓴 전역 요소 크기 — 화면이 줄일 크기를 이것으로 제안한다."""
    levels: list[ConvergenceLevelOut]
    """절점 수가 적은 것(성긴 것)부터."""
    metrics: list[ConvergenceMetricOut]
    notes: list[str] = Field(default_factory=list)
    """판정을 읽을 때 알아야 할 것 — 솔버가 섞였다 · 접촉 강성이 크기를 따라간다 등."""


# --- 실측 ---------------------------------------------------------------------------


class ResonanceMatchOut(BaseModel):
    """실측 공진 하나와 그 짝 — **센서 자리에서 움직이는 모드 중** 가장 가까운 것."""

    probe: str | None = None
    measured_hz: float
    mode: int | None = None
    """짝지은 모드의 전체 번호. 창(±25%) 안에 없으면 비운다 — 억지로 짓지 않는다."""
    elastic_number: int | None = None
    analysis_hz: float | None = None
    diff_pct: float | None = None
    visibility: float | None = None
    """그 모드가 센서 자리에서 얼마나 움직이나(그 자리 최대에 대한 비)."""
    ambiguous: bool = False
    """10% 안에 후보가 둘 이상 — 짝이 확실하지 않다."""


class FrequencyComparisonOut(BaseModel):
    matches: list[ResonanceMatchOut]
    mean_abs_pct: float | None = None
    max_abs_pct: float | None = None
    explanation: str = ""
    suggested_modulus_gpa: float | None = None


class FrfComparisonOut(BaseModel):
    """측정점 하나의 FRF — 실측과 해석을 **같은 물리량 · 같은 단위**로 겹친다."""

    probe: str
    quantity: str
    """displacement · velocity · acceleration — 해석 변위를 실측 물리량으로 옮겨 견준다."""
    unit: str
    measured: list[list[float]]
    """`[[Hz, 진폭], …]` — 화면에 실을 만큼 솎았다(봉우리는 남긴다)."""
    analysis: list[list[float]]
    measured_peak_hz: float | None = None
    analysis_peak_hz: float | None = None
    peak_diff_pct: float | None = None
    amplitude_ratio: float | None = None
    """해석 봉우리 / 실측 봉우리. 가진력으로 나눈 FRF 면 비운다."""
    measured_damping: float | None = None
    """실측 곡선의 반전력 대역에서 잰 감쇠비."""
    analysis_damping: float | None = None
    suggested_damping: float | None = None
    note: str = ""


class StaticMatchOut(BaseModel):
    probe: str | None = None
    kind: str
    """displacement · strain"""
    component: str
    """x · y · z · magnitude"""
    measured: float
    analysis: float | None = None
    unit: str
    """변위는 mm, 변형률은 무차원(빈 글자)."""
    diff_pct: float | None = None
    note: str = ""


class StaticComparisonOut(BaseModel):
    matches: list[StaticMatchOut]
    mean_abs_pct: float | None = None
    explanation: str = ""
    suggested_modulus_gpa: float | None = None


class ComparisonOut(BaseModel):
    """실측 한 벌과 작업 하나의 결과를 견준 것 — **읽을 때 견준다**(저장하지 않는다)."""

    recipe: str
    frequency: FrequencyComparisonOut | None = None
    frf: list[FrfComparisonOut] = Field(default_factory=list)
    static: StaticComparisonOut | None = None
    skipped: list[str] = Field(default_factory=list)
    """그 레시피로 못 견주는 종류와 그 까닭."""
    score_pct: float | None = None
    """차이의 절댓값 평균(%) — 스터디가 설계점을 줄 세운다."""


class MeasurementOut(BaseModel):
    id: uuid.UUID
    label: str
    original_name: str
    simulation_id: uuid.UUID | None = None
    study_id: str | None = None
    kinds: list[str]
    probes: list[str]
    rows: int
    created_at: datetime
    created_by_name: str | None = None
    comparison: ComparisonOut | None = None
    """작업에서 물었을 때 그 작업의 결과와 견준 것. 결과가 아직 없으면 비운다."""


class StudyMatchOut(BaseModel):
    """설계점 하나가 실측에 얼마나 가까운가."""

    simulation_id: uuid.UUID
    number: int
    params: dict[str, float | str]
    status: str
    score_pct: float | None = None


class StudyMeasurementOut(MeasurementOut):
    points: list[StudyMatchOut] = Field(default_factory=list)
    best_point: int | None = None
    """실측에 가장 가까운 설계점 번호 — 물성 · 감쇠를 훑은 DOE 면 그 값이 차이를 설명한다."""
    explanation: str = ""
