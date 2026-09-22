"""`solve.out` 의 참여계수 표를 읽는다 — **DPF 가 안 주는 값이라 텍스트를 읽는다.**

모드마다 「어느 방향으로 얼마나 흔들리는가」 를 말해 주는 유효질량비가 여기 있다. 고유진동수만
보면 2583 Hz 가 굽힘인지 비틀림인지 알 수 없는데, 이 표의 X · Y · Z 비율이 그것을 가른다 —
그리고 **가진 방향으로 유효질량이 0 인 모드는 그 시험에서 안 흔들린다.**

MAPDL 이 찍는 모양(실측 2026-09-20):

    ***** PARTICIPATION FACTOR CALCULATION *****  X  DIRECTION
                                                          CUMULATIVE     RATIO EFF.MASS
    MODE FREQUENCY PERIOD PARTIC.FACTOR RATIO EFFECTIVE MASS MASS FRACTION TO TOTAL MASS
       1  0.00000  0.0000  0.62633E-02  1.000000  0.392295E-04  0.551437     0.551437

방향은 X · Y · Z · ROTX · ROTY · ROTZ 여섯이다. **표가 없어도 실패하지 않는다** — 참여계수는
곁들이는 값이고, 그것 때문에 다 끝난 해석을 실패로 적을 이유가 없다.
"""

from __future__ import annotations

import re

#: 표의 시작. 방향 이름이 `*****` 바로 뒤에 붙어 나오기도 한다(ROTX — 실측).
_HEADER = re.compile(r"PARTICIPATION FACTOR CALCULATION\s*\*+\s*(\w+)\s+DIRECTION")

#: 표의 한 줄. 모드 번호 + 숫자 일곱. 마지막이 「전체 질량 대비 유효질량비」 다.
_ROW = re.compile(
    r"^\s*(\d+)\s+" + r"\s+".join([r"([-+]?[\d.]+(?:[eE][-+]?\d+)?)"] * 7) + r"\s*$"
)


#: 표의 끝. 이 줄을 보기 전까지는 표 안이다 — **표 제목과 첫 줄 사이에 글자 줄이 둘 있어서**,
#: 「숫자 줄이 아니면 표가 끝났다」 로 읽으면 표를 시작하자마자 놓친다(실측으로 겪었다).
_END = "---"


def parse(text: str) -> dict[str, dict[int, float]]:
    """`{방향: {모드 번호: 유효질량비}}`. 못 읽으면 빈 dict — 예외를 던지지 않는다."""
    found: dict[str, dict[int, float]] = {}
    direction: str | None = None
    for line in text.splitlines():
        header = _HEADER.search(line)
        if header:
            direction = header.group(1).upper()
            found.setdefault(direction, {})
            continue
        if direction is None:
            continue
        if line.strip().startswith(_END):
            # 표가 끝났다. 다음 헤더를 만날 때까지 안 읽는다 — 표 밖에도 숫자 여덟 개짜리
            # 줄이 있고, 그것을 모드로 읽으면 없는 방향이 생긴다.
            direction = None
            continue
        row = _ROW.match(line)
        if row is None:
            continue
        found[direction][int(row.group(1))] = float(row.group(8))
    return {name: modes for name, modes in found.items() if modes}


def dominant(
    ratios: dict[str, dict[int, float]], mode: int, *, floor: float = 0.01
) -> str | None:
    """이 모드가 가장 크게 흔들리는 방향. 전부 작으면 None — **없는 것을 만들어 내지 않는다.**

    강체 모드나 국부 모드는 어느 방향으로도 유효질량이 거의 없다. 그때 「X」 라고 적으면
    사람은 그 방향으로 가진하면 울릴 것이라고 읽는다.
    """
    best: tuple[float, str] | None = None
    for direction, modes in ratios.items():
        value = modes.get(mode)
        if value is None:
            continue
        if best is None or value > best[0]:
            best = (value, direction)
    if best is None or best[0] < floor:
        return None
    return best[1]
