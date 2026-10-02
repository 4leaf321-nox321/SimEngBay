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

## 영역은 면만 안다

조건은 선택 그룹 이름으로 자리를 가리키고, 그 자리는 점 파일의 `regions` 에 설계점마다
풀려 있다. 우리 매처는 **면**만 짝지으므로(`app/core/regions`), 엣지 · 점 그룹을 가리키는
조건은 `refused` 다 — CompCore 에도 「접촉 · 압력 · 원통 지지는 면 그룹만」 으로 막아 달라고
적어 두었다(2026-09-28).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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
    """메시는 우리가 만든다 — 이것은 **바람**이다."""

    region: str
    """`전체` 또는 선택 그룹 이름."""
    element_size: float | None = None
    """선언된 단위계의 길이. SI 폴더면 m 로 온다."""
    order: str = ""


@dataclass(frozen=True)
class Analysis:
    """무엇을 풀라고 했나 — 우리 스펙과 견주는 데 쓴다."""

    kind: str = "modal"
    modes: int | None = None
    frequency_range: tuple[float, float] | None = None
    prestressed: bool = False


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
    analysis: Analysis = field(default_factory=Analysis)
    skipped: list[Note] = field(default_factory=list)
    """이 레시피에서 답을 바꾸지 않는 것 — 하중처럼."""
    refused: list[Note] = field(default_factory=list)
    """답을 바꾸는데 아직 못 거는 것. **하나라도 있으면 모델링은 멈춘다.**"""

    @property
    def empty(self) -> bool:
        return not (self.constraints or self.contacts or self.mesh_hints or self.loads)

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
    made.frames = _frames(payload, block)
    known = {one.name for one in made.frames}
    for row in _rows(block, "constraints"):
        _needs_frame(row, known, made)
    for row in _rows(block, "constraints"):
        _constraint(row, regions, made)
    for row in _rows(block, "contacts"):
        _contact(row, regions, made)
    for row in _rows(block, "mesh_hints"):
        _mesh_hint(row, made)
    for row in _rows(block, "loads"):
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


def _mesh_hint(row: dict[str, Any], made: Conditions) -> None:
    region = str(row.get("on") or "전체")
    size = _number(row.get("element_size"))
    order = str(row.get("order") or "")
    if size is None and not order:
        return
    made.mesh_hints.append(MeshHint(region=region, element_size=size, order=order))


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
    return Analysis(
        kind=str(block.get("type") or "modal"),
        modes=int(modes) if isinstance(modes, int) else None,
        frequency_range=pair,
        prestressed=bool(block.get("prestressed")),
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
