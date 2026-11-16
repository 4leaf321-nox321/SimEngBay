"""**모달의 찾을 주파수 범위**(`app/core/modes/search.py`) — 두 솔버가 같은 뜻(범위 안을 최대
모드 수만큼)으로 풀게 하는 규칙과, CalculiX 경로의 다시 풀기 · 거르기.

`fixtures/calculix/cantilever_modal.dat` 은 ccx 2.21 이 외팔보 판(폭 40 · 두께 2)을 푼 진짜
출력이다(2026-11-17) — 167 · 859 · 1,038 · 2,735 · 2,909 · 2,938 · 5,056 · 5,677 · 6,915 ·
8,036 Hz.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core import conditions as condition_model
from app.core.calculix import read as calculix_read
from app.core.calculix import tables
from app.core.modes import search
from app.core.spec import ModalSpec

#: 꾸러미가 같은 이름의 함수(`solve`)를 내보내므로 모듈은 이름으로 집는다.
calculix_solve = importlib.import_module("app.core.calculix.solve")

DAT = Path(__file__).resolve().parents[1] / "fixtures" / "calculix" / "cantilever_modal.dat"
MATERIAL = {
    "name": "SS400",
    "youngs_modulus_gpa": 200,
    "poisson_ratio": 0.3,
    "density_kg_m3": 7850,
}


def _spec(**extra: Any) -> ModalSpec:
    return ModalSpec.model_validate({"material": MATERIAL, "modes": 3, **extra})


def _given(kind: str = "modal", span: list[float] | None = None) -> condition_model.Conditions:
    analysis: dict[str, Any] = {"type": kind}
    if span is not None:
        analysis["frequency_range"] = span
    return condition_model.read({"conditions": {"analysis": analysis}})


def test_범위는_CAD_가_먼저고_모달로_적은_것만_쓴다() -> None:
    spec = _spec(frequency_range_hz=(100, 5000))
    assert search.mode_search(_spec(), _given()) is None
    from_spec = search.mode_search(spec, _given())
    assert from_spec == search.ModeSearch(100, 5000, 3, "spec")
    assert search.mode_search(spec, _given(span=[800, 3000])) == search.ModeSearch(
        800, 3000, 3, "cad"
    )
    # 조화로 적은 점 파일의 범위는 **훑을 범위**다 — 모달의 찾을 범위로 쓰지 않는다.
    assert search.mode_search(_spec(), _given("harmonic", [200, 2000])) is None
    # 틀린 CAD 범위는 버리고 스펙으로.
    assert search.mode_search(spec, _given(span=[3000, 800])) == from_spec


def test_스펙의_범위는_0_이상_하한_미만_상한() -> None:
    assert _spec(frequency_range_hz=(0, 10)).frequency_range_hz == (0, 10)
    for bad in ((10, 10), (20, 10), (-1, 10)):
        with pytest.raises(ValidationError, match="0 ≤ 하한 < 상한"):
            _spec(frequency_range_hz=bad)


def test_범위_안이_모자라고_위쪽에_못_닿았으면_늘려_다시_푼다() -> None:
    wanted = search.ModeSearch(800, 3000, 3, "spec")
    # 낮은 것부터 3개(167 · 859 · 1,038) — 범위 안 2개, 위쪽(3,000) 못 닿음 → 범위 아래 1 + 3 +
    # 2.
    assert search.next_count([167, 859, 1038], 3, wanted) == 6
    # 범위 안이 찼다.
    assert search.next_count([167, 859, 1038, 2735], 4, wanted) is None
    # 범위 위쪽을 넘는 모드까지 풀었다 — 범위 안은 다 나왔다(모자라도 그것이 전부).
    narrow = search.ModeSearch(800, 900, 3, "spec")
    assert search.next_count([167, 859, 1038], 3, narrow) is None
    # 청한 것보다 적게 나왔다 — 모델이 가진 모드를 다 냈다.
    assert search.next_count([167, 859], 3, wanted) is None
    # 범위 아래가 많으면 그만큼 겨눈다 · 상한을 넘지 않는다.
    high = search.ModeSearch(5000, 9000, 5, "spec")
    assert search.next_count(list(range(1, 31)), 30, high) == 60
    assert search.next_count(list(range(1, 151)), 150, high) == search.MAX_SOLVED
    assert search.next_count(list(range(1, 201)), search.MAX_SOLVED, high) is None


def test_범위_안만_남기고_탄성_차수를_그_안에서_센다() -> None:
    modes: list[dict[str, Any]] = [
        {"number": 1, "frequency_hz": 0.0, "rigid_body": True, "elastic_number": None},
        {"number": 2, "frequency_hz": 167.0, "rigid_body": False, "elastic_number": 1},
        {"number": 3, "frequency_hz": 859.0, "rigid_body": False, "elastic_number": 2},
        {"number": 4, "frequency_hz": 1038.0, "rigid_body": False, "elastic_number": 3},
        {"number": 5, "frequency_hz": 2735.0, "rigid_body": False, "elastic_number": 4},
        {"number": 6, "frequency_hz": 2909.0, "rigid_body": False, "elastic_number": 5},
    ]
    shown, below = search.kept(modes, search.ModeSearch(800, 3000, 3, "spec"))
    assert [(one["number"], one["elastic_number"]) for one in shown] == [
        (3, 1),
        (4, 2),
        (5, 3),
    ]
    assert below == 1, "범위 아래의 탄성 모드(167 Hz)만 센다 — 강체는 세지 않는다"
    assert modes[2]["elastic_number"] == 2, "원본은 건드리지 않는다"
    # 0 Hz 부터면 강체 모드도 범위 안 — 남기되 원하는 수에 세지 않는다.
    shown, below = search.kept(modes, search.ModeSearch(0, 3000, 2, "cad"))
    assert [one["number"] for one in shown] == [1, 2, 3] and below == 0


def test_모자랐을_때만_말한다() -> None:
    wanted = search.ModeSearch(800, 3000, 3, "spec")
    assert search.note(wanted, 3) is None
    assert search.note(wanted, 1) is None, "범위 안의 모드가 그것뿐이면 할 말이 없다"
    assert "안에 모드가 없습니다" in (search.note(wanted, 0) or "")
    stuck = [float(at) for at in range(1, search.MAX_SOLVED + 1)]
    assert "끝까지 훑지 못했습니다" in (search.note(wanted, 0, stuck) or "")


def test_범위는_boundary_로_건너간다(tmp_path: Path) -> None:
    wanted = search.ModeSearch(800, 3000, 3, "cad")
    path = tmp_path / "boundary.json"
    path.write_text(json.dumps({search.KEY: wanted.as_boundary()}), encoding="utf-8")
    assert search.read(path) == wanted
    path.write_text("{not json", encoding="utf-8")
    assert search.read(path) is None
    assert search.read(tmp_path / "없음.json") is None


DECK = "*NODE\n1, 0, 0, 0\n*STEP\n*FREQUENCY, SOLVER=SPOOLES\n3\n*NODE FILE\nU\n*END STEP\n"


def test_덱의_모드_수를_읽고_바꾸고_고유치_덱은_SPOOLES_를_한_스레드로() -> None:
    assert calculix_solve.asked_modes(DECK) == 3
    changed = calculix_solve.with_modes(DECK, 8)
    assert calculix_solve.asked_modes(changed) == 8 and changed.endswith("\n")
    assert "*FREQUENCY, SOLVER=SPOOLES\n8\n" in changed
    assert calculix_solve.eigen_env(DECK) == {"CCX_NPROC_EQUATION_SOLVER": "1"}
    assert calculix_solve.eigen_env("*STEP\n*STATIC\n1.0, 1.0\n*END STEP\n") is None


def _eigen_table(values: list[float]) -> str:
    rows = "\n".join(
        f"{at:7d}   0.1000000E+07   0.1000000E+04   {value:.7E}   0.0000000E+00"
        for at, value in enumerate(values, start=1)
    )
    return f"     E I G E N V A L U E   O U T P U T\n\n{rows}\n\n"


def test_솔브는_범위가_차도록_모드를_늘려_다시_푼다(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ccx 대신 — 덱의 모드 수만큼 낮은 것부터 낸다. 처음 3개는 범위 안이 모자라 늘려 다시
    푼다."""
    spectrum = tables.frequencies(DAT.read_text(encoding="utf-8"))
    (tmp_path / "model.inp").write_text(DECK, encoding="utf-8")
    wanted = search.ModeSearch(800, 3000, 3, "spec")
    (tmp_path / "boundary.json").write_text(
        json.dumps({search.KEY: wanted.as_boundary()}), encoding="utf-8"
    )
    asked: list[int] = []
    envs: list[Any] = []

    def fake_run(
        _binary: Any, _args: Any, *, cwd: Path, env_extra: Any = None, **_: Any
    ) -> Any:
        count = calculix_solve.asked_modes((cwd / "model.inp").read_text(encoding="utf-8"))
        assert count is not None
        asked.append(count)
        envs.append(env_extra)
        (cwd / "model.dat").write_text(_eigen_table(spectrum[:count]), encoding="utf-8")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(calculix_solve.tools, "run", fake_run)
    monkeypatch.setattr(calculix_solve.tools, "ccx_bin", lambda: Path("/usr/bin/ccx"))
    done = calculix_solve.solve(tmp_path)
    assert asked == [3, 6], "범위 아래 1 + 원하는 3 + 여유 2"
    assert envs == [{"CCX_NPROC_EQUATION_SOLVER": "1"}] * 2
    assert done.summary["mode_search"] == "800~3000 Hz · 2번 풀어 모드 6개까지"


