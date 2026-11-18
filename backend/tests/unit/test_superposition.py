"""**모드 중첩의 공용 셈**(`app/core/superposition.py`, 2026-11-18) — 조화 응답의 잔여 벡터 ·
응력, 랜덤 진동의 상당응력 1σ 가 함께 쓴다.

솔버까지 도는 시험은 `tests/opensolver` 다(시험_진동_150Hz 의 150 Hz 응답 = 1 g 정적 해,
시험_랜덤진동의 응력 1σ = 1 g 정적 응력 x Grms).
"""

from __future__ import annotations

import math

import pytest

from app.core import random_vibration as random_model
from app.core import superposition


def test_선형계를_푼다() -> None:
    got = superposition.solve(
        [[2.0, 1.0, 0.0], [1.0, 3.0, 1.0], [0.0, 1.0, 4.0]], [3.0, 5.0, 5.0]
    )
    assert got == pytest.approx([1.0, 1.0, 1.0])


def test_모드_계수를_0_Hz_응답에서_정확히_되찾는다() -> None:
    """u₀ = Σ cₘφₘ 는 모드들이 덮은 공간 안에 있다 — 최소제곱이 c 를 그대로 낸다."""
    shapes = [
        {node: [math.sin(node), 0.1 * node, 1.0] for node in range(1, 50)},
        {node: [math.cos(node), 1.0, -0.02 * node] for node in range(1, 50)},
        {node: [0.0, math.sin(2 * node), math.cos(3 * node)] for node in range(1, 50)},
    ]
    truth = [0.7, -1.3, 2.5e-3]
    target = {
        node: [sum(truth[m] * shapes[m][node][a] for m in range(3)) for a in range(3)]
        for node in range(1, 50)
    }
    assert superposition.modal_coefficients(shapes, target) == pytest.approx(truth, rel=1e-9)


def test_동적_배율은_0_Hz_에서_1_공진에서_1_2ζ() -> None:
    assert superposition.dynamic_gain(100.0, 1e-6, 0.02) == pytest.approx(1.0)
    assert abs(superposition.dynamic_gain(100.0, 100.0, 0.02)) == pytest.approx(25.0)


def test_상당응력_꼴과_위상을_돌린_최대() -> None:
    uniaxial = [10.0, 0, 0, 0, 0, 0]
    shear = [0, 0, 0, 5.0, 0, 0]
    assert math.sqrt(superposition.von_mises_form(uniaxial, uniaxial)) == pytest.approx(10.0)
    assert math.sqrt(superposition.von_mises_form(shear, shear)) == pytest.approx(
        5 * math.sqrt(3)
    )
    # 실수부만 — 위상과 무관하게 그 크기.
    assert superposition.peak_von_mises(uniaxial, [0.0] * 6) == pytest.approx(10.0)
    # σxx(실수부)와 τxy(허수부)가 90° 어긋나면 둘이 함께 크지 않다 — σᵥ² = 100 cos²θ + 75 sin²θ
    # 의 최대는 θ = 0 의 10 이다(함께 크다고 셈하면 √175 = 13.2).
    assert superposition.peak_von_mises(uniaxial, shear) == pytest.approx(10.0)
    # 위상을 잘게 돌려 찾은 최대와 같다.
    real, imag = [3.0, -1.0, 2.0, 0.5, 0.2, -0.7], [-1.0, 2.5, 0.3, -0.4, 1.1, 0.6]
    sampled = max(
        math.sqrt(
            superposition.von_mises_form(
                [r * math.cos(t) - i * math.sin(t) for r, i in zip(real, imag, strict=True)],
                [r * math.cos(t) - i * math.sin(t) for r, i in zip(real, imag, strict=True)],
            )
        )
        for t in (k * math.pi / 3600 for k in range(3600))
    )
    assert superposition.peak_von_mises(real, imag) == pytest.approx(sampled, rel=1e-6)


def test_랜덤_상당응력_1σ_는_상한으로_거른_최대가_다_셈한_최대와_같다() -> None:
    """모드 하나면 1σ = √R · σᵥ(ψ). 절점 여럿 · 모드 여럿에서 상한으로 거른 최대가 모든 절점을
    다 셈한 최대와 같다."""
    psi = [4.0, 0, 0, 0, 0, 0]
    assert superposition.von_mises_rms([psi], [[0.25]]) == pytest.approx(0.5 * 4.0)
    stresses = [
        {
            node: [math.sin(node + m), 0.3 * m, math.cos(node), 0.1, 0.0, 0.2 * node % 1.3]
            for node in range(1, 200)
        }
        for m in range(4)
    ]
    matrix = [
        [2.0, 0.3, -0.1, 0.0],
        [0.3, 1.0, 0.2, 0.05],
        [-0.1, 0.2, 0.5, 0.0],
        [0.0, 0.05, 0.0, 1e-3],
    ]
    best, node = random_model.stress_sigma(stresses, matrix)
    brute = {
        at: superposition.von_mises_rms([one[at] for one in stresses], matrix)
        for at in range(1, 200)
    }
    top = max(brute, key=lambda at: brute[at])
    assert node == top and best == pytest.approx(brute[top], rel=1e-12)
