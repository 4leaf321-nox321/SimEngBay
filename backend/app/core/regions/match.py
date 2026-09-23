"""좌표 지문 ↔ Mechanical 면 짝짓기.

## 계약 (CompCore `core/recipe/topology.py` 가 정본)

    { "units": "mm",
      "bodies":  [{ "name", "step_product", "volume", "centroid", "bbox" }],
      "regions": { "<이름>": [{ "centroid", "area", "normal"? , "radius"?, "axis"? }] },
      "unresolved": ["<CAD 가 못 푼 이름>"] }

## 평면과 원통을 다르게 잰다 — **다르게 어긋나기 때문이다**

실측(2026-09-23, 지름 12 반쪽 구멍):

| | CAD 가 적은 중심 | Mechanical 이 내는 중심 | 어긋남 |
| --- | --- | --- | --- |
| 온전한 구멍 | 축 위 (경계상자 중심) | 축 위 (넓이 무게중심) | 0.000 |
| **모서리에 걸친 반쪽 구멍** | 축에서 3.000 (= r/2) | 축에서 3.817 (= 2r/π) | **0.817** |

둘 다 남은 면 쪽으로 치우치지만 **치우친 양이 다르다.** 평면에 쓰는 좁은 허용오차(모델 크기의
0.2%)로 원통을 재면 반쪽 구멍이 통째로 안 잡히고, 반대로 원통 허용오차로 평면을 재면 나란한
면 둘이 서로 바뀐다. 그래서 **원통은 반지름을 먼저 맞추고 중심은 반지름에 견주어** 본다.

## 못 찾으면 **즉시 실패한다**

조용히 빼면 구속 없는 해석이 끝까지 돌고, 결과는 0 Hz 여섯 개를 달고 나온다 — 그것을 사람은
「해석이 됐다」 로 읽는다. CompCore 도 같은 이유로 못 푼 이름을 `unresolved` 에 남긴다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: 평면의 중심이 이만큼 안에 들어와야 한다 — 모델 크기(경계상자 대각선) 대비 비율.
#: 두 면이 이보다 가까이 나란히 있는 형상은 애초에 사람이 구별해 주어야 한다.
PLANE_TOLERANCE_RATIO = 0.002
#: 그래도 이보다는 넓게 본다(mm). 작은 부품에서 비율만 쓰면 부동소수 오차에도 안 걸린다.
PLANE_TOLERANCE_MIN = 0.5

#: 원통의 중심은 **반지름에 견주어** 본다(위 표). 반쪽 구멍의 어긋남이 0.14r 였으니 넉넉하다.
CYLINDER_TOLERANCE_RATIO = 0.5
#: 반지름은 좁게 — 이것이 구멍을 가르는 가장 강한 열쇠다.
RADIUS_TOLERANCE = 0.02

#: 법선 사이 각(도). 나란한 면을 가르는 데 쓴다 — 앞뒤가 뒤집힌 것(180도)은 다른 면이다.
NORMAL_TOLERANCE_DEGREES = 15.0

#: 넓이는 **얼마나 다른가**만 본다. 반쪽 구멍처럼 면이 잘리면 절반이 되므로 원통에는 안 쓴다.
AREA_TOLERANCE_RATIO = 0.05


@dataclass(frozen=True)
class FaceRecord:
    """Mechanical 이 내는 면 하나.

    **코어는 Ansys 를 모른다** — 부르는 쪽이 이 모양으로 옮겨 준다.
    """

    id: int
    centroid: tuple[float, float, float]
    area: float
    surface: str = ""
    normal: tuple[float, float, float] | None = None
    radius: float | None = None

    @property
    def is_cylinder(self) -> bool:
        return "cylinder" in self.surface.lower() or (self.radius or 0) > 0


@dataclass
class MatchFailure:
    """왜 못 찾았나.

    **가장 가까웠던 후보까지 적는다** — 허용오차를 늘릴지 형상을 볼지가 갈린다.
    """

    region: str
    index: int
    reason: str
    wanted: dict[str, Any]
    nearest: dict[str, Any] | None = None


@dataclass
class RegionMatch:
    faces: dict[str, list[int]] = field(default_factory=dict)
    failures: list[MatchFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.dist(a, b)


def _angle_degrees(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    length = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if length == 0:
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / length))))


def _triple(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, list | tuple) or len(value) != 3:
        return None
    return (float(value[0]), float(value[1]), float(value[2]))


def model_scale(topology: dict[str, Any]) -> float:
    """모델의 크기(경계상자 대각선). 허용오차를 여기에 견준다 — 100mm 부품과 2m 지그에
    같은 mm 값을 쓰면 한쪽은 너무 좁고 한쪽은 너무 넓다."""
    spans: list[float] = []
    for body in topology.get("bodies") or []:
        box = body.get("bbox")
        if not isinstance(box, list) or len(box) != 2:
            continue
        low, high = _triple(box[0]), _triple(box[1])
        if low and high:
            spans.append(math.dist(low, high))
    return max(spans) if spans else 100.0


def _score(wanted: dict[str, Any], face: FaceRecord, scale: float) -> tuple[bool, float, str]:
    """(짝인가, 얼마나 가까운가, 아니라면 왜)."""
    centroid = _triple(wanted.get("centroid"))
    if centroid is None:
        return False, math.inf, "중심 좌표가 없습니다"
    distance = _distance(centroid, face.centroid)

    radius = wanted.get("radius")
    if radius is not None:
        if not face.is_cylinder:
            return False, distance, "원통면이 아닙니다"
        if face.radius is None or abs(face.radius - float(radius)) > RADIUS_TOLERANCE:
            return False, distance, f"반지름이 다릅니다({face.radius} ≠ {radius})"
        # **중심은 반지름에 견주어 본다.** 면이 잘리면 CAD 와 해석이 서로 다르게 치우친다.
        limit = max(CYLINDER_TOLERANCE_RATIO * float(radius), PLANE_TOLERANCE_MIN)
        if distance > limit:
            return (
                False,
                distance,
                f"중심이 {distance:.2f}mm 떨어져 있습니다(한계 {limit:.2f})",
            )
        return True, distance, ""

    if face.is_cylinder:
        return False, distance, "평면이 아닙니다"
    limit = max(PLANE_TOLERANCE_RATIO * scale, PLANE_TOLERANCE_MIN)
    if distance > limit:
        return False, distance, f"중심이 {distance:.2f}mm 떨어져 있습니다(한계 {limit:.2f})"

    normal = _triple(wanted.get("normal"))
    if normal is not None and face.normal is not None:
        angle = _angle_degrees(normal, face.normal)
        if angle > NORMAL_TOLERANCE_DEGREES:
            return False, distance, f"법선이 {angle:.0f}도 틀어져 있습니다"

    area = wanted.get("area")
    if area is not None and float(area) > 0:
        ratio = abs(face.area - float(area)) / float(area)
        if ratio > AREA_TOLERANCE_RATIO:
            return False, distance, f"넓이가 {ratio * 100:.0f}% 다릅니다"
    return True, distance, ""


def match_regions(
    topology: dict[str, Any],
    faces: list[FaceRecord],
    *,
    wanted_regions: list[str] | None = None,
) -> RegionMatch:
    """`topology.json` 의 영역들을 형상의 면 번호로 푼다.

    `wanted_regions` 를 주면 **그것만** 푼다 — 스펙이 쓰지도 않는 영역이 안 풀렸다고 해석을
    막을 이유는 없다.
    """
    result = RegionMatch()
    regions: dict[str, Any] = topology.get("regions") or {}
    unresolved_by_cad: set[str] = set(topology.get("unresolved") or [])
    scale = model_scale(topology)
    taken: set[int] = set()

    for name in wanted_regions if wanted_regions is not None else list(regions):
        if name in unresolved_by_cad:
            # CAD 가 이미 못 풀었다고 적어 보냈다. 그 이름으로는 형상에 자리가 없다.
            result.failures.append(
                MatchFailure(name, 0, "CAD 가 이 영역을 풀지 못했습니다(unresolved)", {})
            )
            continue
        wanted_faces = regions.get(name)
        if not wanted_faces:
            result.failures.append(
                MatchFailure(name, 0, "topology.json 에 없는 영역입니다", {})
            )
            continue

        found: list[int] = []
        for index, wanted in enumerate(wanted_faces):
            best: tuple[float, FaceRecord] | None = None
            nearest: tuple[float, FaceRecord, str] | None = None
            for face in faces:
                if face.id in taken:
                    continue
                ok, distance, why = _score(wanted, face, scale)
                if ok and (best is None or distance < best[0]):
                    best = (distance, face)
                if not ok and (nearest is None or distance < nearest[0]):
                    nearest = (distance, face, why)
            if best is None:
                result.failures.append(
                    MatchFailure(
                        region=name,
                        index=index,
                        reason=nearest[2] if nearest else "후보가 없습니다",
                        wanted=dict(wanted),
                        nearest=(
                            {
                                "id": nearest[1].id,
                                "centroid": list(nearest[1].centroid),
                                "area": nearest[1].area,
                                "distance": round(nearest[0], 3),
                            }
                            if nearest
                            else None
                        ),
                    )
                )
                continue
            taken.add(best[1].id)
            found.append(best[1].id)
        if found:
            result.faces[name] = found
    return result
