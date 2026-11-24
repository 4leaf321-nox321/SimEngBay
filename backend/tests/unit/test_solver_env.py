"""단계 설정이 **단계 자식까지 닿는가**(2026-11-25).

코어는 설정을 모르고 환경 변수만 읽는다. 넘기는 길은 셋이다 — 서버에서 고치는 해석 값
(`server/runtime.py` → `StageContext.env`, **프로세스 환경을 이긴다**), 기계마다 다른 자리
(`machine_env` — `.env` 가 채우고 **프로세스 환경이 이긴다**), STE 비밀(`ste_env` — STE
솔브만).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.core import toolcheck
from app.core.calculix import bonding, ste, tools
from app.core.executors.subprocess_executor import SubprocessExecutor, SubprocessOptions
from app.core.stages import StageContext
from app.modules.server import runtime
from app.modules.simulations import services


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (tools.GMSH_ENV, tools.CCX_ENV, tools.LD_ENV, bonding.BONDING_ENV):
        monkeypatch.delenv(name, raising=False)


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_기계마다_다른_자리는_env_에서_자식으로_간다() -> None:
    settings = _settings(
        gmsh_bin="/opt/gmsh/bin/gmsh",
        ccx_bin="/opt/ccx/bin/ccx",
        opensolver_ld_path="/opt/ccx/lib",
    )
    passed = dict(services.machine_env(settings))
    assert passed == {
        "GMSH_BIN": "/opt/gmsh/bin/gmsh",
        "CCX_BIN": "/opt/ccx/bin/ccx",
        "OPENSOLVER_LD_PATH": "/opt/ccx/lib",
    }
    child = SubprocessExecutor("local", SubprocessOptions(extra_env=tuple(passed.items())))
    env = child.child_env()
    assert {name: env[name] for name in passed} == passed
    assert services.machine_env(_settings()) == (), "빈 칸은 싣지 않는다(PATH 로 찾는다)"


def test_기계_자리는_프로세스_환경이_이긴다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(tools.CCX_ENV, "/from/unit/env/ccx")
    child = SubprocessExecutor(
        "local", SubprocessOptions(extra_env=((tools.CCX_ENV, "/from/dotenv/ccx"),))
    )
    assert child.child_env()[tools.CCX_ENV] == "/from/unit/env/ccx"


def test_작업의_단계_설정은_프로세스_환경을_이긴다(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """워커 하나의 환경(`worker-N.env`)이 다르다고 같은 작업이 다르게 풀리면 안 된다."""
    monkeypatch.setenv(bonding.BONDING_ENV, "shared")
    ctx = StageContext(
        stage="modeling",
        spec={"recipe": "static"},
        workdir=tmp_path,
        env=((bonding.BONDING_ENV, "tie"),),
    )
    assert (
        SubprocessExecutor("local", SubprocessOptions()).child_env(ctx)[bonding.BONDING_ENV]
        == "tie"
    )


def test_서버_설정은_코어가_읽는_이름으로_가고_빈_값은_싣지_않는다() -> None:
    pairs = dict(
        runtime.env_pairs(
            {
                "calculix_bonding": "tie",
                "calculix_linear_solver": "iterative",
                "calculix_boolean_tolerance_mm": "",
                "omp_num_threads": "4",
                "ste_mem_gb_max": "32",
            }
        )
    )
    assert pairs == {
        "CALCULIX_BONDING": "tie",
        "CALCULIX_LINEAR_SOLVER": "iterative",
        "OMP_NUM_THREADS": "4",
        "STE_MEM_GB_MAX": "32",
    }


@pytest.mark.parametrize(
    ("key", "raw", "stored"),
    [
        ("calculix_bonding", " TIE ", "tie"),
        ("omp_num_threads", "4.0", "4"),
        ("calculix_boolean_tolerance_mm", "0.0020", "0.002"),
        ("ste_base_url", "https://hwax.example/ste/", "https://hwax.example/ste"),
        ("ste_calculix_app", "calculix-2.21", "calculix-2.21"),
    ],
)
def test_서버_설정_값을_가다듬는다(key: str, raw: str, stored: str) -> None:
    assert runtime.normalize(runtime.BY_KEY[key], raw) == stored


@pytest.mark.parametrize(
    ("key", "raw"),
    [
        ("calculix_bonding", "glue"),
        ("omp_num_threads", "0"),
        ("omp_num_threads", "2.5"),
        ("calculix_boolean_tolerance_mm", "넓게"),
        ("ste_base_url", "hwax.example/ste"),
        ("ste_calculix_app", "../calculix"),
        ("ste_mem_gb_max", "1"),
        ("ste_poll_seconds", ""),
    ],
)
def test_틀린_서버_설정은_받지_않는다(key: str, raw: str) -> None:
    with pytest.raises(ValueError):
        runtime.normalize(runtime.BY_KEY[key], raw)


def test_결과를_바꾸는_값만_작업에_고정한다() -> None:
    assert set(runtime.FROZEN) == {
        "calculix_bonding",
        "calculix_linear_solver",
        "calculix_boolean_tolerance_mm",
        "omp_num_threads",
        "ste_mem_gb_max",
    }
    assert all(
        knob.env not in (ste.SECRET_ENV, tools.CCX_ENV, tools.GMSH_ENV)
        for knob in runtime.KNOBS
    ), "비밀 · 기계 자리는 서버 화면에 두지 않는다"


def test_도구_점검은_자식이_볼_환경으로_찾는다(tmp_path: Path) -> None:
    """`.env` 의 `CCX_BIN` 으로만 찾을 수 있는 ccx — 점검이 그 자리를 봐야 워커가 CalculiX 를
    집는다."""
    ccx = tmp_path / "ccx_2.21"
    ccx.write_text("#!/bin/sh\n", encoding="utf-8")
    gmsh = tmp_path / "gmsh"
    gmsh.write_text("#!/bin/sh\n", encoding="utf-8")
    found = toolcheck.report(
        executor="local",
        ansys_root=None,
        ansys_version=252,
        environ={tools.CCX_ENV: str(ccx), tools.GMSH_ENV: str(gmsh)},
    )
    assert found["ccx"] == str(ccx) and found["gmsh"] == str(gmsh)
    missing = toolcheck.report(
        executor="local",
        ansys_root=None,
        ansys_version=252,
        environ={tools.CCX_ENV: str(tmp_path / "없음")},
    )
    assert missing["ccx"] is None, "가리킨 자리가 틀리면 PATH 로 물러서지 않는다"


@pytest.mark.parametrize(
    ("given", "threads"), [("4", 4), ("4,2", 4), ("", 2), ("많이", 2), ("0", 2)]
)
def test_STE_잡의_스레드_수는_OMP_NUM_THREADS_에서(given: str, threads: int) -> None:
    assert ste._threads(given) == threads
