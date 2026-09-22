"""실행기 — **Ansys 없이 확인할 수 있는 부분.**

명령을 어떻게 만드나, 결과 파일을 어떻게 읽나, 설정이 빠졌을 때 어디서 죽나. 진짜 Ansys 가
필요한 것은 `tests/ansys/` 에 있고 표시(`-m ansys`)가 붙어 기본으로 안 돈다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.core import executors
from app.core.executors import subprocess_executor as bridge
from app.core.run import read_result, result_path
from app.core.spec import parse_spec
from app.core.stages import StageContext, StageFailure

MATERIAL = {
    "name": "SS400",
    "youngs_modulus_gpa": 200,
    "poisson_ratio": 0.3,
    "density_kg_m3": 7850,
}
SPEC = {"recipe": "modal", "material": MATERIAL, "modes": 4}


def _ctx(stage: str, workdir: Path) -> StageContext:
    return StageContext(stage=stage, spec=SPEC, workdir=workdir)  # type: ignore[arg-type]


def test_local_은_이_파이썬으로_코어를_부른다(tmp_path: Path) -> None:
    runner = executors.resolve("local")
    command = runner.command(_ctx("modeling", tmp_path))  # type: ignore[attr-defined]
    assert command[0] == sys.executable
    # **PYTHONPATH 환경변수를 쓰지 않는다** — WSL → Windows 로는 환경이 안 건너간다.
    assert "-c" in command
    assert str(bridge.BACKEND_DIR) in command[command.index("-c") + 1]
    assert "modeling" in command
    assert str(tmp_path) in command


def test_windows_bridge_는_경로를_윈도우_표기로_바꾼다(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실제 변환은 `wslpath` 가 한다 — 직접 바꾸면 저장소가 WSL 파일시스템에 있을 때 틀린다."""
    monkeypatch.setattr(
        bridge,
        "to_windows_path",
        lambda path: "C:\\" + str(path).strip("/").replace("/", "\\"),
    )
    runner = executors.resolve(
        "windows-bridge", python=Path("/mnt/c/py/python.exe"), ansys_version=252
    )
    command = runner.command(_ctx("solving", tmp_path))  # type: ignore[attr-defined]
    assert command[0] == "/mnt/c/py/python.exe"
    assert command[1:3] == ["-X", "utf8"]
    assert any(one.startswith("C:\\") for one in command), command
    assert "--ansys-version" in command and "252" in command


def test_단계마다_다른_상한을_준다(tmp_path: Path) -> None:
    """솔브만 유난히 길다. 한 값으로 묶으면 모델링이 하루 종일 매달린다."""
    runner = executors.resolve("local")
    modeling = runner.command(_ctx("modeling", tmp_path))  # type: ignore[attr-defined]
    solving = runner.command(_ctx("solving", tmp_path))  # type: ignore[attr-defined]
    at = modeling.index("--timeout-seconds")
    assert int(modeling[at + 1]) < int(solving[solving.index("--timeout-seconds") + 1])


def test_windows_bridge_는_파이썬을_안_주면_기동에서_죽는다() -> None:
    with pytest.raises(RuntimeError, match="WINDOWS_PYTHON"):
        executors.resolve("windows-bridge")


def test_결과_파일이_없으면_도중에_죽은_것이다(tmp_path: Path) -> None:
    """**종료 코드가 아니라 결과 파일을 믿는다** — 자식이 왜 죽었는지는 그 파일에만 있다."""
    with pytest.raises(StageFailure) as caught:
        read_result(tmp_path, "modeling")
    assert caught.value.code == "internal"
    assert "죽었" in caught.value.message


def test_실패_파일은_코드와_메시지를_그대로_나른다(tmp_path: Path) -> None:
    result_path(tmp_path, "solving").write_text(
        json.dumps(
            {
                "ok": False,
                "code": "license",
                "message": "라이선스 없음",
                "details": {"tail": "…"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(StageFailure) as caught:
        read_result(tmp_path, "solving")
    assert caught.value.code == "license"
    assert caught.value.message == "라이선스 없음"
    assert caught.value.details["tail"] == "…"


def test_성공_파일의_경로는_작업폴더_기준이다(tmp_path: Path) -> None:
    """자식은 다른 OS 일 수 있다 — `C:\\...` 절대경로를 WSL 이 열 수 없다."""
    (tmp_path / "model.dat").write_text("x", encoding="utf-8")
    result_path(tmp_path, "modeling").write_text(
        json.dumps(
            {
                "ok": True,
                "summary": {"nodes": 10},
                "detail": "바디 1",
                "artifacts": [{"kind": "dat", "path": "model.dat"}],
            }
        ),
        encoding="utf-8",
    )
    result = read_result(tmp_path, "modeling")
    assert result.summary == {"nodes": 10}
    assert result.artifacts[0].path == tmp_path / "model.dat"


def test_형상_단계는_진짜_자식_프로세스에서_돈다(tmp_path: Path) -> None:
    """**Ansys 없이 다리의 왕복을 확인한다.** 형상 준비는 파일만 보므로 어디서든 돈다 —
    명령 만들기 · 자식 기동 · 결과 파일 읽기가 한 번에 검증된다."""
    (tmp_path / "spec.json").write_text(parse_spec(SPEC).model_dump_json(), encoding="utf-8")
    (tmp_path / "input.step").write_text(
        "ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8"
    )

    result = executors.resolve("local").run(_ctx("fetching", tmp_path))
    assert result.summary["input_bytes"] > 0
    assert "input.step" in result.detail


def test_입력이_없으면_자식이_사람이_읽는_실패를_남긴다(tmp_path: Path) -> None:
    (tmp_path / "spec.json").write_text(parse_spec(SPEC).model_dump_json(), encoding="utf-8")
    with pytest.raises(StageFailure) as caught:
        executors.resolve("local").run(_ctx("fetching", tmp_path))
    assert caught.value.code == "geometry_import"
