"""CAD 가 보낸 해석 조건을 읽는다 — **중립 표현 → 우리가 걸 수 있는 것.**

CompCore 는 점 파일에 조건 한 벌을 실어 보낸다: 구속 7종 · 하중 8종 · 접촉 · 초기조건 ·
메시 힌트 · 해석 설정 · 좌표계. 그쪽은 **솔버를 모르는 층**이고, 「`cylindrical` 을 Mechanical
의 무엇으로 거나」 는 우리 표다(CompCore 해석-조건-설계 4장).

## 걸 수 없는 것을 조용히 버리지 않는다

이 모듈이 내는 것은 **세 갈래**다:

| 갈래 | 뜻 | 모델링이 하는 일 |
| --- | --- | --- |
| `applied` | 우리가 Mechanical 에 거는 것 | 건다 |
| `skipped` | 이 레시피에서 **답을 바꾸지 않는 것** | 요약에 적고 넘어간다 |
| `refused` | 답을 바꾸는데 **아직 못 거는 것** | **멈춘다** |

조용히 버리면 사람은 「조건을 넣었는데 왜 결과가 같지」 를 영원히 모른다. 모달에서 하중이
그 자리다 — 선응력(`prestressed`)이 아니면 하중은 고유진동수를 **바꾸지 않는다**. 그것은
버그가 아니라 해석의 성질이므로 `skipped` 에 넣고 말해 준다. 반면 못 거는 구속은 `refused`
다: 구속이 빠지면 모드가 통째로 달라진다.

## 파트별 설정(`body_settings`, CompCore 2026-10-04)

파트(바디)마다 **거동 · 표현 · 해석 제외 · 메시**를 정한다. 이름은 점 파일 `bodies[].name`
(단품은 「전체」)이고, 해석 쪽 바디와는 부피 · 무게중심으로 짝짓는다(`app/core/bodies.py`).
적지 않은 파트는 기본값(변형체 · 솔리드 · 포함 · 메시는 위로 미룸)이다.

**쉘 파트**는 점 파일의 `midsurface`(파트마다 두께 · 넓이 · 무게중심, CompCore v0.8.1)와
`<형상>_mid.step` 의 중간면으로 푼다. 중간면이 없거나 CompCore 가 못 만들었으면(`failed[]`)
`refused` 다 — 솔리드로 풀면 다른 모델이 된다. 쉘 파트에 걸린 영역은 지문의 `mid`(중간면의
면 · 모서리 · 점)로 짝짓는다(`shell_view`). 파트 메시의 요소 형상 · 차수는 메시 힌트와 같이
**바람**이다 — 솔버가 못 따르면 `skipped` 에 적는다.

## 영역은 면만 안다

조건은 선택 그룹 이름으로 자리를 가리키고, 그 자리는 점 파일의 `regions` 에 설계점마다
풀려 있다. 우리 매처는 **면**만 짝지으므로(`app/core/regions`), 엣지 · 점 그룹을 가리키는
조건은 `refused` 다 — CompCore 에도 「접촉 · 압력 · 원통 지지는 면 그룹만」 으로 막아 달라고
적어 두었다(2026-09-28).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import Any, Literal

from app.core import cases, contract
from app.core.regions.match import not_a_face

#: 우리가 Mechanical 에 걸 수 있는 구속 — CompCore 의 7종 그대로.
CONSTRAINT_KINDS = (
    "fixed_support",
    "displacement",
    "remote_displacement",
    "frictionless",
    "cylindrical",
    "compression_only",
    "elastic_support",
)

#: 접촉 종류 — Mechanical 의 Contact Type 과 같은 이름이다.
CONTACT_KINDS = ("bonded", "no_separation", "frictional", "frictionless", "rough")

#: 모달에서 **답을 바꾸지 않는** 하중. 선응력 해석이 붙으면 그때 쓰인다.
_INERT_IN_MODAL = (
    "pressure",
    "force",
    "moment",
    "bearing",
    "bolt_pretension",
    "standard_earth_gravity",
    "acceleration",
    "rotational_velocity",
)

#: 하중이 답을 바꾸지 않는 레시피(선응력을 켜지 않으면) — 모드를 푸는 해석들. 랜덤 진동도
#: 모드를 풀고 가진은 PSD 로 따로 온다(`Psd`).
QUIET_LOADS = ("modal", "random")

#: 하중 종류 — CompCore 의 아홉(가속도 PSD 는 랜덤 진동의 가진이라 따로 읽는다, `_psd`).
LOAD_KINDS = (*_INERT_IN_MODAL, "psd_acceleration")

#: **선응력을 받는 해석** — 같은 하중의 정적을 앞에 풀고 그 응력을 안고 모드를 뽑는다. 솔버가
#: 더 좁힐 수 있다(Ansys 는 모달만 — `mechanical.build.PRESTRESS_RECIPES`).
PRESTRESS_RECIPES = ("modal", "random")
#: 조화 응답의 선응력은 **두 솔버 모두 받지 않는다** — 전에는 말없이 무시했다(CompCore 와 정함
#: 2026-11-27: CompCore 는 조화에 그 칸을 내지 않고, 우리는 실려 오면 막는다).
HARMONIC_PRESTRESS = (
    "조화 응답은 선응력을 받지 않습니다(CalculiX · Ansys 모두) — 선응력은 모달 · 랜덤 "
    "진동에서 씁니다"
)
#: **조화 응답이 받지 않는 하중**과 그 까닭 — 두 솔버 모두 작업을 만들 때 막는다.
#:
#: - 볼트 예압 · 회전 속도: 흔드는 하중이 아니다(조이거나 돌린 상태는 정적 · 선응력 모달이
#:   본다). 전에는 CalculiX 덱이 모델링에서야 막았고 Ansys 는 그대로 조화 쪽에 걸었다.
#: - 중력: 정적 하중이다. Mechanical 의 조화는 받지 않고(실측 2026-11-27, 2025 R2 — 넣으면
#:   「invalid object for the current analysis」 로 덜 정의된 채 풀기가 서지 않는다.
#:   가속도 · 압력 · 힘 · 모멘트 · 베어링은 풀린다), CalculiX 는 1 g **가진**으로 흔들었다 —
#:   사람은 「중력이 걸린 채」 로 읽는다. 사용자가 두 솔버 모두 막기로 정했다(2026-11-27).
#:   1 g 로 흔들려면 가속도 하중(배율 표 포함)으로 적는다.
_NOT_EXCITATION = "조화 응답의 가진으로 쓰지 않습니다 — 정적 · 선응력 모달에서 겁니다."
HARMONIC_REFUSED: dict[str, str] = {
    "bolt_pretension": _NOT_EXCITATION,
    # CompCore 의 저장 점검과 같은 뜻(ec46826).
    "standard_earth_gravity": "조화 응답에서는 중력을 받지 않습니다(CalculiX · Ansys 모두) — "
    "정적 중력도 가진도 아닙니다. 1 g 로 흔들려면 가속도 하중으로 적으세요.",
    "rotational_velocity": _NOT_EXCITATION,
}
HARMONIC_REFUSED_LOADS = tuple(HARMONIC_REFUSED)

#: 케이스로 나눈 조건을 케이스를 고르지 않고 읽으려 할 때.
CASES_UNPICKED = "해석 케이스로 나눈 조건입니다 — 케이스(사슬)를 골라 읽습니다"

#: 원격 변위의 원격점 자리 — 그룹 중심 · 좌표계 원점(CompCore 계약, 전역 좌표계면 막는다).
REMOTE_LOCATIONS = ("centroid", "cs_origin")

#: 파트 거동 · 표현 · 메시 — CompCore `BodySetting` · `BodyMesh` 의 값 그대로.
BODY_BEHAVIORS = ("deformable", "rigid")
BODY_REPRESENTATIONS = ("solid", "shell")
MESH_METHODS = ("automatic", "tetrahedrons", "hex_dominant", "sweep", "multizone")
MESH_ORDERS = ("program_controlled", "linear", "quadratic")
#: 「모든 파트」 — 단품이면 파트 이름이 이것이다(`materials.ALL_BODIES` 와 같은 말).
ALL_BODIES = "전체"
#: 메시 힌트가 「모델 전체」 를 가리키는 이름.
WHOLE_REGIONS = ("전체", "all")
#: 두께 없는 시트 파트(`bodies[].kind`, CompCore 2026-10-15). 부피가 0 이고 넓이가 온다.
SHEET = "sheet"
#: `shell_view` 가 옮긴 판에 다는 표 — 그 쉘 파트 이름들.
SHELL_VIEW = "_shell_view"
SHEET_AS_SOLID = (
    "두께 없는 시트(셸 모델)라 솔리드로 풀 수 없습니다 — CompCore 의 파트 설정에서 쉘로 두고 "
    "두께를 적으십시오"
)

Hold = Literal["fixed", "free"]


@dataclass(frozen=True)
class Constraint:
    """구속 하나 — **우리 말로 옮긴 것.**"""

    name: str
    kind: str
    region: str
    cs: str = "global"
    """좌표계 이름. `global` 이면 전역이다."""
    components: tuple[float | None, ...] = (None, None, None)
    """`displacement` · `remote_displacement` 의 이동 성분. **`None` 은 자유, 0 은 고정**,
    그 밖은 그만큼 움직인다(선언된 단위계의 길이)."""
    rotations: tuple[float | None, ...] = (None, None, None)
    """`remote_displacement` 의 회전 성분(도)."""
    radial: Hold = "fixed"
    axial: Hold = "fixed"
    tangential: Hold = "fixed"
    """`cylindrical` 의 방향마다 고정 · 자유."""
    stiffness: float | None = None
    """`elastic_support` 의 기초 강성(응력/길이)."""
    location: str = "centroid"
    behavior: str = "deformable"
    """`remote_displacement` 의 원격점과 면 거동."""


@dataclass(frozen=True)
class Frame:
    """좌표계 하나 — 구속 · 하중의 성분이 가리키는 방향.

    점 파일에 **설계점마다 풀려서** 온다(`{name, source, origin, x, y, z}`). 원점은 선언된
    단위계의 길이고(`length_units.coordinate_systems`), 축은 단위 벡터다.
    """

    name: str
    origin: tuple[float, float, float]
    x_axis: tuple[float, float, float]
    y_axis: tuple[float, float, float]
    z_axis: tuple[float, float, float]
    source: str = ""


@dataclass(frozen=True)
class Contact:
    """접촉 한 쌍 — 두 **면 그룹**이 만나는 자리."""

    name: str
    kind: str
    source: str
    target: str
    friction: float | None = None
    behavior: str = "program_controlled"
    formulation: str = "program_controlled"
    pinball: float | None = None
    """검색 반경 — **선언된 단위계의 길이**(쓸 때 `length_mm` 을 곱한다). 이 안의 면을 묶는다.
    비면 솔버가 정한다(CalculiX 는 요소 크기의 절반 — `calculix.build._bonded_ties`)."""
    interface_treatment: str = "program_controlled"
    """초기 간극 처리 — `adjust_to_touch`(종속 면을 주 면에 붙인다) · `add_offset_ramped` ·
    `add_offset_no_ramping`(Mechanical 의 이름 그대로)."""


@dataclass(frozen=True)
class Load:
    """하중 하나 — **선응력 모달**(정적 → 모달)에서 쓴다.

    크기는 선언된 단위계의 값이고(`unit` 이 함께 온다), 방향은 좌표계(`cs`)의 성분이거나
    `"normal"`(면의 법선 — 압력만)이다.
    """

    name: str
    kind: str
    region: str = ""
    cs: str = "global"
    magnitude: float | None = None
    unit: str = ""
    direction: tuple[float, float, float] | None = None
    normal: bool = False
    preload: float | None = None
    frequency_table: tuple[tuple[float, float], ...] | None = None
    """**조화 응답의 주파수별 배율**(CompCore 2026-11-17, 가진 프로파일) — `((Hz, 배율),
    …)`, 그
    주파수의 진폭 = `magnitude` x 배율, 사이는 주파수에 대해 선형 보간(CalculiX `*AMPLITUDE` 와
    같은
    뜻). `None` 이면 모든 주파수에서 1. 표는 해석의 주파수 범위를 다 덮는다(CompCore 가
    막는다)."""
    phase: float | None = None
    """조화 응답의 위상각(도). `None` · 0 이면 실수부만."""
    time_table: tuple[tuple[float, float], ...] | None = None
    """**정적의 시간별 배율**(CompCore ②, 2026-11-27) — `((시각, 배율), …)` 총 시각 기준, 양
    끝은 0 과 마지막 단계의 끝 시각, 사이는 선형. 회전 속도는 ω 에 곱한다. `None` 이면 아래
    규칙(`history.scale`)."""
    active_steps: tuple[int, ...] | None = None
    """**적용 단계**(1 부터) — 켜지는 단계 안에서 0 → 크기, 꺼지는 단계 안에서 0 으로 선형.
    `None` 이면 모든 단계(첫 단계에서 오르고 유지)."""
    bolt_steps: tuple[str, ...] | None = None
    """볼트의 단계마다 동작 — `load`(첫 단계) 뒤 `lock`. `None` 이면 같은 뜻이다."""


@dataclass(frozen=True)
class Psd:
    """**랜덤 진동의 가진** 하나 — 가속도 PSD(CompCore `psd_acceleration`, 2026-11-17).

    모든 고정 지지를 `direction` 으로 흔든다(`on` 이 비어 있다). 표는 `((Hz, g²/Hz), …)` 이고
    사이는 로그-로그 보간, 표 밖은 0 이다(`random_vibration.psd_at`). 여럿이면 서로 무관한
    가진으로 더한다.
    """

    name: str
    table: tuple[tuple[float, float], ...]
    direction: tuple[float, float, float]
    cs: str = "global"
    grms: float | None = None
    """CompCore 가 표로 셈한 입력 Grms(g) — 우리 셈과 견주는 데만 쓴다."""


@dataclass(frozen=True)
class MeshHint:
    """메시는 우리가 만든다 — 이것은 **바람**이다.

    CompCore 2026-10-04 부터 「국부 메시」 다: 「전체」 또는 **면 · 엣지** 그룹만 가리키고,
    요소 형상 · 차수는 「전체」 에만 온다. 파트 하나 전체는 `body_settings` 가 든다.
    """

    region: str
    """`전체` 또는 선택 그룹 이름."""
    element_size: float | None = None
    """선언된 단위계의 길이. SI 폴더면 m 로 온다."""
    order: str = ""
    method: str = ""

    @property
    def whole(self) -> bool:
        return self.region in WHOLE_REGIONS


@dataclass(frozen=True)
class BodySetting:
    """파트(바디) 하나를 해석에서 어떻게 다루나 — CompCore `body_settings[]` 한 줄.

    **강체**는 변형하지 않는 것으로 푼다(질량 · 관성은 남는다). **해석 제외**는 형상에는 남기고
    해석에서만 뺀다 — 물성도 필요 없다. 메시 칸은 그 파트 전체의 요소 크기 · 형상 · 차수다.
    """

    name: str
    rigid: bool = False
    suppressed: bool = False
    shell: bool = False
    """중간면 + 두께로 쉘 요소를 짓는다."""
    thickness: float | None = None
    """쉘 두께(mm, 점 파일 `midsurface.bodies[].thickness`)."""
    element_size: float | None = None
    """선언된 단위계의 길이(SI 폴더면 m). 비면 위(전역 크기)로 미룬다."""
    method: str = "automatic"
    order: str = "program_controlled"

    @property
    def meshed(self) -> bool:
        """메시 칸을 하나라도 정했나."""
        return (
            self.element_size is not None
            or self.method != "automatic"
            or self.order != "program_controlled"
        )

    def describe(self) -> str:
        """사람이 읽는 한 줄 — 「강체 · 요소 4 mm」."""
        if self.suppressed:
            return "해석 제외"
        parts = ["강체" if self.rigid else "변형체"]
        if self.shell:
            parts.append(f"쉘 {self.thickness:g} mm" if self.thickness else "쉘")
        if self.element_size is not None:
            parts.append(f"요소 {self.element_size:g}")
        if self.method != "automatic":
            parts.append(_METHOD_LABELS.get(self.method, self.method))
        if self.order != "program_controlled":
            parts.append(_ORDER_LABELS.get(self.order, self.order))
        return " · ".join(parts)


_METHOD_LABELS = {
    "tetrahedrons": "사면체",
    "hex_dominant": "육면체 우세",
    "sweep": "스윕",
    "multizone": "멀티존",
}
_ORDER_LABELS = {"linear": "1차", "quadratic": "2차"}


@dataclass(frozen=True)
class Analysis:
    """무엇을 풀라고 했나 — 우리 스펙과 견주는 데 쓴다."""

    kind: str = "modal"
    modes: int | None = None
    frequency_range: tuple[float, float] | None = None
    prestressed: bool = False
    #: 조화 응답의 감쇠비. **봉우리 높이를 거의 이 값이 정한다**(1/2ζ) — CAD 가 적어 보내면
    #: 그것으로 푼다. 스펙 기본값으로 조용히 덮으면 CAD 가 2% 라고 한 모델이 5% 로 풀린다.
    damping_ratio: float | None = None
    #: 범위를 몇 점으로 나눠 푸나. 점이 적으면 **봉우리가 점 사이로 빠져나간다**(실측).
    intervals: int | None = None
    #: 정적의 큰 변형(기하 비선형). CompCore 는 정적이면 늘 적는다(기본 거짓) — 안 적었으면
    #: `None`(정적 폴더가 아니거나 옛 폴더).
    large_deflection: bool | None = None
    #: 정적의 **초기 부단계 수** — 비선형(큰 변형 · 접촉)을 몇 걸음으로 나눠 시작하나. 비면
    #: 받는 쪽이 정한다.
    substeps: int | None = None
    #: 정적의 **하중 단계**(CompCore ②) — 비면 한 단계(v1 그대로).
    load_steps: tuple[LoadStep, ...] = ()


@dataclass(frozen=True)
class LoadStep:
    """하중 단계 하나(CompCore ② `analysis.load_steps[i]`) — 끝 시각(총 시각)과 부단계 수.

    부단계는 최소 ≤ 처음 ≤ 최대이고, 비면 받는 쪽이 정한다(`history.increments`)."""

    name: str
    end_time: float
    initial: int | None = None
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class Note:
    """걸지 않은 조건 하나와 그 까닭 — 요약 · 화면이 이 말을 그대로 보여 준다."""

    what: str
    why: str


@dataclass(frozen=True)
class Stage:
    """사슬(판 2)의 **앞 정적 케이스** 하나 — 그 케이스에 걸린 하중과 해석 설정. 뒤 케이스는 그
    끝 상태에서 시작하고 **하중은 이어지지 않는다**(조인 볼트만 그 길이로 잠긴 채 이어진다)."""

    name: str
    loads: list[Load]
    analysis: Analysis


@dataclass(frozen=True)
class StaticCase:
    """정적으로 풀 케이스 하나(`Conditions.static_cases`) — 이름이 비면 판 1 의 한 벌이다."""

    name: str
    loads: list[Load]
    analysis: Analysis


@dataclass
class Conditions:
    """점 파일 한 장에서 읽은 조건 — **걸 것 · 넘길 것 · 막을 것**으로 갈라 둔다."""

    constraints: list[Constraint] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    """이름 붙인 좌표계. 구속의 `cs` 가 이 이름을 가리킨다."""
    loads: list[Load] = field(default_factory=list)
    """**선응력 모달에서만 쓴다.** 그냥 모달이면 `skipped` 에 적고 여기는 비운다."""
    psd: list[Psd] = field(default_factory=list)
    """랜덤 진동의 가진(가속도 PSD) — `loads` 와 따로 둔다: 정적 단계에 걸 하중이 아니고,
    `prestressed` 는 `loads` 로 판정한다."""
    mesh_hints: list[MeshHint] = field(default_factory=list)
    suggested_size_mm: float | None = None
    """CompCore 가 형상으로 셈한 전역 요소 크기 **제안값**(mm, `mesh_suggestion`) — 조건
    밖이다. 사람이 「전체」 크기를 적었으면 그것이 먼저다(`global_size`)."""
    suggested_basis: str = ""
    """그 제안의 까닭(「최소 벽 두께(5 mm, 「받침판」)의 절반」 같은 것) — 화면에 그대로
    보인다."""
    body_settings: list[BodySetting] = field(default_factory=list)
    """파트별 설정 — 적힌 파트만. 쉘 파트는 여기 오지 않고 `refused` 에 있다."""
    analysis: Analysis = field(default_factory=Analysis)
    stages: list[Stage] = field(default_factory=list)
    """사슬(판 2)의 앞 정적 케이스들 — 차례대로. v1 으로 접히는 사슬과 판 1 은 비어 있다
    (`app/core/cases.py`)."""
    case: str = ""
    """판 2 면 끝 케이스의 이름(보기의 `conditions.case`) — 판 1 이면 빈 글자."""
    skipped: list[Note] = field(default_factory=list)
    """이 레시피에서 답을 바꾸지 않는 것 — 하중처럼."""
    refused: list[Note] = field(default_factory=list)
    """답을 바꾸는데 아직 못 거는 것. **하나라도 있으면 모델링은 멈춘다.**"""

    @property
    def empty(self) -> bool:
        return not (
            self.constraints
            or self.contacts
            or self.mesh_hints
            or self.loads
            or self.psd
            or self.body_settings
        )

    @property
    def suppressed(self) -> set[str]:
        """해석에서 뺀 파트 이름."""
        return {one.name for one in self.body_settings if one.suppressed}

    @property
    def rigid(self) -> set[str]:
        """강체로 푸는 파트 이름(뺀 파트는 빼고)."""
        return {one.name for one in self.body_settings if one.rigid and not one.suppressed}

    @property
    def shells(self) -> dict[str, float]:
        """쉘로 푸는 파트 → 두께(mm)."""
        return {
            one.name: float(one.thickness or 0.0)
            for one in self.body_settings
            if one.shell and not one.suppressed
        }

    @property
    def whole_mesh(self) -> MeshHint | None:
        """「전체」 메시 힌트 — 전역 크기 · 요소 형상 · 차수."""
        return next((one for one in self.mesh_hints if one.whole), None)

    def global_size(self, length_mm: float) -> tuple[float, Literal["cad", "compcore"]] | None:
        """전역 요소 크기(mm)와 **어디서 왔나** — 「전체」 메시 힌트, 없으면 CompCore 의
        제안값.

        차례는 CompCore 와 맞춘 것이다(2026-10-23): 파트 · 면 · 엣지 크기는 이것과 따로 그대로
        쓰고, 전역만 「전체」 → 제안 순서로. 힌트는 **선언된 계의 길이**라(SI 면 m) `length_mm`
        을 곱하고, 제안은 늘 mm 다. 스펙의 크기는 이보다 먼저다 — 그것은 부르는 쪽이 본다.
        """
        for one in self.mesh_hints:
            if one.whole and one.element_size is not None:
                return one.element_size * length_mm, "cad"
        if self.suggested_size_mm is not None:
            return self.suggested_size_mm, "compcore"
        return None

    @property
    def drives(self) -> bool:
        """**강제로 움직이는 구속이 있나** — 0 이 아닌 변위 · 원격 변위(회전 포함).

        시편 시험은 대부분 힘이 아니라 변위로 당긴다(그립 고정 · 그립 강제 변위). 그런 정적
        해석은 하중이 없어도 답이 있다 — 「걸린 하중이 하나도 없다」 로 막으면 안 된다
        (CompCore 시험 규격 픽스처, 2026-10-07: E8 · D5766 · D695 … 일곱이 그 점검에 막혔다).
        """
        return any(
            one.kind in ("displacement", "remote_displacement")
            and any(value not in (None, 0) for value in (*one.components, *one.rotations))
            for one in self.constraints
        )

    @property
    def driven(self) -> bool:
        """답을 만들 것이 있나 — 하중이 있거나(앞 정적 케이스의 것까지) 강제로 움직인다(정적 ·
        조화의 점검)."""
        return bool(self.all_loads) or self.drives

    @property
    def prestressed(self) -> bool:
        """정적 해석을 먼저 풀어야 하나 — **하중이 있고 선응력을 켰을 때**(판 2 면 앞 정적
        케이스가 있을 때)."""
        return self.analysis.prestressed and bool(self.loads or self.stages)

    @property
    def all_loads(self) -> list[Load]:
        """앞 정적 케이스들의 하중까지 모두 — 하중 자리 · 볼트 단면을 메시에서 세울 때."""
        return [*(load for stage in self.stages for load in stage.loads), *self.loads]

    def static_cases(self) -> list[StaticCase]:
        """정적으로 **차례대로** 풀 케이스들 — 앞 정적 케이스(`stages`)와, 끝이 정적이면 끝
        케이스. 판 1 은 한 벌(선응력 모달이면 그 앞 정적)이다. 모드 해석(모달 · 랜덤)의 끝
        케이스는 정적으로 풀 것이 없다 — 그 하중은 앞 정적에 있다."""
        out = [StaticCase(one.name, one.loads, one.analysis) for one in self.stages]
        if self.analysis.kind == "static" or not self.stages:
            out.append(StaticCase(self.case, self.loads, self.analysis))
        return out


def read(payload: Any, *, recipe: str = "modal") -> Conditions:
    """점 파일(`pNNNN.json`) 한 장 → 조건.

    **조건이 없으면 빈 것을 돌려준다**(오류가 아니다) — 형상만 온 폴더도 있고, 그때는 사람이
    화면에서 준 스펙으로 돈다.
    """
    block = _dict(_dict(payload).get("conditions"))
    made = Conditions()
    # **제안은 조건 밖에 온다** — 조건이 비어도(형상만 보낸 폴더) 전역 크기는 쓸 수 있다.
    made.suggested_size_mm, made.suggested_basis = _suggestion(payload)
    if not block:
        return made
    # **모르는 판이면 아무것도 안 읽는다** — 칸의 자리가 다르면 비어 있는 것과 못 찾은 것을 못
    # 가린다(`contract.py`).
    unknown = contract.problem(payload)
    if unknown:
        made.refused.append(Note("조건의 판", unknown))
        return made
    if cases.is_cases(payload):
        # **케이스로 나눈 조건(v2)은 케이스를 골라 읽는다** — 작업마다 v1 모양 한 벌로 편 것
        # (`cases.view`)을 읽는다. 날것을 읽으면 맨 위가 비어 「조건 없음」 으로 읽힌다.
        made.refused.append(Note("해석 케이스", CASES_UNPICKED))
        return made

    regions = set(_dict(payload).get("regions") or {})
    # **해석 설정을 먼저 읽는다** — 선응력인지에 따라 하중을 걸지 넘길지가 갈린다.
    made.analysis = _analysis(_dict(block.get("analysis")))
    broken_steps = steps_problem(_dict(block.get("analysis")))
    if broken_steps:
        made.refused.append(Note("해석 설정 (하중 단계)", broken_steps))
    if recipe == "harmonic" and made.analysis.prestressed:
        # 모달로 적은 점 파일을 조화로 돌려도 같다 — 선응력을 빼고 풀면 CAD 가 적은 것과 다른
        # 해석이다.
        made.refused.append(Note("해석 설정 (선응력 반영)", HARMONIC_PRESTRESS))
    if made.analysis.kind and made.analysis.kind != recipe:
        # **다른 해석을 하라고 적혀 있다.** 막지는 않는다 — 사람이 모달로 돌려 보는 일은
        # 흔하다. 다만 말해 주지 않으면 「CAD 가 시킨 대로 돈 것」 으로 읽는다.
        made.skipped.append(
            Note(
                f"해석 설정 ({made.analysis.kind})",
                f"이 작업은 {recipe} 로 돕니다 — CAD 는 {made.analysis.kind} 를 적었습니다",
            )
        )
    made.frames = _frames(payload, block)
    # **파트별 설정을 먼저 읽는다** — 뺀 파트에 걸린 조건을 가려야 한다.
    middle = _midsurface(payload)
    for row in _rows(block, "body_settings"):
        _body_setting(row, made, middle)
    # **시트는 쉘로 풀거나 뺀다** — 부피가 0 이라 솔리드로 풀 길이 없다. 설정 줄이 이미 막힌
    # 시트(두께를 못 받은 쉘)는 그 까닭이 먼저 섰다.
    halted = {str(row.get("name") or "") for row in _rows(block, "body_settings")}
    halted -= {one.name for one in made.body_settings}
    for name in loose_sheets(payload, made):
        if name not in halted:
            made.refused.append(Note(f"파트 「{name}」", SHEET_AS_SOLID))
    gone = _on_suppressed(payload, made.suppressed)
    # **이미 중간면으로 옮긴 판**(`shell_view`)이면 옮겼나를 다시 묻지 않는다 — 옮긴 행에는
    # `mid` 가 없어 모두 「못 옮겼다」 로 막혔다. 그 판으로 조건을 읽던 Ansys 추출이 쉘 파트의
    # 구속을 통째로 잃고 반력을 비워 냈다(2026-10-16, 시트 외팔보).
    flat = {} if _dict(payload).get(SHELL_VIEW) else _off_midsurface(payload, set(made.shells))
    entities = {
        str(one.get("name") or ""): str(one.get("entity") or "face")
        for one in _rows(block, "named_selections")
    }
    odd = _not_faces(payload, entities)
    known = {one.name for one in made.frames}
    for row in _rows(block, "constraints"):
        _needs_frame(row, known, made)
    for row in _rows(block, "constraints"):
        place = str(row.get("on") or "")
        if place in gone:
            made.refused.append(
                Note(
                    f"구속 「{row.get('name') or '이름 없는 구속'}」",
                    f"해석에서 뺀 파트({gone[place]})에 걸려 있습니다 — 거기에는 형상이 "
                    "없습니다",
                )
            )
            continue
        if place in flat:
            made.refused.append(
                Note(f"구속 「{row.get('name') or '이름 없는 구속'}」", flat[place])
            )
            continue
        if place in odd:
            made.refused.append(
                Note(f"구속 「{row.get('name') or '이름 없는 구속'}」", odd[place])
            )
            continue
        _constraint(row, regions, made)
    wrong = misplaced(payload)
    for row in _rows(block, "contacts"):
        ends = [str(row.get(key) or "") for key in ("source", "target")]
        hit = next((gone[one] for one in ends if one in gone), None)
        if hit is not None:
            # 한쪽 파트가 없으면 접촉도 없다 — Ansys 도 그 접촉을 스스로 끈다(실측).
            made.skipped.append(
                Note(
                    f"접촉 「{row.get('name') or '이름 없는 접촉'}」",
                    f"해석에서 뺀 파트({hit})의 접촉이라 뺐습니다",
                )
            )
            continue
        stuck = next((flat[one] for one in ends if one in flat), None)
        if stuck is None:
            stuck = next((odd[one] for one in ends if one in odd), None)
        if stuck is not None:
            made.refused.append(Note(f"접촉 「{row.get('name') or '이름 없는 접촉'}」", stuck))
            continue
        flagged = wrong.pop(_contact_key(row), None)
        if flagged is not None:
            made.refused.append(
                Note(f"접촉 「{row.get('name') or '이름 없는 접촉'}」", flagged)
            )
            continue
        _contact(row, regions, made)
    for (name, _source, _target), why in wrong.items():
        # 판정은 있는데 조건에 그 접촉이 없다 — 두 목록이 어긋났다. 모르는 채로 풀지 않는다.
        made.refused.append(Note(f"접촉 「{name or '이름 없는 접촉'}」", why))
    for row in _rows(block, "mesh_hints"):
        _mesh_hint(row, made, _dict(_dict(payload).get("regions")), entities)
    for row in _rows(block, "loads"):
        _read_load(row, recipe, made, gone, flat, odd, entities)
    for row in _rows(block, "initial"):
        _initial(row, recipe, made)
    case = block.get("case")
    made.case = str(case.get("name") or "") if isinstance(case, dict) else ""
    for row in _rows(block, "stages"):
        # **사슬의 앞 정적 케이스**(판 2, `cases.view`) — 하중은 정적으로 읽고 말에는 케이스를
        # 단다.
        name = str(row.get("name") or "")
        part = Conditions(frames=made.frames, analysis=_analysis(_dict(row.get("analysis"))))
        for one in _rows(row, "loads"):
            _read_load(one, "static", part, gone, flat, odd, entities)
        made.stages.append(Stage(name=name, loads=part.loads, analysis=part.analysis))
        made.refused += [
            Note(f"케이스 「{name}」 · {one.what}", one.why) for one in part.refused
        ]
        made.skipped += [
            Note(f"케이스 「{name}」 · {one.what}", one.why) for one in part.skipped
        ]
    return made


def _read_load(
    row: dict[str, Any],
    recipe: str,
    made: Conditions,
    gone: dict[str, str],
    flat: dict[str, str],
    odd: dict[str, str],
    entities: dict[str, str],
) -> None:
    """하중 한 줄 — 뺀 파트 · 중간면 · 면이 아닌 자리를 먼저 본 뒤 `_load`."""
    place = str(row.get("on") or "")
    if place in gone:
        what = f"하중 「{row.get('name') or '이름 없는 하중'}」"
        why = f"해석에서 뺀 파트({gone[place]})에 걸려 있습니다"
        if recipe in QUIET_LOADS and not made.analysis.prestressed:
            made.skipped.append(Note(what, why + " — 모달이라 답과 상관없습니다"))
        else:
            made.refused.append(Note(what, why + " — 거기에는 형상이 없습니다"))
        return
    live = not (recipe in QUIET_LOADS and not made.analysis.prestressed)
    if place in flat and live:
        made.refused.append(
            Note(f"하중 「{row.get('name') or '이름 없는 하중'}」", flat[place])
        )
        return
    bolted_body = (
        str(row.get("type") or "") == "bolt_pretension" and entities.get(place) == "body"
    )
    if place in odd and live and not bolted_body:
        made.refused.append(
            Note(f"하중 「{row.get('name') or '이름 없는 하중'}」", odd[place])
        )
        return
    if bolted_body and live and str(row.get("cs") or "") in GLOBAL_FRAMES:
        # **바디에 건 예압은 단면을 좌표계로 정한다**(CompCore 2f402f2 — 우리가 고른 (가)):
        # Z 축이 볼트 축, 원점이 단면 자리. Ansys 의 바디 예압과 같은 뜻이다. 전역이면
        # 원점(0, 0, 0)을 지나는 평면이라 거의 늘 엉뚱한 자리다 — CompCore 도 저장할 때
        # 막는다.
        made.refused.append(
            Note(
                f"하중 「{row.get('name') or '이름 없는 하중'}」",
                "바디에 건 볼트 예압은 좌표계가 있어야 합니다 — Z 축이 볼트 축, 원점이 "
                "단면 자리입니다",
            )
        )
        return
    _load(row, recipe, made)


# --- 갈래마다 ------------------------------------------------------------------


#: `cs` 가 이 이름이면 전역이다 — CompCore 와 같은 말을 쓴다.
GLOBAL_FRAMES = {"", "global", "전역"}


def _frames(payload: dict[str, Any], block: dict[str, Any]) -> list[Frame]:
    """점 파일의 `coordinate_systems` — 설계점마다 풀린 원점과 축.

    조건 블록에도 같은 이름의 정의가 있지만 그것은 **식이 섞인 원본**이다. 푼 값은 점 파일
    바깥에 실려 오므로 그쪽을 쓴다.
    """
    rows = _dict(payload).get("coordinate_systems")
    if not isinstance(rows, list):
        rows = block.get("coordinate_systems") if isinstance(block, dict) else None
    made: list[Frame] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        origin = _triple(row.get("origin"))
        x_axis = _triple(row.get("x")) or (1.0, 0.0, 0.0)
        y_axis = _triple(row.get("y")) or (0.0, 1.0, 0.0)
        z_axis = _triple(row.get("z")) or (0.0, 0.0, 1.0)
        if not name or origin is None:
            continue
        made.append(
            Frame(
                name=name,
                origin=origin,
                x_axis=x_axis,
                y_axis=y_axis,
                z_axis=z_axis,
                source=str(row.get("source") or ""),
            )
        )
    return made


def _needs_frame(row: dict[str, Any], known: set[str], made: Conditions) -> None:
    """**모르는 좌표계를 조용히 전역으로 읽지 않는다** — 성분이 딴 방향으로 걸린다."""
    name = str(row.get("cs") or "").strip()
    kind = str(row.get("type") or "")
    if kind not in ("displacement", "remote_displacement"):
        # 나머지 종류는 좌표계를 안 쓴다(원통은 원통의 축, 면 지지는 면을 따른다).
        return
    if name.lower() in GLOBAL_FRAMES or name in known:
        return
    made.refused.append(
        Note(
            f"구속 「{row.get('name') or kind}」",
            f"가리키는 좌표계 「{name}」 가 점 파일에 없습니다",
        )
    )


def _triple(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, list | tuple) or len(value) != 3:
        return None
    made = [_number(one) for one in value]
    if any(one is None for one in made):
        return None
    return (float(made[0]), float(made[1]), float(made[2]))  # type: ignore[arg-type]


def _constraint(row: dict[str, Any], regions: set[str], made: Conditions) -> None:
    name = str(row.get("name") or "이름 없는 구속")
    kind = str(row.get("type") or "")
    region = str(row.get("on") or "")
    if kind not in CONSTRAINT_KINDS:
        made.refused.append(Note(f"구속 「{name}」", f"모르는 종류입니다: {kind}"))
        return
    if not region:
        made.refused.append(Note(f"구속 「{name}」", "걸 자리(선택 그룹)가 비어 있습니다"))
        return
    if region not in regions:
        # **CAD 가 못 푼 그룹이다.** 그대로 두면 구속 없는 해석이 끝까지 돈다.
        made.refused.append(
            Note(f"구속 「{name}」", f"「{region}」 이 점 파일의 영역에 없습니다")
        )
        return

    location = str(row.get("location") or "centroid")
    cs = str(row.get("cs") or "global")
    if kind == "remote_displacement" and location not in REMOTE_LOCATIONS:
        made.refused.append(Note(f"구속 「{name}」", f"모르는 원격점 자리입니다: {location}"))
        return
    if location == "cs_origin" and cs.lower() in GLOBAL_FRAMES:
        # 전역 원점은 형상과 상관없는 자리라 거의 늘 실수다 — CompCore 도 저장할 때 막는다.
        made.refused.append(
            Note(f"구속 「{name}」", "원격점을 좌표계 원점에 세우려면 좌표계가 있어야 합니다")
        )
        return

    made.constraints.append(
        Constraint(
            name=name,
            kind=kind,
            region=region,
            cs=cs,
            components=tuple(_number(row.get(axis)) for axis in ("x", "y", "z")),
            rotations=tuple(_number(row.get(axis)) for axis in ("rx", "ry", "rz")),
            radial=_hold(row.get("radial")),
            axial=_hold(row.get("axial")),
            tangential=_hold(row.get("tangential")),
            stiffness=_number(row.get("stiffness")),
            location=location,
            behavior=str(row.get("behavior") or "deformable"),
        )
    )


#: CompCore 가 **잘못 걸렸다고 판정한 접촉**(점 파일 `quality.misplaced_contacts`, CompCore
#: v0.31.1 — 2026-11-26). 접촉 자동 찾기가 면의 중심으로 규칙을 지어(v0.26.0 ~ v0.31.0) 본딩
#: 면이 딴 면에 걸렸다 — 중심이 구멍 속인 면, 딴 바디와 자리가 같은 면(판 구멍 ↔ 볼트 몸통).
#: 면 지문은 그 딴 면과 맞으므로 우리 짝짓기로는 못 가린다. 저장된 규칙이라 다시 내보내도
#: 남는다.
MISPLACED_TEXT = {
    "same_face": "두 그룹이 같은 면을 가리킵니다 — 면이 제 자신과 묶일 뿐 바디는 안 묶입니다",
    "apart": "두 그룹이 맞닿아 있지 않습니다 — 떨어지지 않는 접촉인데 묶을 면이 없습니다",
}


def _contact_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("name") or ""),
        str(row.get("source") or ""),
        str(row.get("target") or ""),
    )


def misplaced(payload: Any) -> dict[tuple[str, str, str], str]:
    """`quality.misplaced_contacts` → (이름, 접촉면, 대상면) → 막는 까닭. CompCore 가 「틀림」
    만 싣는다(같은 면은 늘, 맞닿지 않음은 본딩 · 분리 없음일 때만) — **실린 것은 모두
    막는다.**"""
    rows = _dict(_dict(payload).get("quality")).get("misplaced_contacts")
    out: dict[tuple[str, str, str], str] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        problem = str(row.get("problem") or "")
        what = MISPLACED_TEXT.get(
            problem, f"CompCore 가 잘못 걸린 접촉으로 판정했습니다({problem})"
        )
        source, target = row.get("source") or "", row.get("target") or ""
        out[_contact_key(row)] = (
            f"{what}(접촉면 「{source}」 · 대상면 「{target}」, CompCore 판정). CompCore 에서 "
            "그 선택 그룹을 고쳐 다시 내보내세요."
        )
    return out


def _contact(row: dict[str, Any], regions: set[str], made: Conditions) -> None:
    name = str(row.get("name") or "이름 없는 접촉")
    kind = str(row.get("type") or "")
    source, target = str(row.get("source") or ""), str(row.get("target") or "")
    if kind not in CONTACT_KINDS:
        made.refused.append(Note(f"접촉 「{name}」", f"모르는 종류입니다: {kind}"))
        return
    missing = [one for one in (source, target) if one not in regions]
    if missing:
        made.refused.append(
            Note(f"접촉 「{name}」", f"영역에 없는 그룹입니다: {' · '.join(missing)}")
        )
        return
    made.contacts.append(
        Contact(
            name=name,
            kind=kind,
            source=source,
            target=target,
            friction=_number(row.get("friction")),
            behavior=str(row.get("behavior") or "program_controlled"),
            formulation=str(row.get("formulation") or "program_controlled"),
            pinball=_number(row.get("pinball")),
            interface_treatment=str(row.get("interface_treatment") or "program_controlled"),
        )
    )


def _mesh_hint(
    row: dict[str, Any],
    made: Conditions,
    regions: dict[str, Any],
    entities: dict[str, str],
) -> None:
    """국부 메시 한 줄. **「전체」 · 면 그룹은 걸고, 바디 그룹(옛 파일)은 파트 메시로 옮기고,
    엣지 그룹은 아직 못 걸어 적는다** — 메시는 바람이라 멈추지 않는다."""
    region = str(row.get("on") or "전체")
    size = _number(row.get("element_size"))
    order = str(row.get("order") or "")
    method = str(row.get("method") or "")
    if order == "program_controlled":
        order = ""
    if method == "automatic":
        method = ""
    if region in WHOLE_REGIONS:
        if size is not None or order or method:
            made.mesh_hints.append(
                MeshHint(region=region, element_size=size, order=order, method=method)
            )
        return
    what = f"국부 메시 「{region}」"
    rows = [one for one in regions.get(region) or [] if isinstance(one, dict)]
    if entities.get(region) == "body":
        _legacy_body_hint(region, size, rows, made)
        return
    if rows and all("midpoint" in one for one in rows):
        made.skipped.append(
            Note(
                f"{what}(엣지)",
                "엣지 그룹의 요소 크기는 아직 못 겁니다 — 그 둘레는 이웃 크기로 풉니다",
            )
        )
        return
    if order or method:
        made.skipped.append(
            Note(
                f"{what} 요소 형상 · 차수",
                "「전체」 와 파트에만 겁니다 — 면에는 뜻이 없습니다",
            )
        )
    if size is not None:
        made.mesh_hints.append(MeshHint(region=region, element_size=size))


def _legacy_body_hint(
    region: str, size: float | None, rows: list[dict[str, Any]], made: Conditions
) -> None:
    """**바디 그룹에 건 옛 힌트** — 그 파트의 파트 메시(`body_settings` 크기)로 읽는다
    (CompCore 2026-10-04 요청). 파트별 설정에 크기가 따로 있으면 그것이 이긴다(새 길이다)."""
    if size is None:
        return
    names = {str(one.get("body") or "") for one in rows} - {""} or {ALL_BODIES}
    for name in sorted(names):
        found = next((one for one in made.body_settings if one.name == name), None)
        if found is not None and found.element_size is not None:
            made.skipped.append(
                Note(
                    f"국부 메시 「{region}」",
                    f"파트 「{name}」 의 파트 메시 크기가 따로 있어 그것으로 풉니다",
                )
            )
            continue
        if found is not None:
            index = made.body_settings.index(found)
            made.body_settings[index] = replace(found, element_size=size)
        else:
            made.body_settings.append(BodySetting(name=name, element_size=size))


def whole_order_note(given: Conditions, wanted: str) -> Note | None:
    """CAD 가 「전체」 요소 차수를 적었는데 작업 스펙과 다르면 그 사실 — **작업 스펙으로 푼다**
    (새 작업 · DOE 창이 CAD 값을 미리 채우고 사람이 고친 것이 스펙이다)."""
    whole = given.whole_mesh
    if whole is None or not whole.order or whole.order == wanted:
        return None
    return Note(
        "메시 「전체」 요소 차수",
        f"CAD 는 {_ORDER_LABELS.get(whole.order, whole.order)} 를 적었습니다 — 작업에서 고른 "
        f"{_ORDER_LABELS.get(wanted, wanted)} 로 풉니다",
    )


def _on_suppressed(payload: Any, off: set[str]) -> dict[str, str]:
    """뺀 파트에**만** 있는 선택 그룹 → 그 파트 이름. 그룹의 면 지문마다 `body` 가 있을 때만
    안다(CompCore 의 바디 그룹 · 파트로 거른 그룹) — 좌표만 적힌 그룹은 모른다."""
    if not off:
        return {}
    found: dict[str, str] = {}
    for name, rows in _dict(_dict(payload).get("regions")).items():
        bodies = (
            {str(one.get("body") or "") for one in rows if isinstance(one, dict)}
            if isinstance(rows, list)
            else set()
        )
        if bodies and "" not in bodies and bodies <= off:
            found[str(name)] = " · ".join(sorted(bodies))
    return found


@dataclass(frozen=True)
class _Middle:
    """점 파일의 `midsurface` — 쉘 파트의 두께와 못 만든 까닭."""

    thickness: dict[str, float] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)


def sheet_parts(payload: Any) -> set[str]:
    """두께 없는 시트(셸 모델) 파트의 이름 — `bodies[].kind == "sheet"`.

    이 날(2026-10-15) 전의 점 파일에는 `kind` 가 없다 — 그때는 모두 솔리드로 읽는다.
    """
    return {
        str(one.get("name") or "")
        for one in _dict(payload).get("bodies") or []
        if isinstance(one, dict) and one.get("kind") == SHEET
    }


def loose_sheets(payload: Any, given: Conditions) -> list[str]:
    """쉘로도 안 풀고 빼지도 않은 시트 — **풀 길이가 없다.**"""
    return sorted(sheet_parts(payload) - given.suppressed - set(given.shells))


def sheet_gap(payload: Any, given: Conditions, *, from_cad: bool) -> str:
    """풀 길이 없는 시트가 있으면 그 까닭 한 줄, 없으면 "".

    **조용히 빠지면 안 된다** — 두 솔버 모두 본 형상의 시트를 지운다(쉘이면 중간면이 그 자리를
    맡고, 빼면 빠진다). 쉘로 안 둔 시트를 그대로 두면 그 파트 없이 풀리고, 그 결과는 그럴듯하게
    틀린다. 쉘 두께는 CAD 의 파트 설정으로만 온다 — CAD 조건을 끄면 시트를 풀 길이가 없다.
    """
    loose = loose_sheets(payload, given)
    if not loose:
        return ""
    why = f"시트 파트({' · '.join(loose)})를 풀 길이가 없습니다: {SHEET_AS_SOLID}"
    if not from_cad:
        why += " (쉘 두께는 CAD 조건으로 옵니다 — 「CAD 가 보낸 조건 사용」 을 켜십시오)"
    return why


def scaled(given: Conditions, factor: float) -> Conditions:
    """파트 요소 크기 · 면 국부 크기에 `factor` 를 곱한 사본 — **비례 정련**(메시 수렴 점검).

    「전체」 힌트는 건드리지 않는다 — 점검 수준은 스펙의 전체 크기를 직접 적고, 그것이 「전체」
    힌트보다 먼저다. 1 이면 그대로 돌려준다.
    """
    if factor == 1:
        return given

    def times(size: float | None) -> float | None:
        return None if size is None else round(size * factor, 9)

    return replace(
        given,
        mesh_hints=[
            hint if hint.whole else replace(hint, element_size=times(hint.element_size))
            for hint in given.mesh_hints
        ],
        body_settings=[
            replace(one, element_size=times(one.element_size)) for one in given.body_settings
        ],
    )


def _not_faces(payload: Any, entities: dict[str, str]) -> dict[str, str]:
    """면이 아닌 지문으로 온 영역 → 막는 까닭.

    **매처는 면만 짝짓는다**(`regions.match`). 여기서 막지 않으면 미리보기는 「반영」 이라 하고
    모델링에서야 「바닥[0] 엣지 그룹입니다」 로 멈췄다(2026-10-05 — CompCore 가 09-24 에 내보낸
    「솔버 덱 함께」). 그 폴더는 「바닥」 을 **면으로 선언하고 엣지 지문 15개를** 실었다 — 그때
    CompCore 는 규칙에 `what` 이 없으면 엣지로 골랐다. 선언과 지문이 어긋나면 그렇다고 말한다:
    고칠 자리가 우리 창이 아니라 CompCore 의 내보내기다.
    """
    found: dict[str, str] = {}
    for name, rows in _dict(_dict(payload).get("regions")).items():
        listed = list(rows) if isinstance(rows, list) else []
        kind = not_a_face(listed)
        if not kind:
            continue
        if entities.get(name) == "face":
            found[name] = (
                f"「{name}」 을 CAD 는 면으로 선언했는데 지문은 {kind} {len(listed)}개로 "
                "왔습니다 — CompCore 에서 다시 내보내야 합니다(면 그룹만 걸 수 있습니다)"
            )
        else:
            found[name] = f"「{name}」 은 {kind} 그룹입니다 — 지금은 면 그룹만 걸 수 있습니다"
    return found


def _midsurface(payload: Any) -> _Middle:
    block = _dict(_dict(payload).get("midsurface"))
    thickness: dict[str, float] = {}
    for row in block.get("bodies") or []:
        if isinstance(row, dict) and _number(row.get("thickness")):
            thickness[str(row.get("name") or "")] = float(row["thickness"])
    failed = {
        str(row.get("name") or ""): str(row.get("error") or "까닭이 적혀 있지 않습니다")
        for row in block.get("failed") or []
        if isinstance(row, dict)
    }
    if block.get("error"):
        # 옛 내보내기 — 점 전체가 한 줄로 실패했다.
        failed.setdefault("", str(block["error"]))
    return _Middle(thickness=thickness, failed=failed)


def _off_midsurface(payload: Any, shells: set[str]) -> dict[str, str]:
    """쉘 파트에 걸린 영역 중 **중간면의 면 · 점으로 못 옮긴 것** → 까닭.

    두께 쪽 면(끝면 · 옆면 · 구멍 벽)은 중간면의 **모서리**가 되는데, 우리 매처는 아직 면 ·
    점만 안다. CompCore 가 못 옮긴 것은 `mid: []` 다.
    """
    if not shells:
        return {}
    found: dict[str, str] = {}
    for name, rows in _dict(_dict(payload).get("regions")).items():
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or str(row.get("body") or ALL_BODIES) not in shells:
                continue
            part = row.get("body") or ALL_BODIES
            mid = row.get("mid")
            if not mid:
                found[str(name)] = (
                    f"쉘 파트({part})의 이 자리를 CompCore 가 중간면으로 옮기지 못했습니다"
                )
                break
            if any(isinstance(one, dict) and "edge" in one for one in mid):
                found[str(name)] = (
                    f"쉘 파트({part})의 두께 쪽 면 — 중간면의 모서리에 거는 조건은 아직 "
                    "못 겁니다"
                )
                break
    return found


def shell_view(payload: dict[str, Any], shells: set[str]) -> dict[str, Any]:
    """쉘 파트의 영역 지문을 **중간면의 것으로** 바꾼 점 파일 — 쉘 모델에서 짝지을 때 쓴다.

    겉면은 중간면의 면(`two_sided` — 쉘은 앞뒤가 없다. 원래 겉면의 바깥 법선은
    `outer_normal` 로 남겨 하중이 미는 쪽을 안다), 점은 중간면 위로 내린 점이다. 쉘이 아닌
    파트의 지문은 그대로 둔다.
    """
    if not shells or not isinstance(payload.get("regions"), dict):
        return payload
    regions: dict[str, Any] = {}
    for name, rows in payload["regions"].items():
        if not isinstance(rows, list):
            regions[name] = rows
            continue
        made: list[Any] = []
        for row in rows:
            body = str(row.get("body") or ALL_BODIES) if isinstance(row, dict) else ""
            if not isinstance(row, dict) or body not in shells:
                made.append(row)
                continue
            for one in row.get("mid") or []:
                if not isinstance(one, dict):
                    continue
                if isinstance(one.get("face"), dict):
                    face = one["face"]
                    made.append(
                        {
                            **face,
                            "body": body,
                            "two_sided": True,
                            "outer_normal": face.get("normal"),
                        }
                    )
                elif one.get("point") is not None:
                    made.append({"point": one["point"], "body": body})
                elif isinstance(one.get("edge"), dict):
                    made.append({**one["edge"], "body": body})
        regions[name] = made
    return {**payload, "regions": regions, SHELL_VIEW: sorted(shells)}


def _body_setting(
    row: dict[str, Any], made: Conditions, middle: _Middle | None = None
) -> None:
    """파트별 설정 한 줄. **모르는 값은 멈춘다** — 거동 · 표현은 답을 바꾼다."""
    name = str(row.get("name") or "")  # 받은 그대로 — `bodies.match_bodies`
    if not name.strip():
        made.refused.append(Note("파트별 설정", "파트 이름이 비어 있습니다"))
        return
    what = f"파트 「{name}」"
    if any(one.name == name for one in made.body_settings):
        made.refused.append(Note(what, "설정이 두 줄입니다 — 파트마다 하나만 받습니다"))
        return
    behavior = str(row.get("behavior") or "deformable")
    representation = str(row.get("representation") or "solid")
    suppressed = bool(row.get("suppressed"))
    if behavior not in BODY_BEHAVIORS:
        made.refused.append(Note(what, f"모르는 거동입니다: {behavior}"))
        return
    if representation not in BODY_REPRESENTATIONS:
        made.refused.append(Note(what, f"모르는 표현입니다: {representation}"))
        return
    thickness: float | None = None
    if representation == "shell" and not suppressed:
        # **솔리드로 풀지 않는다** — 판을 쉘로 둔 모델과 솔리드 모델은 강성이 다르고, 사람은
        # 쉘로 풀었다고 읽는다. 중간면이 없으면 그 까닭을 단다.
        middle = middle or _Middle()
        if behavior == "rigid":
            made.refused.append(Note(f"{what} 쉘 표현", "강체는 쉘로 풀 수 없습니다"))
            return
        thickness = middle.thickness.get(name)
        if thickness is None:
            why = middle.failed.get(name) or middle.failed.get("")
            made.refused.append(
                Note(
                    f"{what} 쉘 표현",
                    f"CompCore 가 중간면을 못 만들었습니다: {why}"
                    if why
                    else "점 파일에 이 파트의 중간면(midsurface)이 없습니다",
                )
            )
            return
    mesh = _dict(row.get("mesh"))
    method = str(mesh.get("method") or "automatic")
    order = str(mesh.get("order") or "program_controlled")
    if method not in MESH_METHODS:
        made.skipped.append(
            Note(f"{what} 요소 형상", f"모르는 값이라 자동으로 둡니다: {method}")
        )
        method = "automatic"
    if order not in MESH_ORDERS:
        made.skipped.append(
            Note(f"{what} 요소 차수", f"모르는 값이라 전체를 따릅니다: {order}")
        )
        order = "program_controlled"
    size = _number(mesh.get("element_size"))
    if mesh.get("element_size") is not None and (size is None or size <= 0):
        made.skipped.append(
            Note(
                f"{what} 요소 크기",
                f"수가 아니라 전체 크기를 따릅니다: {mesh['element_size']}",
            )
        )
        size = None
    made.body_settings.append(
        BodySetting(
            name=name,
            rigid=behavior == "rigid",
            suppressed=suppressed,
            shell=thickness is not None,
            thickness=thickness,
            element_size=size,
            method=method,
            order=order,
        )
    )


def _load(row: dict[str, Any], recipe: str, made: Conditions) -> None:
    """하중 — **선응력 모달이면 걸고, 그냥 모달이면 넘긴다.**

    조여 놓고 떠는 상태(볼트 예압 · 원심력)를 보려면 정적 해석을 먼저 풀어야 한다. 선응력이
    아니면 하중은 고유진동수를 바꾸지 않으므로 그 사실을 적고 넘어간다 — 조용히 버리면 사람은
    「압력을 줬는데 왜 주파수가 같지」 를 묻지도 못한다.
    """
    name = str(row.get("name") or "이름 없는 하중")
    kind = str(row.get("type") or "")
    if kind == "psd_acceleration":
        if recipe == "random":
            _psd(row, name, made)
            return
        # 랜덤 진동의 가진(CompCore 2026-11-17) — 다른 해석에서는 뜻이 없다. 막지 않고
        # 알린다(같은 형상 · 조건을 모달로 먼저 보는 일이 흔하다).
        made.skipped.append(
            Note(
                f"하중 「{name}」(가속도 PSD)",
                "랜덤 진동의 가진이라 이 해석에서는 쓰지 않습니다",
            )
        )
        return
    if kind not in _INERT_IN_MODAL:
        made.refused.append(Note(f"하중 「{name}」", f"모르는 하중입니다: {kind}"))
        return
    if recipe in QUIET_LOADS and not made.analysis.prestressed:
        made.skipped.append(
            Note(
                f"하중 「{name}」({kind})",
                "모달에서는 하중이 고유진동수를 바꾸지 않습니다 — 선응력을 켜면 쓰입니다"
                if recipe == "modal"
                else "랜덤 진동은 가속도 PSD 로만 흔듭니다 — 선응력을 켜면 앞 정적 단계에"
                " 쓰입니다",
            )
        )
        return

    if recipe == "harmonic" and kind in HARMONIC_REFUSED:
        made.refused.append(Note(f"하중 「{name}」({kind})", HARMONIC_REFUSED[kind]))
        return

    direction = row.get("direction")
    # **가진 프로파일은 조화 응답에서만 읽는다** — 다른 해석에서는 CompCore 가 비워 보내고(그
    # 해석의 칸이 아니다), 안 쓰는 칸의 값으로 막지 않는다(능력표의 `fields.loads`).
    table, broken = (
        _frequency_table(row.get("frequency_table")) if recipe == "harmonic" else (None, "")
    )
    if broken:
        made.refused.append(Note(f"하중 「{name}」 의 주파수별 배율", broken))
        return
    timed, active, bolt_steps, why = (
        _history(row, kind, made.analysis) if recipe == "static" else (None, None, None, "")
    )
    if why:
        made.refused.append(Note(f"하중 「{name}」({kind})", why))
        return
    made.loads.append(
        Load(
            name=name,
            kind=kind,
            region=str(row.get("on") or ""),
            cs=str(row.get("cs") or "global"),
            magnitude=_number(row.get("magnitude")),
            unit=str(row.get("unit") or ""),
            direction=_triple(direction),
            normal=direction == "normal",
            preload=_number(row.get("preload")) if kind == "bolt_pretension" else None,
            frequency_table=table,
            phase=_number(row.get("phase")) if recipe == "harmonic" else None,
            time_table=timed,
            active_steps=active,
            bolt_steps=bolt_steps,
        )
    )


#: 시간별 배율을 받는 하중(CompCore ② — 중력 · 볼트는 못 쓴다).
TIMED_LOADS = (
    "force",
    "pressure",
    "moment",
    "bearing",
    "acceleration",
    "rotational_velocity",
)
BOLT_STEP_ACTIONS = ("load", "lock")


def _history(
    row: dict[str, Any], kind: str, analysis: Analysis
) -> tuple[
    tuple[tuple[float, float], ...] | None, tuple[int, ...] | None, tuple[str, ...] | None, str
]:
    """정적 하중의 하중 이력 칸(시간별 배율 · 적용 단계 · 볼트 단계) — 틀리면 까닭.

    단계는 해석 설정의 `load_steps`(비면 끝 시각 1 의 한 단계)다. 규칙은 CompCore 가 저장할 때
    막는 것과 같다 — 시간별 배율은 양 끝(0 · 마지막 끝 시각)을 적고 시각이 늘며, 적용 단계와
    함께 쓰지 않는다. 적용 단계는 늘어나는 단계 번호, 볼트 단계는 단계 수만큼 `load` 뒤 `lock`.
    """
    steps = analysis.load_steps or (LoadStep(name="", end_time=1.0),)
    end = steps[-1].end_time
    raw_table, raw_active, raw_bolt = (
        row.get(key) for key in ("time_table", "active_steps", "bolt_steps")
    )
    table: tuple[tuple[float, float], ...] | None = None
    if raw_table is not None:
        if kind not in TIMED_LOADS:
            return None, None, None, "시간별 배율(time_table)은 이 하중에 쓸 수 없습니다"
        if raw_active is not None:
            return None, None, None, "시간별 배율과 적용 단계는 함께 쓰지 않습니다"
        if not isinstance(raw_table, list) or len(raw_table) < 2:
            return None, None, None, "시간별 배율은 [시각, 배율] 두 줄 이상입니다"
        rows: list[tuple[float, float]] = []
        for one in raw_table:
            pair = (
                (_number(one[0]), _number(one[1]))
                if isinstance(one, list | tuple) and len(one) == 2
                else (None, None)
            )
            if pair[0] is None or pair[1] is None:
                return None, None, None, "시간별 배율의 줄이 [시각, 배율]이 아닙니다"
            rows.append((pair[0], pair[1]))
        times = [one[0] for one in rows]
        if any(after <= before for before, after in pairwise(times)):
            return None, None, None, "시간별 배율의 시각은 줄마다 늘어야 합니다"
        if times[0] != 0 or abs(times[-1] - end) > 1e-9 * max(1.0, abs(end)):
            return (
                None,
                None,
                None,
                (
                    f"시간별 배율은 시각 0 과 마지막 단계의 끝 시각({end:g})을 양 끝으로"
                    " 적습니다"
                ),
            )
        table = tuple(rows)
    active: tuple[int, ...] | None = None
    if raw_active is not None:
        if kind in ("standard_earth_gravity", "bolt_pretension"):
            return None, None, None, "적용 단계(active_steps)는 중력 · 볼트에 쓸 수 없습니다"
        numbers = raw_active if isinstance(raw_active, list) else None
        if (
            not numbers
            or any(_count(one) is None for one in numbers)
            or numbers != sorted(set(numbers))
            or numbers[-1] > len(steps)
        ):
            return (
                None,
                None,
                None,
                (f"적용 단계는 1 ~ {len(steps)} 의 단계 번호를 늘어나는 차례로 적습니다"),
            )
        active = tuple(int(one) for one in numbers)
    bolt: tuple[str, ...] | None = None
    if raw_bolt is not None:
        if kind != "bolt_pretension":
            return None, None, None, "볼트 단계(bolt_steps)는 볼트 예압에만 씁니다"
        actions = [str(one) for one in raw_bolt] if isinstance(raw_bolt, list) else []
        if actions != ["load", *["lock"] * (len(steps) - 1)]:
            return (
                None,
                None,
                None,
                ("볼트 단계는 단계 수만큼 적고 첫 단계에서 조인(load) 뒤 잠급니다(lock)"),
            )
        bolt = tuple(actions)
    return table, active, bolt, ""


#: PSD 단위 — CompCore 는 늘 `g^2/Hz` 로 보낸다(2026-11-17). 다른 단위는 막는다(g 와 m/s² 를
#: 섞으면 응답이 96배 틀린다).
PSD_UNITS = ("g^2/hz", "g²/hz", "g2/hz")


def _psd(row: dict[str, Any], name: str, made: Conditions) -> None:
    """가속도 PSD 한 줄 → `made.psd`. 못 쓰면 까닭을 달아 막는다(랜덤 진동의 답 전부다)."""
    what = f"하중 「{name}」(가속도 PSD)"
    table, broken = _psd_table(row.get("psd_table"))
    if table is None:
        made.refused.append(Note(what, broken or "PSD 표(psd_table)가 없습니다."))
        return
    unit = str(row.get("unit") or "g^2/Hz").replace(" ", "")
    if unit.lower() not in PSD_UNITS:
        made.refused.append(Note(what, f"PSD 단위는 g^2/Hz 만 받습니다: {unit}"))
        return
    place = str(row.get("on") or "")
    if place:
        made.refused.append(
            Note(
                what,
                f"랜덤 진동은 모든 고정 지지를 함께 흔듭니다 — 한 영역(「{place}」)만 흔드는"
                " 가진은 아직 못 겁니다.",
            )
        )
        return
    direction = _triple(row.get("direction"))
    if direction is None or not any(direction):
        made.refused.append(Note(what, "흔드는 방향(direction)이 없습니다."))
        return
    made.psd.append(
        Psd(
            name=name,
            table=table,
            direction=direction,
            cs=str(row.get("cs") or "global"),
            grms=_number(row.get("grms")),
        )
    )


def _psd_table(value: Any) -> tuple[tuple[tuple[float, float], ...] | None, str]:
    """`[[Hz, g²/Hz], …]` → 표와 **틀렸으면 까닭**. 로그-로그로 보간하므로 주파수 · 값이 모두 0
    보다 커야 한다(Ansys 의 PSD 표와 같은 규칙)."""
    if value is None:
        return None, ""
    if not isinstance(value, list) or len(value) < 2:
        return None, "PSD 표는 [주파수, g²/Hz] 두 줄 이상이어야 합니다."
    rows: list[tuple[float, float]] = []
    for one in value:
        pair = one if isinstance(one, list | tuple) and len(one) == 2 else None
        hz = _number(pair[0]) if pair else None
        level = _number(pair[1]) if pair else None
        if hz is None or level is None:
            return None, f"PSD 표의 줄이 [주파수, g²/Hz] 가 아닙니다: {one}"
        if hz <= 0 or level <= 0:
            return None, (
                f"PSD 표의 주파수 · 값은 0 보다 커야 합니다(로그-로그 보간): {hz:g} Hz,"
                f" {level:g}"
            )
        if rows and hz <= rows[-1][0]:
            return None, "PSD 표의 주파수가 커지는 차례가 아닙니다."
        rows.append((hz, level))
    return tuple(rows), ""


def _initial(row: dict[str, Any], recipe: str, made: Conditions) -> None:
    kind = str(row.get("type") or "")
    if kind == "environment_temperature":
        # **물성 기준 온도로 쓴다**(CompCore 계약 2026-11-17 —
        # `materials.reference_temperature`). 열 변형은 풀지 않는다 — 덱에 열팽창 계수를
        # 넣지 않아 열 변형이 0 이다(Ansys 도 바디 온도가 따로 없으면 0).
        made.skipped.append(
            Note(
                "초기조건 (환경 온도)",
                "물성 기준 온도로 씁니다(탄성계수 온도 표에서 가장 가까운 점) — 열 변형은 "
                "풀지 않습니다",
            )
        )
        return
    if kind == "prestress":
        # **선응력은 `analysis.prestressed` 와 한 짝이다**(CompCore: 「초기조건의 「선응력」 과
        # 함께 사용합니다」) — 같은 하중의 정적을 앞에 풀고 그 응력을 안고 모드를 뽑는다.
        # 전에는 이 줄을 「아직 걸 수 없다」 로 막아 선응력 모달 폴더가 통째로 멈췄다(CompCore
        # 볼트 픽스처, 2026-10-27). 다른 해석의 단계(`from_step`)에서 가져오는 것은 아직
        # 못 한다.
        source = str(row.get("from_step") or "").strip()
        if source:
            made.refused.append(
                Note(
                    "초기조건 (선응력)",
                    f"다른 해석({source})의 응력은 아직 못 가져옵니다 — 비우면 같은 하중의 "
                    "정적을 앞에 풉니다",
                )
            )
        elif recipe == "harmonic":
            made.refused.append(Note("초기조건 (선응력)", HARMONIC_PRESTRESS))
        elif recipe not in PRESTRESS_RECIPES:
            made.skipped.append(Note("초기조건 (선응력)", "모달 · 랜덤 진동에서만 씁니다"))
        elif not made.analysis.prestressed:
            made.skipped.append(
                Note(
                    "초기조건 (선응력)",
                    "해석 설정의 「선응력 반영」 이 꺼져 있어 쓰지 않습니다",
                )
            )
        return
    made.refused.append(Note("초기조건", f"아직 걸 수 없습니다: {kind}"))


#: 해석 종류마다 **읽는** 해석 설정 칸(CompCore 의 칸 이름) — 능력표의 `fields.analysis` 다.
#: 여기 없는 칸(정적의 `steps` · 모든 해석의 `solver` · 조화의 `method`)은 읽지 않는다 —
#: 능력표가 그것을 「받지 않음」 으로 보이게 한다(CompCore 해석-확장-설계 5장).
#:
#: - `modes` — 작업의 모드 수가 비면 이 값(`services._with_cad_modes`, 모드가 있는 스펙 셋).
#: - `frequency_range` — 모달 · 랜덤은 모드를 찾을 범위(`modes.search`), 조화는 훑을 범위.
#: - `prestressed` — 모달 · 랜덤(솔버가 더 좁힌다). 조화는 막는다(`HARMONIC_PRESTRESS`).
#: - `damping_ratio` — 조화(`harmonic.harmonic_plan`) · 랜덤(`random_vibration.plan`).
#: - `large_deflection` · `substeps` — 정적(`statics.static_plan`).
#: 하중 칸(CompCore `Load` 의 차례) — `curve` 는 없다: CompCore 가 내보낼 때 곡선을 하중 안의
#: 표로 풀어 오고 칸은 빼므로(해석-확장-설계 4장) 우리에게 오지 않는다.
LOAD_FIELD_ORDER = (
    "name",
    "type",
    "on",
    "cs",
    "magnitude",
    "unit",
    "direction",
    "preload",
    "frequency_table",
    "phase",
    "psd_table",
    "grms",
    "time_table",
    "active_steps",
    "bolt_steps",
)
_STATIC_LOAD_FIELDS = ("name", "type", "on", "cs", "magnitude", "unit", "direction", "preload")
#: 정적에서만 읽는 하중 이력 칸(CompCore ②, `_history`).
HISTORY_LOAD_FIELDS = ("time_table", "active_steps", "bolt_steps")
#: 해석마다 **읽는** 하중 칸 — 능력표의 `fields.loads`(그 해석에서 그 묶음의 읽는 칸 전부).
#: 모달 · 랜덤은 선응력의 앞 정적에 걸 때의 칸이다(솔버가 선응력을 안 받으면 빠진다).
#: 볼트 예압의 `preload` 는 볼트에서만, 조화의 배율 · 위상은 조화에서만 읽는다.
LOAD_FIELDS: dict[str, tuple[str, ...]] = {
    "modal": _STATIC_LOAD_FIELDS,
    "static": (*_STATIC_LOAD_FIELDS, *HISTORY_LOAD_FIELDS),
    "harmonic": (
        *(one for one in _STATIC_LOAD_FIELDS if one != "preload"),
        "frequency_table",
        "phase",
    ),
    "random": _STATIC_LOAD_FIELDS,
}
#: 가속도 PSD 의 칸(`_psd`) — 랜덤 진동의 가진. `on` 은 비어야 한다(모든 고정 지지를 흔든다).
PSD_FIELDS = ("name", "type", "on", "cs", "unit", "direction", "psd_table", "grms")

ANALYSIS_FIELDS: dict[str, tuple[str, ...]] = {
    "modal": ("modes", "frequency_range", "prestressed"),
    "static": ("large_deflection", "substeps", "load_steps"),
    "harmonic": ("modes", "frequency_range", "solution_intervals", "damping_ratio"),
    "random": ("modes", "frequency_range", "prestressed", "damping_ratio"),
}


def _analysis(block: dict[str, Any]) -> Analysis:
    span = block.get("frequency_range")
    pair: tuple[float, float] | None = None
    if isinstance(span, list | tuple) and len(span) == 2:
        low, high = _number(span[0]), _number(span[1])
        if low is not None and high is not None:
            pair = (low, high)
    modes = block.get("modes")
    intervals = block.get("solution_intervals")
    large = block.get("large_deflection")
    substeps = block.get("substeps")
    return Analysis(
        kind=str(block.get("type") or "modal"),
        modes=int(modes) if isinstance(modes, int) else None,
        frequency_range=pair,
        prestressed=bool(block.get("prestressed")),
        damping_ratio=_number(block.get("damping_ratio")),
        intervals=int(intervals) if isinstance(intervals, int) else None,
        large_deflection=large if isinstance(large, bool) else None,
        substeps=(
            substeps
            if isinstance(substeps, int) and not isinstance(substeps, bool) and substeps > 0
            else None
        ),
        load_steps=_load_steps(block.get("load_steps")),
    )


def _count(value: Any) -> int | None:
    """양의 정수 칸 — 아니면 `None`(받는 쪽이 정한다)."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _load_steps(value: Any) -> tuple[LoadStep, ...]:
    """`analysis.load_steps` — 끝 시각이 비면 단계 번호(CompCore 와 같은 규칙). 틀린 값은
    `steps_problem` 이 까닭을 말한다(읽기는 너그럽게)."""
    if not isinstance(value, list):
        return ()
    out: list[LoadStep] = []
    for index, row in enumerate(value, start=1):
        row = _dict(row)
        sub = _dict(row.get("substeps"))
        end = _number(row.get("end_time"))
        out.append(
            LoadStep(
                name=str(row.get("name") or f"단계 {index}"),
                end_time=float(index) if end is None else end,
                initial=_count(sub.get("initial")),
                minimum=_count(sub.get("minimum")),
                maximum=_count(sub.get("maximum")),
            )
        )
    return tuple(out)


