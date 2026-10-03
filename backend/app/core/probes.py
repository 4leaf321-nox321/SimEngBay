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


def body_of(topology: dict[str, Any], name: str) -> str | None:
    """그 측정점이 **어느 바디의 것인가**. 지문에 `body` 가 없으면 `None`(전체에서 찾는다).

    같은 자리에 두 바디의 꼭짓점이 겹칠 수 있다 — 이음 입구가 그렇다. 바디를 가르지 않으면 두
    측정점이 **같은 절점**을 잡고, 둘의 차(미끄럼)가 늘 0 으로 나온다. 그 0 은
    「안 미끄러졌다」 로 읽힌다. CompCore 가 2026-10-03 부터 조립 지문에 `body` 를 붙인다.
    """
    rows = (topology.get("regions") or {}).get(name)
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        body = rows[0].get("body")
        if isinstance(body, str) and body:
            return body
    return None


def row(
    *,
    name: str,
    point: tuple[float, float, float],
    node: int,
    distance_mm: float,
    value: float,
    unit: str,
    vector: list[float] | None = None,
    body: str | None = None,
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
    if vector is not None:
        # **성분도 싣는다** — 크기만으로는 미끄럼(두 점의 X 차)을 못 잰다.
        made["vector"] = [round(one, 12) for one in vector[:3]]
    if body is not None:
        made["body"] = body
    if distance_mm > FAR_MM:
        made["warning"] = (
            f"가장 가까운 절점이 {distance_mm:.2f} mm 떨어져 있습니다 — 메시를 그 자리에서 "
            f"촘촘하게 하거나 측정점을 절점에 맞추세요."
        )
    return made
