"""v1 으로 접히는 사슬(v2)은 **v1 픽스처와 같은 CalculiX 덱**을 낸다 — 「솔버 덱은 그대로」 를
시험으로 굳힌다(`app/core/cases.py` 의 접기, CompCore 「v2 사슬 픽스처」 2026-11-27).

같은 모델을 v1(「조건_볼트예압_정적」 · 「…_선응력모달」 점 1)과 v2(사슬)로 뽑은 폴더다 — 형상
·
선택 그룹 · 재료 · 접촉 · 메시가 같다. 작업 만들기가 담는 사슬의 보기로 모델링하고 덱을 견준다.
**STEP 은 둘 다 v1 의 것을 쓴다.** 견주는 것은 조건이 덱에 들어가는 길이다 — 덱의 **뼈대**
(키워드 줄의 차례: 집합 · 구속 · 단계 · 하중 카드)와 모델링 요약의 조건 칸(걸린 조건 · 물성 ·
본딩 · 접촉 쌍 · 넘긴 것). 메시는 같은 입력도 돌릴 때마다 절점이 조금씩 달라(gmsh — 같은 v1 을
두 번 모델링해도 줄 수가 35,776 ↔ 36,118) 덱을 바이트로 견주지 못한다.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core import cases
from app.core.calculix import tools
from app.core.run import run_stage
from app.core.spec import parse_spec
from app.core.stages import StageFailure

pytestmark = pytest.mark.opensolver

DOE = Path(__file__).resolve().parents[1] / "fixtures" / "doe"


@pytest.fixture
def ready() -> None:
    for find in (tools.gmsh_bin, tools.ccx_bin):
        try:
            find()
        except StageFailure as failure:
            pytest.skip(str(failure))


def _step(folder: str) -> Path:
    point = json.loads((DOE / folder / "points" / "p0001.json").read_text(encoding="utf-8"))
    return DOE / folder / ((point.get("point") or {}).get("step_file") or "points/p0001.step")


#: 모델링 요약 중 메시와 상관없는 칸 — 조건이 어떻게 걸렸나.
SAME = (
    "solver",
    "bodies",
    "deck_materials",
    "bonding",
    "contact_pairs",
    "constrained_regions",
    "material",
    "material_from",
    "conditions_from",
    "unit_system",
)


def _model(
    folder: str, step: Path, workdir: Path, recipe: str, case: str | None
) -> tuple[list[str], dict[str, Any]]:
    """폴더의 점 1 을 작업 폴더로 — 사슬이면 그 보기(작업 만들기가 담는 것) — 모델링까지."""
    point_file = DOE / folder / "points" / "p0001.json"
    point: dict[str, Any] = json.loads(point_file.read_text(encoding="utf-8"))
    shutil.copy(step, workdir / "input.step")
    if case is not None:
        found, broken = cases.chains(point)
        assert not broken
        chain = next(one for one in found if one.name == case)
        assert cases.problem(chain) == ""
        point = cases.view(point, chain)
    (workdir / "topology.json").write_text(json.dumps(point, ensure_ascii=False), "utf-8")
    spec = parse_spec(
        {"recipe": recipe, "solver": "calculix", "mesh": {"element_size_mm": 4}, "modes": 6}
        if recipe == "modal"
        else {"recipe": recipe, "solver": "calculix", "mesh": {"element_size_mm": 4}}
    )
    summary: dict[str, Any] = {}
    for stage in ("fetching", "modeling"):
        done = run_stage(
            stage,
            spec,
            workdir,
            input_name="input.step",
            version=252,
            ansys_root=None,
            solver_processes=2,
            timeout_seconds=900,
            visual_modes=6,
        )
        summary.update(done.summary)
    deck = (workdir / "model.inp").read_text(encoding="utf-8")
    skeleton = [line for line in deck.splitlines() if line.startswith("*")]
    kept = {key: summary.get(key) for key in SAME}
    # 넘긴 것의 수(고정된 자유도 몇 개 …)는 메시를 따른다 — 말만 견준다.
    kept["skipped"] = re.sub(r"\d+", "#", str(summary.get("conditions_skipped") or ""))
    return skeleton, kept


@pytest.mark.parametrize(
    ("v1", "v2", "case", "recipe"),
    [
        ("조건_볼트예압_정적", "조건_볼트예압_두케이스_솔버없음", "외력", "static"),
        ("조건_볼트예압_정적", "조건_볼트예압_사슬_둘", "외력", "static"),
        ("조건_볼트예압_선응력모달", "조건_볼트예압_사슬_정적모달", "모달", "modal"),
        ("조건_볼트예압_선응력모달", "조건_볼트예압_사슬_세케이스", "모달", "modal"),
    ],
)
def test_접히는_사슬은_v1_과_같은_덱을_낸다(
    ready: None, tmp_path: Path, v1: str, v2: str, case: str, recipe: str
) -> None:
    (tmp_path / "v1").mkdir()
    (tmp_path / "v2").mkdir()
    step = _step(v1)
    want = _model(v1, step, tmp_path / "v1", recipe, None)
    got = _model(v2, step, tmp_path / "v2", recipe, case)
    assert got[0] == want[0], "덱의 뼈대"
    assert got[1] == want[1], "모델링 요약의 조건 칸"
    assert any(line.startswith("*STEP") for line in got[0])
