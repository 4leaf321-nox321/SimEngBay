"""비례 정련 — **두 솔버가 같은 배율로** CAD 의 파트 · 면 요소 크기를 줄이는가.

메시 수렴 점검은 수준마다 스펙에 「새 크기 / 원래 크기」 를 적는다(`mesh.local_scale`). 그
배율은 모델링이 조건을 읽는 한 자리(`_declared_conditions`)에서 곱한다 — 크기를 쓰는 자리가
여럿이라 거기서마다 곱하면 한 곳은 빠진다.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.spec import parse_spec

# 패키지가 같은 이름의 함수 `build` 를 내보낸다 — 모듈은 이름으로 집는다.
mechanical_build = importlib.import_module("app.core.mechanical.build")
calculix_build = importlib.import_module("app.core.calculix.build")

POINT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "doe"
    / "조건_측면가진"
    / "points"
    / "p0001.json"
)
BOTH = pytest.mark.parametrize(
    "module", [mechanical_build, calculix_build], ids=["ansys", "calculix"]
)


def _topology() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(POINT.read_text(encoding="utf-8"))
    payload["conditions"]["body_settings"] = [{"name": "기둥", "mesh": {"element_size": 1.5}}]
    payload["conditions"]["mesh_hints"].append({"on": "기둥 끝", "element_size": 0.8})
    return payload


@BOTH
def test_두_솔버가_같은_배율을_곱한다(module: Any) -> None:
    spec = parse_spec({"recipe": "modal", "mesh": {"element_size_mm": 2, "local_scale": 0.5}})
    given = module._declared_conditions(spec, _topology())
    assert {one.name: one.element_size for one in given.body_settings} == {"기둥": 0.75}
    assert {one.region: one.element_size for one in given.mesh_hints} == {
        "전체": 2.0,
        "기둥 끝": 0.4,
    }


@BOTH
def test_배율이_없으면_CAD_값_그대로다(module: Any) -> None:
    spec = parse_spec({"recipe": "modal"})
    given = module._declared_conditions(spec, _topology())
    assert {one.name: one.element_size for one in given.body_settings} == {"기둥": 1.5}


def test_배율은_0_보다_커야_한다() -> None:
    with pytest.raises(ValueError):
        parse_spec({"recipe": "modal", "mesh": {"local_scale": 0}})
