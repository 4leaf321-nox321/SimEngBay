"""모드 하나를 **변위 분포로** 설명하는 지표들.

## 왜 필요한가

유효질량비는 「바닥을 통째로 흔들었을 때 얼마나 반응하나」 다. 자유-자유 해석에서는 그 값이
**정확히 0 이다** — 탄성 모드가 강체 모드와 질량 직교라서, 공중에 뜬 물체를 균일하게 밀면
변형하지 않는다. 그래서 구속을 걸기 전(4단계 전)까지는 유효질량비로 모드를 설명할 수 없다.

대신 **변위장 자체**에서 읽을 수 있는 것이 있다. 여기 있는 둘은 모달 변위가 질량 정규화된
상대값이어도 성립한다 — **비율**만 쓰기 때문이다.

    direction_share  모드가 주로 어느 축으로 움직이나 (|u_x|² : |u_y|² : |u_z|²)
    localization     전체가 함께 움직이나, 한 구석만 떠는가

`localization` 은 참여비(inverse participation ratio)다:

    L = (Σ|u|²)² / (N · Σ|u|⁴)

절점 전부가 똑같이 움직이면 1, 한 절점만 움직이면 1/N 이다. **국부 모드는 대개 쓸모가 없다** —
얇은 립 하나가 떠는 것이고, 그것을 1차 공진으로 읽으면 엉뚱한 곳을 보강하게 된다.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

#: 이보다 작으면 「국부」 로 본다.
#:
#: **실측으로 정했다**(2026-09-21, L 브래킷 2025 R2). 판 전체가 휘는 정상적인 모드도 참여비는
#: 1 이 아니다 — 반파장 사인 분포만으로 0.67 이 되고, 몸통의 3분의 1(플랜지)이 움직이는 모드는
#: 0.17~0.38 이었다. 그것을 「국부」 라고 적으면 **정상 모드에 매번 경고가 붙고, 그러면 경고는
#: 아무 뜻도 못 갖는다.** 한 구석만 떠는 모드(립 하나)는 0.05 아래로 떨어진다.
LOCAL_BELOW = 0.1


def _rows(vectors: Any) -> Iterator[tuple[float, float, float]]:
    """(n, 3) 배열이든 납작한 길이 3n 이든 세 개씩 끊어 읽는다.

    **numpy 를 쓰지 않는다.** 이 계산은 합 몇 개라 파이썬으로도 충분히 빠르고, numpy 를 부르면
    API 서버 · CI 에 없는 것(워커에만 있다)이 되어 **이 수학을 아무 데서도 시험할 수 없다.**
    """
    flat: list[float] = []
    for item in vectors:
        if isinstance(item, Iterable) and not isinstance(item, str | bytes):
            values = [float(one) for one in item]
            if len(values) != 3:
                raise ValueError(f"변위 벡터는 성분 셋이어야 합니다: {len(values)}")
            yield values[0], values[1], values[2]
            continue
        flat.append(float(item))
        if len(flat) == 3:
            yield flat[0], flat[1], flat[2]
            flat.clear()
    if flat:
        raise ValueError("변위 값의 개수가 3의 배수가 아닙니다.")


def direction_share(vectors: Any) -> dict[str, float]:
    """축별 변위 에너지 비중. 합이 1 이다.

    **크기가 아니라 비율이라** 모달 변위의 정규화 방식과 무관하다.
    """
    sums = [0.0, 0.0, 0.0]
    for x, y, z in _rows(vectors):
        sums[0] += x * x
        sums[1] += y * y
        sums[2] += z * z
    total = sum(sums)
    if total <= 0:
        return {"x": 0.0, "y": 0.0, "z": 0.0}
    return {
        "x": round(sums[0] / total, 4),
        "y": round(sums[1] / total, 4),
        "z": round(sums[2] / total, 4),
    }


def dominant_axis(share: dict[str, float], *, floor: float = 0.5) -> str | None:
    """가장 큰 축.

    어느 축도 절반을 못 넘으면 None — **섞인 모드를 한 축이라고 말하지 않는다.**
    """
    if not share:
        return None
    axis, value = max(share.items(), key=lambda one: one[1])
    # **절반을 「넘어야」 한다.** 정확히 반반인 모드(x 0.5 · y 0.5)는 한 축의 모드가 아니라
    # 대각선으로 움직이는 모드다 — 그것을 X 라고 적으면 다음 사람이 X 가진만 확인한다.
    return axis.upper() if value > floor else None


def localization(vectors: Any) -> float:
    """전역(1)에서 국부(1/N)까지. 절점 수가 달라도 견줄 수 있게 참여비로 잰다."""
    count = 0
    total = 0.0
    fourth = 0.0
    for x, y, z in _rows(vectors):
        squared = x * x + y * y + z * z
        total += squared
        fourth += squared * squared
        count += 1
    if count == 0 or total <= 0 or fourth <= 0:
        return 0.0
    return round(total**2 / (count * fourth), 4)


def is_local(value: float) -> bool:
    return 0.0 < value < LOCAL_BELOW
