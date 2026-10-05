"""그림의 파트 나누기 — **이어진 덩어리가 바디이고, 바디 지문으로 이름을 붙인다.**

3D 뷰어가 파트마다 보이고 숨기려면 면마다 파트 번호가 있어야 한다(`surface_parts`). Ansys 는
겉면만 오므로 덩어리로 나누고, CalculiX 는 사면체가 어느 바디인지 안다.
"""

from __future__ import annotations

import pytest

from app.core import surface_parts


def _cube(
    origin: tuple[float, float, float], side: float, start: int
) -> tuple[list[tuple[float, float, float]], list[list[int]]]:
    """정육면체 겉면 — 점 여덟, 사각형 여섯(바깥을 보게)."""
    x, y, z = origin
    points = [
        (x + dx * side, y + dy * side, z + dz * side)
        for dz in (0, 1)
        for dy in (0, 1)
        for dx in (0, 1)
    ]
    faces = [
        [0, 2, 3, 1],
        [4, 5, 7, 6],
        [0, 1, 5, 4],
        [2, 6, 7, 3],
        [0, 4, 6, 2],
        [1, 3, 7, 5],
    ]
    return points, [[start + one for one in face] for face in faces]


def test_이어지지_않은_덩어리마다_번호를_큰_것부터_준다() -> None:
    _, small = _cube((10, 0, 0), 1, 0)
    _, big = _cube((0, 0, 0), 2, 8)
    labels = surface_parts.components(small + big, 16)
    # 면 수가 같으면 먼저 나온 것이 0 — 둘 다 여섯이므로 작은 정육면체가 앞이다.
    assert labels == [0] * 6 + [1] * 6
    # 한 덩어리에 면을 하나 더 붙이면(같은 점을 나눈다) 그쪽이 커져 0 이 된다.
    labels = surface_parts.components(small + big + [[8, 9, 13]], 16)
    assert labels[:6] == [1] * 6 and labels[6:] == [0] * 7


def test_닫힌_겉면의_부피와_무게중심을_mm_로_잰다() -> None:
    points, faces = _cube((1, 2, 3), 2, 0)
    labels = [0] * len(faces)
    [record] = surface_parts.body_records(points, faces, labels, to_mm=10.0)
    assert record.index == 0
    # 한 변 2 를 mm 로 20 — 부피 8000 mm³, 무게중심 (20, 30, 40) mm.
    assert record.volume == pytest.approx(8000.0)
    assert record.centroid == pytest.approx((20.0, 30.0, 40.0))


def test_CAD_바디_지문과_짝지어_이름을_붙이고_못_짝지으면_번호로_부른다() -> None:
    small_points, small = _cube((10, 0, 0), 1, 0)
    big_points, big = _cube((0, 0, 0), 2, 8)
    cells = small + big
    labels = surface_parts.components(cells, 16)
    # 결과 파일은 m 로 왔다고 치고(1 → 1000 mm), CAD 지문은 mm 다.
    records = surface_parts.body_records(
        small_points + big_points, cells, labels, to_mm=1000.0
    )
    topology = {
        "bodies": [
            {"name": "받침판", "volume": 8e9, "centroid": [1000.0, 1000.0, 1000.0]},
        ]
    }
    assert surface_parts.names_for(2, records, topology) == ["파트 1", "받침판"]
    assert surface_parts.names_for(2, records, None) == ["파트 1", "파트 2"]


def test_두_바디가_맞닿은_면은_둘_다의_것이다() -> None:
    """한쪽을 숨기면 다른 쪽의 겉면으로 보여야 한다 — 하나에만 주면 숨긴 자리에 구멍이 난다."""
    solids = {
        1: [(1, [1, 2, 3, 4])],
        2: [(2, [1, 2, 3, 5])],
    }
    triangles = [(3, 2, 1), (1, 2, 4), (1, 3, 5), (9, 9, 9)]
    owners = surface_parts.owners_by_solid(solids, triangles)
    assert owners == [[1, 2], [1], [2], []]
