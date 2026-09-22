"""해석 코어 — 스펙 검증과 가짜 실행기. **DB 도 서버도 없이 돈다.**"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core import executors
from app.core.executors.fake import write_fixture_step
from app.core.spec import RIGID_BODY_MODES, ModalSpec, parse_spec
from app.core.stages import STAGES, StageContext, StageFailure

MATERIAL = {
    "name": "SS400",
    "youngs_modulus_gpa": 200,
    "poisson_ratio": 0.3,
    "density_kg_m3": 7850,
}


def test_스펙은_레시피가_모르는_칸을_거절한다() -> None:
    """Mechanical 의 모든 기능을 노출하지 않는다 — 허용 칸 밖은 여기서 죽는다."""
    with pytest.raises(ValidationError):
        parse_spec({"recipe": "modal", "material": MATERIAL, "solver": "sparse"})
    with pytest.raises(ValidationError):
        parse_spec({"recipe": "warp", "material": MATERIAL})


def test_자유_자유면_강체_모드_여섯을_더_찾는다() -> None:
    spec = parse_spec({"recipe": "modal", "material": MATERIAL, "modes": 10})
    assert isinstance(spec, ModalSpec)
    assert spec.is_free_free
    assert spec.modes_to_find == 10 + RIGID_BODY_MODES

    fixed = parse_spec(
        {"recipe": "modal", "material": MATERIAL, "constraints": [{"region": "fixed_base"}]}
    )
    assert isinstance(fixed, ModalSpec)
    assert fixed.modes_to_find == 10


def test_가짜_실행기는_네_단계를_같은_모양으로_남긴다(tmp_path: Path) -> None:
    """파일 이름과 result.json 의 모양이 진짜 실행기와 같아야 한다 — 화면이 그것을 보고
    만들어진다."""
    write_fixture_step(tmp_path / "input.step")
    spec = parse_spec({"recipe": "modal", "material": MATERIAL, "modes": 4}).model_dump()
    runner = executors.resolve("fake")

    kinds: list[str] = []
    for stage in STAGES:
        result = runner.run(StageContext(stage=stage, spec=spec, workdir=tmp_path))
        kinds.extend(one.kind for one in result.artifacts)
        for one in result.artifacts:
            assert one.path.is_file(), one
    assert kinds == ["dat", "mechdb", "rst", "solve_out", "result_json"]

    import json

    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["boundary"] == "free-free"
    assert result["rigid_body_modes"] == RIGID_BODY_MODES
    assert len(result["modes"]) == 4 + RIGID_BODY_MODES
    assert sum(1 for one in result["modes"] if one["rigid_body"]) == RIGID_BODY_MODES
    assert result["units"]["frequency"] == "Hz"


def test_입력이_없으면_fetching_에서_사람이_읽는_실패로_멈춘다(tmp_path: Path) -> None:
    spec = parse_spec({"recipe": "modal", "material": MATERIAL}).model_dump()
    runner = executors.resolve("fake")
    with pytest.raises(StageFailure) as caught:
        runner.run(StageContext(stage="fetching", spec=spec, workdir=tmp_path))
    assert caught.value.code == "geometry_import"


def test_모르는_실행기는_기동에서_죽는다() -> None:
    """작업을 집고 나서 죽으면 그 작업이 failed 로 남고, 사람은 설정 오타를 작업 실패로
    읽는다."""
    with pytest.raises(RuntimeError, match="모르는 실행기"):
        executors.resolve("typo")
    # **다리를 놓을 파이썬을 안 주는 것도 같은 부류다.** 그대로 두면 첫 작업이 「파이썬을
    # 찾지 못했습니다」 로 실패하고, 그 메시지는 설정이 빈 것과 경로가 틀린 것을 안 가른다.
    with pytest.raises(RuntimeError, match="WINDOWS_PYTHON"):
        executors.resolve("windows-bridge")


def test_참여계수_표를_솔버_출력에서_읽는다() -> None:
    """**표 제목과 첫 줄 사이에 글자 줄이 둘 있다.** 「숫자 줄이 아니면 표가 끝났다」 로 읽으면
    표를 시작하자마자 놓친다 — 그렇게 만들었다가 빈 결과를 받았다(실측)."""
    from app.core.dpf import participation

    text = (
        Path(__file__).resolve().parents[1] / "fixtures" / "solver" / "participation.out"
    ).read_text(encoding="utf-8", errors="replace")
    ratios = participation.parse(text)

    assert sorted(ratios) == ["ROTX", "ROTY", "ROTZ", "X", "Y", "Z"]
    assert len(ratios["X"]) == 11
    # 자유-자유에서는 강체 모드가 유효질량을 전부 가져간다 — 탄성 모드(7번 이상)는 0 이다.
    assert ratios["X"][7] == 0.0
    assert participation.dominant(ratios, 3) == "Z"
    # **전부 작으면 방향을 만들어 내지 않는다.** 「X」 라고 적으면 사람은 그 방향으로
    # 가진하면 울릴 것이라고 읽는다.
    assert participation.dominant(ratios, 7) is None


def test_참여계수_표가_없어도_실패하지_않는다() -> None:
    """참여계수는 곁들이는 값이다 — 없다고 다 끝난 해석을 실패로 적지 않는다."""
    from app.core.dpf import participation

    assert participation.parse("아무 표도 없는 로그\n1 2 3\n") == {}
    assert participation.dominant({}, 1) is None


def test_변위_지표는_정규화_방식과_무관하다() -> None:
    """**비율만 쓴다.** 모달 변위는 질량 정규화된 상대값이라 크기 자체에는 뜻이 없다 —
    전체를 10배 해도 축 비중과 국부성은 그대로여야 한다."""
    from app.core.dpf import metrics

    vectors = [[0.0, 0.0, 1.0], [0.0, 0.0, 2.0], [0.0, 0.0, 1.0]]
    share = metrics.direction_share(vectors)
    assert share == {"x": 0.0, "y": 0.0, "z": 1.0}
    assert metrics.dominant_axis(share) == "Z"

    scaled = [[value * 10 for value in row] for row in vectors]
    assert metrics.direction_share(scaled) == share
    assert metrics.localization(scaled) == metrics.localization(vectors)


def test_섞인_모드는_한_축이라고_말하지_않는다() -> None:
    from app.core.dpf import metrics

    mixed = metrics.direction_share([[1.0, 1.0, 0.0]])
    assert mixed["x"] == mixed["y"] == 0.5
    assert metrics.dominant_axis(mixed) is None


def test_한_구석만_움직이면_국부_모드다() -> None:
    """국부 모드를 1차 공진으로 읽으면 엉뚱한 곳을 보강하게 된다."""
    from app.core.dpf import metrics

    uniform = [[0.0, 0.0, 1.0]] * 100
    assert metrics.localization(uniform) == 1.0
    assert not metrics.is_local(metrics.localization(uniform))

    spike = [[0.0, 0.0, 1.0]] + [[0.0, 0.0, 0.0]] * 99
    value = metrics.localization(spike)
    assert value < 0.05
    assert metrics.is_local(value)


def test_몸통_일부가_휘는_정상_모드는_국부가_아니다() -> None:
    """**정상 모드에 매번 경고가 붙으면 경고는 아무 뜻도 못 갖는다.**

    실측(L 브래킷, 2026-09-21): 플랜지가 휘는 모드들의 참여비가 0.17~0.38 이었다 — 판 전체가
    반파장으로 휘기만 해도 0.67 이라 1 에서 멀어지는 것이 정상이다.
    """
    # 절점의 3분의 1이 사인 꼴로 움직이는 모드.
    import math

    from app.core.dpf import metrics

    third = [[0.0, 0.0, math.sin(math.pi * index / 33)] for index in range(33)]
    rest = [[0.0, 0.0, 0.0]] * 67
    value = metrics.localization(third + rest)
    assert 0.1 < value < 0.4, value
    assert not metrics.is_local(value)
