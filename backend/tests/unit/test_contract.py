"""조건의 판 — **모르는 판은 조용히 읽지 않고 막는다**(`app/core/contract.py`, 2026-11-25).

v2(케이스 여럿)가 오면 거절하지 않고 구속 0 · 하중 0 · modal 로 읽었다 — 자유-자유 모달이
끝까지 돌고 그럴듯한 결과가 나온다. v2 를 받게 된 뒤로는(`app/core/cases.py`) **날 v2 를 그대로
읽지 않는다** — 작업마다 사슬 하나의 v1 보기로 펴서 읽는다. 읽는 판은 1 · 2 다.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core import cases, conditions, contract
from app.core.calculix import build as calculix_build
from app.core.doe import read_folder
from app.core.spec import parse_spec
from app.core.stages import StageFailure

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
BOLT = FIXTURES / "doe" / "조건_볼트예압_정적" / "points" / "p0001.json"


def _payload() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(BOLT.read_text(encoding="utf-8"))
    return loaded


def _v2(**marks: Any) -> dict[str, Any]:
    """CompCore 설계 2장의 모양 — 공유는 위, 해석 · 하중 · 구속 · 초기조건은 `cases[]`."""
    payload = _payload()
    block = payload["conditions"]
    block.pop("schema_version", None)
    case = {key: block.pop(key) for key in ("analysis", "loads", "constraints", "initial")}
    block["cases"] = [
        {"name": "예압", **case},
        {"name": "외력", "depends_on": "예압", **copy.deepcopy(case)},
    ]
    block.update(marks)
    return payload


def test_픽스처의_점_파일은_모두_판_1_이나_2_이고_막히지_않는다() -> None:
    """CompCore 가 낸 점 파일 전부 — 이 검사가 멀쩡한 폴더를 막으면 안 된다. 판 2 는 케이스가
    사슬로 갈린다."""
    seen = {1: 0, 2: 0}
    for path in sorted(FIXTURES.rglob("points/*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert contract.problem(loaded) is None, path
        block = loaded.get("conditions")
        if isinstance(block, dict):
            assert block["schema_version"] in (1, 2), path
            seen[block["schema_version"]] += 1
            if block["schema_version"] == 2:
                found, broken = cases.chains(loaded)
                assert found and not broken, path
    assert seen[1] > 50 and seen[2] >= 6


@pytest.mark.parametrize(
    "declared", [None, 1, 1.0], ids=["비어 있음", "정수", "실수로 적은 1"]
)
def test_판_1_과_안_적은_것은_그대로_읽는다(declared: Any) -> None:
    payload = _payload()
    payload["conditions"]["schema_version"] = declared
    assert contract.problem(payload) is None
    assert len(conditions.read(payload, recipe="static").constraints) == 1
    assert contract.problem({"regions": {}}) is None, "조건이 없는 폴더"
    assert contract.problem(None) is None


@pytest.mark.parametrize("key", ["schema_version", "version"])
@pytest.mark.parametrize("declared", [3, "2", "1", True, 1.5, [1]])
def test_모르는_판은_막는다(key: str, declared: Any) -> None:
    payload = _payload()
    payload["conditions"][key] = declared
    said = contract.problem(payload)
    assert said is not None and key in said and "읽는 판: 1 · 2" in said


@pytest.mark.parametrize("marks", [{"version": 2}, {"schema_version": 2}])
@pytest.mark.parametrize("recipe", ["static", "modal"])
def test_날_v2_는_빈_조건으로_읽지_않고_케이스를_고르라고_막는다(
    marks: dict[str, Any], recipe: str
) -> None:
    """맨 위가 비어 「조건 없음」 으로 읽히던 길이다 — 케이스 보기(`cases.view`)로 읽는다."""
    found = conditions.read(_v2(**marks), recipe=recipe)
    assert [(one.what, one.why) for one in found.refused] == [
        ("해석 케이스", conditions.CASES_UNPICKED)
    ]
    assert not found.contacts and not found.mesh_hints, "반만 읽지 않는다"


@pytest.mark.parametrize("recipe", ["static", "modal"])
def test_판_1_인데_케이스가_있으면_판으로_막는다(recipe: str) -> None:
    """판을 안 적고 모양만 v2 인 것 — 판 1 로 읽는다(안 적은 것은 1)."""
    found = conditions.read(_v2(), recipe=recipe)
    assert [one.what for one in found.refused] == ["조건의 판"]
    assert "판 1 인데 해석 케이스 2개" in found.refused[0].why


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda rows: rows.append(dict(rows[0])), "두 번 있습니다"),
        (lambda rows: rows[1].update(depends_on="없는 것"), "그보다 앞에 없습니다"),
        (lambda rows: rows.append({**rows[1], "name": "외력 둘"}), "둘 이상"),
    ],
    ids=["이름 겹침", "앞 케이스 없음", "갈래"],
)
def test_케이스의_꼴이_틀리면_점을_막는다(change: Any, said: str) -> None:
    payload = _v2(schema_version=2)
    change(payload["conditions"]["cases"])
    found = contract.problem(payload)
    assert found is not None and said in found


def test_빈_cases_는_v1_이다() -> None:
    payload = _payload()
    payload["conditions"]["cases"] = []
    assert contract.problem(payload) is None


@pytest.mark.parametrize("conditions_from", ["cad", "spec"])
def test_모델링은_CAD_조건을_꺼도_멈춘다(tmp_path: Path, conditions_from: str) -> None:
    """검사가 없던 때 걸린 작업 — 조건을 꺼도 같은 블록의 물성 · 단위 · 기준 온도를 읽는다."""
    (tmp_path / "input.step").write_text("ISO-10303-21;", encoding="utf-8")
    (tmp_path / "topology.json").write_text(json.dumps(_v2()), encoding="utf-8")
    spec = parse_spec(
        {
            "recipe": "modal",
            "conditions_from": conditions_from,
            "mesh": {"element_size_mm": 5},
        }
    )
    with pytest.raises(StageFailure) as caught:
        calculix_build(spec, tmp_path)
    assert "해석 케이스 2개로 나눈 조건" in caught.value.message


def test_Ansys_모델링도_Mechanical_을_띄우기_전에_멈춘다(tmp_path: Path) -> None:
    from app.core.mechanical import build as mechanical_build

    (tmp_path / "input.step").write_text("ISO-10303-21;", encoding="utf-8")
    (tmp_path / "topology.json").write_text(json.dumps(_v2()), encoding="utf-8")
    spec = parse_spec({"recipe": "modal", "solver": "ansys", "conditions_from": "spec"})
    with pytest.raises(StageFailure) as caught:
        mechanical_build(spec, tmp_path, input_name="input.step", version=252)
    assert "해석 케이스 2개로 나눈 조건" in caught.value.message


def test_폴더의_설계점은_걸_수_없는_점으로_까닭을_보인다(tmp_path: Path) -> None:
    source = BOLT.parents[1]
    target = tmp_path / "doe"
    for path in source.rglob("*"):
        if path.is_file():
            copied = target / path.relative_to(source)
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes(path.read_bytes())
    before = read_folder(target)
    assert before.points[0].usable, before.points[0].skip_reason
    (target / "points" / BOLT.name).write_text(json.dumps(_v2(version=3)), encoding="utf-8")
    after = read_folder(target)
    assert not after.points[0].usable
    assert "조건의 판(version = 3)" in after.points[0].skip_reason
    # 판 2 는 폴더에서는 걸 수 있는 점이다 — 사슬마다의 규칙은 가져올 때 본다.
    (target / "points" / BOLT.name).write_text(json.dumps(_v2(version=2)), encoding="utf-8")
    assert read_folder(target).points[0].usable


@pytest.mark.parametrize("conditions_from", ["cad", "spec"])
def test_날_v2_점_파일은_모델링에서도_멈춘다(tmp_path: Path, conditions_from: str) -> None:
    """작업에는 늘 케이스 보기를 담는다(`services.case_view`) — 날것이 모델링까지 오면
    멈춘다."""
    (tmp_path / "input.step").write_text("ISO-10303-21;", encoding="utf-8")
    (tmp_path / "topology.json").write_text(
        json.dumps(_v2(schema_version=2)), encoding="utf-8"
    )
    spec = parse_spec(
        {"recipe": "modal", "conditions_from": conditions_from, "mesh": {"element_size_mm": 5}}
    )
    with pytest.raises(StageFailure) as caught:
        calculix_build(spec, tmp_path)
    assert "케이스" in caught.value.message