def steps_problem(block: dict[str, Any]) -> str:
    """하중 단계(`analysis.load_steps`)를 받을 수 없는 까닭 — 비면 받는다. CompCore 가 저장할
    때 막는 규칙과 같다(끝 시각은 늘고, 부단계는 최소 ≤ 처음 ≤ 최대, v1 의 `steps` ·
    `substeps` 는 기본값)."""
    rows = block.get("load_steps")
    if rows is None or rows == []:
        return ""
    if not isinstance(rows, list):
        return "하중 단계(load_steps)가 목록이 아닙니다"
    before = 0.0
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            return f"하중 단계 {index} 가 단계가 아닙니다"
        end = row.get("end_time")
        when = float(index) if end is None else _number(end)
        if when is None or when <= before:
            return f"하중 단계 {index} 의 끝 시각이 앞 단계보다 커야 합니다"
        before = when
        sub = _dict(row.get("substeps"))
        counts = [sub.get(key) for key in ("minimum", "initial", "maximum")]
        if any(one is not None and _count(one) is None for one in counts):
            return f"하중 단계 {index} 의 부단계 수는 양의 정수입니다"
        given = [one for one in counts if one is not None]
        if given != sorted(given):
            return f"하중 단계 {index} 의 부단계 수는 최소 ≤ 처음 ≤ 최대여야 합니다"
    if block.get("steps") not in (None, 1) or block.get("substeps") is not None:
        return (
            "하중 단계(load_steps)를 쓰면 「하중 단계 수」(steps) · 「초기 부단계 수」"
            "(substeps)는 비웁니다"
        )
    return ""


