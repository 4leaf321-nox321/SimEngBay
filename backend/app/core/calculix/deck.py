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
from dataclasses import dataclass, field

from app.core import conditions as condition_model
from app.core import units
from app.core.harmonic import HarmonicPlan
from app.core.materials import Material

logger = logging.getLogger(__name__)

#: 걸 수 있는 구속. 나머지는 거절한다(원통 지지 · 회전 자유도 등은 국부 좌표 변환이 필요하다).
SUPPORTED_CONSTRAINTS = ("fixed_support",)
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


def write_modal(
    *,
    nodes: dict[int, tuple[float, float, float]],
    solids: dict[int, list[tuple[int, list[int]]]],
    body_of: dict[str, int],
    materials: list[Material],
    held_nodes: dict[str, set[int]],
    given: condition_model.Conditions,
    modes: int,
    second_order: bool,
) -> Plan:
    """모달 덱. 구속 · 물성 · 고유치 단계까지.

    `held_nodes` 는 **영역 이름 → 절점**이다 — 면 지문을 푼 결과를 부른 쪽에서 넣어 준다
    (그 매칭은 `app/core/regions` 가 하고, 솔버를 모른다).
    """
    plan = Plan()
    lines = _head(nodes, solids, body_of, materials, plan, second_order)
    lines += _holds(held_nodes, given, plan)

    for pair in given.contacts:
        if pair.kind in LINEARIZED_CONTACTS:
            # **절점을 공유시켜 이미 붙였다** — 그 사실을 적어 둔다. 조용히 두면 사람은
            # 마찰이 모델에 들어갔다고 읽는다.
            plan.skipped.append(
                condition_model.Note(
                    f"접촉 「{pair.name}」({pair.kind})",
                    "맞닿은 면의 절점을 공유시켜 **붙은 것으로** 풀었습니다"
                    "(모달에서는 같은 답입니다).",
                )
            )
            continue
        plan.refused.append(
            condition_model.Note(f"접촉 「{pair.name}」({pair.kind})", "모르는 접촉입니다.")
        )

    for load in given.loads:
        # 모달은 하중으로 답이 바뀌지 않는다 — Ansys 쪽과 같은 말을 적는다.
        plan.skipped.append(
            condition_model.Note(
                f"하중 「{load.name}」({load.kind})", "모달에서는 하중이 답을 바꾸지 않습니다."
            )
        )

    for hint in given.mesh_hints:
        if hint.region not in ("전체", "all"):
            plan.skipped.append(
                condition_model.Note(
                    f"메시 힌트 「{hint.region}」", "영역별 요소 크기는 아직 못 겁니다."
                )
            )

    lines += [
        "*STEP",
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


#: 걸 수 있는 하중 — 압력(면 법선)과 힘(면 절점에 분배). 나머지는 거절한다.
SUPPORTED_LOADS = ("pressure", "force")

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
    system: units.UnitSystem,
    second_order: bool,
) -> Plan:
    """정적 덱. **하중이 답을 만든다** — 하나도 못 걸면 전부 0 이 나오고, 그 그림은
    「해석이 됐다」 처럼 보인다. 그래서 하중이 없으면 거절한다.

    `load_faces` 는 영역 → [(요소 번호, 면 이름)] 이고 압력에 쓴다. `load_areas` 는 영역 →
    {절점: 분담 면적} 이고 힘을 나눌 때 쓴다 — 부른 쪽(`build.py`)이 메시에서 만들어 준다.
    """
    plan = Plan()
    lines = _head(nodes, solids, body_of, materials, plan, second_order)
    lines += _holds(held_nodes, given, plan)

    lines.append("*STEP")
    lines.append("*STATIC")
    applied_loads = 0
    for load in given.loads:
        if load.kind not in SUPPORTED_LOADS:
            plan.refused.append(
                condition_model.Note(
                    f"하중 「{load.name}」({load.kind})",
                    "CalculiX 경로가 아직 못 거는 하중입니다 — Ansys 로 돌리세요.",
                )
            )
            continue
        if load.magnitude is None:
            plan.refused.append(
                condition_model.Note(f"하중 「{load.name}」", "크기가 없습니다.")
            )
            continue
        if load.kind == "pressure":
            faces = load_faces.get(load.region) or []
            if not faces:
                plan.refused.append(
                    condition_model.Note(
                        f"하중 「{load.name}」",
                        f"영역 「{load.region}」 의 요소면을 못 찾았습니다.",
                    )
                )
                continue
            # 압력은 **선언된 계의 응력 단위**로 온다(MPa 등) — 덱은 MPa 다.
            value = (
                units.stress_from(load.magnitude, load.unit or "MPa")
                / units.STRESS_UNITS["mpa"]
            )
            lines.append("*DLOAD")
            for element, face in faces:
                lines.append(f"{element}, {face}, {value:.8g}")
            plan.applied.append(f"pressure:{load.region}")
            applied_loads += 1
            continue

        # 힘 — 면 절점에 **분담 면적으로 나눈다.** 고르게 나누면 모서리 절점이 과하게 받는다.
        areas = load_areas.get(load.region) or {}
        members = load_nodes.get(load.region) or set()
        if not areas or not members:
            plan.refused.append(
                condition_model.Note(
                    f"하중 「{load.name}」", f"영역 「{load.region}」 의 절점을 못 찾았습니다."
                )
            )
            continue
        direction = load.direction or (0.0, 0.0, -1.0)
        total = sum(areas.values())
        if total <= 0:
            plan.refused.append(
                condition_model.Note(f"하중 「{load.name}」", "면적이 0 입니다.")
            )
            continue
        lines.append("*CLOAD")
        for node, share in sorted(areas.items()):
            portion = load.magnitude * share / total
            for axis, component in enumerate(direction[:3], start=1):
                if component:
                    lines.append(f"{node}, {axis}, {portion * component:.8g}")
        plan.applied.append(f"force:{load.region}")
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
    held_nodes: dict[str, set[int]], given: condition_model.Conditions, plan: Plan
) -> list[str]:
    """구속 — 레시피가 달라도 같은 부분이다."""
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
        lines += _nset(f"HOLD{index}", members)
        lines += ["*BOUNDARY", f"HOLD{index}, 1, 3, 0.0"]
        plan.applied.append(f"{rule.kind}:{rule.region}")
    return lines


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
    lines += _holds(held_nodes, given, plan)

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
        rows, why = _load_rows(load, load_faces, load_areas, load_nodes)
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
) -> tuple[list[str], condition_model.Note | None]:
    """하중 한 줄 뭉치 — 압력은 요소면, 힘은 절점. 못 걸면 까닭을 돌려준다."""
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
    total = sum(areas.values())
    if total <= 0:
        return [], condition_model.Note(f"하중 「{load.name}」", "면적이 0 입니다.")
    direction = load.direction or (0.0, 0.0, -1.0)
    rows = ["*CLOAD"]
    for node, share in sorted(areas.items()):
        portion = load.magnitude * share / total
        for axis, component in enumerate(direction[:3], start=1):
            if component:
                rows.append(f"{node}, {axis}, {portion * component:.8g}")
    return rows, None