def test_결과는_범위_안만_싣고_표는_전체_차례로_찾는다(tmp_path: Path) -> None:
    """진짜 ccx 출력 — 범위 800 ~ 3,000 Hz 에서 3개. 유효질량 표는 전체 차례(2 ~ 4번)로
    붙는다."""
    shutil.copy(DAT, tmp_path / "model.dat")
    (tmp_path / "boundary.json").write_text(
        json.dumps(
            {
                "constrained": True,
                search.KEY: search.ModeSearch(800, 3000, 3, "cad").as_boundary(),
            }
        ),
        encoding="utf-8",
    )
    calculix_read.extract(ModalSpec.model_validate({"material": MATERIAL}), tmp_path)
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    rows = [
        (one["number"], one["elastic_number"], round(one["frequency_hz"], 1))
        for one in result["modes"]
    ]
    assert rows == [(2, 1, 859.4), (3, 2, 1038.4), (4, 3, 2735.5)]
    # 2번(859 Hz)은 X 회전 비틀림 — 1번(167 Hz, Y 회전 굽힘)의 값이 붙으면 어긋난 것이다.
    assert result["modes"][0]["dominant_direction"] == "ROTX"
    assert result["frequency_range_hz"] == [800, 3000]
    assert result["range_from"] == "cad"
    assert result["modes_below_range"] == 1
    assert "range_note" not in result
