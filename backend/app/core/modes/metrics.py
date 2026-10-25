"""모드 하나를 **변위 분포로** 설명하는 지표들.

## 왜 필요한가

유효질량비는 「바닥을 통째로 흔들었을 때 얼마나 반응하나」 다. 자유-자유 해석에서는 그 값이
**정확히 0 이다** — 탄성 모드가 강체 모드와 질량 직교라서, 공중에 뜬 물체를 균일하게 밀면
변형하지 않는다. 그래서 구속을 걸기 전(4단계 전)까지는 유효질량비로 모드를 설명할 수 없다.

대신 **변위장 자체**에서 읽을 수 있는 것이 있다. 여기 있는 둘은 모달 변위가 질량 정규화된
상대값이어도 성립한다 — **비율**만 쓰기 때문이다.

    direction_share  모드가 주로 어느 축으로 움직이나 (|u_x|² : |u_y|² : |u_z|²)
    localization     전체가 함께 움직이나, 한 구석만 떠는가

`localization` 은 참여비(inverse participation ratio)다. 절점마다 그 절점이 맡은 **부피**
`w`(쉘은 넓이 x 두께)로 가중한다:

    L = (Σ w|u|²)² / (W · Σ w|u|⁴),  W = Σ w

전부가 똑같이 움직이면 1, 부피 비율 f 만큼만 고르게 움직이면 f 다 — **움직이는 부피의
몫**으로 읽힌다. **국부 모드는 대개 쓸모가 없다** — 얇은 립 하나가 떠는 것이고, 그것을 1차
공진으로 읽으면 엉뚱한 곳을 보강하게 된다.

## 왜 부피로 재나 · 왜 파트마다 보나(2026-10-25)

처음에는 절점 수로 셌다(w = 1). 그러면 **메시가 촘촘한 곳이 값을 가져간다** — 같은 기둥 ·
받침판 모델(`조건_측면가진`)의 1차 굽힘이 Ansys 0.094 · CalculiX 0.055 로 갈렸다(CalculiX 가
받침판을 더 촘촘히 나눈다). 부피로 재면 메시와 무관해진다.

그래도 그 1차는 「국부」 였다 — 고정된 받침판은 안 움직이고 기둥만 휘니 움직이는 부피가
작다. 바디가 둘 이상이면 **어느 파트가 움직이나**(`part_share` · `dominant_part`)를 먼저
말하고, 국부 · 전역은 **그 파트 안에서** 잰다. 「기둥 98% · 전역」 이 그 모드의 말이다. 한
바디 안에서 립 하나만 떠는 진짜 국부 모드는 여전히 「국부」 다 — 그것이 이 경고가 잡으려는
것이다.

## 왜 여기 있나

**두 솔버가 같은 셈을 한다**(2026-10-25). 처음에는 Ansys 쪽(`core/dpf`)에만 있어 CalculiX
결과의 「성격」(전역 · 국부)과 변위 축 비중이 늘 비었다. 모드 지문(`signature.py`)과 같은
까닭으로 솔버와 무관한 이 자리에 둔다 — 순수 파이썬이라 CalculiX 워커(numpy 없음)에서도 돈다.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

#: 이보다 작으면 「국부」 로 본다.
#:
#: **실측으로 정했다**(2026-09-21, L 브래킷 2025 R2). 판 전체가 휘는 정상적인 모드도 참여비는
#: 1 이 아니다 — 반파장 사인 분포만으로 0.67 이 되고, 몸통의 3분의 1(플랜지)이 움직이는 모드는
#: 0.17~0.38 이었다. 그것을 「국부」 라고 적으면 **정상 모드에 매번 경고가 붙고, 그러면 경고는
#: 아무 뜻도 못 갖는다.** 한 구석만 떠는 모드(립 하나)는 0.05 아래로 떨어진다.
#:
#: 부피로 재고 나서 다시 봤다(2026-10-25, 요소 5 mm): 같은 L 브래킷(자유-자유) 탄성 모드 10개가
#: CalculiX 0.10~0.40 · Ansys 0.11~0.39 로 두 솔버가 모드마다 0.01 안팎에서 맞고, 모두 문턱
#: 위다. 기둥 · 받침판의 1차는 기둥 안에서 0.43(두 솔버). 문턱은 그대로 둔다.
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


def direction_share(vectors: Any, weights: Sequence[float] | None = None) -> dict[str, float]:
    """축별 변위 에너지 비중(부피 가중). 합이 1 이다.

    **크기가 아니라 비율이라** 모달 변위의 정규화 방식과 무관하다.
    """
    sums = [0.0, 0.0, 0.0]
    for index, (x, y, z) in enumerate(_rows(vectors)):
        weight = 1.0 if weights is None else weights[index]
        sums[0] += weight * x * x
        sums[1] += weight * y * y
        sums[2] += weight * z * z
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


def localization(vectors: Any, weights: Sequence[float] | None = None) -> float:
    """전역(1)에서 국부(0 에 가까움)까지 — 움직이는 부피의 몫. 가중치가 없으면 절점 수로 센다.

    가중치가 0 인 절점은 세지 않는다 — 파트 안에서만 잴 때 다른 파트의 절점이 그렇다.
    """
    weight = 0.0
    total = 0.0
    fourth = 0.0
    for index, (x, y, z) in enumerate(_rows(vectors)):
        share = 1.0 if weights is None else float(weights[index])
        if share <= 0:
            continue
        squared = x * x + y * y + z * z
        weight += share
        total += share * squared
        fourth += share * squared * squared
    if weight <= 0 or total <= 0 or fourth <= 0:
        return 0.0
    return round(total**2 / (weight * fourth), 4)


def part_shares(vectors: Any, parts: Mapping[str, Sequence[float]]) -> dict[str, float]:
    """파트마다 **움직임의 몫** — Σ w_파트 |u|² 를 모두의 합으로 나눈 것. 합이 1 이다.

    `parts[이름][i]` 는 절점 i 가 그 파트에서 맡은 부피다 — 두 바디가 절점을 나눠 쓰면 양쪽에
    몫이 있다.
    """
    energies = [x * x + y * y + z * z for x, y, z in _rows(vectors)]
    sums = {
        name: sum(weight * energy for weight, energy in zip(weights, energies, strict=True))
        for name, weights in parts.items()
    }
    total = sum(sums.values())
    if total <= 0:
        return {}
    return {name: round(value / total, 4) for name, value in sums.items()}


def describe(
    vectors: Any,
    weights: Sequence[float] | None = None,
    parts: Mapping[str, Sequence[float]] | None = None,
) -> dict[str, Any]:
    """모드 하나의 **성격** — 두 솔버가 같은 열쇠로 결과에 싣는다.

    `weights` 는 절점마다 맡은 부피(없으면 절점 수로), `parts` 는 그것을 파트마다 나눈 것이다.
    파트가 둘 이상이면 가장 많이 움직이는 파트와 그 몫을 적고, 국부 · 전역은 **그 파트 안에서**
    잰다(모듈 설명).
    """
    vectors = list(_rows(vectors))
    out: dict[str, Any] = {}
    share = direction_share(vectors, weights)
    out["direction_share"] = share
    axis = dominant_axis(share)
    if axis is not None:
        out["dominant_axis"] = axis
    inside: Sequence[float] | None = weights
    if parts and len(parts) >= 2:
        shares = part_shares(vectors, parts)
        if shares:
            top = max(shares, key=lambda name: shares[name])
            out["part_share"] = shares
            out["dominant_part"] = top
            inside = parts[top]
    value = localization(vectors, inside)
    out["localization"] = value
    out["local_mode"] = is_local(value)
    return out


def is_local(value: float) -> bool:
    return 0.0 < value < LOCAL_BELOW
