"""② 비선형 정적 받기(CompCore 해석-확장-설계 8장) — **재료 모델 · 하중 단계 · 하중 이력**을
솔버 없이 본다.

솔버로 끝까지 푸는 시험은 `tests/opensolver/test_nonlinear_static.py` · `tests/ansys/
test_nonlinear_static_ansys.py` 다. 여기서 못 박는 것:

- 소성 칸을 받은 그대로 읽고(응력은 `stress_unit` 으로), 틀린 표 · 모르는 모델은 **막는다**.
- 하중 단계 · 시간별 배율 · 적용 단계 · 볼트 단계를 CompCore 가 저장할 때와 같은 규칙으로 읽고,
  틀리면 까닭과 함께 막는다.
- 두 솔버가 쓰는 **총 시각 배율표**(`history`)가 CompCore 와 정한 뜻 그대로다.
- CalculiX 덱이 `*PLASTIC`(응력이 먼저) · `*AMPLITUDE, TIME=TOTAL TIME` · 단계마다 거두고 다시
  걸기 · 볼트 잠금을 쓴다.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core import cases, history, materials, units
from app.core import conditions as condition_model

DOE = Path(__file__).resolve().parents[1] / "fixtures" / "doe"


def _point(folder: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (DOE / folder / "points" / "p0001.json").read_text(encoding="utf-8")
    )
    return loaded


def _view(folder: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if payload is not None else _point(folder)
    found, broken = cases.chains(payload)
    assert not broken
    [chain] = found
    return cases.view(payload, chain)


def _materials(payload: dict[str, Any]) -> list[materials.Material]:
    return materials.read(payload, units.declared_in(payload))


# --- 재료 모델 -----------------------------------------------------------------


def test_이선형은_항복과_접선_계수를_받고_소성_기울기를_셈한다() -> None:
    [one] = _materials(_point("조건_봉_항복_이선형"))
    assert one.model == materials.BILINEAR
    assert one.plastic is not None
    assert one.plastic.yield_stress_pa == pytest.approx(250e6)
    assert one.plastic.tangent_modulus_pa == pytest.approx(2000e6)
    # H = E·Et/(E - Et) = 205000 · 2000 / 203000 — CompCore README 의 2019.704 MPa.
    assert one.plastic.hardening_pa(one.youngs_modulus_pa) / 1e6 == pytest.approx(2019.704)
    first, last = one.plastic.rows(one.youngs_modulus_pa)
    assert first[0] == 0.0 and first[1] == pytest.approx(250e6)
    assert last[0] == materials.BILINEAR_REACH


def test_다선형은_표를_받은_그대로_읽는다() -> None:
    [one] = _materials(_point("조건_봉_항복_다선형"))
    assert one.model == materials.MULTILINEAR
    assert one.plastic is not None
    assert [row[0] for row in one.plastic.table] == [0.0, 0.05]
    assert [row[1] for row in one.plastic.table] == pytest.approx([250e6, 350.985e6])


def test_선형_탄성에는_소성이_없다() -> None:
    [one] = _materials(_point("조건_외팔보_두케이스"))
    assert one.plastic is None and one.model == materials.LINEAR_ELASTIC


def _with_plastic(**changes: Any) -> dict[str, Any]:
    payload = copy.deepcopy(_point("조건_봉_항복_다선형"))
    payload["conditions"]["materials"][0].update(changes)
    return payload


@pytest.mark.parametrize(
    ("changes", "words"),
    [
        ({"model": "kinematic_hardening"}, "모르는 재료 모델"),
        ({"plastic": {"table": [[0.0, 250.0]], "stress_unit": "MPa"}}, "2 ~ 5000"),
        (
            {"plastic": {"table": [[0.001, 250.0], [0.05, 300.0]], "stress_unit": "MPa"}},
            "첫 행은 소성 변형률 0",
        ),
        (
            {"plastic": {"table": [[0.0, 250.0], [0.0, 300.0]], "stress_unit": "MPa"}},
            "행마다 늘어야",
        ),
        (
            {"plastic": {"table": [[0.0, 250.0], [0.05, 200.0]], "stress_unit": "MPa"}},
            "줄지 않아야",
        ),
        ({"plastic": {"table": [[0.0, 250.0], [0.05, 300.0]]}}, "응력 단위"),
        (
            {
                "model": "bilinear_isotropic",
                "plastic": {
                    "yield_stress": 250,
                    "tangent_modulus": 205000,
                    "stress_unit": "MPa",
                },
            },
            "탄성계수",
        ),
    ],
)
def test_틀린_소성_칸은_막는다(changes: dict[str, Any], words: str) -> None:
    with pytest.raises(materials.MaterialProblem, match=words):
        _materials(_with_plastic(**changes))


def test_소성_응력은_단위_이름으로_읽는다() -> None:
    payload = _with_plastic(
        plastic={"table": [[0.0, 2.5e8], [0.05, 3.5e8]], "stress_unit": "Pa"}
    )
    [one] = _materials(payload)
    assert one.plastic is not None
    assert one.plastic.table[0][1] == pytest.approx(250e6)


def test_모드_해석에서는_소성을_뗀다() -> None:
    found = _materials(_point("조건_봉_항복_이선형"))
    assert materials.plastic(found)
    assert not materials.plastic(materials.elastic_only(found))


# --- 하중 단계 · 하중 이력 ------------------------------------------------------


def test_하중_단계와_시간별_배율을_읽는다() -> None:
    given = condition_model.read(_view("조건_봉_당겼다풀기"), recipe="static")
    assert not given.refused
    steps = given.analysis.load_steps
    assert [(one.name, one.end_time) for one in steps] == [("당기기", 1.0), ("풀기", 2.0)]
    assert (steps[0].initial, steps[0].minimum, steps[0].maximum) == (20, 10, 200)
    [pull] = given.loads
    assert pull.time_table == ((0.0, 0.0), (1.0, 1.0), (2.0, 0.0))


def test_적용_단계와_볼트_단계를_읽는다() -> None:
    given = condition_model.read(_view("조건_볼트예압_단계둘"), recipe="static")
    assert not given.refused
    by_kind = {one.kind: one for one in given.loads}
    assert by_kind["bolt_pretension"].bolt_steps == ("load", "lock")
    assert by_kind["force"].active_steps == (2,)


def _static_view(folder: str, **load: Any) -> dict[str, Any]:
    payload = copy.deepcopy(_point(folder))
    row = payload["conditions"]["cases"][0]["loads"][0]
    row.pop("time_table", None)
    row.pop("active_steps", None)
    row.update(load)
    return _view(folder, payload)


@pytest.mark.parametrize(
    ("load", "words"),
    [
        ({"time_table": [[0, 0], [1, 1]]}, "끝 시각(2)"),
        ({"time_table": [[0, 0], [1, 1], [1, 0], [2, 0]]}, "줄마다 늘어야"),
        ({"time_table": [[0, 0], [2, 1]], "active_steps": [1]}, "함께 쓰지 않습니다"),
        ({"active_steps": [3]}, "1 ~ 2"),
        ({"active_steps": [2, 1]}, "늘어나는 차례"),
        ({"bolt_steps": ["load", "lock"]}, "볼트 예압에만"),
    ],
)
def test_틀린_하중_이력은_막는다(load: dict[str, Any], words: str) -> None:
    given = condition_model.read(_static_view("조건_봉_당겼다풀기", **load), recipe="static")
    assert any(words in one.why for one in given.refused), given.refused


def test_중력에는_적용_단계를_쓰지_않는다() -> None:
    payload = copy.deepcopy(_point("조건_볼트예압_단계둘"))
    payload["conditions"]["cases"][0]["loads"].append(
        {
            "name": "중력",
            "type": "standard_earth_gravity",
            "on": "",
            "cs": "global",
            "direction": [0, 0, -1],
            "active_steps": [2],
        }
    )
    given = condition_model.read(_view("조건_볼트예압_단계둘", payload), recipe="static")
    assert any("중력 · 볼트" in one.why for one in given.refused)


def test_볼트_단계는_조인_뒤_잠근다() -> None:
    payload = copy.deepcopy(_point("조건_볼트예압_단계둘"))
    bolt = next(
        one
        for one in payload["conditions"]["cases"][0]["loads"]
        if one["type"] == "bolt_pretension"
    )
    bolt["bolt_steps"] = ["lock", "load"]
    given = condition_model.read(_view("조건_볼트예압_단계둘", payload), recipe="static")
    assert any("첫 단계에서 조인" in one.why for one in given.refused)


@pytest.mark.parametrize(
    ("analysis", "words"),
    [
        ({"load_steps": [{"end_time": 1}, {"end_time": 1}]}, "앞 단계보다 커야"),
        (
            {"load_steps": [{"end_time": 1, "substeps": {"initial": 5, "minimum": 10}}]},
            "최소 ≤ 처음 ≤ 최대",
        ),
        ({"load_steps": [{"end_time": 1}], "substeps": 5}, "비웁니다"),
    ],
)
def test_틀린_하중_단계는_막는다(analysis: dict[str, Any], words: str) -> None:
    assert words in condition_model.steps_problem(analysis)


def test_하중_이력_칸은_정적에서만_읽는다() -> None:
    """모달로 돌리면 시간별 배율은 읽지 않는다(그 해석의 칸이 아니다)."""
    given = condition_model.read(_view("조건_봉_당겼다풀기"), recipe="modal")
    assert all(one.time_table is None for one in given.loads)


# --- 총 시각 배율표 --------------------------------------------------------------


def _timeline(*ends: float) -> history.History:
    return history.History(
        tuple(
            condition_model.LoadStep(name=f"{index}", end_time=end)
            for index, end in enumerate(ends, 1)
        )
    )


def _load(**fields: Any) -> condition_model.Load:
    return condition_model.Load(name="힘", kind="force", **fields)


def test_배율이_없는_하중은_첫_단계에서_오르고_유지한다() -> None:
    assert _timeline(1, 2, 3).scale(_load()) == ((0, 0), (1, 1), (2, 1), (3, 1))


def test_적용_단계는_단계_끝마다_켜고_끈다() -> None:
    # v1 볼트 정적과 같은 뜻 — 볼트가 아닌 하중은 둘째 단계에서 오른다.
    assert _timeline(1, 2).scale(_load(active_steps=(2,))) == ((0, 0), (1, 0), (2, 1))
    # 「켜고끄기」 — 첫 단계에만, 둘째 단계 안에서 0 으로 내린다.
    assert _timeline(1, 2).scale(_load(active_steps=(1,))) == ((0, 0), (1, 1), (2, 0))


def test_시간별_배율은_단계_끝에_점을_넣는다() -> None:
    table = ((0.0, 0.0), (2.0, 1.0))
    assert _timeline(1, 2).scale(_load(time_table=table)) == ((0, 0), (1, 0.5), (2, 1))


def test_원심력은_제곱한_배율이다() -> None:
    """「회전봉_시간표」 — ω 배율 [[0, 0], [1, 0.5]] → 끝에서 ω² 배율 0.25(1/4)."""
    line = _timeline(1)
    squared = line.squared(line.scale(_load(time_table=((0.0, 0.0), (1.0, 0.5)))))
    assert history.at(squared, 1.0) == pytest.approx(0.25)
    assert history.at(squared, 0.5) == pytest.approx(0.0625)


def test_증분은_부단계_수로_정한다() -> None:
    step = condition_model.LoadStep(
        name="끌기", end_time=2.0, initial=20, minimum=10, maximum=200
    )
    found = history.increments(step, 1.0, incremental=True)
    assert (found.initial, found.period, found.minimum, found.maximum) == (
        0.05,
        1.0,
        0.005,
        0.1,
    )
    assert found.count == 400
    linear = history.increments(step, 1.0, incremental=False)
    assert (linear.initial, linear.period, linear.minimum) == (1.0, 1.0, None)


def test_하중_이력이_없으면_지금의_길이다() -> None:
    given = condition_model.read(_view("조건_외팔보_두케이스"), recipe="static")
    assert history.of(given) is None


# --- CalculiX 덱 -----------------------------------------------------------------


def test_ccx_소성_줄은_응력이_먼저다() -> None:
    from app.core.calculix.deck import _material_lines

    [one] = _materials(_point("조건_봉_표끝넘어"))
    lines = _material_lines("M1", one)
    at = lines.index("*PLASTIC")
    assert lines[at + 1 : at + 3] == ["250, 0", "270.197, 0.01"]


# --- 사슬 ------------------------------------------------------------------------


def _modal_after(folder: str) -> dict[str, Any]:
    """그 픽스처의 정적 케이스 뒤에 모달 케이스를 잇는다."""
    payload = copy.deepcopy(_point(folder))
    static = payload["conditions"]["cases"][0]
    payload["conditions"]["cases"].append(
        {
            "name": "모달",
            "depends_on": static["name"],
            "target": {"solver": ""},
            "analysis": {"type": "modal", "modes": 6},
            "constraints": copy.deepcopy(static["constraints"]),
            "loads": [],
            "initial": [],
        }
    )
    return payload


def _chain(payload: dict[str, Any]) -> cases.Chain:
    found, broken = cases.chains(payload)
    assert not broken
    return found[-1]


def test_소성_정적_뒤의_모달은_막는다() -> None:
    payload = _modal_after("조건_봉_항복_이선형")
    for one in payload["conditions"]["cases"]:
        one["analysis"].pop("load_steps", None)
    assert cases.PLASTIC_EIGEN in cases.problem(_chain(payload), payload)
    # 재료가 탄성이면 지금처럼 받는다.
    payload["conditions"]["materials"][0].pop("model")
    payload["conditions"]["materials"][0].pop("plastic")
    assert cases.problem(_chain(payload), payload) == ""


def test_앞_케이스가_있는_사슬의_하중_이력은_막는다() -> None:
    payload = _modal_after("조건_외팔보_켜고끄기")
    assert cases.HISTORY_IN_CHAIN in cases.problem(_chain(payload))


def test_케이스_하나의_하중_이력은_받는다() -> None:
    for folder in ("조건_봉_당겼다풀기", "조건_볼트예압_단계둘", "조건_회전봉_시간표"):
        payload = _point(folder)
        assert cases.problem(_chain(payload), payload) == "", folder


# --- MatNexus 카드에서 온 소성 표 ------------------------------------------------


def _carded(card_modulus: float | None) -> dict[str, Any]:
    """카드에서 온 다선형 표(CompCore 2c36f2d 의 꼴) — 숫자는 지어낸 것이다."""
    card: dict[str, Any] = {
        "id": "card-1",
        "code": "C-000099",
        "label": "인장 MD",
        "test_type": "tensile",
        "orientation": "MD",
        "status": "published",
        "fetched_at": "2026-11-28T00:00:00Z",
    }
    if card_modulus is not None:
        card["youngs_modulus"] = card_modulus
    return _with_plastic(
        plastic={
            "table": [[0.0, 250.77], [0.05, 340.0]],
            "source": "matnexus",
            "card": card,
            "stress_unit": "MPa",
        }
    )


def test_카드의_E_가_물성_E_와_크게_다르면_경고하고_물성_E_로_푼다() -> None:
    found = _materials(_carded(3629.0))
    [one] = found
    assert one.youngs_modulus_pa == pytest.approx(205e9), "풀이는 물성 E"
    assert one.plastic is not None and one.plastic.source == "matnexus"
    assert (
        one.plastic.card is not None
        and one.plastic.card.youngs_modulus_pa == pytest.approx(3629e6)
    )
    warning = materials.card_warning(found)
    assert warning is not None
    assert "C-000099" in warning and "3,629 MPa" in warning and "205,000 MPa" in warning
    assert "98 %" in warning and "물성 E 로 풉니다" in warning
    line = materials.card_line(found)
    assert line is not None and "MD" in line and "published" in line


def test_카드의_E_가_가까우면_경고하지_않는다() -> None:
    assert materials.card_warning(_materials(_carded(210000.0))) is None
    assert materials.card_warning(_materials(_carded(None))) is None


def test_손으로_적은_표에는_카드가_없다() -> None:
    found = _materials(_point("조건_봉_표끝넘어"))
    assert found[0].plastic is not None and found[0].plastic.card is None
    assert materials.card_line(found) is None and materials.card_warning(found) is None


# --- 무중단 갱신 중의 옛 워커 ----------------------------------------------------


def test_소성_하중_이력_작업은_needs_를_저장해_옛_워커가_거절한다() -> None:
    """v0.37.0 워커는 재료 모델 · 하중 단계 칸을 말없이 버리고 탄성으로 풀어 정상 결과처럼
    끝낸다 — 스펙의 `needs` 가 그 워커의 `extra="forbid"` 에 걸려 크게 실패하게 한다."""
    from app.core.spec import StaticSpec, parse_spec
    from app.modules.simulations import services

    spec = parse_spec({"recipe": "static"})
    plastic = services._with_needs(spec, _view("조건_봉_당겼다풀기"))
    assert isinstance(plastic, StaticSpec)
    assert plastic.needs == ["plastic", "load_history"]
    assert services._stored_spec(plastic)["needs"] == ["plastic", "load_history"]
    assert StaticSpec.model_config.get("extra") == "forbid"
    timed = services._with_needs(spec, _view("조건_외팔보_켜고끄기"))
    assert isinstance(timed, StaticSpec) and timed.needs == ["load_history"]
    plain = services._with_needs(spec, _view("조건_외팔보_두케이스", _single_case()))
    assert "needs" not in services._stored_spec(plain)
    # CAD 조건 · 물성을 안 쓰면 그 칸도 안 읽는다.
    own = parse_spec(
        {
            "recipe": "static",
            "conditions_from": "spec",
            "material_from": "spec",
            "material": {
                "name": "강",
                "youngs_modulus_gpa": 205,
                "poisson_ratio": 0.29,
                "density_kg_m3": 7850,
            },
            "constraints": [{"region": "바닥", "kind": "fixed"}],
        }
    )
    assert services._with_needs(own, _view("조건_봉_당겼다풀기")).needs == []  # type: ignore[union-attr]


def _single_case() -> dict[str, Any]:
    """「외팔보_두케이스」 의 첫 케이스 하나만(사슬 없음)."""
    payload = copy.deepcopy(_point("조건_외팔보_두케이스"))
    payload["conditions"]["cases"] = payload["conditions"]["cases"][:1]
    return payload
