"""Ansys 추출의 반력 — **모델링이 남긴 절점이 정본이다**(`reaction_nodes.json`).

DPF 는 이 기계에 없다 — 절점의 반력을 더하는 함수는 가짜로 끼우고, 파일을 어떻게 읽는지만
본다. 끝까지 도는 것은 `tests/opensolver/test_shell_model.py` 의 Ansys 교차 검증이 본다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.dpf import probes
from app.core.dpf import static as dpf_static

TOPOLOGY: dict[str, Any] = {
    "regions": {
        "끝": [{"centroid": [0, 0, 0], "area": 1.0, "normal": [1, 0, 0]}],
        "옆": [{"centroid": [0, 5, 0], "area": 1.0, "normal": [0, 1, 0]}],
    },
    "conditions": {
        "constraints": [
            {"name": "당김", "type": "displacement", "on": "끝", "x": 0.1},
            {"name": "옆 당김", "type": "displacement", "on": "옆", "y": 0.0},
        ]
    },
}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"on": [], "plane": []}

    def reaction_on(model: Any, nodes: Any) -> list[float]:
        calls["on"].append(nodes)
        return [1.0, 2.0, 3.0]

    def reaction(model: Any, mesh: Any, row: Any) -> list[float]:
        calls["plane"].append(row)
        return [9.0, 9.0, 9.0]

    monkeypatch.setattr(probes, "reaction_on", reaction_on)
    monkeypatch.setattr(probes, "reaction", reaction)
    return calls


def test_파일이_있으면_빠진_영역을_평면으로_다시_찾지_않는다(
    tmp_path: Path, fake: dict[str, list[Any]]
) -> None:
    """빠진 영역은 그 절점이 다 다른 구속의 몫이라 뺀 것이다 — 평면으로 다시 찾으면 그 절점을
    두 번 센다(2026-10-16 검토). 축마다 다른 절점은 그대로 넘긴다."""
    (tmp_path / "reaction_nodes.json").write_text(
        json.dumps({"끝": {"x": [1, 2], "y": [2], "z": []}}), encoding="utf-8"
    )
    found = dpf_static._reactions(object(), object(), TOPOLOGY, tmp_path)
    assert found == {"끝": [1.0, 2.0, 3.0]}
    assert fake["on"] == [{"x": [1, 2], "y": [2], "z": []}]
    assert fake["plane"] == []


def test_파일이_없던_옛_작업은_변위를_평면으로_찾는다(
    tmp_path: Path, fake: dict[str, list[Any]]
) -> None:
    found = dpf_static._reactions(object(), object(), TOPOLOGY, tmp_path)
    assert set(found) == {"끝", "옆"}
    assert len(fake["plane"]) == 2 and fake["on"] == []
