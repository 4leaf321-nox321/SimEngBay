"""추출 단계 — CalculiX 의 `.dat` 에서 고유진동수를 읽는다.

**결과 모양은 Ansys 쪽과 같다**(`app/core/dpf/extract.py`). 화면 · 스터디 비교 · 모드 추적이 그
모양을 읽으므로, 솔버가 바뀌었다고 다른 모양을 내면 전부 손봐야 한다. 그래서 같은 열쇠를 쓴다 —
고유진동수 · **유효질량비**(`.dat` 의 유효모달질량 ÷ 전체 유효질량) · **모드 형상**(`.frd` 의
변위를 `.vtp` 로) · **모드 지문**(`signature` — 설계점 사이에서 같은 모드를 잇는다. 2026-10-24
전에는 Ansys 쪽에만 있어서 CalculiX DOE 의 「모드 지도」 가 비었다) · **성격**(변위 축 비중 ·
전역/국부 — 2026-10-25 까지 Ansys 에만). **없는 것은 넣지
않는다**: 썸네일 PNG 는 안 만든다(pyvista 가 필요하고, 화면은 3D 뷰어로 본다). 비어 있는 것과
0 은 다르다.

`result.json` 에 **어느 솔버로 풀었는지 도장을 찍는다.** 두 솔버의 수가 몇 % 갈리므로(실측
2026-10-02: 1차 1,266.4 대 1,263.5 Hz), 그 도장이 없으면 「어제와 값이 다르다」 가 영구
미해결로 남는다.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.core import conditions as condition_model
from app.core.calculix import frd as frd_reader
from app.core.calculix import probes, tables, vtp
from app.core.calculix.mesh import Mesh, read_mesh
from app.core.modes import metrics, signature
from app.core.modes import rigid as rigid_modes
from app.core.modes import search as mode_search
from app.core.numbers import significant
from app.core.spec import ModalSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"
DATA_NAME = "model.dat"
BOUNDARY_NAME = "boundary.json"

#: 모드 형상을 몇 개까지 그릴까 — Ansys 쪽 `visual_modes` 와 같은 뜻이다.
VISUAL_MODES = 6


def extract(spec: ModalSpec, workdir: Path, **_ignored: object) -> StageResult:
    """`model.dat` → `result.json`."""
    data = workdir / DATA_NAME
    if not data.is_file():
        raise StageFailure("solver_failed", f"결과 파일이 없습니다: {DATA_NAME}")

    report = data.read_text(encoding="utf-8", errors="replace")
    values = tables.frequencies(report)
    if not values:
        raise StageFailure(
            "solver_failed",
            f"{DATA_NAME} 에서 고유진동수를 못 읽었습니다 — 솔버 로그를 보세요.",
        )
    constrained, mesh = _declared(workdir)
    modes: list[dict[str, Any]] = []
    elastic_index = 0
    for index, value in enumerate(values, start=1):
        # **구속이 있어도 0 Hz 는 강체 모드다**(2026-11-16, `modes.rigid`) — 떠 있는 바디 ·
        # 열어 둔 방향 · 미끄럼 접촉의 움직임은 탄성 모드가 아니다. 전에는 구속이 있으면 세지
        # 않아 「1차 탄성 0 Hz」 가 나왔다. Ansys 쪽과 같은 규칙이다(`dpf/extract.py`).
        rigid = rigid_modes.is_rigid(value)
        if not rigid:
            elastic_index += 1
        modes.append(
            {
                "number": index,
                "elastic_number": None if rigid else elastic_index,
                "frequency_hz": round(value, 4),
                "rigid_body": rigid,
            }
        )
    rigid_found = sum(1 for one in modes if one["rigid_body"])
    elastic = [one for one in modes if not one["rigid_body"]]

    # **유효질량비는 곁들이는 값이다** — 표가 없다고 다 끝난 해석을 실패로 적지 않는다.
    ratios = tables.effective_mass_ratios(report)
    for one in modes:
        direction = tables.dominant(ratios, int(one["number"]))
        if direction is not None:
            one["dominant_direction"] = direction
            one["effective_mass_ratio"] = round(ratios[direction][int(one["number"])], 4)

    # 그림 · 지문 · 측정점이 **같은 메시와 변위를 읽는다** — `.frd` 는 수십 MB 라 한 번만.
    found = _read_shapes(workdir)
    # 강체 모드도 성격을 잰다 — 0 Hz 모드에서 **어느 바디가 움직이나**(`part_share`)가 경고의
    # 재료다. Ansys 쪽도 모든 모드를 잰다.
    _describe_modes(workdir, found, modes)
    # **구속이 있는데 0 Hz** — 열어 둔 방향일 수도, 떠 있는 바디일 수도 있다. 값만으로는 못
    # 가르므로 움직이는 바디와 그럴 만한 까닭(모델링이 남긴 연결)을 적어 **사람에게 묻는다.**
    # 자유-자유는 강체 모드가 6개가 아니면 — 바디가 떨어져 있으면 바디마다 6개씩 나온다.
    # **범위로 거르기 전에 본다** — 범위 아래의 0 Hz 도 모델의 문제다.
    said = rigid_modes.warning(
        modes,
        constrained=constrained,
        connections=rigid_modes.read_connections(workdir / BOUNDARY_NAME),
    )
    # **찾을 주파수 범위** — 범위 안만 남기고 탄성 차수를 그 안에서 다시 센다(`modes.search`).
    # 표 · 형상은 전체 차례(`number`)로 찾으므로 어긋나지 않는다.
    searched = mode_search.read(workdir / BOUNDARY_NAME)
    below = 0
    if searched is not None:
        modes, below = mode_search.kept(modes, searched)
        elastic = [one for one in modes if not one["rigid_body"]]
    shapes, parts = _draw_modes(
        workdir, found, [one["number"] for one in elastic[:VISUAL_MODES]], modes
    )
    # **측정점은 모드 형상 위에서 읽는다** — 질량 정규화된 값이라 절대 크기가 아니고,
    # 「그 자리가 이 모드에서 움직이나」 를 보는 데 쓴다(센서를 그 자리에 붙인다). **탄성 모드
    # 전부**에서 읽는다: 실측 공진과 짝을 지을 때 「센서 자리에서 안 움직이는 모드는 실측에
    # 안 보인다」 가 첫 거름망이다.
    spots = _probe_modes(workdir, found, elastic)

    result: dict[str, Any] = {
        "recipe": "modal",
        "solver": "calculix",
        "boundary": "constrained" if constrained else "free-free",
        # 덱을 mm · tonne · N 으로 쓰므로 주파수는 Hz 다(`calculix/deck.py`).
        "units": {"frequency": "Hz", "system": "ConsistentNMM"},
        "normalization": "mass",
        "rigid_body_modes": rigid_found,
        **({"mesh": mesh} if mesh else {}),
        "modes": modes,
        # 화면이 「방향별로 얼마나 흔들리나」 를 그릴 수 있게 원본 표도 함께 싣는다.
        **({"participation": ratios} if ratios else {}),
        **({"probes": spots} if spots else {}),
        # 그림의 셀 배열 `part` 번호의 이름 — 화면이 파트마다 보이고 숨긴다.
        **({"parts": parts} if parts else {}),
        **(_range_fields(searched, len(elastic), below, values) if searched else {}),
    }
    if said:
        result["warning"] = said

    path = workdir / RESULT_NAME
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    first = elastic[0]["frequency_hz"] if elastic else None
    return StageResult(
        artifacts=[
            ArtifactSpec("result_json", path),
            *(ArtifactSpec("mode_vtp", workdir / name) for name in shapes),
        ],
        summary={
            "solver": "calculix",
            "modes": len(modes),
            "rigid_body_modes": rigid_found,
            "first_elastic_hz": first,
            "mode_shapes": len(shapes),
            # 요약만 읽는 쪽(MCP · 목록)도 경고를 보게.
            **({"result_warning": said} if said else {}),
        },
        detail=f"모드 {len(modes)}개" + (f" · 1차 탄성 {first} Hz" if first else ""),
    )


def _range_fields(
    searched: mode_search.ModeSearch, found: int, below: int, solved: list[float]
) -> dict[str, Any]:
    """결과에 적는 범위 찾기 — 범위 · 누가 정했나 · 범위 아래에서 뺀 탄성 모드 수 · 모자랐을
    때의
    말(두 솔버 같은 열쇠 — `dpf/extract.py`)."""
    said = mode_search.note(searched, found, solved)
    return {
        "frequency_range_hz": [searched.low, searched.high],
        "range_from": searched.source,
        **({"modes_below_range": below} if below else {}),
        **({"range_note": said} if said else {}),
    }


def _read_shapes(workdir: Path) -> tuple[Mesh, list[frd_reader.Block]] | None:
    """메시와 모드마다의 변위(`.frd` 의 블록 순서가 모드 순서다). **못 읽으면 None** — 그림 ·
    지문 · 측정점만 없다, 해석은 끝난 것이다.

    표면 삼각형은 `.msh` 에서 다시 읽는다 — 모델링이 남긴 파일이 정본이고, 그래야 이 단계를
    따로 다시 돌릴 수 있다.
    """
    result = workdir / "model.frd"
    msh = workdir / "model.msh"
    if not result.is_file() or not msh.is_file():
        return None
    try:
        mesh = read_mesh(msh, require_solid=False)
        blocks = [one for one in frd_reader.read_folded(workdir, result) if one.kind == "DISP"]
    except Exception:  # pragma: no cover - 파일이 깨진 경우
        logger.warning("모드 형상을 못 읽었습니다 — 그림 · 지문 · 측정점 없이", exc_info=True)
        return None
    return mesh, blocks


#: 그 절점의 값이 없을 때 — 움직이지 않은 것으로 센다.
_STILL = [0.0, 0.0, 0.0]


def _volume_weights(mesh: Mesh, workdir: Path, ids: list[int]) -> dict[str, list[float]]:
    """절점마다 맡은 **부피**(mm³)를 파트마다 — 성격(`metrics.describe`)이 메시와 무관해지게.

    사면체는 꼭짓점 넷으로 잰 부피를 그 요소의 절점에 고르게 나눈다. 쉘은 중간면 삼각형의 넓이
    x 두께(모델링이 남긴 `boundary.json` 의 `shells.thickness` — 그 전 작업이면 접을 거리에서
    되짚는다). 파트 이름은 그림과 같다(`vtp.parted` — 바디는 `bodies`, 쉘은 `shells.parts`).
    """
    index = {node: at for at, node in enumerate(ids)}
    boundary: dict[str, Any] = {}
    path = workdir / BOUNDARY_NAME
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            boundary = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            logger.warning("%s 를 읽지 못했습니다 — 파트 이름 없이 잽니다", BOUNDARY_NAME)
    bodies = boundary.get("bodies")
    name_of = {
        int(entity): str(name)
        for name, entity in (bodies.items() if isinstance(bodies, dict) else [])
        if isinstance(entity, int)
    }
    found_shells = boundary.get("shells")
    shells: dict[str, Any] = found_shells if isinstance(found_shells, dict) else {}
    shell_names = {int(key): str(value) for key, value in (shells.get("parts") or {}).items()}
    thickness = shells.get("thickness") or {}
    reach = shells.get("reach")
    # 두께를 안 남긴 옛 작업 — 접을 거리는 가장 두꺼운 쉘의 0.55 배다(`build`).
    guessed = float(reach) / 0.55 if reach else 0.0
    parts: dict[str, list[float]] = {}

    def add(name: str, nodes: list[int], amount: float) -> None:
        if amount <= 0 or not nodes:
            return
        row = parts.setdefault(name, [0.0] * len(ids))
        share = amount / len(nodes)
        for node in nodes:
            at = index.get(node)
            if at is not None:
                row[at] += share

    for entity, rows in mesh.solids.items():
        name = name_of.get(entity, f"solid{entity}")
        for _, nodes in rows:
            a, b, c, d = (mesh.nodes[one] for one in nodes[:4])
            add(name, nodes, abs(_triple(_minus(b, a), _minus(c, a), _minus(d, a))) / 6.0)
    for surface in sorted(int(one) for one in shells.get("surfaces") or []):
        name = shell_names.get(surface, f"쉘 {surface}")
        depth = float(thickness.get(name) or guessed)
        for triangle in mesh.face_triangles.get(surface, []):
            a, b, c = (mesh.nodes[one] for one in triangle)
            cross = _cross(_minus(b, a), _minus(c, a))
            add(name, list(triangle), 0.5 * sum(one * one for one in cross) ** 0.5 * depth)
    return parts


def _minus(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _triple(a: tuple[float, ...], b: tuple[float, ...], c: tuple[float, ...]) -> float:
    cross = _cross(b, c)
    return a[0] * cross[0] + a[1] * cross[1] + a[2] * cross[2]


def _describe_modes(
    workdir: Path,
    found: tuple[Mesh, list[frd_reader.Block]] | None,
    wanted: list[dict[str, Any]],
) -> None:
    """탄성 모드마다 **성격과 지문**을 붙인다 — Ansys 쪽(`dpf/extract._describe_modes`)과 같은
    열쇠 · 같은 셈(`core/modes`).

    - `direction_share` · `dominant_axis` — 변위가 주로 어느 축인가(비율이라 정규화와 무관).
    - `localization` · `local_mode` — 전체가 함께 움직이나, 한 구석만 떠는가(부피 가중 참여비).
      전에는 CalculiX 결과의 「성격」 칸이 늘 비었다(2026-10-25).
    - `part_share` · `dominant_part` — 바디가 둘 이상이면 어느 파트가 움직이나(국부 · 전역은 그
      파트 안에서).
    - `signature` — 설계점 사이에서 같은 모드를 잇는 열쇠. 칸마다 가까운 절점은 메시 하나에 한
      번만 찾는다.

    **못 셈하면 그 값만 없다** — 화면이 「—」 로 두고, 해석은 끝난 것이다.
    """
    if found is None or not wanted:
        return
    mesh, blocks = found
    # 변위가 있는 절점만 — 쉘을 접고 나면 펼쳤던 절점은 빠진다(`frd.fold_shells`).
    ids = [node for node in mesh.nodes if blocks and node in blocks[0].values]
    if not ids:
        return
    try:
        spots = [ids[index] for index in signature.anchors([mesh.nodes[node] for node in ids])]
    except Exception:  # pragma: no cover - 좌표가 깨진 경우
        logger.warning("모드 지문 자리를 못 찾았습니다 — 지문 없이 갑니다", exc_info=True)
        spots = []
    try:
        parts: dict[str, list[float]] | None = _volume_weights(mesh, workdir, ids) or None
    except Exception:  # pragma: no cover - 메시가 깨진 경우
        logger.warning("절점의 부피를 못 쟀습니다 — 절점 수로 셉니다", exc_info=True)
        parts = None
    weights = [sum(column) for column in zip(*parts.values(), strict=True)] if parts else None
    for mode in wanted:
        number = int(mode["number"])
        if number > len(blocks):
            continue
        rows = blocks[number - 1].values
        try:
            vectors = [rows.get(node, _STILL)[:3] for node in ids]
            mode.update(metrics.describe(vectors, weights, parts))
            if spots:
                picked = (rows.get(node, _STILL) for node in spots)
                mode["signature"] = signature.fingerprint(picked)
        except Exception:  # pragma: no cover - 값이 깨진 경우
            logger.warning("모드 %s 의 성격을 못 셈했습니다", number, exc_info=True)


def _probe_modes(
    workdir: Path,
    found: tuple[Mesh, list[frd_reader.Block]] | None,
    wanted: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """탄성 모드마다 **측정점**의 변위. 점 그룹이 없으면 빈 목록. 줄마다 `mode` 가 붙는다.

    모드 형상은 질량 정규화된 값이라 절대 크기가 아니다 — 그래서 단위를 `정규화` 로 적는다.
    「그 자리가 이 모드에서 움직이나」 가 이 값으로 답할 물음이다. 자리는 한 번만 찾는다.
    """
    topology = workdir / "topology.json"
    if not wanted or found is None or not topology.is_file():
        return []
    mesh, blocks = found
    try:
        payload = json.loads(topology.read_text(encoding="utf-8"))
        # 쉘 파트의 측정점은 중간면 위의 점이다(지문의 `mid`).
        shells = condition_model.read(payload).shells
        payload = condition_model.shell_view(payload, set(shells)) if shells else payload
        if not probes.wanted(payload):
            return []
    except Exception:  # pragma: no cover - 파일이 깨진 경우
        logger.warning("측정점을 못 읽었습니다 — 없이 갑니다", exc_info=True)
        return []
    spots = probes.locate(
        payload, mesh.nodes, body_nodes=probes.body_nodes(workdir, mesh.solids)
    )
    made: list[dict[str, Any]] = []
    for mode in wanted:
        number = int(mode["number"])
        if number > len(blocks):
            continue
        block = blocks[number - 1]
        for one in probes.rows(
            spots,
            frd_reader.magnitudes(block),
            unit="정규화",
            vectors={node: values[:3] for node, values in block.values.items()},
        ):
            one["mode"] = number
            made.append(one)
    return made


def _draw_modes(
    workdir: Path,
    found: tuple[Mesh, list[frd_reader.Block]] | None,
    wanted: list[int],
    modes: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """고른 모드의 형상을 `.vtp` 로 쓴다 — (파일 이름들, 파트 이름들). **못 만들면 그림만
    없다** — 해석은 끝난 것이다. 파트는 모드마다 같다(`vtp.parted`).
    """
    if not wanted or found is None:
        return [], []
    mesh, blocks = found
    try:
        triangles, parts, names = vtp.parted(mesh, workdir)
    except Exception:  # pragma: no cover - 나누기만 못 한다
        logger.warning("그림을 파트로 못 나눴습니다 — 나누지 않고 그립니다", exc_info=True)
        triangles, parts, names = list(mesh.triangles), None, []

    by_mode = {index: block for index, block in enumerate(blocks, start=1)}
    made: list[str] = []
    for number in wanted:
        block = by_mode.get(number)
        if block is None:
            continue
        magnitude = frd_reader.magnitudes(block)
        name = f"mode_{number:02d}.vtp"
        counts = vtp.write(
            workdir / name,
            nodes=mesh.nodes,
            triangles=triangles,
            displacement=block.values,
            magnitude=magnitude,
            parts=parts,
        )
        made.append(name)
        for one in modes:
            if one["number"] == number:
                one["vtp"] = name
                one["max_displacement"] = significant(max(magnitude.values(), default=0.0))
                one["points"] = counts["points"]
    return made, (names if made else [])


def _declared(workdir: Path) -> tuple[bool, dict[str, int]]:
    """모델링이 남긴 것 — 구속 여부와 메시 크기. **없으면 비워 둔다**(지어내지 않는다)."""
    path = workdir / BOUNDARY_NAME
    constrained = True
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            constrained = bool(loaded.get("constrained", True))
        except (OSError, ValueError):
            logger.warning("%s 를 읽지 못했습니다", BOUNDARY_NAME)
    mesh: dict[str, int] = {}
    msh = workdir / "model.msh"
    if msh.is_file():
        counts = msh.read_text(encoding="utf-8", errors="replace")
        nodes = re.search(r"\$Nodes\s*\n\s*(\d+)", counts)
        elements = re.search(r"\$Elements\s*\n\s*(\d+)", counts)
        if nodes:
            mesh["nodes"] = int(nodes.group(1))
        if elements:
            mesh["elements"] = int(elements.group(1))
    return constrained, mesh
