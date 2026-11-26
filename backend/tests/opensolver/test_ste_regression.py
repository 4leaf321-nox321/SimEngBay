"""E-7 회귀 틀을 **가짜 STE 로 끝까지** — 픽스처 둘(모달 · 정적)을 이 서버와 STE 로 풀어 같다고
말하나. 가짜 STE 는 이 기계의 ccx 로 풀므로 늘 같아야 한다 — 다르면 틀이 틀렸다(덱을 두 번
만들었거나 결과를 섞었거나). 진짜 STE 로는 `python scripts/ste_regression.py --email …` 로
돌린다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from app.core.calculix import tools
from app.core.stages import StageFailure

pytestmark = pytest.mark.opensolver

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ste_regression.py"


@pytest.fixture
def ready() -> None:
    try:
        tools.ccx_bin()
        tools.gmsh_bin()
    except StageFailure as failure:
        pytest.skip(str(failure))


def test_가짜_STE_로_돌리면_모두_같다고_말한다(
    ready: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = importlib.util.spec_from_file_location("ste_regression", SCRIPT)
    assert spec is not None and spec.loader is not None
    harness = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = harness  # 데이터클래스가 제 모듈을 찾는다
    spec.loader.exec_module(harness)
    for name in ("STE_BASE_URL", "STE_SSO_SECRET", "STE_SSO_CLIENT", "STE_POLL_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STE_TOKEN_DIR", "/kept/as/before")

    code = harness.main(
        [
            "--fake",
            "--only",
            "조건_원통_SI",
            "조건_반쪽구멍",
            "--points",
            "1",
            "--out",
            str(tmp_path),
        ]
    )

    # 심은 STE 환경을 되돌렸다 — 뒤 시험의 자식이 내린 가짜 STE 주소를 물려받으면 깨진다.
    assert "STE_BASE_URL" not in os.environ
    assert os.environ["STE_TOKEN_DIR"] == "/kept/as/before"
    rows = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert code == 0, rows
    assert [(one["folder"], one["recipe"], one["same"]) for one in rows] == [
        ("조건_반쪽구멍", "static", True),
        ("조건_원통_SI", "modal", True),
    ]
    modal = rows[1]
    assert modal["local"]["frequencies"] and modal["ste"]["frequencies"]
    assert modal["ste"]["result"], "STE 쪽도 추출까지 했다"
    ledger = tmp_path / "조건_원통_SI" / "p0001" / "ste" / ".ste-jobs.jsonl"
    assert ledger.is_file(), "STE 쪽은 정말 STE 잡으로 풀었다"
    assert not (tmp_path / "조건_원통_SI" / "p0001" / "local" / ".ste-jobs.jsonl").exists()
