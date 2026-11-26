"""E-7 회귀 틀(`scripts/ste_regression.py`)의 견주기 — 무엇을 같다고 · 다르다고 보나.

틀을 가짜 STE 로 끝까지 돌리는 것은 `tests/opensolver/test_ste_regression.py` 다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ste_regression.py"


@pytest.fixture(scope="module")
def harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ste_regression", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # 데이터클래스가 제 모듈을 찾는다
    spec.loader.exec_module(module)
    return module


def test_고유진동수는_찍힌_자릿수까지_같아야_한다(harness: ModuleType) -> None:
    a = harness.Outcome(True, frequencies=[101.23, 250.5])
    assert harness.compare(a, harness.Outcome(True, frequencies=[101.23, 250.5])) == []
    [line] = harness.compare(a, harness.Outcome(True, frequencies=[101.24, 250.5]))
    assert line.startswith("고유진동수")


def test_결과의_수는_상대차_1e_6_안이면_같다(harness: ModuleType) -> None:
    ours = {"max_displacement_mm": 0.123456, "reactions": {"바닥": [0.0, 0.0, -600.0]}}
    near = {
        "max_displacement_mm": 0.123456 * (1 + 5e-7),
        "reactions": {"바닥": [0.0, 0.0, -600.0]},
    }
    far = {
        "max_displacement_mm": 0.123456 * (1 + 5e-6),
        "reactions": {"바닥": [0.0, 1e-3, -600.0]},
    }
    assert (
        harness.compare(harness.Outcome(True, result=ours), harness.Outcome(True, result=near))
        == []
    )
    found = harness.compare(
        harness.Outcome(True, result=ours), harness.Outcome(True, result=far)
    )
    assert [line.split(":")[0] for line in found] == [
        "max_displacement_mm",
        "reactions.바닥[1]",
    ]


def test_어디서_얼마나_걸렸나는_견주지_않는다(harness: ModuleType) -> None:
    ours = {"solve_seconds": 3.0, "solved_on": None, "linear_solver": "spooles"}
    theirs = {
        "solve_seconds": 90.0,
        "solved_on": "ste",
        "ste_jobs": 2,
        "linear_solver": "spooles",
    }
    assert (
        harness.compare(
            harness.Outcome(True, result=ours), harness.Outcome(True, result=theirs)
        )
        == []
    )
    theirs["linear_solver"] = "iterative"
    assert harness.compare(
        harness.Outcome(True, result=ours), harness.Outcome(True, result=theirs)
    )


def test_판정이_다르면_그것만_말한다(harness: ModuleType) -> None:
    ok = harness.Outcome(True, frequencies=[1.0])
    broken = harness.Outcome(False, "solver_failed", "CalculiX 가 실패했습니다: *ERROR")
    [line] = harness.compare(ok, broken)
    assert line.startswith("판정") and "solver_failed" in line
    assert (
        harness.compare(broken, harness.Outcome(False, "solver_failed", broken.message)) == []
    )


def test_0_에_가까운_성분은_그_벡터의_크기로_견준다(harness: ModuleType) -> None:
    """실측(2026-11-27, 「조건_반쪽구멍」): 구멍 반력 x 가 -3.28e-10 ↔ -3.58e-10 N — SPOOLES
    여러 스레드의 끝자리 잡음이다. 상대차로만 보면 9% 라 「다르다」 가 된다."""
    ours = {"reactions": {"구멍": [-3.28098e-10, -1000.0, 8.35991e-10]}}
    theirs = {"reactions": {"구멍": [-3.5781e-10, -1000.0, 8.42111e-10]}}
    assert (
        harness.compare(
            harness.Outcome(True, result=ours), harness.Outcome(True, result=theirs)
        )
        == []
    )


def test_통째로_잡음인_벡터는_같은_칸의_큰_값으로_견준다(harness: ModuleType) -> None:
    ours = {"reactions": {"바닥": [0.0, 0.0, -600.0], "옆": [1.1e-10, -2.0e-11, 3.0e-11]}}
    theirs = {"reactions": {"바닥": [0.0, 0.0, -600.0], "옆": [1.4e-10, -2.6e-11, 2.1e-11]}}
    assert (
        harness.compare(
            harness.Outcome(True, result=ours), harness.Outcome(True, result=theirs)
        )
        == []
    )


def test_작은_값도_제_크기에서_다르면_다르다(harness: ModuleType) -> None:
    """질량은 tonne 이라 작다 — 다른 칸의 큰 값에 묻히면 안 된다."""
    ours = {"mass_tonne": 1.0e-6, "max_von_mises_mpa": 250.0}
    theirs = {"mass_tonne": 1.1e-6, "max_von_mises_mpa": 250.0}
    [line] = harness.compare(
        harness.Outcome(True, result=ours), harness.Outcome(True, result=theirs)
    )
    assert line.startswith("mass_tonne")
