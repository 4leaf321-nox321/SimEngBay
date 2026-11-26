"""ccx 지문(요청서 E-5) — 워커가 재는 이 서버의 지문, STE 앱 정보에서 읽는 지문, 잡마다 남기는
견줌. 고르기를 막는 것은 `tests/api/test_ste_fingerprint.py` 다."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core import toolcheck
from app.core.calculix import ste, tools
from tests.fake_ste import CLIENT, FakeSte, Outcome

solve_module = importlib.import_module("app.core.calculix.solve")

ME = "kim.cae@corp.example"
SHA = "6adaabf5bf0382fc2bfd692b984320ed375dba777f7dc8297562f818043faa1b"


def test_워커는_ccx_의_지문을_링크를_따라가_잰다(tmp_path: Path) -> None:
    real = tmp_path / "ccx_2.21"
    real.write_bytes(b"\x7fELF ccx 2.21")
    link = tmp_path / "ccx"
    link.symlink_to(real)
    gmsh = tmp_path / "gmsh"
    gmsh.write_text("#!/bin/sh\n", encoding="utf-8")
    found = toolcheck.report(
        executor="local",
        ansys_root=None,
        ansys_version=252,
        environ={tools.CCX_ENV: str(link), tools.GMSH_ENV: str(gmsh)},
    )
    assert found["ccx_sha256"] == hashlib.sha256(b"\x7fELF ccx 2.21").hexdigest()
    assert toolcheck.sha256_of(tmp_path / "없음") is None


@pytest.mark.parametrize(
    ("body", "found"),
    [
        ({"meta": {"ccx_sha256": SHA}}, SHA),
        ({"metadata": {"ccx_sha256": SHA.upper()}}, SHA),
        ({"ccx_sha256": f" {SHA} "}, SHA),
        ({"meta": {"ccx_sha256": "6adaabf5"}}, None),
        ({"meta": "ccx 2.21"}, None),
        ({}, None),
    ],
)
def test_앱_정보에서_지문을_읽는다(body: dict[str, Any], found: str | None) -> None:
    assert ste.sha_in(body) == found


def _done(folder: Path, params: object) -> Outcome:
    (folder / "model.dat").write_text("", encoding="utf-8")
    (folder / "model.frd").write_text("frd", encoding="utf-8")
    (folder / "ccx.out").write_text(f"sha256={SHA}\n Job finished\n", encoding="utf-8")
    return Outcome("COMPLETED", 0)


@pytest.mark.parametrize(("local", "matches"), [(SHA, True), ("f" * 64, False), (None, None)])
def test_잡마다_이_서버의_ccx_와_같은지_남긴다(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, local: str | None, matches: bool | None
) -> None:
    fake = FakeSte(secrets_by_client={CLIENT: "ste-secret"}, runner=_done)
    monkeypatch.setattr(ste, "TRANSPORT", httpx.MockTransport(fake.handle))
    monkeypatch.setattr(ste, "_local_ccx_sha", lambda: local)
    for name, value in (
        (ste.BASE_URL_ENV, "http://ste.test/ste"),
        (ste.SECRET_ENV, "ste-secret"),
        (ste.CLIENT_ENV, CLIENT),
        (ste.POLL_ENV, "0"),
        (ste.TOKEN_DIR_ENV, str(tmp_path / "tokens")),
    ):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(tools, "run", lambda *_, **__: pytest.fail("로컬 ccx 를 불렀다"))
    work = tmp_path / "work"
    work.mkdir()
    (work / "model.inp").write_text(
        "*NODE\n1, 0, 0, 0\n2, 1, 0, 0\n*ELEMENT, TYPE=T3D2, ELSET=E\n1, 1, 2\n"
        "*STEP\n*STATIC\n*END STEP\n",
        encoding="utf-8",
    )

    solve_module.solve(work, solve_on="ste", requester_email=ME)

    [record] = ste.read_ledger(work)
    assert record["ccx_sha256"] == SHA
    assert record.get("ccx_matches_local") is matches
    assert record.get("local_ccx_sha256") == local
