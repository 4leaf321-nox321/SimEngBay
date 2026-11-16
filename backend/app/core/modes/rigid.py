"""**0 Hz 모드** — 강체 모드로 세고, 움직이는 바디와 그럴 만한 까닭을 말한다(두 솔버 공통).

## 2026-11-16 에 바꾼 것

전에는 구속이 있으면 0 Hz 모드를 강체로 세지 않았다. 「구속된 모델의 0 Hz 는 자유로 둔
방향이다」 라는 생각이었다. 그러면 바닥을 고정한 조립에서 덮개 하나가 떠 있을 때
「강체 모드 0개 · 1차 탄성 0 Hz」 가 나왔다(CompCore 의 조립 점검). 설계점 비교 · 모드
추적 · 실측 짝짓기가 그 0 Hz 를 탄성 모드로 읽었다.

0 Hz 모드는 변형 에너지가 없는 움직임이다. 통째로 떠 있든, 원통 지지의 접선처럼 일부러
열어 둔 방향이든, 미끄럼 접촉으로만 이어진 바디가 미끄러지든 탄성 모드가 아니다. 그래서
이제 **구속이 있어도 문턱(1 Hz) 아래는 강체 모드로 센다.** 강체 모드가 있으면 경고를 단다:

- 구속이 있을 때: 0 Hz 모드 수, 그 모드에서 **움직이는 바디**(파트 몫 `part_share` 가
  20 % 이상), 그럴 만한 까닭(모델링이 남긴 `boundary.json` 의 `connections` — 맞닿았는데
  접촉이 없는 쌍, 미끄럼으로 푼 접촉).
- 자유-자유일 때: 강체 모드가 6개가 아니면.

앞의 6개만 세던 상한도 없앴다. 바디 둘이 떨어진 자유-자유는 0 Hz 가 12개다. 상한이 있으면
6개만 강체로 세어 「6개여야 한다」 경고가 안 섰다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.core.spec import RIGID_BODY_MODES

#: 이보다 낮으면 강체 모드다. 수치 오차로 0 이 정확히 0 으로 안 나온다(실측: 여섯 번째가
#: 0.0023 Hz). 이 해석들의 탄성 모드는 수백 Hz 위다.
RIGID_BODY_HZ = 1.0
#: 0 Hz 모드에서 움직임의 몫이 이 이상인 파트를 「움직이는 바디」 로 적는다.
MOVING_SHARE = 0.2


def read_connections(boundary: Path) -> dict[str, Any] | None:
    """모델링이 남긴 연결(`boundary.json` 의 `connections`) — 접촉 없이 맞닿은 쌍 · 미끄럼으로
    푼 접촉. 없거나 못 읽으면 None."""
    if not boundary.is_file():
        return None
    try:
        found = json.loads(boundary.read_text(encoding="utf-8")).get("connections")
    except (OSError, ValueError, AttributeError):
        return None
    return found if isinstance(found, dict) else None


def is_rigid(frequency_hz: float) -> bool:
    """강체 모드인가 — 구속과 상관없이 문턱 아래면."""
    return frequency_hz < RIGID_BODY_HZ


def moving_bodies(modes: Sequence[Mapping[str, Any]]) -> list[str]:
    """0 Hz 모드에서 움직이는 바디 — 가장 크게 움직인 차례. 파트 몫이 없으면(바디 하나 ·
    형상을 못 읽음) 빈 목록."""
    best: dict[str, float] = {}
    for one in modes:
        if not one.get("rigid_body"):
            continue
        for name, share in (one.get("part_share") or {}).items():
            if isinstance(share, int | float) and share >= MOVING_SHARE:
                best[str(name)] = max(float(share), best.get(str(name), 0.0))
    return sorted(best, key=lambda name: (-best[name], name))


def warning(
    modes: Sequence[Mapping[str, Any]],
    *,
    constrained: bool,
    connections: Mapping[str, Any] | None = None,
) -> str | None:
    """결과에 달 경고 — 없으면 None."""
    rigid = sum(1 for one in modes if one.get("rigid_body"))
    if constrained:
        if not rigid:
            return None
        moving = moving_bodies(modes)
        text = (
            f"구속이 있는데 0 Hz 모드가 {rigid}개입니다 — 강체 모드로 세어 탄성 모드에서 "
            "뺐습니다."
        )
        if moving:
            text += f" 움직이는 바디: {', '.join(moving)}."
        causes = _causes(moving, connections)
        return f"{text} " + (
            causes
            or "자유로 둔 방향(원통 지지의 접선 · 마찰 없는 지지 · 탄성 지지의 면 방향)이나 "
            "빠진 접촉 · 구속이 있는지 보세요."
        )
    if rigid == RIGID_BODY_MODES:
        return None
    text = f"자유-자유인데 강체 모드가 {rigid}개입니다(6개여야 합니다)."
    return f"{text} " + (
        _causes([], connections) or "바디가 여럿이면 맞닿은 면이 붙지 않았을 수 있습니다."
    )


def _causes(moving: Sequence[str], connections: Mapping[str, Any] | None) -> str:
    """그럴 만한 까닭 — 움직이는 바디가 낀 「접촉 없이 맞닿은 쌍」 · 「미끄럼 접촉」. 움직이는
    바디를 모르면 전부."""
    if not connections:
        return ""
    picked = set(moving)

    def involved(names: Sequence[Any]) -> bool:
        return not picked or bool(picked & {str(one) for one in names})

    said: list[str] = []
    untied = [
        one
        for one in connections.get("untied") or []
        if isinstance(one, Mapping) and involved([one.get("a"), one.get("b")])
    ]
    if untied:
        pairs = ", ".join(f"{one.get('a')} ↔ {one.get('b')}" for one in untied)
        said.append(f"접촉 미정의: 인접 바디 {pairs} — 떨어진 채로 풀었습니다. 접촉을 거세요.")
    sliding = [
        one
        for one in connections.get("sliding") or []
        if isinstance(one, Mapping) and involved(one.get("bodies") or [])
    ]
    if sliding:
        names = ", ".join(f"「{one.get('contact')}」" for one in sliding)
        said.append(
            f"미끄럼으로 푼 접촉 {names}(분리 없음 · 마찰 없음)은 면 방향을 잡지 않습니다 — "
            "그 접촉으로만 이어진 바디는 미끄러집니다."
        )
    return " ".join(said)
