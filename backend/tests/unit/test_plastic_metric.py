"""소성 변형률을 **견줄 값**으로 — 스터디 비교 · CSV · 다변수 분석 · 메시 수렴이 같은 값을
본다.

v0.38.1 부터 소성 재료로 푼 정적의 `result.json` 에 `max_equivalent_plastic_strain` 이 있었지만
작업 화면에만 보였다. 여기서 못 박는 것:

- `values.read` 가 그 값을 무차원 그대로 꺼내고(항복하지 않은 0 도 0 그대로), 탄성 재료 · 못
  읽은 결과에는 **비워 둔다**(0 으로 지어내지 않는다 — 「0 과 모름」 은 추출이 가른다,
  `tests/unit/test_dpf_plastic.py`).
- 스터디 CSV · 분석 열 · 수렴 지표는 **소성으로 푼 점이 하나라도 있을 때만** 그 열을 낸다 —
  탄성 스터디에 빈 열이 생기지 않는다.
- 수렴 지표는 응력처럼 「특이점일 수 있음」 이다(모서리 · 하중점에 몰린다). 모든 수준이
  0.01 % 아래면(항복 문턱 언저리) 수렴으로 본다 — 0 과 1e-6 의 상대 변화는 무한대다.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core import values
from app.modules.simulations import analysis, services
from app.modules.simulations.schemas import StudyOut, StudyPointOut


def _static(**extra: Any) -> dict[str, Any]:
    return {
        "recipe": "static",
        "units": {"displacement": "mm", "stress": "MPa", "force": "N"},
        "max_displacement": 1.5,
        "max_von_mises": 260.0,
        **extra,
    }


def _point(number: int, thickness: float, **found: Any) -> StudyPointOut:
    return StudyPointOut(
        simulation_id=uuid.uuid4(),
        number=number,
        params={"두께": thickness},
        status="done",
        recipe="static",
        **found,
    )


def _study(points: list[StudyPointOut]) -> StudyOut:
    return StudyOut(study_id="s", name="봉", factors=["두께"], recipe="static", points=points)


#: 두께가 얇을수록 더 항복한다 — 셋째 점은 항복하지 않았다(0). 끝 점은 탄성 재료로 풀었다.
PLASTIC = [
    _point(1, 2, max_von_mises_mpa=262.0, max_equivalent_plastic_strain=0.0148535),
    _point(2, 3, max_von_mises_mpa=251.0, max_equivalent_plastic_strain=0.0021),
    _point(3, 4, max_von_mises_mpa=180.0, max_equivalent_plastic_strain=0.0),
    _point(4, 5, max_von_mises_mpa=150.0),
]
ELASTIC = [
    _point(1, 2, max_von_mises_mpa=120.0),
    _point(2, 3, max_von_mises_mpa=90.0),
]


def test_소성_결과의_값을_무차원_그대로_꺼내고_탄성은_비운다() -> None:
    found = values.read(_static(max_equivalent_plastic_strain=0.0148535))
    assert found.max_equivalent_plastic_strain == 0.0148535
    # 응력 단위(Pa)가 달라도 변형률은 옮기지 않는다.
    si = values.read(
        _static(
            units={"displacement": "m", "stress": "Pa"},
            max_von_mises=2.6e8,
            max_equivalent_plastic_strain=0.0148535,
        )
    )
    assert si.max_equivalent_plastic_strain == 0.0148535
    assert si.max_von_mises_mpa == 260.0
    assert values.read(_static()).max_equivalent_plastic_strain is None
    # 항복하지 않은 0 은 0 그대로 — 빈 값으로 바꾸지 않는다.
    yielded = values.read(_static(max_equivalent_plastic_strain=0.0))
    assert yielded.max_equivalent_plastic_strain == 0
    # 모달 · 조화 · 랜덤은 소성으로 풀지 않는다 — 결과에 칸이 있어도 읽지 않는다.
    modal = values.read({"recipe": "modal", "modes": [], "max_equivalent_plastic_strain": 0.1})
    assert modal.max_equivalent_plastic_strain is None


def test_스터디_CSV_는_소성으로_푼_점이_있을_때만_그_열을_낸다() -> None:
    head, rows = services.study_table(_study(PLASTIC))
    at = head.index("최대 등가 소성 변형률")
    assert head[at - 1] == "최대 상당응력 (MPa)"
    assert [row[at] for row in rows] == ["0.0148535", "0.0021", "0", ""]

    head, _ = services.study_table(_study(ELASTIC))
    assert "최대 등가 소성 변형률" not in head


def test_다변수_분석의_열과_조건으로_소성_변형률을_쓴다() -> None:
    keys = {one.key: one for one in analysis.columns_of(_study(PLASTIC))}
    assert keys["max_peeq"].label == "최대 등가 소성 변형률"
    assert keys["max_peeq"].unit == ""
    assert "max_peeq" not in {one.key for one in analysis.columns_of(_study(ELASTIC))}

    # 「소성 변형률 0.5 % 아래에서 가장 얇은 것」 — 항복하지 않은 점(0)은 조건을 채우고, 탄성
    # 재료로 푼 점(값이 없다)은 못 채운다.
    found = analysis.analyze(
        _study(PLASTIC), objective="factor:두께", goal="min", where=["max_peeq<=0.005"]
    )
    assert found.choice is not None and found.choice.best is not None
    assert (found.choice.feasible, found.choice.best.number) == (2, 2)


def test_메시_수렴은_소성_변형률을_특이점일_수_있는_값으로_본다() -> None:
    levels: list[values.Values | None] = [
        values.read(_static(max_equivalent_plastic_strain=strain))
        for strain in (0.0120, 0.0141, 0.0148)
    ]
    metrics = {one[0]: one for one in services._convergence_metrics("static", levels)}
    _key, label, unit, _tolerance, numbers, singular = metrics["max_peeq"]
    assert (label, unit, singular) == ("최대 등가 소성 변형률", "", True)
    assert numbers == [0.0120, 0.0141, 0.0148]

    assert services._singular_note("max_peeq").startswith("최대 소성 변형률은 ")
    assert services._singular_note("max_mpa").startswith("첨두응력은 ")

    # 항복 문턱 언저리 — 0 과 1e-6 은 상대 변화가 무한대라 「발산」 으로 읽힌다. 0.01 % 아래면
    # 수렴.
    tiny = [(1000, 0.0), (2000, 1e-6), (4000, 3e-6)]
    verdict, note = services._judged("max_peeq", tiny, tolerance=0.02, singular=True)
    assert (verdict.status, note) == ("converged", services.PLASTIC_FLOOR_NOTE)
    # 같은 값이라도 응력이면 그대로 판정한다.
    stress, _note = services._judged("max_mpa", tiny, tolerance=0.02, singular=True)
    assert stress.status != "converged"
    # 수준 하나로는 판정하지 않는다(문턱 아래여도).
    one, _note = services._judged("max_peeq", tiny[:1], tolerance=0.02, singular=True)
    assert one.status == "insufficient"
    # 항복했으면 문턱을 쓰지 않는다 — 촘촘할수록 커지면 특이점 알림.
    grown = [(1000, 0.010), (2000, 0.014), (4000, 0.020)]
    verdict, note = services._judged("max_peeq", grown, tolerance=0.02, singular=True)
    assert verdict.status != "converged" and note.startswith("최대 소성 변형률은 ")

    elastic: list[values.Values | None] = [values.read(_static()) for _ in range(3)]
    keys = {one[0] for one in services._convergence_metrics("static", elastic)}
    assert "max_peeq" not in keys
