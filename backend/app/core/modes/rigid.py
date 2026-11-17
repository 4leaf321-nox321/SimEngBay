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


#: 모양이 **강체 운동**인 모드 — 변위를 a + θ x (x - c) 로 맞추고 남은 몫(크기 대비)이 이 아래.
#: 구속식이 회전을 잡아 올라온 강체 모드는 0.1 % 안팎이고, 탄성 모드는 수십 % 다.
RIGID_SHAPE = 0.02
#: 강체 맞춤에 쓰는 절점 수 상한 — 고르게 솎는다(큰 모델에서 모드마다 한 번).
FIT_NODES = 20_000


def rigid_residual(
    points: Sequence[Sequence[float]], vectors: Sequence[Sequence[float]]
) -> float:
    """변위장을 **강체 운동** a + θ x (x - c) 로 맞추고 남은 몫 √(Σ|남은 것|² / Σ|u|²).

    0 이면 강체 운동이다. 무게중심 c 둘레로 놓으면 a 는 평균 변위이고 θ 는 관성 텐서
    Σ(|r|²I - r rᵀ) θ = Σ r x (u - a) 를 풀면 된다(numpy 없이). 변위가 없으면 1."""
    count = min(len(points), len(vectors))
    if count < 3:
        return 1.0
    step = max(1, count // FIT_NODES)
    picked = range(0, count, step)
    n = len(picked)
    c = [sum(points[at][axis] for at in picked) / n for axis in range(3)]
    a = [sum(vectors[at][axis] for at in picked) / n for axis in range(3)]
    inertia = [[0.0] * 3 for _ in range(3)]
    rhs = [0.0, 0.0, 0.0]
    total = 0.0
    for at in picked:
        r = [points[at][axis] - c[axis] for axis in range(3)]
        u = [vectors[at][axis] for axis in range(3)]
        v = [u[axis] - a[axis] for axis in range(3)]
        total += u[0] * u[0] + u[1] * u[1] + u[2] * u[2]
        size = r[0] * r[0] + r[1] * r[1] + r[2] * r[2]
        for i in range(3):
            for j in range(3):
                inertia[i][j] += (size if i == j else 0.0) - r[i] * r[j]
        rhs[0] += r[1] * v[2] - r[2] * v[1]
        rhs[1] += r[2] * v[0] - r[0] * v[2]
        rhs[2] += r[0] * v[1] - r[1] * v[0]
    if total <= 0:
        return 1.0
    theta = _solve3(inertia, rhs)
    left = 0.0
    for at in picked:
        r = [points[at][axis] - c[axis] for axis in range(3)]
        spin = (
            theta[1] * r[2] - theta[2] * r[1],
            theta[2] * r[0] - theta[0] * r[2],
            theta[0] * r[1] - theta[1] * r[0],
        )
        for axis in range(3):
            gap = vectors[at][axis] - a[axis] - spin[axis]
            left += gap * gap
    return float((left / total) ** 0.5)


def _solve3(matrix: Sequence[Sequence[float]], rhs: Sequence[float]) -> list[float]:
    """3x3 풀기(크라머). 특이하면(한 줄에 놓인 절점) 0 — 회전 몫 없이 맞춘다."""

    def det(m: Sequence[Sequence[float]]) -> float:
        return (
            m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
        )

    whole = det(matrix)
    scale = max(abs(value) for row in matrix for value in row) or 1.0
    if abs(whole) <= 1e-12 * scale**3:
        return [0.0, 0.0, 0.0]
    out = []
    for column in range(3):
        swapped = [
            [rhs[i] if j == column else matrix[i][j] for j in range(3)] for i in range(3)
        ]
        out.append(det(swapped) / whole)
    return out


def held_rigid(
    modes: list[dict[str, Any]],
    residual_of: Any,
) -> list[dict[str, Any]]:
    """**구속식이 잡은 강체 모드** — 자유-자유에서 문턱(1 Hz)을 넘었지만 모양이 강체 운동인
    낮은 모드. 강체 모드로 고쳐 세고(탄성 차수를 다시 센다) 그 모드들을 돌려준다.

    낮은 쪽부터 탄성 모드를 보고 모양이 강체가 아닌 첫 모드에서 멈춘다(강체 모드는 다 해서
    6개를 넘지 않게). `residual_of(number)` 는 그 모드의 `rigid_residual` — 못 셈하면 None.

    예: 쉘 ↔ 솔리드를 `*TIE` 로 묶었을 때 회전 셋이 2.6 · 5.0 · 12.8 Hz 로 올라왔다
    (셸모델_시트받침조립, 1차 탄성 475 Hz — 지금은 구속식으로 묶어 안 생긴다). 그대로 두면
    「1차 탄성 2.6 Hz」 다. 고친 뒤로는 안전망이다."""
    held: list[dict[str, Any]] = []
    rigid = sum(1 for one in modes if one.get("rigid_body"))
    for one in modes:
        if one.get("rigid_body"):
            continue
        if rigid + len(held) >= RIGID_BODY_MODES:
            break
        left = residual_of(int(one["number"]))
        if left is None or left >= RIGID_SHAPE:
            break
        one["rigid_body"] = True
        one["held_rigid"] = True
        one["rigid_residual"] = round(left, 6)
        held.append(one)
    if held:
        elastic = 0
        for one in modes:
            if one.get("rigid_body"):
                one["elastic_number"] = None
            else:
                elastic += 1
                one["elastic_number"] = elastic
    return held


def held_note(held: Sequence[Mapping[str, Any]]) -> str:
    """구속식이 잡은 강체 모드의 말 — 무엇이 그렇게 하는지까지."""
    numbers = " · ".join(str(one["number"]) for one in held)
    values = " · ".join(f"{float(one['frequency_hz']):,.3g}" for one in held)
    return (
        f"모드 {numbers}({values} Hz)는 모양이 강체 운동인데 0 Hz 가 아닙니다 — 바디를 잇는 "
        "구속식(*TIE · *EQUATION)이 강체 회전을 잡아 올라온 것이라 강체 모드로 셌습니다. "
        "종속 절점이 상대 면에서 떨어진 채 묶이면 생깁니다. 그 바디들 사이의 탄성 거동도 "
        "그만큼 굳어 있을 수 있습니다 — 접합 면의 형상 · 검색 반경을 보세요."
    )


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
