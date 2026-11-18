"""**모드 중첩의 공용 셈** — 조화 응답 · 랜덤 진동이 함께 쓴다(2026-11-18). numpy 없이 쓴다 —
CalculiX 워커(API 와 같은 파이썬)에는 numpy 가 없다.

## 모드 계수를 솔버에게서 되찾는다

하중 F 의 모드 좌표 정적 값 cₘ = φₘᵀF / ωₘ² 를 우리가 셈하려면 하중을 절점 힘으로 옮겨야
한다(압력은 요소면 적분, 관성은 질량 행렬). 그 대신 CalculiX 에게 **거의 0 Hz 로 훑게** 하면
응답이 u₀ = Σₘ φₘ cₘ 다 — u₀ 는 모드들이 덮은 공간 안에 있으니 최소제곱으로 c 가 정확히
나온다(`modal_coefficients`, 사인 스윕 덱에서 맞춤 오차 3x10⁻⁶ · 그 c 로 만든 응답이 CalculiX
조화 응답과 상대 3x10⁻⁶ 안). 그러면 아무 주파수의 모드 좌표가

    qₘ(f) = cₘ · Dₘ(f) · k(f) · e^{iφ},   Dₘ(f) = ωₘ² / (ωₘ² - Ω² + 2iζωₘΩ)

이고, 응력은 모드 응력을 같은 qₘ 로 더한다(`dynamic_gain`).

## 상당응력

von Mises 는 성분의 이차 형식이다 — σᵥ² = sᵀPs(`von_mises_form`). 조화 응답의 복소 응력
s = a + ib 는 위상 θ 에서 a cosθ - b sinθ 이고, 그 σᵥ 의 최댓값은 닫힌
꼴이다(`peak_von_mises`).
랜덤 진동의 1σ 는 E[σᵥ²] = Σᵢⱼ Pᵢⱼ Cov(sᵢ, sⱼ) 의 제곱근이다(Segalman — Ansys 의 랜덤 진동
상당응력과 같은 정의, `von_mises_rms`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

#: CalculiX `.frd` 의 `STRESS` 성분 차례 — SXX · SYY · SZZ · SXY · SYZ · SZX.
STRESS_COMPONENTS = 6
#: 모드 계수 맞춤에 쓰는 절점 수 상한 — 고르게 솎는다(모드 수 K 면 K² x 3 x 이 수만큼 곱한다).
FIT_NODES = 2_000


def solve(matrix: Sequence[Sequence[float]], rhs: Sequence[float]) -> list[float]:
    """선형계 풀기 — 부분 피벗 가우스 소거. 특이한 행은 0 으로 둔다."""
    size = len(rhs)
    rows = [[*matrix[i], rhs[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda at: abs(rows[at][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        lead = rows[col][col]
        if abs(lead) < 1e-300:
            continue
        for at in range(size):
            if at == col:
                continue
            factor = rows[at][col] / lead
            if factor:
                for k in range(col, size + 1):
                    rows[at][k] -= factor * rows[col][k]
    return [
        rows[i][size] / rows[i][i] if abs(rows[i][i]) >= 1e-300 else 0.0 for i in range(size)
    ]


def modal_coefficients(
    shapes: Sequence[Mapping[int, Sequence[float]]],
    target: Mapping[int, Sequence[float]],
) -> list[float]:
    """target ≈ Σₘ cₘ φₘ 의 c — 최소제곱(정규 방정식, 절점을 고르게 솎는다). 변위 세 성분."""
    count = len(shapes)
    if not count:
        return []
    nodes = [node for node in target if all(node in one for one in shapes)]
    step = max(1, len(nodes) // FIT_NODES)
    normal = [[0.0] * count for _ in range(count)]
    rhs = [0.0] * count
    for node in nodes[::step]:
        goal = target[node]
        for axis in range(3):
            row = [shapes[m][node][axis] for m in range(count)]
            value = goal[axis]
            for i in range(count):
                if not row[i]:
                    continue
                rhs[i] += row[i] * value
                line = normal[i]
                for j in range(count):
                    line[j] += row[i] * row[j]
    return solve(normal, rhs)


def dynamic_gain(natural_hz: float, hz: float, damping_ratio: float) -> complex:
    """모드 좌표의 동적 배율 Dₘ(f) = ωₘ² / (ωₘ² - Ω² + 2iζωₘΩ) — 정적 값에 곱한다(f → 0 이면
    1)."""
    wn = 2 * math.pi * natural_hz
    w = 2 * math.pi * hz
    return complex(wn * wn) / complex(wn * wn - w * w, 2 * damping_ratio * wn * w)


def von_mises_form(a: Sequence[float], b: Sequence[float]) -> float:
    """von Mises 이차 형식의 쌍선형 꼴 Q(a, b) — Q(s, s) = σᵥ². 성분은 SXX · SYY · SZZ · SXY ·
    SYZ · SZX."""
    return (
        a[0] * b[0]
        + a[1] * b[1]
        + a[2] * b[2]
        - 0.5 * (a[0] * b[1] + a[1] * b[0])
        - 0.5 * (a[1] * b[2] + a[2] * b[1])
        - 0.5 * (a[2] * b[0] + a[0] * b[2])
        + 3.0 * (a[3] * b[3] + a[4] * b[4] + a[5] * b[5])
    )


def peak_von_mises(real: Sequence[float], imaginary: Sequence[float]) -> float:
    """복소 응력(조화 응답)의 **위상을 돌린 최대 σᵥ** — s(θ) = a cosθ - b sinθ 에서

        σᵥ²(θ) = A cos²θ + B sin²θ - 2C sinθ cosθ,  A = Q(a,a) · B = Q(b,b) · C = Q(a,b)

    의 최댓값 (A+B)/2 + √(((A-B)/2)² + C²) 의 제곱근."""
    big_a = von_mises_form(real, real)
    big_b = von_mises_form(imaginary, imaginary)
    cross = von_mises_form(real, imaginary)
    top = (big_a + big_b) / 2 + math.sqrt(((big_a - big_b) / 2) ** 2 + cross * cross)
    return math.sqrt(max(top, 0.0))


def von_mises_rms(
    shapes: Sequence[Sequence[float]], matrix: Sequence[Sequence[float]]
) -> float:
    """**랜덤 응답의 상당응력 1σ**(Segalman) — √E[σᵥ²], E[σᵥ²] = Σₘₖ Rₘₖ Q(ψₘ, ψₖ).

    `shapes` 는 모드마다 그 절점의 응력 ψₘ(성분 여섯), `matrix` 는 모드 결합 행렬 R
    (`random_vibration.couplings` — 변위 1σ 와 같은 것)."""
    total = 0.0
    count = len(shapes)
    for m in range(count):
        row = matrix[m]
        if not row[m]:
            continue
        total += row[m] * von_mises_form(shapes[m], shapes[m])
        for k in range(m + 1, count):
            if row[k]:
                total += 2 * row[k] * von_mises_form(shapes[m], shapes[k])
    return math.sqrt(max(total, 0.0))
