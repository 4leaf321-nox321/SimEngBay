"""영역 매칭 — **진짜 형상과 진짜 Mechanical 면 데이터로.**

`tests/fixtures/topology/*.json` 은 CompCore 가 제 코드로 쓴 것이고,
`tests/fixtures/mechanical/*.faces.json` 은 임베디드 Mechanical 이 그 STEP 에서 낸 값이다.
손으로 지어낸 값으로 시험하면 **우리가 상상한 CAD 와 우리가 상상한 Mechanical** 만 맞춰 보게
된다 — 정작 둘이 어긋나는 자리는 그런 값에 없다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.regions import FaceRecord, match_regions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _topology(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (FIXTURES / "topology" / f"{name}.topology.json").read_text(encoding="utf-8")
    )
    return loaded


def _faces(name: str) -> list[FaceRecord]:
    rows = json.loads(
        (FIXTURES / "mechanical" / f"{name}.faces.json").read_text(encoding="utf-8")
    )
    return [
        FaceRecord(
            id=row["id"],
            centroid=tuple(row["centroid"]),
            area=row["area"],
            surface=row.get("surface", ""),
            normal=tuple(row["normal"]) if row.get("normal") else None,
            radius=row.get("radius"),
        )
        for row in rows
    ]


def test_바닥면과_볼트_구멍_넷을_찾는다() -> None:
    found = match_regions(_topology("plate_holes"), _faces("plate_holes"))
    assert found.ok, [f.reason for f in found.failures]
    assert len(found.faces["fixed_base"]) == 1
    assert len(found.faces["bolt_holes"]) == 4
    # 같은 면을 두 영역이 나눠 갖지 않는다.
    assert len(set(found.faces["fixed_base"]) & set(found.faces["bolt_holes"])) == 0


def test_모서리에_걸친_반쪽_구멍도_찾는다() -> None:
    """**이것이 이 모듈의 어려운 부분이다.** 잘린 원통면에서 CAD 는 경계상자 중심을,
    Mechanical 은 넓이 무게중심을 내므로 두 점이 0.8mm 어긋난다(실측) — 평면에 쓰는 좁은
    허용오차로 재면 구멍이 통째로 안 잡힌다."""
    topology = _topology("plate_halfholes")
    found = match_regions(topology, _faces("plate_halfholes"))
    assert found.ok, [f.reason for f in found.failures]
    assert len(found.faces["bolt_holes"]) == 2

    # 반쪽 구멍(r=6)이 가운데 구멍(r=4.25)으로 잘못 붙지 않았는가 — 반지름이 가른다.
    half = next(one for one in topology["regions"]["bolt_holes"] if one["radius"] == 6.0)
    matched = {face.id: face for face in _faces("plate_halfholes")}
    picked = [matched[i] for i in found.faces["bolt_holes"]]
    assert any(abs((one.radius or 0) - half["radius"]) < 0.01 for one in picked)


def test_두께를_훑어도_같은_개수가_풀린다() -> None:
    """**이 모듈이 있는 이유.** DOE 는 치수를 바꿔 형상을 여러 벌 만든다 — 면 번호로 적었으면
    두께 하나 바꾸는 순간 다른 면을 가리켰을 것이다."""
    for thickness in (6, 12, 20):
        name = f"plate_t{thickness}"
        found = match_regions(_topology(name), _faces(name))
        assert found.ok, (name, [f.reason for f in found.failures])
        assert len(found.faces["fixed_base"]) == 1, name
        assert len(found.faces["bolt_holes"]) == 4, name


def test_필요한_영역만_푼다() -> None:
    """스펙이 쓰지도 않는 영역이 안 풀렸다고 해석을 막을 이유는 없다."""
    found = match_regions(
        _topology("plate_holes"), _faces("plate_holes"), wanted_regions=["fixed_base"]
    )
    assert found.ok
    assert set(found.faces) == {"fixed_base"}


def test_못_찾으면_가장_가까웠던_후보를_적는다() -> None:
    """허용오차를 늘릴지 형상을 볼지는 **얼마나 떨어졌나**로 갈린다.

    「못 찾음」 만 적으면 다음 사람이 할 수 있는 일이 없다.
    """
    topology = _topology("plate_holes")
    topology["regions"]["fixed_base"][0]["centroid"] = [0.0, 0.0, -500.0]
    found = match_regions(topology, _faces("plate_holes"))
    assert not found.ok
    failure = found.failures[0]
    assert failure.region == "fixed_base"
    assert failure.nearest is not None
    assert failure.nearest["distance"] > 100
    assert "떨어져" in failure.reason


def test_CAD_가_못_푼_이름은_그대로_실패한다() -> None:
    """**조용히 빼지 않는다.** 구속 없는 해석이 끝까지 돌면 0 Hz 여섯 개를 달고 나오고,
    사람은 그것을 「해석이 됐다」 로 읽는다."""
    topology = _topology("plate_holes")
    topology["unresolved"] = ["fixed_base"]
    found = match_regions(topology, _faces("plate_holes"), wanted_regions=["fixed_base"])
    assert not found.ok
    assert "unresolved" in found.failures[0].reason


def test_없는_영역을_달라고_하면_실패한다() -> None:
    found = match_regions(
        _topology("plate_holes"), _faces("plate_holes"), wanted_regions=["load_face"]
    )
    assert not found.ok
    assert "없는 영역" in found.failures[0].reason
