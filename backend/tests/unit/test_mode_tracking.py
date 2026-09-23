"""모드 잇기 — **순번이 아니라 형상으로.**

치수가 바뀌면 모드 순서가 뒤바뀐다(mode crossing). 순번으로 이으면 「2차 대 두께」 그래프가
서로 다른 모드를 이은 선이 되고, 그것은 **없는 그림보다 나쁘다** — 사람이 그것을 믿고 두께를
정한다.
"""

from __future__ import annotations

from app.core.modes import mac, track_modes


def test_같은_모양이면_1_다른_모양이면_0() -> None:
    shape = [1.0, 0.0, 0.0, 0.5, 0.0, 0.0]
    other = [0.0, 1.0, 0.0, 0.0, 0.5, 0.0]
    assert mac(shape, shape) == 1.0
    assert mac(shape, other) == 0.0


def test_부호가_뒤집혀도_같은_모드다() -> None:
    """모드 형상의 부호에는 뜻이 없다 — 위로 휘든 아래로 휘든 같은 모드다."""
    shape = [1.0, 0.0, 0.5, 0.0]
    assert mac(shape, [-one for one in shape]) == 1.0


def test_크기가_달라도_같은_모드다() -> None:
    """모달 변위는 질량 정규화된 상대값이라 크기 자체에는 뜻이 없다."""
    shape = [1.0, 0.0, 0.5, 0.0]
    assert mac(shape, [one * 37 for one in shape]) == 1.0


def test_모르는_것은_0_이다() -> None:
    assert mac([], [1.0]) == 0.0
    assert mac([1.0, 0.0], [1.0]) == 0.0  # 길이가 다르면 짐작하지 않는다
    assert mac([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_순서가_뒤바뀌어도_형상으로_잇는다() -> None:
    """**이 모듈이 있는 이유.** 두께가 커지면 굽힘은 크게 오르고 비틀림은 덜 올라, 2차와
    3차가 자리를 바꾼다. 주파수 순서로 이으면 그 순간 다른 모드를 잇는다."""
    bending = [1.0, 0.0, 0.0, 0.0]
    torsion = [0.0, 1.0, 0.0, 0.0]
    local = [0.0, 0.0, 1.0, 0.0]

    reference = [bending, torsion, local]
    # 두꺼워진 설계점 — 굽힘이 비틀림을 앞질러 순서가 바뀌었다.
    thicker = [torsion, bending, local]

    links = track_modes(reference, thicker)
    assert [one.number for one in links] == [2, 1, 3]
    assert all(one.confidence > 0.9 for one in links)


def test_닮은_것이_없으면_잇지_않는다() -> None:
    """**억지로 이으면 없는 그림보다 나쁘다.** 대신 가장 높았던 값을 적어 둔다 — 0.55 와
    0.05 는 다음에 할 일이 다르다."""
    reference = [[1.0, 0.0, 0.0]]
    candidate = [[0.0, 1.0, 0.0]]
    links = track_modes(reference, candidate)
    assert links[0].number is None
    assert links[0].confidence == 0.0


def test_한_모드는_한_번만_쓰인다() -> None:
    """두 기준 모드가 같은 후보를 가리키면 MAC 이 높은 쪽이 가져간다 — 안 그러면 한 모드가
    둘로 갈라져 그래프에 두 번 선다."""
    reference = [[1.0, 0.0], [0.99, 0.141]]  # 거의 같은 두 모드
    candidate = [[1.0, 0.0]]
    links = track_modes(reference, candidate)
    assert [one.number for one in links] == [1, None]
