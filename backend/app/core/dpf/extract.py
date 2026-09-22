"""`.rst` → `result.json`.

## 반드시 함께 싣는 것

- **단위계**(`units`) — DPF 가 결과 파일에서 읽어 준다. 값만 보면 mm-t-s 와 MKS 가 구별되지
  않고, 그 차이는 고유진동수를 31.6배 틀리게 한다.
- **강체 모드 표시**(`rigid_body`) — 자유-자유는 앞 6개가 0 Hz 다. 표시하지 않으면 사람은
  「해석이 실패했다」 로 읽는다.

## 실측 (2026-09-20, 2025 R2)

`Model.metadata.time_freq_support.time_frequencies` 가 모드 주파수 전부를 Hz 로 준다. 판
100 x 60 x 5 에서 앞 6개가 ≈0, 7번째가 2583 Hz — `solve.out` 의 표와 같았다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.dpf import metrics, participation, shapes
from app.core.spec import RIGID_BODY_MODES, ModalSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"

#: 이보다 낮으면 강체 모드로 본다. 수치 오차 때문에 0 이 정확히 0 으로 안 나온다
#: (실측: 여섯 번째가 0.0023 Hz).
RIGID_BODY_HZ = 1.0


def extract(
    spec: ModalSpec,
    workdir: Path,
    *,
    result_name: str = "file.rst",
    solver_output: str = "solve.out",
    visual_modes: int = 6,
) -> StageResult:
    """고유진동수와 모드 형상을 읽어 `result.json` · `mode_NN.vtp` · `mode_NN.png` 를 쓴다.

    `visual_modes` 는 **탄성 모드 기준**이다. 강체 모드는 형상이 「통째로 움직이는 것」 이라
    그릴 값이 없고, 모드마다 파일 둘이 생기므로 전부 그리면 작업 폴더가 그만큼 커진다.
    """
    rst = workdir / result_name
    if not rst.is_file():
        raise StageFailure("solver_failed", f"결과 파일이 없습니다: {result_name}")

    frequencies, units, nodes, elements = _read(rst)
    if not frequencies:
        raise StageFailure("solver_failed", "결과 파일에 모드가 없습니다.")

    modes: list[dict[str, Any]] = []
    elastic_index = 0
    for index, value in enumerate(frequencies):
        rigid = spec.is_free_free and value < RIGID_BODY_HZ and index < RIGID_BODY_MODES
        if not rigid:
            elastic_index += 1
        modes.append(
            {
                "number": index + 1,
                "elastic_number": None if rigid else elastic_index,
                "frequency_hz": round(float(value), 4),
                "rigid_body": rigid,
            }
        )

    rigid_found = sum(1 for one in modes if one["rigid_body"])
    elastic = [one for one in modes if not one["rigid_body"]]

    # 참여계수는 **곁들이는 값이다.** 표가 없다고 다 끝난 해석을 실패로 적지 않는다.
    output = workdir / solver_output
    ratios = (
        participation.parse(output.read_text(encoding="utf-8", errors="replace"))
        if output.is_file()
        else {}
    )
    for one in modes:
        direction = participation.dominant(ratios, int(one["number"]))
        if direction is not None:
            one["dominant_direction"] = direction
            one["effective_mass_ratio"] = round(ratios[direction][int(one["number"])], 4)

    # **변위에서 읽는 지표는 모든 모드에 붙인다.** 그림(VTP · PNG)은 앞 몇 개만 만들지만,
    # 「이 모드가 어느 축으로 · 전체가 함께 움직이나」 는 표의 모든 줄이 필요로 한다 —
    # 자유-자유에서는 유효질량비가 0 이라 이것 말고는 모드를 설명할 말이 없다.
    _describe_modes(rst, modes)
    artifacts = _draw_modes(
        rst, workdir, [one["number"] for one in elastic[:visual_modes]], modes
    )
    result: dict[str, Any] = {
        "recipe": "modal",
        "boundary": "free-free" if spec.is_free_free else "constrained",
        "units": units,
        # 모드 형상의 크기는 질량 정규화된 값이다 — 절대 변위가 아니다. 3단계의 뷰어가 이 말을
        # 읽고 「배율」 을 말한다.
        "normalization": "mass",
        "rigid_body_modes": rigid_found,
        "mesh": {"nodes": nodes, "elements": elements},
        "modes": modes,
        # 화면이 「방향별로 얼마나 흔들리나」 를 그릴 수 있게 원본 표도 함께 싣는다.
        "participation": {name: value for name, value in ratios.items()},
    }
    if spec.is_free_free and rigid_found != RIGID_BODY_MODES:
        # **세어 보고 다르면 적어 둔다.** 다중 바디에서 접촉이 빠지면 강체 모드가 6개가 아니라
        # 12개(바디마다 6개)로 나온다 — 값은 그럴듯한데 모델이 붙어 있지 않은 상태다.
        result["warning"] = (
            f"자유-자유인데 강체 모드가 {rigid_found}개입니다(6개여야 합니다). "
            f"바디가 여럿이면 접촉이 잡히지 않았을 수 있습니다."
        )

    path = workdir / RESULT_NAME
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    first = elastic[0]["frequency_hz"] if elastic else None
    return StageResult(
        artifacts=[ArtifactSpec("result_json", path), *artifacts],
        summary={
            "modes": len(modes),
            "rigid_body_modes": rigid_found,
            "first_elastic_hz": first,
            "mode_shapes": sum(1 for one in artifacts if one.kind == "mode_vtp"),
        },
        detail=f"모드 {len(modes)}개" + (f" · 1차 탄성 {first} Hz" if first else ""),
    )


def _describe_modes(rst: Path, modes: list[dict[str, Any]]) -> None:
    """모드마다 축 비중 · 국부성을 붙인다.

    **실패해도 해석은 끝난 것이다** — 설명이 빠질 뿐 고유진동수는 이미 나왔다.
    """
    try:
        from ansys.dpf import core as dpf

        model = dpf.Model(str(rst))
        for one in modes:
            if one["rigid_body"]:
                # 강체 모드는 「통째로 움직이는 것」 이라 국부성이 뜻을 갖지 않는다. 표에서도
                # 접혀 있으므로 설명을 붙이지 않는다.
                continue
            field = model.results.displacement.on_time_scoping([int(one["number"])]).eval()[0]
            vectors = field.data
            share = metrics.direction_share(vectors)
            one["direction_share"] = share
            axis = metrics.dominant_axis(share)
            if axis is not None:
                one["dominant_axis"] = axis
            value = metrics.localization(vectors)
            one["localization"] = value
            one["local_mode"] = metrics.is_local(value)
    except Exception:
        logger.warning("모드 지표 계산 실패 — 주파수만 남깁니다", exc_info=True)


def _draw_modes(
    rst: Path, workdir: Path, numbers: list[Any], modes: list[dict[str, Any]]
) -> list[ArtifactSpec]:
    """모드 형상 파일들. **여기서 실패해도 해석은 끝난 것이다** — 고유진동수는 이미 나왔고,
    그림이 없다고 그 숫자를 버릴 이유가 없다. 대신 무엇이 없는지 로그에 남는다."""
    if not numbers:
        return []
    made: list[ArtifactSpec] = []
    try:
        from ansys.dpf import core as dpf

        model = dpf.Model(str(rst))
        skin = shapes.skin_of(model.metadata.meshed_region)
        by_number = {int(one["number"]): one for one in modes}
        for number in numbers:
            drawn = shapes.export_mode(model, skin, int(number), workdir)
            by_number[int(number)].update(
                {key: value for key, value in drawn.items() if key in ("vtp", "png")}
            )
            by_number[int(number)]["max_displacement"] = drawn["max_displacement"]
            made.append(ArtifactSpec("mode_vtp", workdir / drawn["vtp"]))
            if "png" in drawn:
                made.append(ArtifactSpec("mode_png", workdir / drawn["png"]))
    except Exception:
        logger.warning("모드 형상 생성 실패 — 고유진동수만 남깁니다", exc_info=True)
    return made


def _read(rst: Path) -> tuple[list[float], dict[str, str], int, int]:
    try:
        from ansys.dpf import core as dpf
    except ImportError as failure:
        raise StageFailure(
            "internal",
            "PyDPF 가 이 파이썬에 없습니다 — 워커 환경(SIMULATION_EXECUTOR)을 확인하세요.",
        ) from failure

    try:
        model = dpf.Model(str(rst))
        support = model.metadata.time_freq_support
        frequencies = [float(one) for one in support.time_frequencies.data]
        frequency_unit = str(support.time_frequencies.unit or "Hz")
        mesh = model.metadata.meshed_region
        nodes = int(mesh.nodes.n_nodes)
        elements = int(mesh.elements.n_elements)
        system = str(model.metadata.result_info.unit_system_name)
    except Exception as failure:
        raise StageFailure("internal", f"결과 파일을 읽지 못했습니다: {failure}") from failure

    return frequencies, {"frequency": frequency_unit, "system": system}, nodes, elements
