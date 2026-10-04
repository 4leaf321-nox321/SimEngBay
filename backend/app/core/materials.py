"""물성 — **CAD 가 보낸 것을 읽어 스펙으로.**

여태 물성은 사람이 화면에서 넣은 한 벌을 설계점 전부에 썼다. 그러면 CompCore 가 재료를 훑는
DOE(1번 SS400 · 2번 AL6061)를 보내도 **두 점이 같은 물성으로 돌고 결과가 똑같이 나온다** —
이름표만 다르다. 비교 화면의 두 축(주파수 · 질량)이 함께 거짓이 되는 자리다.

## 중립 표현을 내부 표준으로 둔다

CompCore 는 물성마다 MatNexus 원본(`payload`)과 **그 계로 환산한 값**(`converted`)을 나란히
보내고, 나중에는 솔버 덱(`materials/m1-ansys.dat`)도 덤으로 실어 보낸다. 덱이 오면 그것이 더
완전하지만(온도 표 · 소성) **내부 표준은 중립으로 둔다** — 덱을 표준으로 삼으면 값이 화면에
못 뜨고(숫자를 다시 파싱해야 한다) 다른 솔버를 붙일 때 되돌릴 수 없다. 그래서 이 모듈이 내는
것은 늘 SI 스칼라 셋이고, 명령 조각은 `mechanical/build.py` 가 **세션의 계로 환산해** 적는다.

덱은 아직 안 읽는다 — 자리는 `Material.commands` 로 뒀다(폴더의 덱 파일을 작업으로 옮기는
일이 먼저다).

## 어느 것이 영률인가 — **열쇠로 푼다**

항목 이름은 출처마다 다르다(`탄성계수` · `Young's modulus`). 그래서 이름으로 고르지 않고
`converted.properties[].key` 의 **표준 열쇠**(`mechanical.youngs_modulus`)로 찾는다 — CompCore
가 MatNexus 물성 사전으로 붙여 준다. 못 붙였으면 그쪽이 `missing_structural` 로 말해 주므로,
그때는 **추측하지 않고 실패한다.** 이름표를 우리가 짐작해 고르면 값은 나오고 그 값이 영률이
아닐 수 있다.

## 단위는 값 곁의 이름으로 읽는다

`converted` 는 값마다 단위 이름을 함께 준다(`unit` · `density_unit`). 선언된 계를 믿고 「mm
계니까 MPa 겠지」 로 읽지 않는다 — `units.stress_from` · `units.density_from` 이 그 이름을 읽고
**모르는 이름이면 거절한다.**

## 실측으로 지키는 것

같은 형상 · 다른 재료(SS400 206 GPa · 7,850 → AL6061 68.9 GPa · 2,700)를 돌리면 주파수 비가
탄성계수/밀도 비의 제곱근(1.014)과 맞고 **질량이 0.89 kg · 0.31 kg 로 갈린다.** 지금은 둘이
똑같이 나온다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core import units
from app.core.spec import MaterialSpec

#: 표준 열쇠 — CompCore · MatNexus 와 같은 이름을 쓴다.
MODULUS_KEY = "mechanical.youngs_modulus"
POISSON_KEY = "mechanical.poisson_ratio"
DENSITY_KEY = "physical.density"

#: 온도 표에서 고를 기준 온도. 모달은 상온 한 점이면 된다 — 여러 점이 오면 여기서 가장
#: 가까운 것을 고르고 **고른 온도를 적어 둔다**(요약에 뜬다).
REFERENCE_C = 22.0

#: CompCore 가 「모든 바디」 를 가리키는 이름. `apply_to: ["전체"]` 가 그 뜻이다.
ALL_BODIES = "전체"


@dataclass(frozen=True)
class Material:
    """물성 한 벌 — **SI 스칼라**로. 세션의 계로 옮기는 일은 모델링이 한다."""

    name: str
    bodies: tuple[str, ...]
    """붙일 바디 이름들. 비어 있으면 **모든 바디**(`전체`)."""
    youngs_modulus_pa: float
    poisson_ratio: float
    density_kg_m3: float
    source: str
    """어디서 읽었나 — `converted`(CAD 가 환산한 값) · `payload`(원본에서 직접)."""
    temperature_c: float | None = None
    """온도 표에서 고른 점. 표가 없으면 `None`."""
    notes: tuple[str, ...] = ()
    """사람에게 전할 말 — 못 바꾼 항목, 문헌 등급 등."""
    commands: str = ""
    """솔버 덱(있으면 그대로 쓴다). **아직 채우지 않는다** — 자리만."""

    @property
    def every_body(self) -> bool:
        return not self.bodies

    def spec(self) -> MaterialSpec:
        """사람이 읽는 단위의 스펙으로 — 화면 · 명령 조각이 쓰는 모양."""
        return MaterialSpec(
            name=self.name[:80],
            youngs_modulus_gpa=self.youngs_modulus_pa / 1e9,
            poisson_ratio=self.poisson_ratio,
            density_kg_m3=self.density_kg_m3,
        )


class MaterialProblem(ValueError):
    """물성을 읽을 수 없다. **추측하지 않는다** — 빠진 물성은 해석이 기본값(구조용 강)으로
    풀어 버리고, 그 사실은 고유진동수가 틀린 뒤에야 드러난다."""

    def __init__(self, name: str, reason: str) -> None:
        self.material = name
        self.reason = reason
        super().__init__(f"물성 「{name}」 을 읽을 수 없습니다: {reason}")


def read(payload: Any, system: units.UnitSystem) -> list[Material]:
    """점 파일 한 장의 `conditions.materials` → 물성 목록.

    **조건이 없으면 빈 목록이다**(오류가 아니다) — 형상만 온 폴더도 있고, 그때는 사람이 화면
    에서 준 스펙을 쓴다. 조건이 있는데 값을 못 읽으면 **실패한다.**
    """
    rows = _rows(payload)
    made: list[Material] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        bodies = _bodies(row)
        name = _name(row)
        # **담아만 둔 재료는 건너뛴다** — CompCore 화면에서 목록에 넣었을 뿐 아직 어느 파트에도
        # 안 붙은 것이다(`apply_to: []`). 그것을 전체에 붙이면 사람이 안 고른 재료로 푼다.
        if row.get("apply_to") == []:
            continue
        made.append(_material(name, bodies, row, system))
    return made


def for_body(materials: list[Material], body: str) -> Material | None:
    """이 바디에 붙는 물성. 이름으로 붙은 것이 먼저, 없으면 「전체」.

    **둘 다 없으면 `None`** — 부르는 쪽이 사람이 준 스펙으로 갈지, 실패할지 정한다.
    """
    for one in materials:
        if body in one.bodies:
            return one
    return next((one for one in materials if one.every_body), None)


def body_names(payload: Any) -> list[str]:
    """점 파일의 `bodies[].name` — CAD 가 이름 붙인 파트들. 없으면 빈 목록."""
    rows = payload.get("bodies") if isinstance(payload, dict) else None
    names = [str(one.get("name") or "").strip() for one in rows or [] if isinstance(one, dict)]
    return [one for one in names if one]


def assigned(materials: list[Material], bodies: list[str]) -> dict[str, Material | None]:
    """파트마다 붙을 물성 — **모델링과 같은 규칙**(`mechanical/build.py` 의 `_apply_material`
    · `calculix/build.py` 의 `_materials`): 한 벌이면 「전체」 거나 파트가 하나일 때 모두에
    붙고, 그 밖에는 파트마다 `for_body` 로 찾는다. 못 찾으면 `None`."""
    if len(materials) == 1 and (materials[0].every_body or len(bodies) <= 1):
        return dict.fromkeys(bodies, materials[0])
    return {one: for_body(materials, one) for one in bodies}


def uncovered(materials: list[Material], bodies: list[str]) -> list[str]:
    """물성이 안 붙는 파트의 이름.

    모델링은 이런 파트를 만나면 멈춘다 — 그대로 풀면 솔버의 기본값(구조용 강)이 붙고, 그
    결과는 그럴듯하게 틀린다. 작업을 만들 때 미리 말해 주려고 여기 둔다.
    """
    return [name for name, one in assigned(materials, bodies).items() if one is None]


# --- 읽기 ---------------------------------------------------------------------


def _rows(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    conditions = payload.get("conditions")
    if not isinstance(conditions, dict):
        return []
    rows = conditions.get("materials")
    return rows if isinstance(rows, list) else []


def _name(row: dict[str, Any]) -> str:
    ref = _dict(row.get("ref"))
    source = _dict(row.get("payload"))
    for value in (ref.get("name"), source.get("record_name"), ref.get("code")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "이름 없는 물성"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bodies(row: dict[str, Any]) -> tuple[str, ...]:
    """`apply_to` — 목록이 정본이고 옛 값은 글자 하나다.

    `전체` 는 「모든 바디」 라는 뜻이라 빈 튜플로 바꾼다.
    """
    raw = row.get("apply_to")
    names = [raw] if isinstance(raw, str) else list(raw or [])
    picked = tuple(str(one).strip() for one in names if str(one).strip())
    return () if ALL_BODIES in picked else picked


def _material(
    name: str, bodies: tuple[str, ...], row: dict[str, Any], system: units.UnitSystem
) -> Material:
    converted = row.get("converted")
    if isinstance(converted, dict) and converted:
        return _from_converted(name, bodies, converted, system)
    source = row.get("payload")
    if isinstance(source, dict) and source:
        return _from_payload(name, bodies, source)
    raise MaterialProblem(
        name, "CAD 가 값을 보내지 않았습니다(payload · converted 둘 다 없음)"
    )


def _from_converted(
    name: str, bodies: tuple[str, ...], converted: dict[str, Any], system: units.UnitSystem
) -> Material:
    """CAD 가 그 계로 환산해 준 값 — **여기가 정본 경로다.**

    출처(등록 재료 · 문헌)가 달라도 `converted` 는 한 모양이다. 그러려고 CompCore 가 밀도 ·
    푸아송비를 목록에서 끌어올려 준다.
    """
    missing = converted.get("missing_structural")
    if missing:
        raise MaterialProblem(
            name,
            f"선형 탄성에 필요한 값이 빠졌습니다: {' · '.join(str(one) for one in missing)}",
        )
    # 선언한 계와 환산한 계가 다르면 값과 단위 선언이 어긋난 것이다 — 그대로 쓰면 어느 쪽이
    # 맞는지 알 수 없다.
    declared = str(converted.get("system") or "").strip()
    if declared and declared != system.key:
        raise MaterialProblem(
            name, f"환산된 계({declared})가 점 파일의 선언({system.key})과 다릅니다"
        )

    notes: list[str] = []
    unconverted = converted.get("unconverted")
    if unconverted:
        # **못 바꾼 항목은 원래 단위 그대로다.** 우리가 쓰는 셋은 아래에서 단위 이름으로 다시
        # 읽으니 안전하고(모르는 이름이면 거절), 나머지는 사람에게 전한다.
        notes.append(f"CAD 가 못 바꾼 항목: {' · '.join(str(one) for one in unconverted)}")

    modulus_pa, temperature = _modulus(name, converted, system)
    poisson = converted.get("poisson_ratio")
    if not isinstance(poisson, int | float):
        raise MaterialProblem(name, "푸아송비가 없습니다")
    density = converted.get("density")
    if not isinstance(density, int | float):
        raise MaterialProblem(name, "밀도가 없습니다")
    unit = converted.get("density_unit")
    if unit:
        try:
            density_kg_m3 = units.density_from(float(density), unit)
        except units.UnknownDensityUnit as failure:
            raise MaterialProblem(name, str(failure)) from failure
    else:
        # 2026-09-24 이전 폴더는 단위 이름 없이 값만 보냈다 — 선언된 계의 밀도로 본다.
        density_kg_m3 = float(density) * system.density_kg_m3

    tier = _tier(converted)
    if tier:
        notes.append(tier)
    return Material(
        name=name,
        bodies=bodies,
        youngs_modulus_pa=modulus_pa,
        poisson_ratio=float(poisson),
        density_kg_m3=density_kg_m3,
        source="converted",
        temperature_c=temperature,
        notes=tuple(notes),
    )


def _modulus(
    name: str, converted: dict[str, Any], system: units.UnitSystem
) -> tuple[float, float | None]:
    """탄성계수 → Pa, 그리고 고른 온도.

    **이름이 아니라 열쇠로 찾는다**(`mechanical.youngs_modulus`). 옛 폴더는 평평한
    `youngs_modulus` 칸에 담아 보냈다 — 그때는 단위 이름이 없어 선언된 계로 읽는다.
    """
    rows = converted.get("properties")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or row.get("key") != MODULUS_KEY:
                continue
            point = _nearest(row.get("points"))
            if point is None:
                continue
            try:
                value = units.stress_from(float(point["value"]), row.get("unit"))
            except units.UnknownStressUnit as failure:
                raise MaterialProblem(name, str(failure)) from failure
            temperature = point.get("temperature_C")
            return value, float(temperature) if isinstance(temperature, int | float) else None

    legacy = converted.get("youngs_modulus")
    if isinstance(legacy, int | float):
        # 2026-09-24 이전 폴더 — 값만 있고 단위 이름이 없다. 선언된 계의 응력 단위로 본다.
        return float(legacy) * system.stress_pa, None

    raise MaterialProblem(
        name,
        f"탄성계수를 찾지 못했습니다 — `{MODULUS_KEY}` 열쇠가 붙은 값이 없습니다"
        f"{_items(rows)}",
    )


def _items(rows: Any) -> str:
    """무슨 항목이 왔는지 — **표를 늘릴 근거는 이것뿐이다.**"""
    if not isinstance(rows, list):
        return ""
    names = [str(one.get("item")) for one in rows if isinstance(one, dict) and one.get("item")]
    return f" (온 항목: {' · '.join(names)})" if names else ""


def _nearest(points: Any) -> dict[str, Any] | None:
    """온도 표에서 기준 온도에 가장 가까운 점. 온도가 없는 점은 그대로 쓴다."""
    rows = [
        one
        for one in (points or [])
        if isinstance(one, dict) and isinstance(one.get("value"), int | float)
    ]
    if not rows:
        return None

    def distance(one: dict[str, Any]) -> float:
        temperature = one.get("temperature_C")
        if not isinstance(temperature, int | float):
            return 0.0
        return abs(float(temperature) - REFERENCE_C)

    return min(rows, key=distance)


def _tier(converted: dict[str, Any]) -> str:
    """문헌 값의 등급 — 값의 일부다. 사람이 「B 등급으로 돌았다」 를 알아야 한다."""
    rows = converted.get("properties")
    if not isinstance(rows, list):
        return ""
    tiers = {
        str(one.get("tier"))
        for one in rows
        if isinstance(one, dict) and one.get("key") == MODULUS_KEY and one.get("tier")
    }
    return f"문헌 값 등급 {' · '.join(sorted(tiers))}" if tiers else ""


def _from_payload(name: str, bodies: tuple[str, ...], source: dict[str, Any]) -> Material:
    """환산값이 없을 때의 대비 경로 — **원본에서 직접.**

    여기서는 값과 단위를 떼지 않는 것이 전부다: 밀도는 `density_si` 또는
    `density`+`density_unit`, 탄성계수는 `declared_properties[].si_unit` 이 붙은 SI 값.
    """
    modulus: float | None = None
    temperature: float | None = None
    for row in source.get("declared_properties") or []:
        if not isinstance(row, dict):
            continue
        points = [
            one
            for one in (row.get("points") or [])
            if isinstance(one, dict) and isinstance(one.get("value_si"), int | float)
        ]
        if not points or str(row.get("item") or "").strip() not in _MODULUS_ITEMS:
            continue
        point = min(
            points,
            key=lambda one: abs(float(one.get("temperature_C") or REFERENCE_C) - REFERENCE_C),
        )
        try:
            modulus = units.stress_from(float(point["value_si"]), row.get("si_unit"))
        except units.UnknownStressUnit as failure:
            raise MaterialProblem(name, str(failure)) from failure
        value = point.get("temperature_C")
        temperature = float(value) if isinstance(value, int | float) else None
        break
    if modulus is None:
        raise MaterialProblem(
            name,
            "원본에서 탄성계수를 찾지 못했습니다 — 아는 항목 이름: "
            f"{' · '.join(sorted(_MODULUS_ITEMS))}",
        )

    poisson = source.get("poisson_ratio")
    if not isinstance(poisson, int | float):
        raise MaterialProblem(name, "원본에 푸아송비가 없습니다")

    density = source.get("density_si")
    if isinstance(density, int | float):
        density_kg_m3 = float(density)
    elif isinstance(source.get("density"), int | float):
        try:
            density_kg_m3 = units.density_from(
                float(source["density"]), source.get("density_unit")
            )
        except units.UnknownDensityUnit as failure:
            raise MaterialProblem(name, str(failure)) from failure
    else:
        raise MaterialProblem(name, "원본에 밀도가 없습니다")

    return Material(
        name=name,
        bodies=bodies,
        youngs_modulus_pa=modulus,
        poisson_ratio=float(poisson),
        density_kg_m3=density_kg_m3,
        source="payload",
        temperature_c=temperature,
        notes=("CAD 의 환산값이 없어 원본에서 읽었습니다",),
    )


#: 원본에서 직접 읽을 때만 쓰는 항목 이름표. **여기 없으면 실패한다** — 짐작해서 고르면 값은
#: 나오고 그것이 영률이 아닐 수 있다. 정본 경로(`converted`)는 열쇠로 찾으므로 이 표가 없다.
_MODULUS_ITEMS: frozenset[str] = frozenset(
    {"탄성계수", "영률", "Young's modulus", "Youngs modulus", "E"}
)
