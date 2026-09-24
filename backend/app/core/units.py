"""단위계 — **선언을 읽고 거기에 맞춰 세션을 세운다.**

CAD(CompCore)는 점 파일에 `conditions.units` 로 **어느 계로 보냈는지 선언한다**(열쇠 이름은
MatNexus `/api/fitting/unit-systems` 와 같다). 그쪽 기본은 `mm_n_tonne` 이다 — mm 로 만든
형상에 mm 계가 맞으니 바꾸라고 할 이유가 없다.

## 왜 검사만으로는 안 되는가 (2026-09-24 결정)

전에는 활성 단위계가 `StandardMKS` 인지 **검사만** 했다. 그러면 「온 값이 무슨 단위인가」 는
아무도 안 본다 — `mm_n_tonne` 으로 온 206000(MPa)을 MKS 세션에 넣으면 206 kPa 가 되고,
**아무 오류 없이 고유진동수만 10³ 배 틀린다.** 그래서 둘을 함께 한다:

1. **선언을 읽는다** — `units.system`. 없으면 SI 로 본다(사람이 화면에서 준 스펙이 그렇다).
2. **그 계로 세션을 세운다** — mm 형상이면 mm 계로. 그러면 CAD 가 어느 계로 보내든 맞고,
   `converted` 값을 그대로 넣을 수 있다(그러려고 그쪽이 그 칸을 만들었다).

**모르는 선언은 거절한다.** 「아마 SI 겠지」 로 돌리면 그 추측이 틀렸을 때 나오는 것은 오류가
아니라 **그럴듯한 값**이다.

## 실측 (2026-09-24, 2025 R2 · Windows)

- `MechanicalUnitSystem` 에 `StandardNMMton`(mm · t · N) 이 있다. `StandardNMM` 은
  mm · **kg** · N 이라 일관계가 아니다 — 솔버가 쓰는 계는 따로 정해진다(바로 아래).
- **명령 조각의 숫자는 표시 단위계가 아니라 솔버 단위계로 읽힌다.** `.dat` 를 그 계로 쓰기
  때문이다. `AnalysisSettings.SolverUnits` 가 기본 `ActiveSystem` 이고, 그때
  `SolverUnitSystem` 은 표시계를 따라간다: `StandardMKS` → `ConsistentMKS`,
  `StandardNMMton` · `StandardNMM` → `ConsistentNMM`(mm · t · N → MPa · t/mm³).
- `body.Volume.Value` 는 **활성계**의 길이³ 로 온다(`StandardNMMton` 에서 113,395 mm³,
  `StandardMKS` 로 되돌리면 같은 형상이 1.134e-4 m³). 질량을 kg 로 내려면 그 계를 알아야 한다.
- `mm_n_tonne` 으로 세워 돌린 `.dat` 를 열어 보면 우리 조각(`MP,EX,matid,200000`)이
  **Mechanical 이 스스로 쓴 기본 물성 줄**(`MP,EX,1,200000 ! tonne s^-2 mm^-1` ·
  `MP,DENS,1,7.85e-09 ! tonne mm^-3`)과 같은 계다 — 조각이 솔버 단위계로 읽힌다는 증거다.
  같은 형상의 고유진동수도 MKS 로 돌린 것과 같았다(1,519.0 Hz · 질량 0.8902 kg).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: 점 파일에서 단위 선언이 있는 자리.
DECLARATION_PATH = "conditions.units.system"


@dataclass(frozen=True)
class UnitSystem:
    """단위계 하나 — **이름과 환산 계수를 한 자리에** 둔다.

    계수는 모두 「이 계의 단위 1 은 SI 로 얼마인가」 다. 곱하면 SI 가 되고 나누면 이 계가
    된다 — 방향을 헷갈리지 않게 한쪽으로만 적는다.
    """

    key: str
    """CAD · 물성 DB 가 쓰는 이름(`mm_n_tonne` · `si`)."""
    mechanical: str
    """Mechanical 의 표시 단위계 — `MechanicalUnitSystem` 의 멤버 이름."""
    solver: str
    """그 표시계에서 솔버가 쓰는 일관계 — `.dat` 의 숫자가 이 계로 읽힌다."""
    length_m: float
    """길이 1 = ? m"""
    stress_pa: float
    """응력 1 = ? Pa"""
    density_kg_m3: float
    """밀도 1 = ? kg/m³"""

    def stress(self, pascal: float) -> float:
        """Pa → 이 계의 응력."""
        return pascal / self.stress_pa

    def density(self, kg_m3: float) -> float:
        """kg/m³ → 이 계의 밀도."""
        return kg_m3 / self.density_kg_m3

    def volume_m3(self, volume: float) -> float:
        """이 계의 부피 → m³. 질량을 kg 로 내는 데 쓴다."""
        return volume * self.length_m**3


SI = UnitSystem(
    key="si",
    mechanical="StandardMKS",
    solver="ConsistentMKS",
    length_m=1.0,
    stress_pa=1.0,
    density_kg_m3=1.0,
)

MM_N_TONNE = UnitSystem(
    key="mm_n_tonne",
    mechanical="StandardNMMton",
    solver="ConsistentNMM",
    length_m=1e-3,
    stress_pa=1e6,  # MPa
    density_kg_m3=1e12,  # t/mm³ — 강 7850 kg/m³ = 7.85e-9
)

#: 우리가 세울 수 있는 계. **여기 없는 선언은 거절한다**(머리말).
KNOWN: dict[str, UnitSystem] = {one.key: one for one in (SI, MM_N_TONNE)}

#: 선언이 없을 때 쓰는 계. 사람이 화면에서 주는 스펙이 SI 계열이다(`youngs_modulus_gpa` ·
#: `density_kg_m3`) — 그 값은 이 모듈이 세우는 계로 환산해서 내보낸다.
DEFAULT = SI


class UnknownUnitSystem(ValueError):
    """모르는 단위계 선언. **추측하지 않는다** — 틀린 추측은 그럴듯한 값을 낸다."""

    def __init__(self, declared: str) -> None:
        self.declared = declared
        super().__init__(
            f"모르는 단위계 선언입니다: {declared!r} (아는 것: {' · '.join(sorted(KNOWN))})"
        )


def resolve(declared: str | None) -> UnitSystem:
    """선언 한 글자 → 단위계. 없으면 기본(SI), 모르는 것이면 거절."""
    if declared is None or not str(declared).strip():
        return DEFAULT
    key = str(declared).strip()
    system = KNOWN.get(key)
    if system is None:
        raise UnknownUnitSystem(key)
    return system


def declared_in(payload: Any) -> UnitSystem:
    """점 파일(`pNNNN.json`) 한 장의 선언을 읽는다 — `conditions.units.system`.

    조건이 아직 없는 폴더(형상만 온 옛 폴더)도 있어서 **없는 것은 오류가 아니다.** 있는데
    모르는 이름이면 거절한다 — 그때는 우리가 모르는 계로 보낸 것이고, 그 값을 아무 계에나
    넣으면 틀린 채로 돈다.
    """
    if not isinstance(payload, dict):
        return DEFAULT
    conditions = payload.get("conditions")
    if not isinstance(conditions, dict):
        return DEFAULT
    units = conditions.get("units")
    if not isinstance(units, dict):
        return DEFAULT
    return resolve(units.get("system"))
