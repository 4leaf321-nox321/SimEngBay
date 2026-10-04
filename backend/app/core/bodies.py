"""바디 짝짓기 — **CAD 의 파트가 해석의 어느 바디인가.**

물성은 파트마다 붙는다(`materials[].apply_to` 가 바디 이름 목록). 그런데 그 이름을 해석 쪽이
어떻게 알아보나? **STEP 은 한글 이름을 못 나른다** — CompCore 실측(2026-09-23): `부품` ·
`지그판` 을 내보내면 파일에 UTF-8 바이트가 아예 없고 `ì¡°ë¦½` 꼴로 망가져 되살릴 수 없었다.
그래서 이름에 기대지 않고 **좌표 지문으로 짝짓는다** — 면을 중심 · 법선 · 넓이로 짝짓는 것과
같은 방식이라 규칙이 하나다(`app/core/regions`).

지문은 점 파일의 `bodies[]` 에 온다: `name`(사람의 말) · `step_product`(기계의 말) ·
`volume` · `centroid` · `bbox`. 모두 **mm** 다(`length_units.regions` 와 같다).

## 무엇으로 짝짓나

**부피가 먼저다.** 같은 조립에서 두 파트의 부피가 2% 안으로 같은 일은 드물고, 부피는 STEP 을
다시 읽어도 거의 변하지 않는다(실측: 113,384 → 113,396 mm³, 0.01%). 부피가 닮은 파트가 둘
이상이면 **무게중심으로 가른다** — 그것도 못 가르면 **짝짓지 않는다**: 틀린 파트에 물성을
붙이면 값이 안 나오는 게 아니라 **그럴듯한 값이 나오고 틀린다.**

## 못 짝지으면 실패한다

한쪽이라도 못 찾으면 이름과 함께 돌려준다. 부르는 쪽(모델링)은 그때 **멈춘다** — 물성이 없는
바디는 Mechanical 이 기본값(구조용 강)으로 풀고, 그 사실은 고유진동수가 틀린 뒤에야 드러난다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.core.conditions import ALL_BODIES, BodySetting

#: 부피가 이 비율 안으로 같으면 「닮았다」 로 본다. STEP 을 다시 읽어 생기는 차이는 0.1% 도 안
#: 되지만(실측 0.01%), 메시 · 곡면 재현이 걸리면 조금 더 벌어질 수 있다.
VOLUME_TOLERANCE_RATIO = 0.02

#: 무게중심은 **크기에 견주어** 본다 — 부피의 세제곱근(대표 길이)의 이 비율까지.
CENTROID_TOLERANCE_RATIO = 0.05

#: 아주 작은 파트에서 위 비율이 0 에 가까워지는 것을 막는다(mm).
CENTROID_TOLERANCE_MIN = 0.5


@dataclass(frozen=True)
class BodyRecord:
    """해석 쪽 바디 하나.

    값은 **mm 로** 맞춰 넣는다 — 부르는 쪽이 활성 단위계를 알고 환산한다.
    """

    index: int
    volume: float
    centroid: tuple[float, float, float]
    name: str = ""


@dataclass
class BodyMatch:
    """짝지은 결과 — 이름 → 해석 쪽 바디 번호."""

    bodies: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    """못 짝지은 CAD 파트 이름과 그 이유, 한 줄씩."""

    @property
    def ok(self) -> bool:
        return not self.failures


def match_bodies(topology: dict[str, Any], records: list[BodyRecord]) -> BodyMatch:
    """점 파일의 `bodies[]` → 해석 쪽 바디 번호.

    **하나씩 집어 간다** — 한 해석 바디가 두 파트의 짝이 될 수는 없다.
    """
    result = BodyMatch()
    wanted = [one for one in (topology.get("bodies") or []) if isinstance(one, dict)]
    if not wanted:
        return result

    taken: set[int] = set()
    for part in wanted:
        name = str(part.get("name") or "").strip()
        if not name:
            continue
        volume = part.get("volume")
        if not isinstance(volume, int | float) or float(volume) <= 0:
            result.failures.append(f"{name}: CAD 가 부피를 보내지 않았습니다")
            continue

        near = [
            one
            for one in records
            if one.index not in taken and _volume_close(float(volume), one.volume)
        ]
        if not near:
            closest = min(
                (abs(one.volume - float(volume)) / float(volume) for one in records),
                default=math.inf,
            )
            result.failures.append(
                f"{name}: 부피 {float(volume):,.1f} mm³ 인 바디가 없습니다"
                + (
                    f"(가장 가까운 것도 {closest * 100:.0f}% 다릅니다)"
                    if closest < math.inf
                    else ""
                )
            )
            continue
        if len(near) > 1:
            near = _by_centroid(part, near)
        if len(near) != 1:
            # **닮은 파트가 둘이면 짝짓지 않는다.** 물성을 뒤바꿔 붙이면 아무 표시 없이 틀린다.
            result.failures.append(
                f"{name}: 부피 · 무게중심이 닮은 바디가 {len(near)}개라 가릴 수 없습니다"
            )
            continue
        taken.add(near[0].index)
        result.bodies[name] = near[0].index
    return result


def _volume_close(wanted: float, found: float) -> bool:
    return abs(found - wanted) / wanted <= VOLUME_TOLERANCE_RATIO


def _by_centroid(part: dict[str, Any], near: list[BodyRecord]) -> list[BodyRecord]:
    """부피로 못 가른 것을 무게중심으로. 중심이 없으면 그대로 돌려준다(가릴 수 없다)."""
    centroid = _triple(part.get("centroid"))
    if centroid is None:
        return near
    volume = float(part["volume"])
    limit = max(CENTROID_TOLERANCE_RATIO * volume ** (1 / 3), CENTROID_TOLERANCE_MIN)
    return [one for one in near if _distance(centroid, one.centroid) <= limit]


def _triple(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, list | tuple) or len(value) != 3:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return None


def _distance(one: tuple[float, float, float], other: tuple[float, float, float]) -> float:
    return math.dist(one, other)


def place_settings(
    settings: list[BodySetting], topology: dict[str, Any], records: list[BodyRecord]
) -> tuple[dict[int, BodySetting], list[str]]:
    """파트별 설정(`body_settings`)을 **해석 쪽 바디 번호에** 붙인다 — (번호 → 설정, 실패).

    단품은 이름이 「전체」 다 — 그 한 줄은 바디 전부에 붙는다(짝지을 것이 없다). 나머지는
    물성과 같은 규칙(부피 · 무게중심)으로 짝짓고, **설정이 적힌 파트만** 본다: 설정이 없는
    파트를 못 짝지은 것은 여기서 실패가 아니다(물성 쪽이 따로 본다).
    """
    if not settings:
        return {}, []
    whole = next((one for one in settings if one.name == ALL_BODIES), None)
    if whole is not None:
        return {one.index: whole for one in records}, []
    matched = match_bodies(topology, records)
    placed: dict[int, BodySetting] = {}
    failures: list[str] = []
    for one in settings:
        index = matched.bodies.get(one.name)
        if index is None:
            why = next(
                (line for line in matched.failures if line.startswith(f"{one.name}:")),
                f"{one.name}: 점 파일의 bodies[] 에 없습니다",
            )
            failures.append(why)
            continue
        placed[index] = one
    return placed, failures


def without(topology: dict[str, Any], names: set[str]) -> dict[str, Any]:
    """해석에서 뺀 파트를 `bodies[]` 에서 지운 점 파일 — 남은 바디와 짝지을 때 쓴다(뺀 파트는
    메시 · 물성 짝짓기에 나오지 않으므로 그대로 두면 「짝이 없다」 로 멈춘다)."""
    if not names or not topology:
        return topology
    rows = [
        one
        for one in topology.get("bodies") or []
        if not (isinstance(one, dict) and str(one.get("name") or "").strip() in names)
    ]
    return {**topology, "bodies": rows}
