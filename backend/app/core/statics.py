"""정적 해석을 **무엇으로 풀 것인가** — 큰 변형 · 초기 부단계 수. 솔버가 둘이라 여기 둔다.

조화 응답의 `harmonic.harmonic_plan` 과 같은 자리다 — 스펙과 CAD 조건을 한 자리에서 합쳐야
Ansys 경로와 CalculiX 경로가 **같은 설정으로** 풀고, 요약이 같은 것을 말한다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from app.core import conditions as condition_model
from app.core.spec import StaticSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaticPlan:
    """큰 변형을 켜나 · 비선형을 몇 걸음으로 시작하나.

    **사람이 적었으면 그것, 비웠으면 CAD 가 적은 것이다.** 전에는 CAD 의
    `analysis.large_deflection` 을 두 솔버 모두 읽지 않아, CompCore 시험 규격 20개 중
    6개(굽힘 · 핀 베어링 · 이음 · 비틀림)가 「큰 변형」 이라 적었는데도 선형으로
    풀렸다(2026-10-08). 새 작업 창은 CAD 값을 미리 채워 보내므로, 사람이 바꾼 것만 CAD 와
    다르다.
    """

    large_deflection: bool
    #: 초기 부단계 수 — CAD 가 적었을 때만. 비선형 단계에서만 뜻이 있다.
    substeps: int | None
    #: 큰 변형을 누가 정했나 — `spec` · `cad` · `default`(둘 다 안 적음 — 끈다).
    source: str


def static_plan(spec: StaticSpec, given: condition_model.Conditions) -> StaticPlan:
    """스펙과 CAD 조건을 합쳐 실제로 풀 정적 설정을 낸다."""
    declared = given.analysis
    if spec.large_deflection is not None:
        large, source = spec.large_deflection, "spec"
    elif declared.large_deflection is not None:
        large, source = declared.large_deflection, "cad"
    else:
        large, source = False, "default"
    if source == "cad":
        logger.info("큰 변형 ← CAD: %s", "켬" if large else "끔")
    return StaticPlan(large_deflection=large, substeps=declared.substeps, source=source)


#: 전역 X · Y · Z 중 어느 축을 막나.
Axes = tuple[bool, bool, bool]
ALL_AXES: Axes = (True, True, True)


def held_directions(rule: condition_model.Constraint) -> int:
    """변형체 면 구속이 막는 **병진 자유도 수** — 고정 3 · 변위는 정한 성분 수 · 마찰 없음 1.

    반력을 읽는 구속만 센다(그 밖은 0). 겹친 절점의 축을 어느 구속에 먼저 줄지 정한다
    (`separate_reactions`).
    """
    if rule.kind == "fixed_support":
        return 3
    if rule.kind == "displacement":
        return sum(1 for value in rule.components[:3] if value is not None)
    if rule.kind == "frictionless":
        return 1
    return 0


def held_axes(
    rule: condition_model.Constraint, normal: Sequence[float] | None = None
) -> Axes | None:
    """변형체 면 구속이 막는 **전역 축** — 반력을 읽지 않는 구속이면 `None`.

    마찰 없는 지지는 법선 축 하나다(`normal` — CAD 지문의 면 법선). 축에 나란하지 않은 면이면
    법선 반력이 세 성분에 다 실리므로 세 축이다(Ansys 만 그런 면을 받는다).
    """
    if rule.kind == "fixed_support":
        return ALL_AXES
    if rule.kind == "displacement":
        held = [value is not None for value in rule.components[:3]]
        held += [False] * (3 - len(held))
        return (held[0], held[1], held[2]) if any(held) else None
    if rule.kind == "frictionless":
        if normal is None or len(normal) != 3:
            return ALL_AXES
        size = sum(float(one) ** 2 for one in normal) ** 0.5
        if not size:
            return ALL_AXES
        unit = [abs(float(one)) / size for one in normal]
        axis = max(range(3), key=lambda index: unit[index])
        if unit[axis] < 0.999:
            return ALL_AXES
        return (axis == 0, axis == 1, axis == 2)
    return None


def separate_reactions(
    rows: Sequence[tuple[str, int, Axes, AbstractSet[int]]],
) -> dict[str, tuple[frozenset[int], frozenset[int], frozenset[int]]]:
    """영역 → **축마다 반력을 읽을 절점** — 절점의 한 축은 한 영역만 센다. 두 솔버가 같이 쓴다.

    `rows` 는 구속 차례대로 (영역, 막는 자유도 수, 막는 축, 절점). 고정단과 바닥처럼 **모서리를
    나누는 구속**은 그 모서리 절점을 둘 다 가진다 — 절점의 반력은 하나인데 두 영역에 다 더하면
    두 번 센다(실측 2026-10-16: CompCore 전단 이음, 마찰 없는 바닥이 X 로 -259 N 을 「버티고」
    반력 합이 클램프 10 kN 에서 102 N 어긋났다).

    **축마다 가른다.** 그 축을 막는 구속 중 자유도를 더 많이 막는 쪽(같으면 앞의 것)이 그
    절점의 그 축을 갖는다 — 대칭면 둘(X 대칭 · Y 대칭)이 모서리를 나누면 모서리의 X 반력은 X
    대칭면, Y 반력은 Y 대칭면의 것이다. 영역이 막지 않는 축은 아무도 그 축을 막지 않는
    절점에서만 센다(거기 반력은 0 이다 — 다른 구속이 막는 절점의 그 축은 그쪽 몫이다). 같은
    영역에 구속이 둘이면 하나로 합친다. 남은 절점이 없는 영역은 뺀다. 구속 자체(경계 조건)는
    그대로다.
    """
    merged: dict[str, tuple[int, list[bool], set[int]]] = {}
    for region, rank, axes, members in rows:
        before = merged.get(region)
        if before is None:
            merged[region] = (rank, list(axes), set(members))
            continue
        merged[region] = (
            max(before[0], rank),
            [mine or theirs for mine, theirs in zip(before[1], axes, strict=True)],
            before[2] | set(members),
        )
    order = sorted(merged, key=lambda region: -merged[region][0])
    claimed: list[set[int]] = [set(), set(), set()]
    held: dict[str, list[frozenset[int]]] = {}
    for region in order:
        _, holds, members = merged[region]
        mine: list[frozenset[int]] = []
        for axis in range(3):
            own = frozenset(members - claimed[axis]) if holds[axis] else frozenset()
            claimed[axis] |= own
            mine.append(own)
        held[region] = mine
    out: dict[str, tuple[frozenset[int], frozenset[int], frozenset[int]]] = {}
    for region in merged:
        _, holds, members = merged[region]
        if not any(held[region][axis] for axis in range(3) if holds[axis]):
            continue
        sets = [
            held[region][axis] if holds[axis] else frozenset(members - claimed[axis])
            for axis in range(3)
        ]
        out[region] = (sets[0], sets[1], sets[2])
    return out
