"""**같은 덱을 로컬과 STE 로 풀면 같은가**(요청서 2026-11-24 E-7 의 작은 판 — 가짜 STE).

가짜 STE(`tests/fake_ste.py`)를 진짜 HTTP 로 띄우고, 실행기가 단계 자식(`python -m app.core.run
solving`)을 띄운다 — 건 사람(명령줄) · STE 연결(환경)이 프로세스 경계를 건너는지, 자식이 그
사람 명의로 업로드 · 제출 · 결과 받기를 하는지 본다. 가짜 STE 는 이 기계의 ccx 로 진짜 푼다.

받아들임(E-7): 고유진동수는 `.dat` 에 찍힌 자릿수까지 같다, 정적 반력은 상대차 1e-6 안, 판정이
같다. 진짜 STE(같은 ccx 2.21 빌드 — A-1)로 같은 시험을 돌리는 것은 STE 가 준비된 뒤다.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.core.calculix import ste, tables, tools
from app.core.executors.subprocess_executor import SubprocessExecutor, SubprocessOptions
from app.core.stages import StageCanceled, StageContext, StageFailure
from tests.fake_ste import CLIENT, FakeSte, serve

pytestmark = pytest.mark.opensolver

ME = "kim.cae@corp.example"
SECRET = "ste-secret"


@pytest.fixture
def ready() -> None:
    try:
        tools.ccx_bin()
    except StageFailure as failure:
        pytest.skip(str(failure))


@pytest.fixture
def fake_ste(ready: None) -> Iterator[tuple[FakeSte, str]]:
    fake = FakeSte(secrets_by_client={CLIENT: SECRET}, lazy=False)
    server, url = serve(fake)
    try:
        yield fake, url
    finally:
        server.shutdown()


def _block(step: str, *, nx: int = 20, n: int = 2) -> str:
    """100 x 10 x 10 mm 강 막대(C3D8) — 한 끝 고정. gmsh 없이 ccx 만으로 푼다."""
    length, side = 100.0, 10.0

    def node(i: int, j: int, k: int) -> int:
        return 1 + i + (nx + 1) * (j + (n + 1) * k)

    lines = ["*NODE"]
    for k in range(n + 1):
        for j in range(n + 1):
            for i in range(nx + 1):
                lines.append(
                    f"{node(i, j, k)}, {i * length / nx}, {j * side / n}, {k * side / n}"
                )
    lines.append("*ELEMENT, TYPE=C3D8, ELSET=EALL")
    number = 0
    for k in range(n):
        for j in range(n):
            for i in range(nx):
                number += 1
                corners = [
                    node(i, j, k),
                    node(i + 1, j, k),
                    node(i + 1, j + 1, k),
                    node(i, j + 1, k),
                    node(i, j, k + 1),
                    node(i + 1, j, k + 1),
                    node(i + 1, j + 1, k + 1),
                    node(i, j + 1, k + 1),
                ]
                lines.append(", ".join(str(one) for one in [number, *corners]))
    for name, at in (("FIX", 0), ("TIP", nx)):
        members = [node(at, j, k) for k in range(n + 1) for j in range(n + 1)]
        lines.append(f"*NSET, NSET={name}")
        lines += [
            ", ".join(str(one) for one in members[s : s + 8])
            for s in range(0, len(members), 8)
        ]
    lines += [
        "*MATERIAL, NAME=STEEL",
        "*ELASTIC",
        "210000, 0.3",
        "*DENSITY",
        "7.85E-9",
        "*SOLID SECTION, ELSET=EALL, MATERIAL=STEEL",
        "*BOUNDARY",
        "FIX, 1, 3",
        "*STEP",
    ]
    tip = (n + 1) ** 2
    if step == "static":
        lines += [
            "*STATIC",
            "*CLOAD",
            f"TIP, 3, {-100.0 / tip}",
            "*NODE PRINT, NSET=FIX, TOTALS=ONLY",
            "RF",
        ]
    else:
        lines += ["*FREQUENCY", "6"]
    lines += ["*NODE FILE", "U", "*END STEP"]
    return "\n".join(lines) + "\n"


def _folder(root: Path, name: str, step: str, solve_on: str) -> tuple[Path, dict[str, Any]]:
    work = root / name
    work.mkdir()
    (work / "model.inp").write_text(_block(step), encoding="utf-8")
    spec = {"recipe": "static" if step == "static" else "modal", "solver": "calculix"}
    if solve_on == "ste":
        spec["solve_on"] = "ste"
    (work / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    return work, spec


def _reaction(dat: str) -> list[float]:
    """`*NODE PRINT … TOTALS=ONLY` 의 합 한 줄."""
    found = re.search(
        r"total force.*?\n\s*\n?\s*([-\d.E+ ]+)\n", dat, re.IGNORECASE | re.DOTALL
    )
    assert found, dat[-500:]
    return [float(one) for one in found.group(1).split()]


@pytest.mark.parametrize("step", ["modal", "static"])
def test_같은_덱을_로컬과_STE_로_풀면_같다(
    tmp_path: Path, fake_ste: tuple[FakeSte, str], step: str
) -> None:
    fake, url = fake_ste
    options = SubprocessOptions(
        ste_env=(
            (ste.BASE_URL_ENV, url),
            (ste.SECRET_ENV, SECRET),
            (ste.CLIENT_ENV, CLIENT),
            (ste.POLL_ENV, "0.2"),
            (ste.TOKEN_DIR_ENV, str(tmp_path / "tokens")),
        )
    )
    runner = SubprocessExecutor("local", options)
    here, local_spec = _folder(tmp_path, "local", step, "local")
    there, ste_spec = _folder(tmp_path, "ste", step, "ste")

    mine = runner.run(StageContext(stage="solving", spec=local_spec, workdir=here))
    theirs = runner.run(
        StageContext(
            stage="solving",
            spec=ste_spec,
            workdir=there,
            requester_email=ME,
            requester_name="김해석",
        )
    )

    [job] = fake.jobs.values()
    assert job.owner == ME, "건 사람 명의로 냈다"
    assert fake.mints == [(ME, CLIENT)]
    assert theirs.summary["solved_on"] == "ste" and "solved_on" not in mine.summary
    for key in ("linear_solver", "memory_estimate_mb"):
        assert theirs.summary.get(key) == mine.summary.get(key), key
    local_dat = (here / "model.dat").read_text(encoding="utf-8")
    ste_dat = (there / "model.dat").read_text(encoding="utf-8")
    if step == "modal":
        assert tables.frequencies(ste_dat) == tables.frequencies(local_dat), "찍힌 자릿수까지"
        assert len(tables.frequencies(ste_dat)) == 6
    else:
        ours, remote = _reaction(local_dat), _reaction(ste_dat)
        assert remote == pytest.approx(ours, rel=1e-6)
        assert ours[2] == pytest.approx(100.0, rel=1e-6), "바닥 반력이 하중과 같다"
    [record] = ste.read_ledger(there)
    assert record["ste_state"] == "COMPLETED" and record["ccx_sha256"]
    assert record["equation_solver_threads"] == (1 if step == "modal" else record["threads"])
    for path in there.iterdir():
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "kst_" not in text and SECRET not in text, path.name


def test_ERROR_덱은_로컬과_같은_실패로_끝난다(
    tmp_path: Path, fake_ste: tuple[FakeSte, str]
) -> None:
    fake, url = fake_ste
    options = SubprocessOptions(
        ste_env=(
            (ste.BASE_URL_ENV, url),
            (ste.SECRET_ENV, SECRET),
            (ste.CLIENT_ENV, CLIENT),
            (ste.POLL_ENV, "0.2"),
        )
    )
    runner = SubprocessExecutor("local", options)
    failures = []
    for name, solve_on in (("local", "local"), ("ste", "ste")):
        work, spec = _folder(tmp_path, name, "static", solve_on)
        broken = (work / "model.inp").read_text().replace("*ELASTIC\n210000, 0.3\n", "")
        (work / "model.inp").write_text(broken, encoding="utf-8")
        with pytest.raises(StageFailure) as caught:
            runner.run(
                StageContext(
                    stage="solving",
                    spec=spec,
                    workdir=work,
                    requester_email=ME if solve_on == "ste" else None,
                )
            )
        failures.append((caught.value.code, caught.value.message))
    assert failures[0] == failures[1]
    assert [one.state for one in fake.jobs.values()] == ["FAILED"], "STE 화면에도 실패로(A-4)"


def test_취소하면_자식을_멈추고_STE_잡도_다음_폴링_안에_CANCELLED(
    tmp_path: Path, ready: None
) -> None:
    """요청서 E-4 · 받아들임 7. 자식은 SIGTERM 으로 바로 죽는다 — 낸 잡의 「끝」 줄이 없다.
    워커가 그 장부를 보고 낸 사람 명의로 취소한다(`ste.close_open` ·
    `services._note_ste_jobs`)."""
    fake = FakeSte(secrets_by_client={CLIENT: SECRET}, lazy=False, hold=True)
    server, url = serve(fake)
    tokens = tmp_path / "tokens"
    try:
        options = SubprocessOptions(
            ste_env=(
                (ste.BASE_URL_ENV, url),
                (ste.SECRET_ENV, SECRET),
                (ste.CLIENT_ENV, CLIENT),
                (ste.POLL_ENV, "0.2"),
                (ste.TOKEN_DIR_ENV, str(tokens)),
            )
        )
        work, spec = _folder(tmp_path, "ste", "static", "ste")

        def running() -> bool:
            return any(one.state == "RUNNING" for one in fake.jobs.values())

        with pytest.raises(StageCanceled):
            SubprocessExecutor("local", options).run(
                StageContext(stage="solving", spec=spec, workdir=work, requester_email=ME),
                should_cancel=running,
            )
        [job] = fake.jobs.values()
        assert job.state == "RUNNING", "자식이 죽어도 STE 잡은 계속 돈다 — 그래서 닫는다"
        [opened] = ste.open_jobs(work)
        assert opened["ste_job_id"] == job.id

        config = ste.SteConfig(
            base_url=url, secret=SECRET, client=CLIENT, poll_seconds=15.0, token_dir=tokens
        )
        began = time.monotonic()
        [closed] = ste.close_open(config, work, email=ME)
        assert closed["ste_state"] == "CANCELLED" and job.state == "CANCELLED"
        assert time.monotonic() - began < config.poll_seconds, "다음 폴링 안에"
        assert fake.mints == [(ME, CLIENT)], "자식이 받은 토큰을 그대로 — 새로 받지 않는다"
    finally:
        server.shutdown()
