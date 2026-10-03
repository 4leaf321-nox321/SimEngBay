"""메시 수렴 판정 — **Celik 외(2008)의 절차와 맞는가, 특이점을 「발산」 으로 읽는가.**"""

from __future__ import annotations

import pytest

from app.core.convergence import judge, size_of


def _nodes(h: float) -> int:
    """대표 크기 h 를 주는 절점 수 — `size_of` 의 거꾸로."""
    return round((1.0 / h) ** 3)


def test_2차_수렴하는_값의_차수와_외삽값을_되찾는다() -> None:
    """φ(h) = 100 + 5h² 를 h = 1 · 2 · 4 로 풀면 p = 2, 외삽값은 100 이어야 한다."""
    levels = [(_nodes(h / 100), 100 + 5 * h**2) for h in (1.0, 2.0, 4.0)]
    verdict = judge(levels, tolerance=0.01)
    assert verdict.order == pytest.approx(2.0, rel=0.02)
    assert verdict.extrapolated == pytest.approx(100.0, rel=1e-3)
    # 가장 촘촘한 값 105 는 외삽값 100 에서 5% — GCI 가 그만큼을 말한다.
    assert verdict.gci == pytest.approx(1.25 * (5 / 105 * 3) / 3, rel=0.05)
    assert verdict.status == "not_converged"


def test_차이가_문턱보다_작으면_수렴이다() -> None:
    levels = [(_nodes(h / 100), 1266.4 * (1 + 1e-4 * h**2)) for h in (1.0, 1.5, 2.25)]
    verdict = judge(levels, tolerance=0.01)
    assert verdict.status == "converged"
    assert verdict.gci is not None and verdict.gci < 0.01


def test_정련할수록_더_커지면_발산이다() -> None:
    """**구속 모서리의 첨두응력** — 요소를 줄일수록 커진다. 고장이 아니라 수렴할 수 없는
    값이다."""
    levels = [(_nodes(h / 100), 120 + 40 / h) for h in (1.0, 2.0, 4.0)]
    assert judge(levels, tolerance=0.02).status == "diverging"


def test_오르내리면_판정을_보류한다() -> None:
    levels = [(1000, 10.0), (8000, 10.4), (64000, 10.1)]
    assert judge(levels, tolerance=0.02).status == "oscillating"


def test_둘이면_상대_변화만_본다() -> None:
    verdict = judge([(1000, 100.0), (8000, 100.5)], tolerance=0.01)
    assert verdict.status == "converged"
    assert verdict.order is None
    assert verdict.change == pytest.approx(0.5 / 100.5)


def test_하나면_판정하지_않는다() -> None:
    assert judge([(1000, 1.0)], tolerance=0.01).status == "insufficient"


def test_대표_크기는_절점_수의_세제곱근에_반비례한다() -> None:
    assert size_of(8000) / size_of(1000) == pytest.approx(0.5)


def test_변화가_이미_문턱보다_작으면_차수가_들쭉날쭉해도_수렴이다() -> None:
    """**실측**(CalculiX · 측면가진 1차 굽힘) — 2.8 · 2.0 · 1.4 mm 에서 1259.0 · 1258.0 ·
    1256.6 Hz. 정련할 때 변화가 0.07% → 0.11% 로 오히려 커져 차수로는 「발산」 이지만, 그
    크기는 1% 문턱의 10분의 1 이다 — 공학적으로 수렴한 값이다."""
    levels = [(29890, 1258.961), (69908, 1258.044), (197419, 1256.632)]
    verdict = judge(levels, tolerance=0.01)
    assert verdict.status == "converged"
    assert verdict.order is None, "점근 구간이 아니라 차수는 재지 않는다"


def test_진짜_메시의_성긴_세_수준은_차수와_외삽값을_낸다() -> None:
    """같은 실측의 4 · 2.8 · 2.0 mm — 관측 차수 2.9, 외삽값 1257.3 Hz, GCI 0.07%."""
    levels = [(11505, 1261.432), (29890, 1258.961), (69908, 1258.044)]
    verdict = judge(levels, tolerance=0.01)
    assert verdict.status == "converged"
    assert verdict.order == pytest.approx(2.88, abs=0.05)
    assert verdict.extrapolated == pytest.approx(1257.32, abs=0.05)
    assert verdict.gci == pytest.approx(0.00072, rel=0.05)
