"""**측정점** — 두 솔버가 함께 쓰는 부분.

CAD 가 선택 그룹에 점(vertex)을 담아 보낸다(`{"point": [5, 5, 90]}`). 그 점은 구속이나 하중을
걸 자리가 아니라 **값을 읽을 자리**다 — 실험에서 센서를 붙인 그 지점이고, 해석과 실측을 견주는
유일한 공통 좌표다. 전체 최대로는 그 비교를 못 한다: 최대는 모델 어디에서든 날 수 있고(구속
모서리의 수치적 첨두가 흔하다) 센서는 그 자리에 없다.

여기 있는 것은 **솔버를 모르는 부분**이다 — 무엇을 읽어야 하나(`wanted`)와 한 줄의 모양(`row`).
절점을 어디서 얻는지는 솔버마다 다르다(`calculix/probes.py` 는 `.msh`, `dpf/probes.py` 는 DPF).
"""

from __future__ import annotations

from typing import Any

#: 이보다 멀면 「그 자리 값이 아니다」 를 적는다(mm). 요소 크기보다 작게 잡을 이유가 없다.
FAR_MM = 1.0


def wanted(topology: dict[str, Any]) -> dict[str, tuple[float, float, float]]:
    """영역 이름 → 그 **점 하나의 좌표**. 점 그룹이 아니면 넘어간다.

    여러 점이 담긴 그룹은 첫 점만 쓴다 — CompCore 의 `limit: 1` 규칙과 같고, 여럿을 평균하면
    「어느 자리 값인가」 가 흐려진다.
    """
    found: dict[str, tuple[float, float, float]] = {}
    for name, rows in (topology.get("regions") or {}).items():
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            continue
        point = rows[0].get("point")
        if isinstance(point, list) and len(point) == 3:
            found[name] = (float(point[0]), float(point[1]), float(point[2]))
    return found


def row(
    *,
    name: str,
    point: tuple[float, float, float],
    node: int,
    distance_mm: float,
    value: float,
    unit: str,
) -> dict[str, Any]:
    """측정점 한 줄. **멀면 그 사실을 적는다** — 그 값은 다른 자리의 값이다.

    조용히 두면 사람은 센서 자리의 값으로 읽는다. 요소 안을 보간하면 더 정확하지만, 거리를 적어
    두면 사람이 그 판단을 할 수 있고 거짓 정밀도도 안 생긴다.
    """
    made: dict[str, Any] = {
        "name": name,
        "point": list(point),
        "node": node,
        "distance_mm": round(distance_mm, 4),
        "value": round(value, 10),
        "unit": unit,
    }
    if distance_mm > FAR_MM:
        made["warning"] = (
            f"가장 가까운 절점이 {distance_mm:.2f} mm 떨어져 있습니다 — 메시를 그 자리에서 "
            f"촘촘하게 하거나 측정점을 절점에 맞추세요."
        )
    return made
