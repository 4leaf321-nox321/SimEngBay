"""**메시 수렴** — 같은 설계점을 요소 크기만 바꿔 풀었을 때 값이 자리를 잡았나.

해석 값은 메시에 기대고, 그 기댐이 얼마인지 모르면 숫자의 자릿수를 믿을 수 없다. 요소 크기 셋
이상으로 풀면 **관측 수렴 차수**와 **격자 수렴 지수(GCI)** 로 「가장 촘촘한 메시의 값이 무한히
촘촘한 메시의 값과 얼마나 다를 수 있나」 를 잰다 — Celik 외(2008, ASME J. Fluids Eng.
130:078001)의 절차 그대로다. 둘이면 차수를 못 재므로 **두 값의 상대 변화**만 본다.

## 크기는 절점 수로 잰다

비구조 메시는 요청한 크기를 그대로 지키지 않는다(gmsh 는 크기의 1/4 까지 줄이고, 곡면 ·
힌트 자리는 더 촘촘하다). 그래서 대표 크기를 `h = (1/N)^(1/3)` 로 둔다 — 3차원에서 절점 수의
세제곱근이 요소 크기에 반비례한다.

## 판정이 넷이다

- **수렴** — 차이(GCI, 없으면 상대 변화)가 문턱 아래.
- **미수렴** — 같은 쪽으로 줄어드는데 아직 문턱 위. 더 촘촘하게 하면 된다.
- **진동** — 정련할 때마다 오르내린다. 차수를 못 믿으므로 판정을 보류한다.
- **발산** — 정련할수록 **더** 변한다. 첨두응력이 구속 모서리의 특이점에 있으면 이렇게 된다 —
  고장이 아니라 그 값이 메시에 수렴할 수 없는 값이라는 뜻이다(측정점 · 변형으로 판단한다).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Status = Literal["converged", "not_converged", "oscillating", "diverging", "insufficient"]

#: GCI 의 안전 계수 — 수준이 셋 이상일 때 Roache 가 권한 값.
SAFETY = 1.25


@dataclass(frozen=True)
class Verdict:
    status: Status
    change: float | None = None
    """가장 촘촘한 두 수준의 상대 변화 |(φ1 - φ2)/φ1|."""
    order: float | None = None
    """관측 수렴 차수 p — 2차 요소면 이론상 2 근처(변위), 응력은 그보다 낮다."""
    gci: float | None = None
    """가장 촘촘한 메시의 격자 수렴 지수(상대값)."""
    extrapolated: float | None = None
    """Richardson 외삽값 — 메시를 무한히 촘촘하게 했을 때의 추정."""


def size_of(nodes: int) -> float:
    """대표 요소 크기 `h = (1/N)^(1/3)` — 견주는 데만 쓰는 상대값이다."""
    return float((1.0 / nodes) ** (1.0 / 3.0))


def _order(r21: float, r32: float, e21: float, e32: float) -> float | None:
    """관측 차수 p — 고정점 반복(Celik 식 5). 수렴하지 않으면 `None`."""
    s = 1.0 if e32 / e21 > 0 else -1.0
    p = abs(math.log(abs(e32 / e21))) / math.log(r21)
    for _ in range(100):
        try:
            q = math.log((r21**p - s) / (r32**p - s))
        except (ValueError, ZeroDivisionError):
            return None
        nxt = abs(math.log(abs(e32 / e21)) + q) / math.log(r21)
        if abs(nxt - p) < 1e-10:
            return nxt
        p = nxt
    return p


def judge(levels: list[tuple[int, float]], *, tolerance: float) -> Verdict:
    """`[(절점 수, 값)]` → 판정. 순서는 상관없다(절점 수로 줄 세운다).

    `tolerance` 는 상대값이다(0.01 = 1%). 같은 절점 수가 겹치면 뒤의 것을 쓴다.
    """
    by_nodes = dict(sorted((int(n), float(v)) for n, v in levels if n > 0))
    ordered = sorted(by_nodes.items(), key=lambda pair: pair[0], reverse=True)  # 촘촘한 것부터
    if len(ordered) < 2:
        return Verdict("insufficient")
    (n1, f1), (n2, f2) = ordered[0], ordered[1]
    change = abs((f1 - f2) / f1) if f1 != 0 else (0.0 if f2 == 0 else math.inf)
    if len(ordered) == 2:
        return Verdict("converged" if change < tolerance else "not_converged", change=change)

    n3, f3 = ordered[2]
    e21, e32 = f2 - f1, f3 - f2
    r21, r32 = size_of(n2) / size_of(n1), size_of(n3) / size_of(n2)
    if e21 == 0:
        # 가장 촘촘한 둘이 같다 — 더 볼 것이 없다.
        return Verdict("converged", change=0.0, extrapolated=f1)
    # **두 변화가 다 문턱보다 작으면 수렴이다** — 점근 구간이 아니라 차수는 못 재도(정련할 때
    # 변화가 0.07% → 0.11% 처럼 들쭉날쭉하다), 그 크기는 판정에 이미 충분히 작다. 실측
    # (2026-10-03, CalculiX · 측면가진 1차): 4 · 2.8 · 2.0 · 1.4 mm 에서 1261.4 · 1259.0 ·
    # 1258.0 · 1256.6 Hz — 촘촘한 셋을 차수로만 보면 「발산」 이 나온다.
    earlier = abs(e32 / f2) if f2 != 0 else math.inf
    small = change < tolerance and earlier < tolerance
    if e32 == 0 or r21 <= 1.0 or r32 <= 1.0:
        return Verdict("converged" if change < tolerance else "not_converged", change=change)
    if e21 * e32 < 0:
        # 정련할 때마다 오르내린다 — 차수를 믿을 수 없다.
        return Verdict("converged" if small else "oscillating", change=change)
    if abs(e21) >= abs(e32):
        # 정련할수록 더 변한다(또는 같은 만큼) — 특이점의 첨두가 흔히 이렇다.
        return Verdict("converged" if small else "diverging", change=change)
    p = _order(r21, r32, e21, e32)
    if p is None or p <= 0:
        return Verdict("not_converged" if change >= tolerance else "converged", change=change)
    grow = r21**p - 1.0
    extrapolated = (r21**p * f1 - f2) / grow
    gci = SAFETY * change / grow
    return Verdict(
        "converged" if gci < tolerance else "not_converged",
        change=change,
        order=p,
        gci=gci,
        extrapolated=extrapolated,
    )
