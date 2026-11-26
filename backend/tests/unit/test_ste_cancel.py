"""취소를 STE 까지(요청서 2026-11-24 E-4) — **끝을 못 적은 STE 잡을 낸 사람 명의로 멈추고,
멈춘 것을 본다**(`ste.close_open`).

자식(단계 실행기)은 잡을 내자마자 작업 폴더의 장부에 적는다. 자식이 취소 · 단계 시간 초과 ·
죽음으로 멈추면 그 잡의 「끝」 줄이 없다 — 워커가 그것을 보고 STE 에서 취소한다. 여기서는 그
닫기만 본다(가짜 STE — `httpx.MockTransport`). 워커가 언제 부르는지는
`tests/api/test_ste_cancel.py`, 진짜 자식 프로세스를 멈추는 것은
`tests/opensolver/test_ste_solve.py` 다.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import httpx
import pytest

from app.core.calculix import ste
from tests.fake_ste import CLIENT, FakeSte, Outcome

ME = "kim.cae@corp.example"
SECRET = "ste-secret"


def _done(folder: Path, params: object) -> Outcome:
    (folder / "ccx.out").write_text(" Job finished\n", encoding="utf-8")
    return Outcome("COMPLETED", 0)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeSte:
    made = FakeSte(secrets_by_client={CLIENT: SECRET}, runner=_done, hold=True)
    monkeypatch.setattr(ste, "TRANSPORT", httpx.MockTransport(made.handle))
    return made


@pytest.fixture
def config(tmp_path: Path) -> ste.SteConfig:
    return ste.SteConfig(
        base_url="http://ste.test/ste",
        secret=SECRET,
        client=CLIENT,
        poll_seconds=0,
        token_dir=tmp_path / "tokens",
    )


def _submitted(config: ste.SteConfig, work: Path, *, run: bool = True) -> str:
    """자식이 하는 일 — 그 사람 명의로 올리고 내고, 장부에 「냄」 만 적은 채 멈췄다."""
    http = ste.http_client()
    session = ste.SteSession(config, ME, http=http, tokens=ste.Tokens(config, http))
    upload = session.accepted(session.call("POST", ste.ENDPOINTS["uploads"], what="u"), "u")
    path = ste.ENDPOINTS["upload_file"].format(upload=upload["id"], name="model.inp")
    session.accepted(session.call("PUT", path, what="p", content=b"*NODE\n"), "p")
    form = ste._submit_form("calculix", upload["id"], {"deck": "model"})
    made = session.call("POST", ste.ENDPOINTS["jobs"], what="j", data=form)
    job = str(session.accepted(made, "j")["id"])
    if run:
        session.call("GET", ste.ENDPOINTS["job"].format(job=job), what="s")  # → RUNNING
    ste.append_ledger(work, {"event": "submit", "ste_job_id": job, "mem_gb": 2, "at": 0})
    http.close()
    return job


def test_끝을_못_적은_잡을_낸_사람_명의로_취소하고_CANCELLED_를_본다(
    fake: FakeSte, config: ste.SteConfig, tmp_path: Path
) -> None:
    job = _submitted(config, tmp_path)
    assert fake.jobs[job].state == "RUNNING"

    [closed] = ste.close_open(config, tmp_path, email=ME)

    assert fake.jobs[job].state == "CANCELLED"
    assert closed["ste_state"] == "CANCELLED" and "discarded" not in closed
    assert ("POST", f"/ste/api/jobs/{job}/cancel", ME) in fake.requests, "낸 사람 명의로"
    assert fake.mints == [(ME, CLIENT)], "자식이 받아 둔 토큰을 나눠 쓴다 — 새로 받지 않는다"
    [record] = ste.read_ledger(tmp_path)
    assert record["ste_state"] == "CANCELLED" and record["canceled_by"] == ste.CANCELED_HERE
    assert record["mem_gb"] == 2, "낸 때의 기록과 합쳐진다"
    assert ste.open_jobs(tmp_path) == []
    assert ste.close_open(config, tmp_path, email=ME) == [], "두 번 닫지 않는다"


def test_이미_끝난_잡은_그_상태를_적고_결과를_버린다(
    fake: FakeSte, config: ste.SteConfig, tmp_path: Path
) -> None:
    fake.hold = False
    job = _submitted(config, tmp_path)
    fake._finish(fake.jobs[job])  # 자식이 멈춘 사이 STE 에서는 끝났다

    [closed] = ste.close_open(config, tmp_path, email=ME)

    assert closed["ste_state"] == "COMPLETED" and closed["discarded"] is True
    assert not any("/result/file/" in path for _, path, _ in fake.requests), "받아 오지 않는다"


def test_멈춘_것을_못_보면_취소를_청함으로_남기고_사람을_붙들지_않는다(
    fake: FakeSte, config: ste.SteConfig, tmp_path: Path
) -> None:
    fake.ignore_cancel = True
    _submitted(config, tmp_path)
    naps: list[float] = []

    [closed] = ste.close_open(config, tmp_path, email=ME, wait_seconds=0, sleep=naps.append)

    assert closed["ste_state"] == ste.CANCEL_REQUESTED and "cancel_error" not in closed
    assert naps == [], "기다리는 시간이 0 이면 묻기만 하고 끝낸다"
    assert ste.open_jobs(tmp_path) == [], "끝을 적었다 — 다음에 다시 해 보지 않는다"


def test_취소는_기다리는_동안_짧게_다시_묻는다(
    fake: FakeSte, config: ste.SteConfig, tmp_path: Path
) -> None:
    fake.ignore_cancel = True
    job = _submitted(config, tmp_path)
    naps: list[float] = []

    def nap(seconds: float) -> None:
        naps.append(seconds)
        if len(naps) == 2:  # 두 번 기다린 뒤 STE 가 멈춘다
            fake.jobs[job].state = "CANCELLED"

    slow = dataclasses.replace(config, poll_seconds=15.0)
    [closed] = ste.close_open(slow, tmp_path, email=ME, wait_seconds=60, sleep=nap)

    assert closed["ste_state"] == "CANCELLED"
    assert naps == [ste.CANCEL_POLL_SECONDS] * 2, "폴링 간격(15초)보다 짧게"


def test_STE_에_못_닿아도_던지지_않고_까닭을_남긴다(
    fake: FakeSte, config: ste.SteConfig, tmp_path: Path
) -> None:
    _submitted(config, tmp_path)
    fake.fault("cancel", 503)
    fake.fault("status", 503)

    [closed] = ste.close_open(config, tmp_path, email=ME, wait_seconds=0)

    assert closed["ste_state"] == ste.CANCEL_REQUESTED
    assert "503" in closed["cancel_error"]


def test_끝을_적은_잡은_건드리지_않는다(
    fake: FakeSte, config: ste.SteConfig, tmp_path: Path
) -> None:
    job = _submitted(config, tmp_path)
    ste.append_ledger(tmp_path, {"event": "end", "ste_job_id": job, "ste_state": "COMPLETED"})
    asked = len(fake.requests)

    assert ste.close_open(config, tmp_path, email=ME) == []
    assert len(fake.requests) == asked, "STE 를 부르지도 않는다"


def test_앞_단계가_낸_잡은_offset_뒤만_본다(
    fake: FakeSte, config: ste.SteConfig, tmp_path: Path
) -> None:
    first = _submitted(config, tmp_path)
    offset = ste.ledger_size(tmp_path)
    second = _submitted(config, tmp_path)

    [closed] = ste.close_open(config, tmp_path, offset, email=ME)

    assert closed["ste_job_id"] == second
    assert fake.jobs[first].state == "RUNNING"
