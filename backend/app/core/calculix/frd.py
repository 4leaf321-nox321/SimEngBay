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


# --- 쉘 접기 ---------------------------------------------------------------------


def read_folded(workdir: Path, path: Path) -> list[Block]:
    """`read` 에 **쉘 접기**를 얹은 것 — 쉘이 없으면 `read` 와 같다.

    모델링이 `boundary.json` 의 `shells`(중간면의 면 번호 · 접을 거리)를 남긴다. 그 면의
    절점이 원래 쉘 절점이다(`model.msh`).
    """
    from app.core import boundary
    from app.core.calculix.mesh import read_mesh

    blocks = read(path)
    info = boundary.read(workdir).get("shells")
    msh = workdir / "model.msh"
    if not isinstance(info, dict) or not msh.is_file():
        return blocks
    mesh = read_mesh(
        msh,
        require_solid=False,
        shell_surfaces=frozenset(int(one) for one in info["surfaces"]),
    )
    shell_nodes = {
        node: mesh.nodes[node]
        for rows in mesh.shells.values()
        for _, ids in rows
        for node in ids
    }
    return fold_shells(
        blocks, read_nodes(path), shell_nodes, set(mesh.nodes), float(info["reach"])
    )


def read_nodes(path: Path) -> dict[int, tuple[float, float, float]]:
    """`.frd` 의 절점 좌표(`2C` 블록). 쉘을 펼친 절점의 자리를 알 때 쓴다."""
    found: dict[int, tuple[float, float, float]] = {}
    inside = False
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("    2C"):
                inside = True
                continue
            if not inside:
                continue
            if line.startswith(" -3"):
                break
            if line.startswith(" -1"):
                numbers = _numbers(line[_NODE_END:])
                if len(numbers) >= 3:
                    found[int(line[3:_NODE_END])] = (numbers[0], numbers[1], numbers[2])
    return found


def fold_shells(
    blocks: list[Block],
    coordinates: dict[int, tuple[float, float, float]],
    shell_nodes: dict[int, tuple[float, float, float]],
    keep: set[int],
    reach: float,
) -> list[Block]:
    """CalculiX 가 **두께 방향으로 펼친** 쉘 결과를 원래 쉘 절점으로 접는다.

    ccx 는 쉘 요소를 두께 방향 입체로 펼쳐 풀고(`OUTPUT=3D`), 결과를 펼친 절점(새 번호)에
    낸다. 그대로면 우리 메시의 쉘 절점에는 값이 없어 측정점 · 변형 그림이 빈다. 그래서 쉘 절점
    마다 **두께의 절반 안**에 있는 펼친 절점을 모아 — 변위는 평균(중간면), 응력 · 변형률은
    상당응력이 큰 쪽(겉면 — 굽힘이 실리는 자리)의 값을 싣는다. `OUTPUT=2D` 로 내면 응력이
    중간면 값이라 굽힘이 빠졌다(실측 2026-10-04: 29.7 MPa · 겉면 91.1 MPa).

    `keep` 은 우리 메시의 절점이다 — 그 밖(펼친 절점 · 강체 기준점)은 결과에서 뺀다.
    """
    if not shell_nodes:
        return blocks
    spread = [
        (node, place)
        for node, place in coordinates.items()
        if node not in keep and node not in shell_nodes
    ]
    cell = max(reach, 1e-9)
    grid: dict[tuple[int, int, int], list[tuple[int, tuple[float, float, float]]]] = {}
    for node, place in spread:
        key = tuple(int(place[axis] // cell) for axis in range(3))
        grid.setdefault(key, []).append((node, place))  # type: ignore[arg-type]
    near: dict[int, list[int]] = {}
    for node, place in shell_nodes.items():
        base = [int(place[axis] // cell) for axis in range(3)]
        hits: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for other, where in grid.get(
                        (base[0] + dx, base[1] + dy, base[2] + dz), []
                    ):
                        if (
                            sum((where[axis] - place[axis]) ** 2 for axis in range(3))
                            <= reach**2
                        ):
                            hits.append(other)
        near[node] = hits

    # 겉면은 **응력 블록에서** 고른다 — 같은 단계의 변형률 · 오차도 그 절점을 쓴다(따로 고르면
    # 겉면 둘이 섞인다).
    picks: dict[tuple[int, float], dict[int, int]] = {}
    for block in blocks:
        if block.kind != "STRESS":
            continue
        chosen: dict[int, int] = {}
        for node, hits in near.items():
            present = [one for one in hits if one in block.values]
            if present:
                chosen[node] = max(present, key=lambda one: _tensor_size(block.values[one]))
        picks[(block.step, block.value)] = chosen

    folded: list[Block] = []
    for block in blocks:
        values = {node: row for node, row in block.values.items() if node in keep}
        pick = picks.get((block.step, block.value), {})
        for node, hits in near.items():
            if block.kind in ("STRESS", "TOSTRAIN", "ERROR"):
                one = pick.get(node)
                if one is not None and one in block.values:
                    values[node] = block.values[one]
                continue
            rows = [block.values[one] for one in hits if one in block.values]
            if rows:
                width = min(len(row) for row in rows)
                values[node] = [
                    sum(row[index] for row in rows) / len(rows) for index in range(width)
                ]
        folded.append(
            Block(kind=block.kind, value=block.value, step=block.step, values=values)
        )
    return folded


def _tensor_size(row: list[float]) -> float:
    """겉면을 고르는 잣대 — 상당 크기(6성분이면 폰 미세스 꼴, 아니면 첫 값)."""
    if len(row) >= 6:
        xx, yy, zz, xy, yz, zx = row[:6]
        return 0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2) + 3 * (
            xy**2 + yz**2 + zx**2
        )
    return abs(row[0]) if row else 0.0
