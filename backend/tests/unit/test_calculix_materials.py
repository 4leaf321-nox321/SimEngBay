"""CalculiX 경로의 물성 — **솔리드마다 물성이 꼭 하나 붙는다.**

덱(`calculix/deck.py`)은 물성의 `bodies` 에 이름이 있는 솔리드에만 `*SOLID SECTION` 을 쓴다.
그래서 여기서 빠뜨리면 오류가 아니라 **물성 없는 요소**가 덱에 남는다. 「전체」 물성이 그렇게
빠졌었다(2026-10-04) — `bodies` 가 비어 있어서 아무 솔리드에도 안 붙었다.

규칙은 Ansys 경로(`mechanical/build.py` 의 `_apply_material`)와 같다. 메시는 지어낸다 —
짝짓기는 부피 · 무게중심만 본다(gmsh 없이 돈다).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core import units
from app.core.bodies import BodyRecord
from app.core.calculix.build import _materials
from app.core.spec import parse_spec
from app.core.stages import StageFailure

TWO_BODIES = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "doe"
    / "조건_두바디_두재료"
    / "points"
    / "p0001.json"
)
SPEC = parse_spec({"recipe": "modal", "solver": "calculix"})


def _payload() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(TWO_BODIES.read_text(encoding="utf-8"))
    return loaded


def _mesh() -> SimpleNamespace:
    """받침판(솔리드 1) · 블록(솔리드 2) — 점 파일의 부피 · 무게중심 그대로."""
    return SimpleNamespace(
        solids={1: [], 2: []},
        bodies=[
            BodyRecord(index=1, volume=30000.0, centroid=(0.0, 0.0, 2.5)),
            BodyRecord(index=2, volume=32000.0, centroid=(0.0, 0.0, 15.0)),
        ],
    )


def test_파트마다_다른_물성을_짝지은_솔리드에_붙인다() -> None:
    body_of, made, source = _materials(SPEC, _payload(), units.MM_N_TONNE, _mesh())
    assert source == "cad"
    assert body_of == {"받침판": 1, "블록": 2}
    assert [(one.name, one.bodies) for one in made] == [
        ("SECC-EXAD87-DP_선언물성_0.8", ("받침판",)),
        ("AL5052H32DEMO_-_-", ("블록",)),
    ]


def test_전체_물성은_솔리드_전부에_붙는다() -> None:
    payload = _payload()
    whole = copy.deepcopy(payload["conditions"]["materials"][0])
    whole["apply_to"] = ["전체"]
    payload["conditions"]["materials"] = [whole]

    body_of, made, source = _materials(SPEC, payload, units.MM_N_TONNE, _mesh())
    assert source == "cad"
    assert len(made) == 1
    # 짝지은 이름을 그대로 쓴다 — 측정점이 그 이름으로 바디를 가른다.
    assert set(made[0].bodies) == set(body_of) == {"받침판", "블록"}


def test_재료가_빠진_파트가_있으면_멈춘다() -> None:
    payload = _payload()
    payload["conditions"]["materials"] = payload["conditions"]["materials"][:1]
    with pytest.raises(StageFailure, match="블록"):
        _materials(SPEC, payload, units.MM_N_TONNE, _mesh())


def test_CAD_도_스펙도_물성이_없으면_멈춘다() -> None:
    payload = _payload()
    payload["conditions"]["materials"] = []
    with pytest.raises(StageFailure, match="물성이 없습니다"):
        _materials(SPEC, payload, units.MM_N_TONNE, _mesh())


def test_스펙_물성은_솔리드_전부에_붙고_이름은_짝지은_것을_쓴다() -> None:
    spec = parse_spec(
        {
            "recipe": "modal",
            "solver": "calculix",
            "material_from": "spec",
            "material": {
                "name": "SS400",
                "youngs_modulus_gpa": 200,
                "poisson_ratio": 0.3,
                "density_kg_m3": 7850,
            },
        }
    )
    body_of, made, source = _materials(spec, _payload(), units.MM_N_TONNE, _mesh())
    assert source == "spec"
    assert [(one.name, set(one.bodies)) for one in made] == [("SS400", {"받침판", "블록"})]
    assert body_of == {"받침판": 1, "블록": 2}
