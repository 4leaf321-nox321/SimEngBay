"""모드 지문 — **메시가 달라도 같은 자리를 견준다**, 두 솔버가 같은 규칙으로.

CalculiX 워커에는 numpy 가 없어 규칙을 순수 파이썬으로 둔다(`core/modes/signature.py`). Ansys
쪽은 가장 가까운 절점만 numpy 로 찾고 칸 · 순서 · 정규화는 이 함수들을 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.core.modes import signature, track_modes


def test_칸_가운데는_x_y_z_겹_고리_순서다() -> None:
    found = signature.centers([0.0, 0.0, 0.0], [4.0, 8.0, 12.0])
    assert len(found) == signature.GRID**3
    assert found[0] == (0.5, 1.0, 1.5)
    assert found[1] == (0.5, 1.0, 4.5)  # z 가 가장 안쪽 고리
    assert found[-1] == (3.5, 7.0, 10.5)


def test_두께가_0_인_축도_칸을_놓는다() -> None:
    """판을 평면으로 그린 메시 — 그 축의 폭을 1 로 두어 모든 칸이 평면 위 언저리에 놓인다."""
    found = signature.centers([0.0, 0.0, 0.0], [4.0, 4.0, 0.0])
    assert {one[2] for one in found} == {0.125, 0.375, 0.625, 0.875}


def test_칸마다_가장_가까운_점을_고르고_같으면_앞의_것() -> None:
    """**같으면 앞의 것** — numpy 의 argmin 과 같아야 두 솔버가 같은 절점을 고른다."""
    points = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]
    found = signature.anchors(points)
    assert len(found) == signature.GRID**3
    assert found[0] == 0  # (0.125, 0.125, 0.125) 칸 — 겹친 두 점 중 앞의 것
    assert found[-1] == 2  # (0.875, 0.875, 0.875) 칸
    with pytest.raises(ValueError):
        signature.anchors([])


def test_지문은_단위_길이고_네번째_성분부터는_버린다() -> None:
    """모달 변위는 질량 정규화된 상대값이라 크기를 지운다. `.frd` 의 줄은 성분이 넷 이상일 수
    있다(합계 칸) — 앞의 셋만 변위다."""
    made = signature.fingerprint([[3.0, 0.0, 0.0, 99.0], [0.0, 4.0, 0.0]])
    assert made == [0.6, 0.0, 0.0, 0.0, 0.8, 0.0]
    assert signature.fingerprint([[0.0, 0.0, 0.0]]) == [0.0, 0.0, 0.0]


def _plate(length: float, width: float, thick: float, step: float) -> list[tuple[float, ...]]:
    """판의 절점 — 두께 · 촘촘함을 바꾸면 절점의 수와 자리가 전부 달라진다."""
    found: list[tuple[float, ...]] = []
    count = (int(length / step) + 1, int(width / step) + 1)
    for ix in range(count[0]):
        for iy in range(count[1]):
            for z in (0.0, thick / 2, thick):
                found.append((ix * step, iy * step - width / 2, z))
    return found


def _bend_up(point: tuple[float, ...]) -> list[float]:
    """위아래 굽힘 — 끝으로 갈수록 z 로 크게."""
    return [0.0, 0.0, (point[0] / 100) ** 2]


def _bend_side(point: tuple[float, ...]) -> list[float]:
    """옆 굽힘 — 끝으로 갈수록 y 로 크게."""
    return [0.0, (point[0] / 100) ** 2, 0.0]


def _sign(
    points: list[tuple[float, ...]], shape: Callable[[tuple[float, ...]], list[float]]
) -> list[float]:
    spots = signature.anchors(points)
    return signature.fingerprint(shape(points[index]) for index in spots)


def test_메시가_달라도_순서가_뒤바뀐_모드를_형상으로_잇는다() -> None:
    """**이 지문이 있는 이유.** 외팔보 판을 두껍게 하면 위아래 굽힘이 옆 굽힘을 앞지른다(실측
    2026-10-24, 두께 2 → 4 mm: 1031 Hz 위아래 · 1587 Hz 옆 → 1588 Hz 옆 · 2048 Hz 위아래).
    두 설계점은 두께도 절점 수도 다르지만, 정규화 격자에서는 같은 자리를 본다."""
    thin = _plate(100, 20, 2, 2.0)
    thick = _plate(100, 20, 4, 2.5)
    assert len(thin) != len(thick)

    reference = [_sign(thin, _bend_up), _sign(thin, _bend_side)]
    swapped = [_sign(thick, _bend_side), _sign(thick, _bend_up)]

    links = track_modes(reference, swapped)
    assert [one.number for one in links] == [2, 1]
    assert all(one.confidence > 0.99 for one in links)