# --- 잔손 ---------------------------------------------------------------------


def _suggestion(payload: Any) -> tuple[float | None, str]:
    """CompCore 의 `mesh_suggestion` — 전역 요소 크기 제안(2026-10-23). 단위는
    `length_units.mesh_suggestion` 이고 늘 mm 다(SI 로 내보내도 옮기지 않는다). **다른 단위면
    쓰지 않는다** — 모르는 단위의 크기를 mm 로 읽으면 메시가 1000배 틀린다."""
    found = _dict(_dict(payload).get("mesh_suggestion"))
    size = found.get("element_size")
    unit = _dict(_dict(payload).get("length_units")).get("mesh_suggestion", "mm")
    if isinstance(size, bool) or not isinstance(size, int | float) or unit != "mm":
        return None, ""
    if size <= 0:
        return None, ""
    return float(size), str(found.get("basis") or "")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(block: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = block.get(key)
    return [one for one in rows if isinstance(one, dict)] if isinstance(rows, list) else []


def _frequency_table(value: Any) -> tuple[tuple[tuple[float, float], ...] | None, str]:
    """`[[Hz, 배율], …]` → 표와 **틀렸으면 까닭**. 비었으면 표 없음(배율 1). 주파수는 커지는
    차례, 배율은 0 이상(뒤집기는 위상으로) — CompCore 가 저장할 때 막는 것과 같은 규칙이다."""
    if value is None:
        return None, ""
    if not isinstance(value, list) or len(value) < 2:
        return None, "표는 [주파수, 배율] 두 줄 이상이어야 합니다."
    rows: list[tuple[float, float]] = []
    for one in value:
        pair = one if isinstance(one, list | tuple) and len(one) == 2 else None
        hz = _number(pair[0]) if pair else None
        factor = _number(pair[1]) if pair else None
        if hz is None or factor is None:
            return None, f"표의 줄이 [주파수, 배율] 이 아닙니다: {one}"
        if factor < 0:
            return None, f"배율은 0 이상이어야 합니다(뒤집기는 위상으로): {factor:g}"
        if rows and hz <= rows[-1][0]:
            return None, "주파수가 커지는 차례가 아닙니다."
        rows.append((hz, factor))
    return tuple(rows), ""


def table_factor(table: tuple[tuple[float, float], ...] | None, hz: float) -> float:
    """그 주파수의 배율 — 선형 보간, 표 밖은 끝값(CalculiX `*AMPLITUDE` 가 그렇게 읽는다). 표가
    없으면 1."""
    if not table:
        return 1.0
    if hz <= table[0][0]:
        return table[0][1]
    for (f1, k1), (f2, k2) in itertools.pairwise(table):
        if hz <= f2:
            return k1 + (k2 - k1) * (hz - f1) / (f2 - f1)
    return table[-1][1]


def table_covers(
    table: tuple[tuple[float, float], ...] | None, low: float, high: float
) -> bool:
    """표가 해석의 주파수 범위를 다 덮나 — 표 밖을 0 으로 읽을지 끝값으로 읽을지 솔버마다
    달라서
    덮지 않으면 걸지 않는다(CompCore 와 같은 규칙)."""
    return table is None or (table[0][0] <= low and table[-1][0] >= high)


def _number(value: Any) -> float | None:
    """**`None` 은 자유다** — 0 과 구별한다. 글자는 숫자가 아니면 없는 것으로 본다."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _hold(value: Any) -> Hold:
    return "free" if str(value or "fixed").strip() == "free" else "fixed"


def euler_xyz(frame: Frame) -> tuple[float, float, float]:
    """좌표계의 축 → **X → Y → Z 고정축 회전각**(도). CompCore 의 규칙과 같은 순서다.

    Mechanical 에는 축 벡터를 바로 적는 칸이 없고 회전으로 세운다. 돌려 보낸 각을 다시 행렬로
    만들면 원래 축이 나와야 한다 — 시험이 그것을 본다(둘이 어긋나면 성분이 딴 방향으로 걸리고,
    그 사실은 결과를 봐도 모른다).
    """
    # 열이 각 축인 회전행렬 R = [x y z] 이고, 고정축 X → Y → Z 는 R = Rz·Ry·Rx 다.
    # 그래서 R[2][0] = -sin(pitch) · R[2][1] = cos(pitch)sin(roll) ·
    # R[1][0] = sin(yaw)cos(pitch) 다.
    pitch = math.asin(max(-1.0, min(1.0, -frame.x_axis[2])))
    if abs(math.cos(pitch)) > 1e-9:
        roll = math.atan2(frame.y_axis[2], frame.z_axis[2])
        yaw = math.atan2(frame.x_axis[1], frame.x_axis[0])
    else:  # pragma: no cover - 짐벌락(90도)에서는 한 쌍으로만 적을 수 있다
        roll = math.atan2(-frame.z_axis[1], frame.y_axis[1])
        yaw = 0.0
    return tuple(round(math.degrees(one), 9) for one in (roll, pitch, yaw))  # type: ignore[return-value]


#: 각속도 단위 → rad/s. CompCore 는 rad/s 로 보낸다 — 나머지는 사람이 적은 조건을 위해.
ANGULAR_UNITS = {"rad/s": 1.0, "rpm": 2 * math.pi / 60, "deg/s": math.pi / 180}
#: 볼트 예압의 단위 — 힘이면 N 으로, 길이(조임량)면 mm 로 가는 곱수. `unit` 이 둘을 가른다
#: (CompCore: 「볼트만 예압(힘) · 조임량(길이)을 `unit` 으로 고른다」).
PRELOAD_FORCE_UNITS = {"n": 1.0, "kn": 1e3}
PRELOAD_LENGTH_UNITS = {"mm": 1.0, "m": 1e3, "cm": 10.0, "um": 1e-3}


def preload_unit(load: Load) -> str:
    """볼트 예압 단위의 열쇠(소문자 · 칸 없이) — 비어 있으면 힘(N)이다."""
    return (load.unit or "N").replace(" ", "").lower()


@dataclass(frozen=True)
class SpinAxis:
    """회전 속도 하나를 전역으로 푼 것 — 두 솔버가 같은 축을 쓴다."""

    omega: float
    """rad/s."""
    point: tuple[float, float, float]
    """축 위의 한 점 — **선언된 계의 길이**(좌표계 원점이 그렇게 온다)."""
    axis: tuple[float, float, float]
    """전역 단위 벡터."""


def spin_axis(load: Load, frames: list[Frame]) -> SpinAxis | str:
    """회전 속도 → 전역 축. 못 풀면 **까닭**(문장)을 돌려준다.

    축은 **좌표계 원점을 지나고**(CompCore 계약 — 전역이면 원점), 방향은 그 좌표계의
    성분이다.
    """
    if load.magnitude is None or load.direction is None:
        return "크기 · 축 방향이 있어야 합니다."
    scale = ANGULAR_UNITS.get((load.unit or "rad/s").replace(" ", "").lower())
    if scale is None:
        return f"각속도 단위 「{load.unit}」 를 모릅니다 — rad/s · rpm · deg/s."
    point = (0.0, 0.0, 0.0)
    axis = tuple(float(one) for one in load.direction)
    if load.cs not in GLOBAL_FRAMES:
        frame = next((one for one in frames if one.name == load.cs), None)
        if frame is None:
            return f"좌표계 「{load.cs}」 가 없습니다."
        point = frame.origin
        axis = _rotated(load.direction, frame)
    length = sum(one * one for one in axis) ** 0.5
    omega = load.magnitude * scale
    if length == 0 or omega == 0:
        return "크기나 축 방향이 0 입니다."
    return SpinAxis(
        omega,
        point,
        (axis[0] / length, axis[1] / length, axis[2] / length),
    )


#: 방향 성분을 좌표계(`cs`)로 읽는 하중 — 회전 속도는 축이 그 원점을 지나 따로 푼다
#: (`spin_axis`). 압력은 면의 법선이다.
DIRECTED_IN_FRAME = ("force", "moment", "bearing", "acceleration", "standard_earth_gravity")


def _rotated(vector: tuple[float, ...], frame: Frame) -> tuple[float, float, float]:
    """좌표계의 성분 → 전역 성분(축이 단위 벡터다 — 원점은 옮기지 않는다)."""
    bases = (frame.x_axis, frame.y_axis, frame.z_axis)
    x, y, z = (
        sum(float(vector[k]) * basis[i] for k, basis in enumerate(bases)) for i in range(3)
    )
    return (x, y, z)


def in_global(load: Load, frames: list[Frame]) -> Load | str:
    """방향 성분을 **전역으로** 옮긴 하중 — 두 솔버가 전역 성분만 다룬다. 좌표계를 못 찾으면
    까닭(문장)을 돌려준다.

    CompCore 계약: 방향 성분의 축은 `cs` 다(구속과 같다). 전에는 두 솔버가 그 칸을 안 보고
    성분을 전역으로 읽었다 — 돌린 좌표계로 적은 힘이 딴 방향으로 걸렸다(2026-10-26 고침).
    CalculiX 는 가속도 · 모멘트를 아예 거절했다.
    """
    if load.kind not in DIRECTED_IN_FRAME or load.cs in GLOBAL_FRAMES or not load.direction:
        return load
    frame = next((one for one in frames if one.name == load.cs), None)
    if frame is None:
        return f"좌표계 「{load.cs}」 가 없습니다."
    return replace(load, direction=_rotated(load.direction, frame), cs="global")
