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
from app.core.materials import Material

logger = logging.getLogger(__name__)

#: 걸 수 있는 구속. 나머지는 거절한다(원통 지지 · 회전 자유도 등은 국부 좌표 변환이 필요하다).
SUPPORTED_CONSTRAINTS = ("fixed_support",)
#: 걸 수 있는 접촉 — **본딩은 절점 공유로 이미 걸려 있다**(`mesh.py` 의 `BooleanFragments`).
#: 마찰 · 무마찰도 모달에서는 처음 붙어 있으면 같은 답이라, 「붙은 것으로 풀었다」 고 적는다.
LINEARIZED_CONTACTS = ("bonded", "no_separation", "frictional", "frictionless", "rough")
#: 지금 풀 수 있는 레시피. 정적 · 조화는 2단계다.
SUPPORTED_RECIPES = ("modal",)


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

    for rule in given.constraints:
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
        lines += _nset(f"HOLD{len(plan.applied)}", members)
        lines += ["*BOUNDARY", f"HOLD{len(plan.applied)}, 1, 3, 0.0"]
        plan.applied.append(f"{rule.kind}:{rule.region}")

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
