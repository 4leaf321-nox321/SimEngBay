"""결과 숫자는 **유효숫자로** 남긴다 — 소수 자리로 자르면 작은 부품의 질량이 0 이 된다
(2026-10-23 운영: 0.029 g 이 모두 0 kg)."""

from __future__ import annotations

import math

import pytest

from app.core.numbers import significant


def test_작은_값도_유효숫자로_남는다() -> None:
    # 0.029 g = 2.9e-5 kg — 전에는 round(x, 4) 가 0 으로 만들었다.
    assert significant(2.9123456e-5) == 2.91235e-5
    assert significant(1.234567e-9) == 1.23457e-9


def test_큰_값은_소수를_더_남기지_않는다() -> None:
    assert significant(123456.789) == 123457.0
    assert significant(-1499.6123) == -1499.61


def test_0_무한_NaN_은_그대로() -> None:
    assert significant(0.0) == 0.0
    assert significant(math.inf) == math.inf
    assert math.isnan(significant(math.nan))


def test_작은_부품의_질량이_0_이_되지_않는다() -> None:
    """운영에서 본 그대로 — 강 3.7 mm³ 는 0.029 g 이다(CalculiX 모델링의 질량 셈)."""
    from types import SimpleNamespace

    from app.core.calculix.build import _mass_kg

    steel = SimpleNamespace(bodies=["핀"], density_kg_m3=7850.0)
    mesh = SimpleNamespace(bodies=[SimpleNamespace(index=1, volume=3.7)])
    mass = _mass_kg([steel], {"핀": 1}, mesh)  # type: ignore[list-item]
    assert mass is not None
    assert mass * 1000 == pytest.approx(0.029045, rel=1e-4)
