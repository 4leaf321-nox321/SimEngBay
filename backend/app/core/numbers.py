"""결과 숫자를 **유효숫자로** 남긴다 — 소수 자리로 자르지 않는다.

`round(x, 4)` 는 kg 으로 적은 질량 0.029 g(2.9e-5 kg)을 0 으로 만들었다(2026-10-23 운영).
결과의 크기는 형상마다 몇 자리씩 다르다 — 작은 부품의 변위는 1e-6 mm, 큰 프레임의 반력은
1e5 N 이다. 그래서 자르는 기준은 자리가 아니라 **유효숫자**다. 여섯 자리를 남긴다 — 화면은
서너 자리를 보이지만, 두 설계점의 차이(몇 %)를 셈하려면 그보다 깊어야 한다. JSON 에는 작은
값이 지수형(`2.9e-05`)으로 적힌다.
"""

from __future__ import annotations

import math

#: 남기는 유효숫자 수.
SIGNIFICANT = 6


def significant(value: float, digits: int = SIGNIFICANT) -> float:
    """유효숫자 `digits` 자리로. 0 · 무한 · NaN 은 그대로 둔다."""
    if value == 0 or not math.isfinite(value):
        return float(value)
    return float(f"{value:.{digits - 1}e}")
