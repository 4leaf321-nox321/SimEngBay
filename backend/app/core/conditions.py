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

from dataclasses import dataclass, field, replace
from typing import Any, Literal

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

#: 파트 거동 · 표현 · 메시 — CompCore `BodySetting` · `BodyMesh` 의 값 그대로.
BODY_BEHAVIORS = ("deformable", "rigid")
BODY_REPRESENTATIONS = ("solid", "shell")
MESH_METHODS = ("automatic", "tetrahedrons", "hex_dominant", "sweep", "multizone")
MESH_ORDERS = ("program_controlled", "linear", "quadratic")
#: 「모든 파트」 — 단품이면 파트 이름이 이것이다(`materials.ALL_BODIES` 와 같은 말).
ALL_BODIES = "전체"
#: 메시 힌트가 「모델 전체」 를 가리키는 이름.
WHOLE_REGIONS = ("전체", "all")

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


@dataclass(frozen=True)
class Note:
    """걸지 않은 조건 하나와 그 까닭 — 요약 · 화면이 이 말을 그대로 보여 준다."""

    what: str
    why: str


@dataclass
class Conditions:
    """점 파일 한 장에서 읽은 조건 — **걸 것 · 넘길 것 · 막을 것**으로 갈라 둔다."""

    constraints: list[Constraint] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    """이름 붙인 좌표계. 구속의 `cs` 가 이 이름을 가리킨다."""
    loads: list[Load] = field(default_factory=list)
    """**선응력 모달에서만 쓴다.** 그냥 모달이면 `skipped` 에 적고 여기는 비운다."""
    mesh_hints: list[MeshHint] = field(default_factory=list)
    body_settings: list[BodySetting] = field(default_factory=list)
    """파트별 설정 — 적힌 파트만. 쉘 파트는 여기 오지 않고 `refused` 에 있다."""
    analysis: Analysis = field(default_factory=Analysis)
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
        """답을 만들 것이 있나 — 하중이 있거나 강제로 움직인다(정적 · 조화의 점검)."""
        return bool(self.loads) or self.drives

    @property
    def prestressed(self) -> bool:
        """정적 해석을 먼저 풀어야 하나 — **하중이 있고 선응력을 켰을 때**."""
        return bool(self.loads) and self.analysis.prestressed


def read(payload: Any, *, recipe: str = "modal") -> Conditions:
    """점 파일(`pNNNN.json`) 한 장 → 조건.

    **조건이 없으면 빈 것을 돌려준다**(오류가 아니다) — 형상만 온 폴더도 있고, 그때는 사람이
    화면에서 준 스펙으로 돈다.
    """
    block = _dict(_dict(payload).get("conditions"))
    made = Conditions()
    if not block:
        return made

    regions = set(_dict(payload).get("regions") or {})
    # **해석 설정을 먼저 읽는다** — 선응력인지에 따라 하중을 걸지 넘길지가 갈린다.
    made.analysis = _analysis(_dict(block.get("analysis")))
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
    gone = _on_suppressed(payload, made.suppressed)
    flat = _off_midsurface(payload, set(made.shells))
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
        _contact(row, regions, made)
    for row in _rows(block, "mesh_hints"):
        _mesh_hint(row, made, _dict(_dict(payload).get("regions")), entities)
    for row in _rows(block, "loads"):
        place = str(row.get("on") or "")
        if place in gone:
            what = f"하중 「{row.get('name') or '이름 없는 하중'}」"
            why = f"해석에서 뺀 파트({gone[place]})에 걸려 있습니다"
            if recipe == "modal" and not made.analysis.prestressed:
                made.skipped.append(Note(what, why + " — 모달이라 답과 상관없습니다"))
            else:
                made.refused.append(Note(what, why + " — 거기에는 형상이 없습니다"))
            continue
        live = not (recipe == "modal" and not made.analysis.prestressed)
        if place in flat and live:
            made.refused.append(
                Note(f"하중 「{row.get('name') or '이름 없는 하중'}」", flat[place])
            )
            continue
        if place in odd and live:
            made.refused.append(
                Note(f"하중 「{row.get('name') or '이름 없는 하중'}」", odd[place])
            )
            continue
        _load(row, recipe, made)
    for row in _rows(block, "initial"):
        _initial(row, recipe, made)
    return made


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

    made.constraints.append(
        Constraint(
            name=name,
            kind=kind,
            region=region,
            cs=str(row.get("cs") or "global"),
            components=tuple(_number(row.get(axis)) for axis in ("x", "y", "z")),
            rotations=tuple(_number(row.get(axis)) for axis in ("rx", "ry", "rz")),
            radial=_hold(row.get("radial")),
            axial=_hold(row.get("axial")),
            tangential=_hold(row.get("tangential")),
            stiffness=_number(row.get("stiffness")),
            location=str(row.get("location") or "centroid"),
            behavior=str(row.get("behavior") or "deformable"),
        )
    )


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
    return {**payload, "regions": regions}


def _body_setting(
    row: dict[str, Any], made: Conditions, middle: _Middle | None = None
) -> None:
    """파트별 설정 한 줄. **모르는 값은 멈춘다** — 거동 · 표현은 답을 바꾼다."""
    name = str(row.get("name") or "").strip()
    if not name:
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
    if kind not in _INERT_IN_MODAL:
        made.refused.append(Note(f"하중 「{name}」", f"모르는 하중입니다: {kind}"))
        return
    if recipe == "modal" and not made.analysis.prestressed:
        made.skipped.append(
            Note(
                f"하중 「{name}」({kind})",
                "모달에서는 하중이 고유진동수를 바꾸지 않습니다 — 선응력을 켜면 쓰입니다",
            )
        )
        return

    direction = row.get("direction")
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
            preload=_number(row.get("preload")),
        )
    )


def _initial(row: dict[str, Any], recipe: str, made: Conditions) -> None:
    kind = str(row.get("type") or "")
    if kind == "environment_temperature":
        made.skipped.append(
            Note("초기조건 (환경 온도)", "열응력을 풀지 않으므로 모달 결과를 바꾸지 않습니다")
        )
        return
    made.refused.append(Note("초기조건", f"아직 걸 수 없습니다: {kind}"))


def _analysis(block: dict[str, Any]) -> Analysis:
    span = block.get("frequency_range")
    pair: tuple[float, float] | None = None
    if isinstance(span, list | tuple) and len(span) == 2:
        low, high = _number(span[0]), _number(span[1])
        if low is not None and high is not None:
            pair = (low, high)
    modes = block.get("modes")
    intervals = block.get("solution_intervals")
    return Analysis(
        kind=str(block.get("type") or "modal"),
        modes=int(modes) if isinstance(modes, int) else None,
        frequency_range=pair,
        prestressed=bool(block.get("prestressed")),
        damping_ratio=_number(block.get("damping_ratio")),
        intervals=int(intervals) if isinstance(intervals, int) else None,
    )


# --- 잔손 ---------------------------------------------------------------------


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(block: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = block.get(key)
    return [one for one in rows if isinstance(one, dict)] if isinstance(rows, list) else []


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
    import math

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
