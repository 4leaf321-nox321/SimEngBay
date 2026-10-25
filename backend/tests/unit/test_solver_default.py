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
    """조건 층은 솔버를 모른다 — 압축 전용 지지는 Ansys 는 걸고 CalculiX 는 아직 못 건다.
    만들 때 안 막으면 DOE 200점이 모델링에서 하나씩 같은 말을 한다."""
    payload = json.loads(SIDE_POINT.read_text(encoding="utf-8"))
    support = payload["conditions"]["constraints"][0]
    payload["conditions"]["constraints"][0] = {**support, "type": "compression_only"}
    calculix = parse_spec({"recipe": "modal", "mesh": {"element_size_mm": 5}})
    ansys = parse_spec({"recipe": "modal", "solver": "ansys"})
    gap = services.conditions_gap(calculix, payload)
    assert (
        gap is not None
        and "CalculiX 로는 아직 못 거는 조건" in gap
        and "compression_only" in gap
    )
    assert services.conditions_gap(ansys, payload) is None


def test_CalculiX_는_요소_크기가_어디에도_없으면_만들_때_막는다() -> None:
    """CalculiX 는 크기를 스펙에서, 비면 CAD 의 「전체」 메시 힌트 · CompCore 의 제안값에서
    얻는다 — 다 없으면 모델링이 「요소 크기가 없습니다」 로 멈춘다. 화면은 미리 막았지만 API 는
    받았다."""
    sized_cad = json.loads(SIDE_POINT.read_text(encoding="utf-8"))
    assert sized_cad["conditions"]["mesh_hints"][0]["on"] == "전체"
    suggested = {**sized_cad, "conditions": {**sized_cad["conditions"], "mesh_hints": []}}
    bare = {key: value for key, value in suggested.items() if key != "mesh_suggestion"}

    sizeless = parse_spec({"recipe": "modal"})
    assert services.size_gap(sizeless, None) is not None
    assert services.size_gap(sizeless, bare) is not None
    # CAD 가 「전체」 크기를 적었으면 그것을 쓴다 — 다만 CAD 조건을 끄면 그 힌트도 안 읽는다.
    assert services.size_gap(sizeless, sized_cad) is None
    # 「전체」 크기가 없어도 CompCore 가 형상으로 셈한 제안이 있으면 그것을 쓴다(2026-10-23).
    assert services.size_gap(sizeless, suggested) is None
    mine = parse_spec({"recipe": "modal", "conditions_from": "spec"})
    assert services.size_gap(mine, sized_cad) is not None
    # 스펙에 크기가 있거나 Ansys 면(그쪽은 크기를 스스로 정한다) 막지 않는다.
    assert (
        services.size_gap(
            parse_spec({"recipe": "modal", "mesh": {"element_size_mm": 3}}), None
        )
        is None
    )
    assert services.size_gap(parse_spec({"recipe": "modal", "solver": "ansys"}), None) is None
