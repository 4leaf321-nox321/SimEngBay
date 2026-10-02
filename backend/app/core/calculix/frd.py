"""`.frd` 를 읽는다 — 절점 결과(변위 · 응력).

## 고정 폭이다

값이 **붙어 나온다**(실측 2026-10-02):

     -1         4-6.84401E-04 7.13110E-04-4.50377E-04

`split()` 으로 끊으면 `4-6.84401E-04` 가 한 덩어리가 되어 조용히 틀린 값이 나온다. 그래서 **칸
위치로** 자른다: 절점 번호는 3~13, 값은 그 뒤로 12칸씩. 여섯 칸을 넘으면 ` -2` 줄로 이어진다.

## 블록 머리

      100CL  101 1263.490689        6401                     2    1MODAL      1
     -4  DISP        4    1

`100CL` 줄의 둘째 수가 **그 블록의 값**이다 — 모달이면 주파수(Hz), 정적이면 시간,
조화면 주파수.
`-4` 줄이 결과 종류(`DISP` · `STRESS` …)와 성분 수를 말한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: 값 한 칸의 폭과 절점 번호가 끝나는 자리.
_NODE_END = 13
_WIDTH = 12


@dataclass(frozen=True)
class Block:
    """결과 한 벌 — 무엇을(`kind`) 언제(`value`) 어느 절점에서."""

    kind: str
    value: float
    step: int
    values: dict[int, list[float]]


def read(path: Path) -> list[Block]:
    """`.frd` 의 결과 블록 전부. 큰 파일이라 한 줄씩 훑는다."""
    blocks: list[Block] = []
    kind = ""
    value = 0.0
    step = 0
    rows: dict[int, list[float]] = {}
    last: int | None = None

    def close() -> None:
        if kind and rows:
            blocks.append(Block(kind=kind, value=value, step=step, values=dict(rows)))

    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("  100CL"):
                close()
                kind, rows, last = "", {}, None
                parts = line.split()
                # `100CL  101 1263.490689  6401 ... 1MODAL 1` — 둘째 수가 값, 넷째가 절점 수.
                value = float(parts[2]) if len(parts) > 2 else 0.0
                step = _step_of(line)
                continue
            if line.startswith(" -4"):
                kind = line.split()[1] if len(line.split()) > 1 else ""
                continue
            if line.startswith(" -1"):
                node = int(line[3:_NODE_END])
                rows[node] = _numbers(line[_NODE_END:])
                last = node
                continue
            if line.startswith(" -2") and last is not None:
                # 이어지는 줄 — 같은 절점의 나머지 성분.
                rows[last].extend(_numbers(line[_NODE_END:]))
                continue
            if line.startswith(" -3"):
                close()
                kind, rows, last = "", {}, None
    close()
    return blocks


def _numbers(tail: str) -> list[float]:
    """12칸씩 끊어 읽는다 — 붙어 나오는 음수를 가르는 유일한 방법이다."""
    found: list[float] = []
    for start in range(0, len(tail.rstrip("\n")), _WIDTH):
        chunk = tail[start : start + _WIDTH].strip()
        if not chunk:
            continue
        try:
            found.append(float(chunk))
        except ValueError:
            # 숫자가 아닌 꼬리(이름표 등)는 버린다 — 값이 아닌 것을 0 으로 적지 않는다.
            continue
    return found


def _step_of(line: str) -> int:
    """`…    1MODAL      1` 에서 단계 번호. 못 읽으면 0 — 쓰는 쪽이 순서로 센다."""
    marked = line.rstrip()
    for name in ("MODAL", "STATIC", "STEADY STATE DYNAMICS", "FREQUENCY"):
        at = marked.find(name)
        if at > 0:
            head = marked[:at].split()
            if head and head[-1].isdigit():
                return int(head[-1])
    return 0


def magnitudes(block: Block) -> dict[int, float]:
    """절점마다 벡터 크기 — 변위 블록에 쓴다(성분 넷째 `ALL` 은 CalculiX 가 이미 크기로 준다).

    그래도 **셋으로 다시 센다**: `ALL` 성분이 없는 판도 있고, 있어도 그것을 믿고 읽으면 성분
    순서가 바뀐 판에서 조용히 틀린다.
    """
    found: dict[int, float] = {}
    for node, values in block.values.items():
        if len(values) < 3:
            continue
        found[node] = (values[0] ** 2 + values[1] ** 2 + values[2] ** 2) ** 0.5
    return found


def von_mises(block: Block) -> dict[int, float]:
    """응력 블록에서 절점마다 상당응력.

    CalculiX 의 성분 순서는 `SXX SYY SZZ SXY SYZ SZX` 다(실측). 순서를 틀리면 오류가 아니라
    **그럴듯한 응력**이 나온다.
    """
    found: dict[int, float] = {}
    for node, values in block.values.items():
        if len(values) < 6:
            continue
        xx, yy, zz, xy, yz, zx = values[:6]
        found[node] = (
            0.5
            * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2 + 6 * (xy**2 + yz**2 + zx**2))
        ) ** 0.5
    return found
