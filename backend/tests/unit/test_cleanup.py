"""작업 폴더 정리 — **결과는 남기고 중간 파일만.**

여기서 지키는 것은 목록이다. 하나라도 잘못 들어가면(예: `result.json`) 사람이 보던 것이
사라지고, 그 사실은 **작업 상세를 다시 열 때**에야 드러난다.
"""

from __future__ import annotations

from pathlib import Path

from app.core import cleanup


def _work(tmp_path: Path) -> Path:
    for name in (
        "input.step",
        "topology.json",
        "spec.json",
        "model.dat",
        "solve.out",
        "result.json",
        "mode_07.vtp",
        "mode_07.png",
        "model.mechdb",
        "file.rst",
        "file.db",
        "file.mode",
        "file.DSP",
        "file0.err",
        "file0.log",
        ".stage-modeling.json",
    ):
        (tmp_path / name).write_bytes(b"x" * 1024)
    return tmp_path


def test_사람이_보는_것은_남는다(tmp_path: Path) -> None:
    cleanup.run(_work(tmp_path))
    남은것 = {path.name for path in tmp_path.iterdir()}
    assert {
        "input.step",
        "topology.json",
        "spec.json",
        "model.dat",
        "solve.out",
        "result.json",
        "mode_07.vtp",
        "mode_07.png",
    } <= 남은것


def test_중간_파일은_사라진다(tmp_path: Path) -> None:
    done = cleanup.run(_work(tmp_path))
    남은것 = {path.name for path in tmp_path.iterdir()}
    for name in ("model.mechdb", "file.rst", "file.db", "file.mode", "file.DSP", "file0.err"):
        assert name not in 남은것, name
    assert done.bytes_freed > 0
    assert len(done.files) >= 6


def test_먼저_얼마나_줄어드는지_말할_수_있다(tmp_path: Path) -> None:
    """**지우기 전에** 세어 볼 수 있어야 한다 — 되돌릴 수 없는 일이다."""
    planned = cleanup.plan(_work(tmp_path))
    assert planned.bytes_freed > 0
    assert all(path.is_file() for path in planned.files)  # 아직 안 지웠다


def test_없는_폴더도_견딘다(tmp_path: Path) -> None:
    assert cleanup.plan(tmp_path / "없는곳").bytes_freed == 0
    assert cleanup.run(tmp_path / "없는곳").files == []


def test_폴더_크기를_센다(tmp_path: Path) -> None:
    _work(tmp_path)
    assert cleanup.folder_bytes(tmp_path) == 16 * 1024
