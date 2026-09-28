"""바디 짝짓기 — **CAD 의 파트가 해석의 어느 바디인가.**

이름으로는 안 된다: STEP 이 한글 이름을 못 나른다(CompCore 실측 — `부품` 이 `ì¡°ë¦½` 꼴로
망가져 되살릴 수 없었다). 그래서 부피 · 무게중심으로 짝짓고, **못 가리면 짝짓지 않는다** —
물성을 뒤바꿔 붙이면 값이 안 나오는 게 아니라 그럴듯한 값이 나오고 틀린다.

폴더는 CompCore 의 내보내기 코드가 쓴 것이다(`tests/fixtures/doe/README-조건픽스처.md`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.bodies import BodyRecord, match_bodies

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "조건_두바디_두재료"


def _point(number: int) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (FIXTURE / "points" / f"p{number:04d}.json").read_text(encoding="utf-8")
    )
    return loaded


def _records(point: dict[str, Any], *, shuffle: bool = True) -> list[BodyRecord]:
    """해석 쪽이 돌려줄 값 흉내 — **부피는 조금 다르게**(STEP 을 다시 읽으면 그렇다).

    번호는 임포트 순서라 CAD 의 순서와 같을 이유가 없다. 그래서 일부러 뒤집어 넣는다.
    """
    rows = list(point["bodies"])
    if shuffle:
        rows = rows[::-1]
    return [
        BodyRecord(
            index=index,
            volume=float(one["volume"]) * 1.0001,
            centroid=tuple(float(v) for v in one["centroid"]),  # type: ignore[arg-type]
            name=f"Solid{index}",
        )
        for index, one in enumerate(rows)
    ]


def test_부피와_무게중심으로_파트를_찾는다() -> None:
    """**이름이 아니라 지문이다.** 순서가 뒤집혀 있어도 제 짝을 찾아야 한다."""
    point = _point(1)
    found = match_bodies(point, _records(point))

    assert found.ok
    assert set(found.bodies) == {"받침판", "블록"}
    # 뒤집어 넣었으므로 받침판(부피 30,000)은 1번, 블록(32,000)은 0번이다.
    assert found.bodies["받침판"] == 1
    assert found.bodies["블록"] == 0


def test_설계점마다_다시_푼다() -> None:
    """두께가 바뀌면 판의 부피 · 무게중심이 바뀐다(30,000 → 48,000 mm³). **점마다 짝을 다시
    풀어야** 두 번째 점에서 물성이 뒤바뀌지 않는다."""
    second = _point(2)
    plate = next(one for one in second["bodies"] if one["name"] == "받침판")
    assert plate["volume"] == 48000.0  # 두께 8

    found = match_bodies(second, _records(second))
    assert found.ok
    # 이 점의 부피로 짝지었다 — 첫 점의 값(30,000)으로 찾으면 못 찾는다.
    assert found.bodies["받침판"] != found.bodies["블록"]

    crossed = match_bodies(second, _records(_point(1)))
    assert not crossed.ok
    assert "받침판" in crossed.failures[0]


def test_부피가_닮으면_무게중심으로_가른다() -> None:
    """조립에는 같은 크기의 파트가 둘 있을 수 있다(좌우 브래킷). 그때 갈라 주는 것은 위치다."""
    topology = {
        "bodies": [
            {"name": "왼쪽", "volume": 1000.0, "centroid": [-50.0, 0.0, 0.0]},
            {"name": "오른쪽", "volume": 1000.0, "centroid": [50.0, 0.0, 0.0]},
        ]
    }
    records = [
        BodyRecord(index=0, volume=1000.0, centroid=(50.0, 0.0, 0.0)),
        BodyRecord(index=1, volume=1000.0, centroid=(-50.0, 0.0, 0.0)),
    ]
    found = match_bodies(topology, records)
    assert found.ok
    assert found.bodies == {"왼쪽": 1, "오른쪽": 0}


def test_가릴_수_없으면_짝짓지_않는다() -> None:
    """부피도 무게중심도 같은 바디가 둘이면 **어느 쪽인지 알 수 없다.** 그때 한쪽을 골라
    붙이면 물성이 뒤바뀐 채로 해석이 끝까지 돌고, 결과는 그럴듯하다."""
    topology = {"bodies": [{"name": "쌍둥이", "volume": 1000.0, "centroid": [0.0, 0.0, 0.0]}]}
    records = [
        BodyRecord(index=0, volume=1000.0, centroid=(0.0, 0.0, 0.0)),
        BodyRecord(index=1, volume=1000.0, centroid=(0.0, 0.0, 0.0)),
    ]
    found = match_bodies(topology, records)
    assert not found.ok
    assert "가릴 수 없습니다" in found.failures[0]


def test_없는_파트는_이름과_함께_말한다() -> None:
    """바디 하나가 임포트에서 빠지는 일이 있다(얇은 판 · 곡면 실패). **조용히 넘기면** 그
    바디만 기본 물성으로 풀린다."""
    point = _point(1)
    only_block = [one for one in _records(point, shuffle=False) if one.volume > 31000]
    found = match_bodies(point, only_block)
    assert not found.ok
    assert any("받침판" in one and "mm³" in one for one in found.failures)
    # 찾은 것은 그대로 들고 있다 — 부르는 쪽이 「무엇이 됐고 무엇이 안 됐나」 를 말할 수 있게.
    assert "블록" in found.bodies


def test_바디_지문이_없으면_짝지을_것도_없다() -> None:
    """옛 폴더(형상만)에는 `bodies` 가 없다 — 오류가 아니다."""
    found = match_bodies({}, [])
    assert found.ok and found.bodies == {}
