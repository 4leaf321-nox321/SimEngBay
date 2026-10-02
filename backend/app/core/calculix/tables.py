"""`.dat` 의 표들을 읽는다 — 고유진동수 · **유효질량비.**

CalculiX 는 `*FREQUENCY` 단계에서 세 표를 찍는다(실측 2026-10-02):

    E I G E N V A L U E   O U T P U T        모드 / 고유치 / rad·s⁻¹ / Hz / 허수부
    P A R T I C I P A T I O N   F A C T O R S   모드마다 방향 여섯
    E F F E C T I V E   M O D A L   M A S S     모드마다 방향 여섯 + TOTAL 줄
    T O T A L   E F F E C T I V E   M A S S     방향마다 전체 질량 한 줄

**유효질량비는 「유효모달질량 ÷ 전체 유효질량」** 이다 — Ansys 가
`RATIO EFF.MASS TO TOTAL MASS`
로 찍는 값과 같은 뜻이라, 화면이 두 솔버의 결과를 같은 그림으로 그릴 수 있다. 참여계수 자체는
정규화 방식에 따라 크기가 달라져 견주기 어렵다 — 그래서 **비율**을 쓴다.

**표가 없어도 실패하지 않는다.** 참여계수는 곁들이는 값이고, 그것 때문에 다 끝난 해석을 실패로
적을 이유가 없다(Ansys 쪽과 같은 규칙).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

EIGEN_HEAD = "E I G E N V A L U E   O U T P U T"
MODAL_MASS_HEAD = "E F F E C T I V E   M O D A L   M A S S"
TOTAL_MASS_HEAD = "T O T A L   E F F E C T I V E   M A S S"

#: 방향 이름 — Ansys 쪽 표기와 맞춘다(화면이 같은 열쇠를 읽는다).
DIRECTIONS = ("X", "Y", "Z", "ROTX", "ROTY", "ROTZ")

#: 모드 한 줄: 번호 + 숫자 여섯. 고유치 표는 숫자 넷(+허수부)이라 따로 읽는다.
_MODE_ROW = re.compile(r"^\s*(\d+)\s+((?:[-+]?[\d.]+E[-+]?\d+\s*){6})$")
#: 고유치 표의 한 줄 — 네 번째 칸이 Hz 다. **칸 수를 못 박지 않는다**(허수부가 붙는다).
_EIGEN_ROW = re.compile(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+\S+)*\s*$")


def frequencies(text: str) -> list[float]:
    """고유진동수(Hz) 목록. 표 뒤에 참여계수 표가 이어지므로 **빈 줄에서 끊는다.**"""
    head = text.find(EIGEN_HEAD)
    if head < 0:
        return []
    found: list[float] = []
    started = False
    for line in text[head + len(EIGEN_HEAD) :].splitlines():
        row = _EIGEN_ROW.match(line)
        if row:
            started = True
            found.append(float(row.group(4)))
            continue
        if started and not line.strip():
            break
    return found


def effective_mass_ratios(text: str) -> dict[str, dict[int, float]]:
    """`{방향: {모드: 유효질량비}}`. 표가 없거나 전체 질량이 0 이면 **빈 것을 준다.**"""
    modal = _rows(text, MODAL_MASS_HEAD)
    total = _totals(text)
    if not modal or not total:
        return {}
    ratios: dict[str, dict[int, float]] = {}
    for index, name in enumerate(DIRECTIONS):
        whole = total[index] if index < len(total) else 0.0
        if whole <= 0:
            continue
        ratios[name] = {
            mode: round(values[index] / whole, 6)
            for mode, values in modal.items()
            if index < len(values)
        }
    return ratios


def _rows(text: str, head: str) -> dict[int, list[float]]:
    """머리말 아래의 `모드 번호 + 숫자 여섯` 줄들. `TOTAL` 줄은 번호가 없어 저절로 빠진다."""
    start = text.find(head)
    if start < 0:
        return {}
    found: dict[int, list[float]] = {}
    started = False
    for line in text[start + len(head) :].splitlines():
        row = _MODE_ROW.match(line)
        if row:
            started = True
            found[int(row.group(1))] = [float(one) for one in row.group(2).split()]
            continue
        if started and not line.strip():
            break
    return found


def _totals(text: str) -> list[float]:
    """`T O T A L   E F F E C T I V E   M A S S` 의 숫자 여섯 — 방향마다 전체 질량.

    그 표에는 모드 번호가 없다(한 줄에 숫자 여섯만 온다).
    """
    start = text.find(TOTAL_MASS_HEAD)
    if start < 0:
        return []
    for line in text[start + len(TOTAL_MASS_HEAD) :].splitlines():
        parts = line.split()
        if len(parts) == len(DIRECTIONS) and all(_number(one) for one in parts):
            return [float(one) for one in parts]
    return []


def _number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def dominant(
    ratios: dict[str, dict[int, float]], mode: int, *, floor: float = 0.01
) -> str | None:
    """그 모드가 **주로 어느 방향으로** 흔들리나. 전부 작으면 `None`.

    구속이 없으면(자유-자유) 강체 모드가 질량을 전부 가져가서 탄성 모드의 비가 0 이다 — 그때는
    없는 값을 지어내지 않고 비워 둔다(Ansys 쪽과 같은 규칙).
    """
    best: tuple[float, str] | None = None
    for name, values in ratios.items():
        value = values.get(mode, 0.0)
        if value >= floor and (best is None or value > best[0]):
            best = (value, name)
    return best[1] if best else None
