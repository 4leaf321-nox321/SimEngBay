"""**모달에 쓰는 구속** — 기울어진 면의 마찰 없는 지지(대칭면 · 미끄럼 받침).

축에 나란한 면은 그 축 하나를 막고(`*BOUNDARY`), 기울어진 면은 절점마다 구속식 「n · u = 0」
(`*EQUATION`)이다(`deck._frictionless`). 같은 블록을 축에 맞춰 둔 것과 30° 돌린 것이 같은 답을
내야
한다 — 회전해도 물리가 같다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.core.calculix import tools
from app.core.stages import StageFailure
from tests.opensolver.test_calculix import SIDE_SHAKE, SPEC, _run

pytestmark = pytest.mark.opensolver


@pytest.fixture
def ready() -> None:
    for find in (tools.gmsh_bin, tools.ccx_bin):
        try:
            find()
        except StageFailure as failure:
            pytest.skip(str(failure))


def _turned(point: tuple[float, float, float], angle: float) -> list[float]:
    """X 축 둘레로 돌린 점."""
    x, y, z = point
    return [
        x,
        y * math.cos(angle) - z * math.sin(angle),
        y * math.sin(angle) + z * math.cos(angle),
    ]


def _block(work: Path, angle: float) -> None:
    """40 x 20 x 10 블록을 X 축 둘레로 `angle` 돌리고, 바닥에 마찰 없는 지지를 건다."""
    work.mkdir(parents=True)
    geo = work / "block.geo"
    geo.write_text(
        'SetFactory("OpenCASCADE");\n'
        "Box(1) = {0, 0, 0, 40, 20, 10};\n"
        f"Rotate {{{{1, 0, 0}}, {{0, 0, 0}}, {angle!r}}} {{ Volume{{1}}; }}\n",
        encoding="utf-8",
    )
    tools.run(
        tools.gmsh_bin(),
        [str(geo), "-0", "-o", str(work / "input.step"), "-v", "1"],
        cwd=work,
        timeout_seconds=120,
        what="gmsh",
    )
    corners = [_turned((x, y, z), angle) for x in (0, 40) for y in (0, 20) for z in (0, 10)]
    payload: dict[str, Any] = json.loads(
        (SIDE_SHAKE / "points" / "p0001.json").read_text(encoding="utf-8")
    )
    payload["bodies"] = [
        {
            "name": "블록",
            "kind": "solid",
            "volume": 8000.0,
            "centroid": _turned((20.0, 10.0, 5.0), angle),
            "bbox": [
                [min(one[axis] for one in corners) for axis in range(3)],
                [max(one[axis] for one in corners) for axis in range(3)],
            ],
        }
    ]
    payload["regions"] = {
        "바닥": [
            {
                "centroid": _turned((20.0, 10.0, 0.0), angle),
                "area": 800.0,
                "normal": _turned((0.0, 0.0, -1.0), angle),
                "body": "블록",
            }
        ]
    }
    conditions = payload["conditions"]
    conditions["constraints"] = [{"name": "바닥 미끄럼", "type": "frictionless", "on": "바닥"}]
    for key in ("contacts", "loads", "materials", "body_settings", "mesh"):
        conditions[key] = []
    payload["named_selections"] = []
    (work / "topology.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_기울어진_면의_마찰_없는_지지는_축에_맞춘_것과_같은_모드를_낸다(
    ready: None, tmp_path: Path
) -> None:
    """바닥만 미끄러지게 받친 블록 — 면 안의 미끄럼 둘과 법선 둘레 회전이 0 Hz, 그 뒤가 탄성
    모드다. 30° 돌려도(구속식) 축에 맞춘 것(경계 조건)과 같아야 한다. 전에는 기울어진 면이면
    「못 거는 구속」 이었다."""
    spec = {**SPEC, "material_from": "spec", "mesh": {"element_size_mm": 5}, "modes": 6}
    found: dict[str, list[float]] = {}
    for label, angle in (("aligned", 0.0), ("turned", math.pi / 6)):
        work = tmp_path / label
        _block(work, angle)
        summary = _run(work, spec)
        assert "frictionless:바닥" in summary["constrained_regions"]
        deck = (work / "model.inp").read_text(encoding="utf-8")
        assert ("*EQUATION" in deck) == (label == "turned")
        modes = json.loads((work / "result.json").read_text(encoding="utf-8"))["modes"]
        found[label] = [float(one["frequency_hz"]) for one in modes]
    for label, freqs in found.items():
        assert sum(1 for one in freqs if one < 1.0) == 3, (label, freqs)
    for aligned, turned in zip(found["aligned"][3:], found["turned"][3:], strict=True):
        assert turned == pytest.approx(aligned, rel=0.02), found


def test_모달에서_쉘이_낀_비본딩_접촉도_푼다(ready: None, tmp_path: Path) -> None:
    """쉘 브래킷 ↔ 솔리드 블록(강체를 변형체로 바꾼다 — 강체면 접촉과 상관없이 강체에 넣는다).
    전에는 본딩이 아니면 멈췄다. 모달에서 마찰은 묶어 붙은 것으로(본딩과 같은 주파수, 그렇다고
    적는다), 무마찰은 솔리드 면의 법선으로만 묶는다(`*EQUATION`)."""
    from tests.opensolver.test_calculix import _shell_point

    spec = {
        "recipe": "modal",
        "solver": "calculix",
        "mesh": {"element_size_mm": 5},
        "modes": 4,
    }
    first: dict[str, float] = {}
    for kind in ("bonded", "frictional", "frictionless"):
        work = tmp_path / kind
        _shell_point(work, 1)
        payload = json.loads((work / "topology.json").read_text(encoding="utf-8"))
        for row in payload["conditions"]["body_settings"]:
            if row["name"] == "지그블록":
                row["behavior"] = "deformable"
        for row in payload["conditions"]["contacts"]:
            row["type"] = kind
        (work / "topology.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        summary = _run(work, spec)
        deck = (work / "model.inp").read_text(encoding="utf-8")
        modes = json.loads((work / "result.json").read_text(encoding="utf-8"))["modes"]
        first[kind] = float(modes[0]["frequency_hz"])
        if kind == "frictionless":
            assert "*EQUATION" in deck
            assert "no_separation:브래킷 접합" in summary["constrained_regions"]
        else:
            assert "*TIE" in deck
        if kind == "frictional":
            assert "붙은 것으로" in summary["conditions_skipped"]
    assert first["frictional"] == pytest.approx(first["bonded"], rel=1e-6)
    assert first["frictionless"] <= first["bonded"] * 1.001
