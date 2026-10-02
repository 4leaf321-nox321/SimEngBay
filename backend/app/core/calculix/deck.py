"""CalculiX 입력 덱(`.inp`) 을 쓴다.

## 능력표가 먼저다

솔버마다 걸 수 있는 조건이 다르다. 그것을 코드 흐름에 숨기면 **못 거는 조건이 조용히 빠진
해석**이 끝까지 돌고, 그 결과는 오류 없이 그럴듯하게 나온다. 그래서 `SUPPORTED_*` 를 위에 두고,
거기 없는 것은 **이름과 까닭을 달아 거절**한다 — Ansys 쪽과 같은 `applied / skipped / refused`
규칙이다.

## 단위

mm · tonne · N (MPa) 로 쓴다 — 형상이 늘 mm 이므로(CompCore 계약) 그 계가 자연스럽고, Ansys 의
`ConsistentNMM` 과 같아서 **두 솔버의 수를 바로 견줄 수 있다.** 주파수 Hz · 변위 mm.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from app.core import conditions as condition_model
from app.core import units
from app.core.harmonic import HarmonicPlan
from app.core.materials import Material

logger = logging.getLogger(__name__)

#: 걸 수 있는 구속.
#:
#: **원통 지지는 국부 좌표계로 건다**(`*TRANSFORM, TYPE=C`) — 그 계의 자유도 1 · 2 · 3 이
#: 반경 · 접선 · 축이다. 그래서 「핀에 끼운 채 돈다」(접선만 자유)가 그대로 표현된다. 전역
#: 좌표로 억지로 옮기면 그 모델은 돌지 못하고, 주파수가 올라간 채 그럴듯하게 나온다.
SUPPORTED_CONSTRAINTS = ("fixed_support", "cylindrical")
#: 걸 수 있는 접촉 — **본딩은 절점 공유로 이미 걸려 있다**(`mesh.py` 의 `BooleanFragments`).
#: 마찰 · 무마찰도 모달에서는 처음 붙어 있으면 같은 답이라, 「붙은 것으로 풀었다」 고 적는다.
LINEARIZED_CONTACTS = ("bonded", "no_separation", "frictional", "frictionless", "rough")
#: 지금 풀 수 있는 레시피. 정적 · 조화는 2단계다.
SUPPORTED_RECIPES = ("modal", "static", "harmonic")


@dataclass
class Plan:
    """덱에 실제로 들어간 것과 빠진 것 — 요약 · 화면이 이 말을 그대로 쓴다."""

    applied: list[str] = field(default_factory=list)
    skipped: list[condition_model.Note] = field(default_factory=list)
    refused: list[condition_model.Note] = field(default_factory=list)
    text: str = ""
    #: 하중 줄들 — **선응력 모달이 그대로 다시 쓴다**(정적 단계에 같은 하중을 걸어야 한다).
    load_rows: list[str] = field(default_factory=list)
    #: 국부 좌표계가 걸린 절점 → (축 위의 점, 축 방향).
    #:
    #: **그 절점에서는 `*CLOAD` 의 자유도 번호도 국부로 읽힌다**(1 반경 · 2 접선 · 3 축) —
    #: CalculiX 가 `*TRANSFORM` 을 구속과 하중에 **함께** 적용한다. 전역 성분을 그대로 적으면
    #: 힘이 엉뚱한 방향으로 들어가고, 그 결과는 오류 없이 그럴듯하게 나온다(실측 2026-10-03:
    #: 베어링 하중이 구멍면에 걸릴 때 그 자리였다).
    local_frames: dict[int, tuple[list[float], list[float]]] = field(default_factory=dict)


def write_modal(
    *,
    nodes: dict[int, tuple[float, float, float]],
    solids: dict[int, list[tuple[int, list[int]]]],
    body_of: dict[str, int],
    materials: list[Material],
    held_nodes: dict[str, set[int]],
    given: condition_model.Conditions,
    shapes: dict[str, dict[str, Any]] | None = None,
    contact_faces: dict[str, list[tuple[int, str]]] | None = None,
    preload: list[str] | None = None,
    element_size_mm: float = 1.0,
    modes: int,
    second_order: bool,
) -> Plan:
    """모달 덱. 구속 · 물성 · 고유치 단계까지.

    `contact_faces` 를 주면 **접촉 쌍을 쓴다**(메시를 쪼개지 않은 경우). `preload` 를 주면 그
    줄들로 **비선형 정적 단계를 앞에 두고** 그 상태에서 모드를 뽑는다(`*STEP, PERTURBATION`) —
    조여 놓은 상태의 공진을 보는 길이고, 접촉이 열리고 닫히는 것이 거기서 결정된다.

    `held_nodes` 는 **영역 이름 → 절점**이다 — 면 지문을 푼 결과를 부른 쪽에서 넣어 준다
    (그 매칭은 `app/core/regions` 가 하고, 솔버를 모른다).
    """
    plan = Plan()
    lines = _head(nodes, solids, body_of, materials, plan, second_order)
    lines += _holds(held_nodes, given, plan, shapes)

    if contact_faces is None:
        # 메시를 쪼개 붙였다(절점 공유) — 그 사실을 적어 둔다. 조용히 두면 사람은 마찰이
        # 모델에 들어갔다고 읽는다.
        for pair in given.contacts:
            if pair.kind in LINEARIZED_CONTACTS:
                why = "맞닿은 면의 절점을 공유시켜 **붙은 것으로** 풀었습니다"
                if pair.kind in NONLINEAR_CONTACTS:
                    # **CalculiX 는 고유치에 접촉을 넣지 않는다**(실측 2026-10-03: 접촉 쌍을
                    # 넣으면 바디가 떠서 강체 모드 6개가 나온다). 마찰을 비선형으로 보려면
                    # 정적으로 돌리거나 Ansys 로 간다.
                    why += (
                        " — CalculiX 는 고유치 해석에 접촉을 넣지 않습니다. 마찰을 비선형으로"
                        " 보려면 정적으로 돌리거나 솔버를 ansys 로 바꾸세요."
                    )
                else:
                    why += "(모달에서는 같은 답입니다)."
                plan.skipped.append(
                    condition_model.Note(f"접촉 「{pair.name}」({pair.kind})", why)
                )
                continue
            plan.refused.append(
                condition_model.Note(
                    f"접촉 「{pair.name}」({pair.kind})", "모르는 접촉입니다."
                )
            )
    else:
        lines += contact_block(
            given.contacts,
            contact_faces,
            plan,
            nonlinear=bool(preload),
            stiffness=contact_stiffness(materials, element_size_mm),
        )

    for load in given.loads:
        # 모달은 하중으로 답이 바뀌지 않는다 — Ansys 쪽과 같은 말을 적는다.
        plan.skipped.append(
            condition_model.Note(
                f"하중 「{load.name}」({load.kind})", "모달에서는 하중이 답을 바꾸지 않습니다."
            )
        )

    # 영역별 메시 힌트는 **메시를 만들 때** 걸린다(`build.py` 의 `_local_sizes`) — 덱에는
    # 남지 않으므로 여기서 할 일이 없다. 못 걸린 힌트는 그 자리에서 경고로 적는다.

    if preload:
        # **① 비선형 정적** — 접촉이 닫히고 마찰이 걸리고 하중이 구조를 조인다.
        lines += ["*STEP, NLGEOM", "*STATIC", "1.0, 1.0"]
        lines += preload
        lines += ["*NODE FILE", "U", "*END STEP"]
        # **② 그 상태에서 선형화해 모드를 뽑는다.** `PERTURBATION` 이 앞 단계의 강성(응력 ·
        # 접촉)을 물고 간다 — 물고 가는지는 **재 봐야 안다**(안 물면 선형 모달과 같은 값이
        # 나오고, 그것은 오류 없이 그럴듯하다).
        lines += ["*STEP, PERTURBATION"]
    else:
        lines += ["*STEP"]
    lines += [
        # SPOOLES — 데비안 패키지가 함께 깔아 주는 희소 솔버. ARPACK 로 고유치를 뽑는다.
        "*FREQUENCY, SOLVER=SPOOLES",
        f"{modes}",
        "*NODE FILE",
        "U",
        "*END STEP",
    ]
    plan.text = "\n".join(lines) + "\n"
    return plan


def _material_block(entity: int, material: Material) -> list[str]:
    """선형 탄성 + 밀도. **SI → mm · tonne · N 으로 옮긴다.**

    물성은 늘 SI 로 들고 다닌다(`app/core/materials.py`) — 여기서만 계를 바꾼다. 곱수를 손으로
    적지 않고 **`units` 의 표에서 끌어온다**: 단위 환산의 정본은 한 곳이어야 한다. 이 자리가
    틀리면 오류가 아니라 **그럴듯한 주파수**가 나온다(10³ 배씩 갈린다).
    """
    name = f"M{entity}"
    modulus_mpa = material.youngs_modulus_pa / units.STRESS_UNITS["mpa"]
    density_tonne_mm3 = material.density_kg_m3 / units.DENSITY_UNITS["tonne/mm3"]
    return [
        f"*MATERIAL, NAME={name}",
        "*ELASTIC",
        f"{modulus_mpa:.8g}, {material.poisson_ratio:.6g}",
        "*DENSITY",
        f"{density_tonne_mm3:.8g}",
        f"*SOLID SECTION, ELSET=E{entity}, MATERIAL={name}",
    ]


def _nset(name: str, members: set[int]) -> list[str]:
    """절점 집합. **한 줄에 몰아 쓰면 CalculiX 가 못 읽는다** — 열여섯 개씩 끊는다."""
    ordered = sorted(members)
    lines = [f"*NSET, NSET={name}"]
    for start in range(0, len(ordered), 16):
        lines.append(", ".join(str(one) for one in ordered[start : start + 16]))
    return lines


#: 걸 수 있는 하중 — 압력(면 법선) · 힘(면 절점에 분배) · 베어링(원통면의 반쪽).
SUPPORTED_LOADS = ("pressure", "force", "bearing")

#: C3D10 · C3D4 의 면 번호 → 모서리 절점 자리(1부터). CalculiX 가 쓰는 순서다 —
#: 틀리면 압력이 **엉뚱한 면에** 걸리고, 그 결과는 오류 없이 그럴듯하게 나온다.
TET_FACES = {
    "P1": (0, 1, 2),
    "P2": (0, 3, 1),
    "P3": (1, 3, 2),
    "P4": (2, 3, 0),
}


def write_static(
    *,
    nodes: dict[int, tuple[float, float, float]],
    solids: dict[int, list[tuple[int, list[int]]]],
    body_of: dict[str, int],
    materials: list[Material],
    held_nodes: dict[str, set[int]],
    load_nodes: dict[str, set[int]],
    load_faces: dict[str, list[tuple[int, str]]],
    load_areas: dict[str, dict[int, float]],
    given: condition_model.Conditions,
    shapes: dict[str, dict[str, Any]] | None = None,
    contact_faces: dict[str, list[tuple[int, str]]] | None = None,
    element_size_mm: float = 1.0,
    second_order: bool,
) -> Plan:
    """정적 덱. **하중이 답을 만든다** — 하나도 못 걸면 전부 0 이 나오고, 그 그림은
    「해석이 됐다」 처럼 보인다. 그래서 하중이 없으면 거절한다.

    `load_faces` 는 영역 → [(요소 번호, 면 이름)] 이고 압력에 쓴다. `load_areas` 는 영역 →
    {절점: 분담 면적} 이고 힘을 나눌 때 쓴다 — 부른 쪽(`build.py`)이 메시에서 만들어 준다.
    """
    plan = Plan()
    lines = _head(nodes, solids, body_of, materials, plan, second_order)
    lines += _holds(held_nodes, given, plan, shapes)
    nonlinear = False
    if contact_faces is not None:
        nonlinear = any(one.kind in NONLINEAR_CONTACTS for one in given.contacts)
        lines += contact_block(
            given.contacts,
            contact_faces,
            plan,
            nonlinear=True,
            stiffness=contact_stiffness(materials, element_size_mm),
        )
    else:
        for pair in given.contacts:
            if pair.kind in LINEARIZED_CONTACTS:
                plan.skipped.append(
                    condition_model.Note(
                        f"접촉 「{pair.name}」({pair.kind})",
                        "맞닿은 면의 절점을 공유시켜 **붙은 것으로** 풀었습니다.",
                    )
                )

    # **비선형 접촉은 증분으로 푼다** — 한 번에 걸면 접촉이 열린 채 수렴하지 못한다.
    lines.append("*STEP, NLGEOM" if nonlinear else "*STEP")
    lines.append("*STATIC")
    if nonlinear:
        lines.append("0.1, 1.0")
    applied_loads = 0
    for load in given.loads:
        rows, why = _load_rows(
            load, load_faces, load_areas, load_nodes, nodes, shapes, plan.local_frames
        )
        if why is not None:
            plan.refused.append(why)
            continue
        lines += rows
        plan.load_rows += rows
        plan.applied.append(f"{load.kind}:{load.region}")
        applied_loads += 1

    if not applied_loads:
        plan.refused.append(
            condition_model.Note(
                "정적 해석", "걸린 하중이 하나도 없습니다 — 전부 0 이 나옵니다."
            )
        )
    for pair in given.contacts:
        if pair.kind in LINEARIZED_CONTACTS:
            plan.skipped.append(
                condition_model.Note(
                    f"접촉 「{pair.name}」({pair.kind})",
                    "맞닿은 면의 절점을 공유시켜 **붙은 것으로** 풀었습니다.",
                )
            )
            continue
        plan.refused.append(
            condition_model.Note(f"접촉 「{pair.name}」({pair.kind})", "모르는 접촉입니다.")
        )

    lines += [
        "*NODE FILE",
        "U",
        # 응력은 요소에서 나와 절점으로 외삽된다 — `.frd` 의 STRESS 블록이 그것이다.
        "*EL FILE",
        "S",
        "*END STEP",
    ]
    plan.text = "\n".join(lines) + "\n"
    return plan


def _bearing_shares(
    load: condition_model.Load,
    areas: dict[int, float],
    direction: tuple[float, float, float],
    nodes: dict[int, tuple[float, float, float]] | None,
    shapes: dict[str, dict[str, Any]] | None,
) -> tuple[dict[int, float], condition_model.Note | None]:
    """베어링 하중 — **구멍의 반쪽만** 받는다.

    핀이 밀면 구멍은 그 방향 쪽 반쪽에서만 눌린다. 면 전체에 고르게 걸면 합력은 같아도 반대쪽을
    당기는 모델이 되어, 구멍 주변 응력과 변형 모양이 달라진다. 그래서 분담 면적에 **반경 방향과
    하중 방향의 겹침**(cos)을 곱한다 — 고전적인 베어링 분포다.

    축은 CAD 지문의 `axis` 를 쓴다(선언이 정본). 없으면 거절한다 — 짐작해서 반쪽을 고르면
    그 결과는 오류 없이 그럴듯하게 나온다.
    """
    shape = (shapes or {}).get(load.region) or {}
    centroid, axis = shape.get("centroid"), shape.get("axis")
    if nodes is None or not (isinstance(centroid, list) and isinstance(axis, list)):
        return {}, condition_model.Note(
            f"하중 「{load.name}」",
            f"영역 「{load.region}」 에 원통 축이 없습니다 — 베어링 하중은 축이 필요합니다.",
        )
    size = math.sqrt(sum(one * one for one in axis))
    if size == 0:
        return {}, condition_model.Note(f"하중 「{load.name}」", "축이 0 입니다.")
    unit_axis = [one / size for one in axis]
    pull = math.sqrt(sum(one * one for one in direction))
    if pull == 0:
        return {}, condition_model.Note(f"하중 「{load.name}」", "방향이 0 입니다.")
    unit_load = [one / pull for one in direction]
    shares: dict[int, float] = {}
    for node, area in areas.items():
        point = nodes.get(node)
        if point is None:
            continue
        offset = [point[index] - centroid[index] for index in range(3)]
        along = sum(offset[index] * unit_axis[index] for index in range(3))
        radial = [offset[index] - along * unit_axis[index] for index in range(3)]
        length = math.sqrt(sum(one * one for one in radial))
        if length == 0:
            continue
        overlap = sum(radial[index] / length * unit_load[index] for index in range(3))
        if overlap > 0:
            shares[node] = area * overlap
    if not shares:
        return {}, condition_model.Note(
            f"하중 「{load.name}」", "하중 방향 쪽 반쪽에 절점이 없습니다."
        )
    return shares, None


def _head(
    nodes: dict[int, tuple[float, float, float]],
    solids: dict[int, list[tuple[int, list[int]]]],
    body_of: dict[str, int],
    materials: list[Material],
    plan: Plan,
    second_order: bool,
) -> list[str]:
    """절점 · 요소 · 물성 — 레시피가 달라도 같은 부분이다."""
    lines: list[str] = [
        "** SimEngBay 가 쓴 덱 — CalculiX. 단위: mm · tonne · N (MPa)",
        "*NODE, NSET=NALL",
    ]
    for number, (x, y, z) in sorted(nodes.items()):
        lines.append(f"{number}, {x:.6f}, {y:.6f}, {z:.6f}")
    kind = "C3D10" if second_order else "C3D4"
    for name, entity in sorted(body_of.items(), key=lambda pair: pair[1]):
        lines.append(f"*ELEMENT, TYPE={kind}, ELSET=E{entity}")
        for number, ids in solids[entity]:
            lines.append(f"{number}, " + ", ".join(str(one) for one in ids))
        logger.info("바디 %s → 솔리드 %s (%s)", name, entity, kind)
    for one in materials:
        for body in one.bodies:
            found = body_of.get(body)
            if found is None:
                continue
            lines += _material_block(found, one)
            plan.applied.append(f"material:{body}")
    return lines


def _holds(
    held_nodes: dict[str, set[int]],
    given: condition_model.Conditions,
    plan: Plan,
    shapes: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """구속 — 레시피가 달라도 같은 부분이다.

    `shapes` 는 영역 이름 → **CAD 가 보낸 지문**이다(원통이면 `axis` · `centroid`). 축은
    메시에서 되맞출 수도 있지만 **선언이 정본이다** — 그쪽이 사람이 의도한 축이다.
    """
    lines: list[str] = []
    for index, rule in enumerate(given.constraints):
        if rule.kind not in SUPPORTED_CONSTRAINTS:
            plan.refused.append(
                condition_model.Note(
                    f"구속 「{rule.name}」({rule.kind})",
                    "CalculiX 경로가 아직 못 거는 구속입니다 — Ansys 로 돌리세요.",
                )
            )
            continue
        members = held_nodes.get(rule.region)
        if not members:
            plan.refused.append(
                condition_model.Note(
                    f"구속 「{rule.name}」", f"영역 「{rule.region}」 의 절점을 못 찾았습니다."
                )
            )
            continue
        name = f"HOLD{index}"
        if rule.kind == "cylindrical":
            rows, why, frame = _cylindrical(
                name, rule, members, (shapes or {}).get(rule.region)
            )
            if why is not None:
                plan.refused.append(why)
                continue
            lines += rows
            if frame is not None:
                for node in members:
                    plan.local_frames[node] = frame
            plan.applied.append(f"cylindrical:{rule.region}")
            continue
        lines += _nset(name, members)
        lines += ["*BOUNDARY", f"{name}, 1, 3, 0.0"]
        plan.applied.append(f"{rule.kind}:{rule.region}")
    return lines


def _cylindrical(
    name: str,
    rule: condition_model.Constraint,
    members: set[int],
    shape: dict[str, Any] | None,
) -> tuple[list[str], condition_model.Note | None, tuple[list[float], list[float]] | None]:
    """원통 지지 — 국부 좌표계를 세우고 방향마다 고정 · 자유를 건다.

    `*TRANSFORM, TYPE=C` 는 **축 위의 두 점**으로 계를 세운다. 그 계에서 자유도 1 이 반경,
    2 가 접선, 3 이 축이다(CalculiX 설명서). 셋 다 자유면 구속이 아니므로 거절한다 — 조용히
    넘기면 그 모델은 떠 있고, 0 Hz 모드가 줄줄이 나온다.
    """
    centroid = (shape or {}).get("centroid")
    axis = (shape or {}).get("axis")
    if not (isinstance(centroid, list) and isinstance(axis, list)):
        return (
            [],
            condition_model.Note(
                f"구속 「{rule.name}」",
                f"영역 「{rule.region}」 에 원통 축이 없습니다 — CAD 지문에 `axis` 가 "
                f"필요합니다.",
            ),
            None,
        )
    held = [
        index
        for index, hold in enumerate((rule.radial, rule.tangential, rule.axial), start=1)
        if hold == "fixed"
    ]
    if not held:
        return (
            [],
            condition_model.Note(
                f"구속 「{rule.name}」", "반경 · 접선 · 축이 모두 자유라 구속이 아닙니다."
            ),
            None,
        )
    second = [centroid[index] + axis[index] for index in range(3)]
    lines = _nset(name, members)
    frame = ([float(one) for one in centroid], [float(one) for one in axis])
    lines += [
        f"*TRANSFORM, NSET={name}, TYPE=C",
        ", ".join(f"{one:.6f}" for one in (*centroid, *second)),
        "*BOUNDARY",
    ]
    # 자유도 번호가 **국부 계의 것**이다: 1 반경 · 2 접선 · 3 축.
    lines += [f"{name}, {dof}, {dof}, 0.0" for dof in held]
    return lines, None, frame


def write_harmonic(
    *,
    nodes: dict[int, tuple[float, float, float]],
    solids: dict[int, list[tuple[int, list[int]]]],
    body_of: dict[str, int],
    materials: list[Material],
    held_nodes: dict[str, set[int]],
    load_nodes: dict[str, set[int]],
    load_faces: dict[str, list[tuple[int, str]]],
    load_areas: dict[str, dict[int, float]],
    given: condition_model.Conditions,
    shapes: dict[str, dict[str, Any]] | None = None,
    plan_of: HarmonicPlan,
    modes: int,
    second_order: bool,
) -> Plan:
    """조화 응답 덱 — **한 파일에 두 단계다.**

    Ansys 는 모달 덱과 조화 덱을 따로 내고 뒤 덱이 앞의 `file.db` 를 이어받는다. CalculiX 는
    `*FREQUENCY, STORAGE=YES` 로 모드를 남기고 **다음 단계**에서 그것을 쓰므로 파일이 하나다 —
    「앞 덱을 먼저 풀어야 한다」 는 함정이 아예 없다.

    **감쇠는 `*MODAL DAMPING` 한 줄이다.** Ansys 에서는 그 속성이 덱에 안 실려 `DMPRAT` 명령
    조각을 넣어야 했는데(실측 2026-10-02), 여기서는 자리가 깔끔하다. 감쇠가 없으면 공진에서
    응답이 끝없이 커지고, 그 큰 수는 그럴듯해 보인다.
    """
    plan = Plan()
    lines = _head(nodes, solids, body_of, materials, plan, second_order)
    lines += _holds(held_nodes, given, plan, shapes)

    # ① 모드를 푸고 남긴다.
    lines += [
        "*STEP",
        "*FREQUENCY, SOLVER=SPOOLES, STORAGE=YES",
        f"{modes}",
        "*END STEP",
    ]

    # ② 그 모드로 주파수를 훑는다.
    lines += [
        "*STEP",
        "*MODAL DAMPING",
        f"1, {modes}, {plan_of.damping_ratio:.6g}",
        "*STEADY STATE DYNAMICS",
        # 범위 · 점 수 · 편향(1 = 고르게).
        #
        # **점 수의 뜻이 Ansys 와 다르다**: CalculiX 는 이 수를 **고유진동수 사이마다** 쓴다
        # (실측 2026-10-03: 90 을 주었더니 200~2000 Hz 에서 268점이 나왔다). 그래서 요청보다
        # 촘촘해지는데, 그 덕에 **봉우리가 점 사이로 빠져나갈 수 없다** — Ansys 쪽에서 2 kHz
        # 간격으로 훑다가 봉우리를 놓친 일이 여기서는 구조적으로 안 생긴다.
        f"{plan_of.low:.6g}, {plan_of.high:.6g}, {plan_of.intervals}, 1",
    ]
    applied_loads = 0
    for load in given.loads:
        rows, why = _load_rows(
            load, load_faces, load_areas, load_nodes, nodes, shapes, plan.local_frames
        )
        if why is not None:
            plan.refused.append(why)
            continue
        lines += rows
        plan.applied.append(f"{load.kind}:{load.region}")
        applied_loads += 1
    if not applied_loads:
        plan.refused.append(
            condition_model.Note(
                "조화 응답", "흔드는 하중이 하나도 없습니다 — 응답이 전부 0 으로 나옵니다."
            )
        )
    for pair in given.contacts:
        if pair.kind in LINEARIZED_CONTACTS:
            plan.skipped.append(
                condition_model.Note(
                    f"접촉 「{pair.name}」({pair.kind})",
                    "맞닿은 면의 절점을 공유시켜 **붙은 것으로** 풀었습니다.",
                )
            )
            continue
        plan.refused.append(
            condition_model.Note(f"접촉 「{pair.name}」({pair.kind})", "모르는 접촉입니다.")
        )
    lines += ["*NODE FILE", "U", "*END STEP"]
    plan.text = "\n".join(lines) + "\n"
    return plan


def _load_rows(
    load: condition_model.Load,
    load_faces: dict[str, list[tuple[int, str]]],
    load_areas: dict[str, dict[int, float]],
    load_nodes: dict[str, set[int]],
    nodes: dict[int, tuple[float, float, float]] | None = None,
    shapes: dict[str, dict[str, Any]] | None = None,
    frames: dict[int, tuple[list[float], list[float]]] | None = None,
) -> tuple[list[str], condition_model.Note | None]:
    """하중 한 줄 뭉치 — 압력은 요소면, 힘 · 베어링은 절점. 못 걸면 까닭을 돌려준다."""
    if load.kind not in SUPPORTED_LOADS:
        return [], condition_model.Note(
            f"하중 「{load.name}」({load.kind})",
            "CalculiX 경로가 아직 못 거는 하중입니다 — Ansys 로 돌리세요.",
        )
    if load.magnitude is None:
        return [], condition_model.Note(f"하중 「{load.name}」", "크기가 없습니다.")
    if load.kind == "pressure":
        faces = load_faces.get(load.region) or []
        if not faces:
            return [], condition_model.Note(
                f"하중 「{load.name}」", f"영역 「{load.region}」 의 요소면을 못 찾았습니다."
            )
        value = (
            units.stress_from(load.magnitude, load.unit or "MPa") / units.STRESS_UNITS["mpa"]
        )
        return [
            "*DLOAD",
            *(f"{element}, {face}, {value:.8g}" for element, face in faces),
        ], None

    areas = load_areas.get(load.region) or {}
    if not areas or not load_nodes.get(load.region):
        return [], condition_model.Note(
            f"하중 「{load.name}」", f"영역 「{load.region}」 의 절점을 못 찾았습니다."
        )
    direction = load.direction or (0.0, 0.0, -1.0)
    if load.kind == "bearing":
        areas, why = _bearing_shares(load, areas, direction, nodes, shapes)
        if why is not None:
            return [], why
    total = sum(areas.values())
    if total <= 0:
        return [], condition_model.Note(f"하중 「{load.name}」", "면적이 0 입니다.")
    rows = ["*CLOAD"]
    for node, share in sorted(areas.items()):
        portion = load.magnitude * share / total
        vector = [portion * component for component in direction[:3]]
        frame = (frames or {}).get(node)
        if frame is not None:
            # **그 절점은 국부 계로 읽힌다** — 전역 성분을 그대로 적으면 힘이 반경 · 접선 ·
            # 축으로 뒤바뀐다(`Plan.local_frames` 참고).
            vector = _to_local(vector, nodes, node, frame)
        for axis, component in enumerate(vector, start=1):
            if component:
                rows.append(f"{node}, {axis}, {component:.8g}")
    return rows, None


def _to_local(
    vector: list[float],
    nodes: dict[int, tuple[float, float, float]] | None,
    node: int,
    frame: tuple[list[float], list[float]],
) -> list[float]:
    """전역 성분 → 원통 국부 성분(반경 · 접선 · 축).

    **근사가 아니라 정확한 변환이다**: 세 단위벡터에 내사영한 것이 그 계의 성분이다. 절점
    좌표를 모르면(있을 수 없는 일이지만) 바꾸지 않고 둔다 — 틀린 변환보다 안 바꾸는 편이 덜
    위험하다.
    """
    point = (nodes or {}).get(node)
    if point is None:
        return vector
    origin, axis = frame
    size = math.sqrt(sum(one * one for one in axis))
    if size == 0:
        return vector
    unit_axis = [one / size for one in axis]
    offset = [point[index] - origin[index] for index in range(3)]
    along = sum(offset[index] * unit_axis[index] for index in range(3))
    radial = [offset[index] - along * unit_axis[index] for index in range(3)]
    length = math.sqrt(sum(one * one for one in radial))
    if length == 0:
        return vector
    unit_radial = [one / length for one in radial]
    unit_tangent = _cross(unit_axis, unit_radial)
    return [
        sum(vector[index] * basis[index] for index in range(3))
        for basis in (unit_radial, unit_tangent, unit_axis)
    ]


def _cross(first: list[float], second: list[float]) -> list[float]:
    return [
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    ]


#: **비선형으로 풀 접촉** — 이것들은 응답 도중 열리고 닫히고 미끄러진다.
NONLINEAR_CONTACTS = ("frictional", "frictionless", "rough")
#: 접촉 강성을 **재료와 요소 크기에서 끌어낸다** — `k = STIFFNESS_FACTOR x E / h`.
#:
#: `PRESSURE-OVERCLOSURE=LINEAR` 의 강성은 「파고든 깊이 1 mm 당 접촉 압력」 이다. 고정값을
#: 쓰면 안 된다: 1e4 N/mm³ 로 두었더니 압력 1.5 MPa 에서 면이 1.5e-4 mm 파고들어, 마찰 접촉이
#: 접착보다 **73% 더 무르게** 나왔다(실측 2026-10-03). Ansys 로 같은 점을 돌려 보니 접착과
#: 마찰이 0.2% 차이였다 — 이 이음은 압축만 받아 전단이 없으므로 **그쪽이 맞다.** 내 수는
#: 물리가 아니라 **접촉 스프링의 무름**이었다.
#:
#: 요소 크기로 나누는 것은 차원 때문이다(E 는 N/mm², 강성은 N/mm³). 계수가 크면 수렴이
#: 어려워지므로 10 에서 시작한다.
STIFFNESS_FACTOR = 10.0


def contact_stiffness(materials: list[Material], element_size_mm: float) -> float:
    """그 모델에 맞는 접촉 강성(N/mm³). 가장 **단단한** 재료로 잡는다 — 무른 쪽으로 잡으면
    단단한 바디가 파고든다."""
    hardest = max((one.youngs_modulus_pa for one in materials), default=200e9)
    modulus_mpa = hardest / units.STRESS_UNITS["mpa"]
    return STIFFNESS_FACTOR * modulus_mpa / max(element_size_mm, 1e-6)


def contact_block(
    contacts: list[condition_model.Contact],
    faces: dict[str, list[tuple[int, str]]],
    plan: Plan,
    *,
    nonlinear: bool,
    stiffness: float,
) -> list[str]:
    """접촉 쌍 — `*SURFACE` 둘 + `*SURFACE INTERACTION` + `*CONTACT PAIR`.

    **CalculiX 의 접착은 `*TIE` 가 아니다**(그것은 주기 대칭이다). `*SURFACE BEHAVIOR,
    PRESSURE-OVERCLOSURE=TIED` 가 붙은 접촉이 접착이다. 마찰은 `LINEAR` + `*FRICTION` 이고,
    **비선형**이라 정적 단계가 증분으로 돈다.

    `nonlinear` 가 거짓이면 접착만 쓴다 — 모달 단독처럼 하중이 없는 해석에서는 마찰 접촉이
    정해지지 않으므로(열려 있는지 붙어 있는지 모른다) 붙은 것으로 푸는 쪽이 예측 가능하다.
    """
    lines: list[str] = []
    for index, pair in enumerate(contacts):
        source = faces.get(pair.source) or []
        target = faces.get(pair.target) or []
        if not source or not target:
            plan.refused.append(
                condition_model.Note(
                    f"접촉 「{pair.name}」",
                    f"면을 못 찾았습니다({pair.source} · {pair.target}) — 접합면이 "
                    f"양쪽으로 와야 합니다.",
                )
            )
            continue
        tied = pair.kind not in NONLINEAR_CONTACTS or not nonlinear
        name = f"C{index}"
        # **면 이름이 `S1` 이다** — 압력(`*DLOAD`)은 `P1` 을 쓰고 면 정의(`*SURFACE`)는 `S1` 을
        # 쓴다. 같은 자리를 가리키는 다른 표기이고, 섞으면 ccx 가 「*SURFACE 를 읽지
        # 못한다」 로 멈춘다(실측 2026-10-03).
        lines += [f"*SURFACE, NAME={name}S, TYPE=ELEMENT"]
        lines += [f"{element}, {face.replace('P', 'S')}" for element, face in source]
        lines += [f"*SURFACE, NAME={name}T, TYPE=ELEMENT"]
        lines += [f"{element}, {face.replace('P', 'S')}" for element, face in target]
        lines += [f"*SURFACE INTERACTION, NAME={name}I", "*SURFACE BEHAVIOR"]
        if tied:
            # 접착 — 면이 서로 붙어 떨어지지도 미끄러지지도 않는다.
            lines[-1] = "*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=TIED"
            lines.append(f"{stiffness:g}")
        else:
            lines[-1] = "*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=LINEAR"
            lines.append(f"{stiffness:g}")
            if pair.kind == "frictional" and pair.friction:
                # 미끄러짐 강성은 마찰계수와 접촉 강성에서 잡는다(CalculiX 의 두 번째 칸).
                lines += ["*FRICTION", f"{pair.friction:g}, {stiffness / 10:g}"]
        lines += [
            f"*CONTACT PAIR, INTERACTION={name}I, TYPE=SURFACE TO SURFACE",
            f"{name}T, {name}S",
        ]
        plan.applied.append(f"{'bonded' if tied else pair.kind}:{pair.source}↔{pair.target}")
        if tied and pair.kind in NONLINEAR_CONTACTS:
            plan.skipped.append(
                condition_model.Note(
                    f"접촉 「{pair.name}」({pair.kind})",
                    "하중이 없어 **붙은 것으로** 풀었습니다 — 마찰은 하중이 있어야 "
                    "뜻이 있습니다.",
                )
            )
    return lines
