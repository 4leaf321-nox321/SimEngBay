"""기본 솔버가 CalculiX 다(2026-10-08) — **새 요청은 CalculiX, 칸이 없는 옛 작업은 Ansys**.

큐(`claim_next`)는 칸이 없으면 Ansys 로 집는다. 실행이 같은 스펙을 기본값(CalculiX)으로 읽으면
Ansys 워커가 집은 옛 작업을 CalculiX 로 푼다 — 재시도 · 메시 수렴 점검이 그 길이었다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.spec import parse_spec, parse_stored_spec
from app.modules.simulations import services

SIDE_POINT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "doe"
    / "조건_측면가진"
    / "points"
    / "p0001.json"
)


def test_새_요청은_CalculiX_저장된_옛_스펙은_Ansys() -> None:
    raw: dict[str, Any] = {"recipe": "modal", "mesh": {"element_size_mm": 5}}
    assert parse_spec(raw).solver == "calculix"
    assert parse_stored_spec(raw).solver == "ansys"
    # 칸이 있으면 그대로다.
    assert parse_stored_spec({**raw, "solver": "calculix"}).solver == "calculix"


def test_CalculiX_가_못_거는_조건은_만들_때_막는다() -> None:
    """조건 층은 솔버를 모른다 — 탄성 지지는 Ansys 는 걸고 CalculiX 는 아직 못 건다. 만들 때
    안 막으면 DOE 200점이 모델링에서 하나씩 같은 말을 한다."""
    payload = json.loads(SIDE_POINT.read_text(encoding="utf-8"))
    support = payload["conditions"]["constraints"][0]
    payload["conditions"]["constraints"][0] = {
        **support,
        "type": "elastic_support",
        "stiffness": 10.0,
    }
    calculix = parse_spec({"recipe": "modal", "mesh": {"element_size_mm": 5}})
    ansys = parse_spec({"recipe": "modal", "solver": "ansys"})
    gap = services.conditions_gap(calculix, payload)
    assert (
        gap is not None
        and "CalculiX 로는 아직 못 거는 조건" in gap
        and "elastic_support" in gap
    )
    assert services.conditions_gap(ansys, payload) is None
