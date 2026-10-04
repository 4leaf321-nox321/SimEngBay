"""추출 단계 — CalculiX 의 `.dat` 에서 고유진동수를 읽는다.

**결과 모양은 Ansys 쪽과 같다**(`app/core/dpf/extract.py`). 화면 · 스터디 비교 · 모드 추적이 그
모양을 읽으므로, 솔버가 바뀌었다고 다른 모양을 내면 전부 손봐야 한다. 그래서 같은 열쇠를 쓴다 —
고유진동수 · **유효질량비**(`.dat` 의 유효모달질량 ÷ 전체 유효질량) · **모드 형상**(`.frd` 의
변위를 `.vtp` 로). **없는 것은 넣지 않는다**: 썸네일 PNG 는 안 만든다(pyvista 가 필요하고,
화면은 3D 뷰어로 본다). 비어 있는 것과 0 은 다르다.

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
from app.core.calculix.mesh import read_mesh
from app.core.spec import RIGID_BODY_MODES, ModalSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"
DATA_NAME = "model.dat"
BOUNDARY_NAME = "boundary.json"

#: 이보다 낮으면 강체 모드로 본다 — Ansys 쪽과 같은 문턱(수치 오차로 0 이 정확히 0 이 아니다).
RIGID_BODY_HZ = 1.0
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
        # **구속이 있으면 강체로 세지 않는다** — Ansys 쪽과 같은 규칙이다(`dpf/extract.py`).
        # 구속된 모델의 0 Hz 는 「강체」 가 아니라 **자유로 둔 방향**이고(원통 지지의 접선 등),
        # 그것은 아래에서 경고로 말한다. 두 솔버가 같은 표를 내야 설계점 비교가 성립한다.
        rigid = not constrained and value < RIGID_BODY_HZ and index <= RIGID_BODY_MODES
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

    shapes = _draw_modes(workdir, [one["number"] for one in elastic[:VISUAL_MODES]], modes)
    # **측정점은 모드 형상 위에서 읽는다** — 질량 정규화된 값이라 절대 크기가 아니고,
    # 「그 자리가 이 모드에서 움직이나」 를 보는 데 쓴다(센서를 그 자리에 붙인다). **탄성 모드
    # 전부**에서 읽는다: 실측 공진과 짝을 지을 때 「센서 자리에서 안 움직이는 모드는 실측에
    # 안 보인다」 가 첫 거름망이다.
    spots = _probe_modes(workdir, elastic)

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
    }
    loose = [
        one for one in modes if one["frequency_hz"] < RIGID_BODY_HZ and not one["rigid_body"]
    ]
    if constrained and loose:
        # **구속이 있는데 0 Hz 모드가 있다** — 어느 방향이 자유라는 뜻이다. 원통 지지의 접선
        # 처럼 일부러 열어 둔 것일 수 있으나, 구속을 잘못 걸어 통째로 떠 있는 경우도 똑같이
        # 보인다. 값만으로는 못 가르므로 **사람에게 묻는다.**
        result["warning"] = (
            f"구속이 있는데 {len(loose)}개 모드가 0 Hz 입니다 — 자유로 둔 방향(원통 지지의 "
            f"접선 등)이 있는지 보세요."
        )
    if not constrained and rigid_found != RIGID_BODY_MODES:
        # **세어 보고 다르면 적어 둔다.** 바디가 여럿인데 접합면이 안 붙었으면 강체 모드가
        # 바디마다 6개씩 나온다 — 값은 그럴듯한데 모델이 떨어져 있는 상태다.
        result["warning"] = (
            f"자유-자유인데 강체 모드가 {rigid_found}개입니다(6개여야 합니다). "
            f"맞닿은 면이 붙지 않았을 수 있습니다."
        )

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
        },
        detail=f"모드 {len(modes)}개" + (f" · 1차 탄성 {first} Hz" if first else ""),
    )


def _probe_modes(workdir: Path, wanted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """탄성 모드마다 **측정점**의 변위. 점 그룹이 없으면 빈 목록. 줄마다 `mode` 가 붙는다.

    모드 형상은 질량 정규화된 값이라 절대 크기가 아니다 — 그래서 단위를 `정규화` 로 적는다.
    「그 자리가 이 모드에서 움직이나」 가 이 값으로 답할 물음이다. 자리는 한 번만 찾는다.
    """
    topology = workdir / "topology.json"
    result = workdir / "model.frd"
    msh = workdir / "model.msh"
    if not wanted or not topology.is_file() or not result.is_file() or not msh.is_file():
        return []
    try:
        payload = json.loads(topology.read_text(encoding="utf-8"))
        # 쉘 파트의 측정점은 중간면 위의 점이다(지문의 `mid`).
        shells = condition_model.read(payload).shells
        payload = condition_model.shell_view(payload, set(shells)) if shells else payload
        if not probes.wanted(payload):
            return []
        mesh = read_mesh(msh)
        blocks = [one for one in frd_reader.read_folded(workdir, result) if one.kind == "DISP"]
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


def _draw_modes(workdir: Path, wanted: list[int], modes: list[dict[str, Any]]) -> list[str]:
    """고른 모드의 형상을 `.vtp` 로 쓴다. **못 만들면 그림만 없다** — 해석은 끝난 것이다.

    `.frd` 의 블록 순서가 모드 순서다. 표면 삼각형은 `.msh` 에서 다시 읽는다 — 모델링이 남긴
    파일이 정본이고, 그래야 이 단계를 따로 다시 돌릴 수 있다.
    """
    result = workdir / "model.frd"
    msh = workdir / "model.msh"
    if not wanted or not result.is_file() or not msh.is_file():
        return []
    try:
        mesh = read_mesh(msh)
        blocks = [one for one in frd_reader.read_folded(workdir, result) if one.kind == "DISP"]
    except Exception:  # pragma: no cover - 파일이 깨진 경우
        logger.warning("모드 형상을 못 읽었습니다 — 그림 없이 갑니다", exc_info=True)
        return []

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
            triangles=mesh.triangles,
            displacement=block.values,
            magnitude=magnitude,
        )
        made.append(name)
        for one in modes:
            if one["number"] == number:
                one["vtp"] = name
                one["max_displacement"] = round(max(magnitude.values(), default=0.0), 8)
                one["points"] = counts["points"]
    return made


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
