"""조건의 판 — **모르는 판은 조용히 읽지 않고 막는다**(`app/core/contract.py`, 2026-11-25).

v2(케이스 여럿)가 오면 거절하지 않고 구속 0 · 하중 0 · modal 로 읽었다 — 자유-자유 모달이
끝까지 돌고 그럴듯한 결과가 나온다.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core import conditions, contract
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


def test_픽스처의_점_파일은_모두_판_1_이고_막히지_않는다() -> None:
    """CompCore 가 낸 점 파일 전부 — 이 검사가 멀쩡한 폴더를 막으면 안 된다."""
    seen = 0
    for path in sorted(FIXTURES.rglob("points/*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert contract.problem(loaded) is None, path
        block = loaded.get("conditions")
        if isinstance(block, dict):
            assert block["schema_version"] == 1, path
            seen += 1
    assert seen > 50


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
@pytest.mark.parametrize("declared", [2, "2", "1", True, 1.5, [1]])
def test_모르는_판은_막는다(key: str, declared: Any) -> None:
    payload = _payload()
    payload["conditions"][key] = declared
    said = contract.problem(payload)
    assert said is not None and key in said and "읽는 판: 1" in said


@pytest.mark.parametrize("marks", [{"version": 2}, {"schema_version": 2}, {}])
@pytest.mark.parametrize("recipe", ["static", "modal"])
def test_v2_는_빈_조건으로_읽지_않고_거절한다(marks: dict[str, Any], recipe: str) -> None:
    """판을 안 적고 모양만 v2 인 것도 — 맨 위가 비어 「조건 없음」 으로 읽히던 길이다."""
    found = conditions.read(_v2(**marks), recipe=recipe)
    assert [one.what for one in found.refused] == ["조건의 판"]
    assert not found.contacts and not found.mesh_hints, "반만 읽지 않는다"


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
    (target / "points" / BOLT.name).write_text(json.dumps(_v2(version=2)), encoding="utf-8")
    after = read_folder(target)
    assert not after.points[0].usable
    assert "조건의 판(version = 2)" in after.points[0].skip_reason
