"""모달의 **찾을 주파수 범위** — 두 솔버가 같은 뜻으로 풀게 한 자리에서 정한다(2026-11-17).

뜻은 Ansys 의 `LimitSearchToRange` 그대로다 — **범위 안의 모드를 최대 `modes` 개.** 범위
아래의 모드는 세지 않는다. 보고 싶은 대역(가진 대역 · 시험 대역)이 낮은 모드에 밀려 모드 수
밖으로 나가지 않게 하는 칸이다. CAD 가 적어 보내면 그것이 먼저다(조화 응답의 범위와 같은 규칙 —
`harmonic.py`).

## CalculiX 에는 범위를 주지 않는다

`*FREQUENCY` 의 범위 칸(하한 · 상한)은 **낮은 차수부터 N 개를 구한 뒤 범위로 거를 뿐**이다
(실측 2026-11-17, ccx 2.21: 외팔보 167 · 859 · 1,038 Hz … 에서 「2, 800, 3000」 은 859 Hz
하나만 냈다 — 범위 안을 찾았다면 859 · 1,038 이 나와야 한다). 게다가 그때 유효질량 표는
**걸러지기 전 차례로** 찍혀 고유치 표와 어긋난다(2 ~ 6번 모드의 자리에 1 ~ 5번 값). 그래서 범위
없이 풀고

1. 범위 위쪽에 닿지 못했는데 범위 안이 모자라면 **모드 수를 늘려 다시 푼다**(`next_count`,
   `calculix/solve.py`) — 범위 아래 모드 수 + 원하는 수를 겨눈다. 상한 `MAX_SOLVED`.
2. 결과를 읽을 때 범위 안만 남긴다(`kept`, `calculix/read.py`) — 표 · 형상은 전체 차례 그대로라
   어긋나지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core import conditions as condition_model
from app.core.spec import ModalSpec

#: `boundary.json` 의 열쇠 — 모델링이 적고 솔브 · 추출이 읽는다.
KEY = "mode_search"
#: CalculiX 가 범위를 채우려고 늘려 풀 수 있는 모드 수의 상한. 넘으면 그 사실을 결과에 적는다.
MAX_SOLVED = 200
#: 다시 푸는 횟수의 상한(처음 것 포함).
MAX_PASSES = 4


@dataclass(frozen=True)
class ModeSearch:
    low: float
    high: float
    want: int
    """범위 안에서 찾을 **탄성** 모드 수(스펙의 `modes`)."""
    source: Literal["cad", "spec"]

    @property
    def label(self) -> str:
        return f"{self.low:g}~{self.high:g} Hz"

    def inside(self, hz: float) -> bool:
        return self.low <= hz <= self.high

    def as_boundary(self) -> dict[str, Any]:
        return {"low": self.low, "high": self.high, "want": self.want, "source": self.source}


def cad_range(given: condition_model.Conditions) -> tuple[float, float] | None:
    """CAD 가 적은 **모달의** 찾을 범위 — 해석 종류가 모달일 때만(조화의 범위는 훑을 범위라
    뜻이 다르다 — 조화로 적은 점 파일을 모달로 걸면 그 범위로 모드를 거르지 않는다)."""
    declared = given.analysis.frequency_range
    if given.analysis.kind != "modal" or declared is None:
        return None
    return declared if 0 <= declared[0] < declared[1] else None


def mode_search(spec: ModalSpec, given: condition_model.Conditions) -> ModeSearch | None:
    """찾을 범위 — CAD(`analysis.frequency_range`)가 먼저, 없으면 스펙. 둘 다 없으면 None."""
    declared = cad_range(given)
    if declared is not None:
        return ModeSearch(float(declared[0]), float(declared[1]), spec.modes, "cad")
    if spec.frequency_range_hz is not None:
        low, high = spec.frequency_range_hz
        return ModeSearch(float(low), float(high), spec.modes, "spec")
    return None


def next_count(frequencies: Sequence[float], asked: int, search: ModeSearch) -> int | None:
    """다시 풀 모드 수 — **됐으면 None.**

    됐다: 범위 안이 원하는 수만큼 찼다 · 범위 위쪽을 넘는 모드까지 풀었다(범위 안은 다
    나왔다) · 청한 것보다 적게 나왔다(모델이 가진 모드를 다 냈다) · 상한에 닿았다.
    """
    if len(frequencies) < asked or asked >= MAX_SOLVED:
        return None
    if sum(1 for one in frequencies if search.inside(one)) >= search.want:
        return None
    if frequencies and frequencies[-1] > search.high:
        return None
    below = sum(1 for one in frequencies if one < search.low)
    return min(MAX_SOLVED, max(asked * 2, below + search.want + 2))


def kept(
    modes: Sequence[dict[str, Any]], search: ModeSearch
) -> tuple[list[dict[str, Any]], int]:
    """범위 안의 모드 — 탄성 모드는 원하는 수까지, **탄성 차수는 범위 안에서 1 부터** 다시 센다
    (Ansys 의 범위 찾기가 그렇게 낸다). 강체 모드는 범위 안에 들면 남긴다(세지 않는다).
    둘째 값은 범위 아래에서 뺀 탄성 모드 수. `number`(전체 차례)는 그대로 둔다 — 표 · 형상을
    그것으로 찾는다."""
    shown: list[dict[str, Any]] = []
    below = 0
    elastic = 0
    for one in modes:
        hz = float(one["frequency_hz"])
        rigid = bool(one.get("rigid_body"))
        if not search.inside(hz):
            if hz < search.low and not rigid:
                below += 1
            continue
        if rigid:
            shown.append(dict(one))
            continue
        if elastic >= search.want:
            continue
        elastic += 1
        shown.append({**one, "elastic_number": elastic})
    return shown, below


def note(search: ModeSearch, found: int, solved: Sequence[float] | None = None) -> str | None:
    """범위 찾기가 모자랐을 때 사람에게 할 말 — 충분하면 None.

    `solved` 는 실제로 푼 고유진동수 전부(CalculiX). 범위 위쪽에 닿지 못했으면 범위 안에 모드가
    더 있을 수 있다 — 조용히 두면 「범위 안의 모드는 이것뿐」 으로 읽힌다."""
    if found >= search.want:
        return None
    if solved and solved[-1] < search.high and len(solved) >= MAX_SOLVED:
        return (
            f"범위 {search.label} 를 끝까지 훑지 못했습니다 — 모드를 {len(solved)}개(상한)"
            f"까지 풀었는데 {solved[-1]:,.1f} Hz 에서 멈췄습니다. 범위를 좁히세요."
        )
    if found == 0:
        return f"범위 {search.label} 안에 모드가 없습니다."
    return None


def read(boundary: Path) -> ModeSearch | None:
    """모델링이 `boundary.json` 에 남긴 범위 — 없거나 못 읽으면 None."""
    try:
        payload = json.loads(boundary.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    row = payload.get(KEY) if isinstance(payload, dict) else None
    if not isinstance(row, dict):
        return None
    try:
        return ModeSearch(
            float(row["low"]),
            float(row["high"]),
            int(row["want"]),
            "cad" if row.get("source") == "cad" else "spec",
        )
    except (KeyError, TypeError, ValueError):
        return None
