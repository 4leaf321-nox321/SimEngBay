"""STE 에서 ccx 를 푼다 — 요청서 2026-11-24 E-1(ccx 한 번 = STE 잡 한 번) · E-3(건 사람
명의로만).

가짜 STE(`tests/fake_ste.py`)를 `httpx.MockTransport` 로 꽂고 `solve()` 를 그대로 부른다 —
판정 · 재시도 · 모드 찾기가 로컬과 같은 코드를 지나는지 본다. 진짜 ccx 로 로컬과 STE 를 견주는
것은 `tests/opensolver/test_ste_solve.py` 다.
"""

from __future__ import annotations

import importlib
import json
import stat
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.core.calculix import ste, tables, tools
from app.core.executors.subprocess_executor import SubprocessExecutor, SubprocessOptions
from app.core.modes import search
from app.core.spec import parse_spec
from app.core.stages import StageContext, StageFailure
from tests.fake_ste import CLIENT, FakeSte, Outcome

solve_module = importlib.import_module("app.core.calculix.solve")

ME = "kim.cae@corp.example"
SECRET = "ste-secret"
SHA = "6adaabf5bf0382fc2bfd692b984320ed375dba777f7dc8297562f818043faa1b"
STATIC_DECK = (
    "*NODE\n1, 0, 0, 0\n2, 1, 0, 0\n*ELEMENT, TYPE=T3D2, ELSET=E\n1, 1, 2\n"
    "*STEP\n*STATIC\n*END STEP\n"
)
DAT = Path(__file__).resolve().parents[1] / "fixtures" / "calculix" / "cantilever_modal.dat"


def finished(folder: Path, params: dict[str, Any]) -> Outcome:
    """ccx 대신 — 결과 셋과 로그를 쓰고 끝난다."""
    (folder / "model.dat").write_text("", encoding="utf-8")
    (folder / "model.frd").write_text("frd", encoding="utf-8")
    (folder / "ccx.out").write_text(f"sha256={SHA}\n Job finished\n", encoding="utf-8")
    return Outcome("COMPLETED", 0)


@pytest.fixture
def work(tmp_path: Path) -> Path:
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "model.inp").write_text(STATIC_DECK, encoding="utf-8")
    return folder


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeSte:
    made = FakeSte(secrets_by_client={CLIENT: SECRET}, runner=finished, ccx_sha256=SHA)
    monkeypatch.setattr(ste, "TRANSPORT", httpx.MockTransport(made.handle))
    monkeypatch.setenv(ste.BASE_URL_ENV, "http://ste.test/ste")
    monkeypatch.setenv(ste.SECRET_ENV, SECRET)
    monkeypatch.setenv(ste.POLL_ENV, "0")
    monkeypatch.setenv(ste.TOKEN_DIR_ENV, str(tmp_path / "tokens"))
    monkeypatch.setenv(ste.CLIENT_ENV, CLIENT)
    monkeypatch.delenv(solve_module.LINEAR_SOLVER_ENV, raising=False)
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)

    def no_local(*_: object, **__: object) -> None:
        raise AssertionError("STE 로 건 작업이 로컬 ccx 를 불렀다")

    monkeypatch.setattr(tools, "run", no_local)
    return made


def _solve(work: Path, **kwargs: Any) -> Any:
    return solve_module.solve(work, solve_on="ste", requester_email=ME, **kwargs)


def test_ccx_한_번이_STE_잡_한_번이고_결과를_같은_이름으로_받는다(
    fake: FakeSte, work: Path
) -> None:
    done = _solve(work, timeout_seconds=3600)

    assert len(fake.jobs) == 1
    job = next(iter(fake.jobs.values()))
    assert job.owner == ME, "건 사람 명의로 냈다"
    assert fake.submitted_params == [
        {
            "deck": "model",
            "threads": 2,
            "equation_solver_threads": 2,
            "mem_gb": ste.MEM_GB_MIN,
            "time_limit_min": 60,
        }
    ]
    for name in ("model.dat", "model.frd", "ccx.out", "ste-slurm.out"):
        assert (work / name).is_file(), name
    assert done.summary["solved_on"] == "ste"
    assert done.summary["ste_jobs"] == 1
    assert "STE 잡 1개" in done.detail
    [record] = ste.read_ledger(work)
    assert record["ste_job_id"] == job.id and record["ste_state"] == "COMPLETED"
    assert record["ccx_sha256"] == SHA
    assert fake.mints == [(ME, CLIENT)]
    # 장부 · 작업 폴더에 토큰이 없다.
    for path in work.iterdir():
        assert "kst_" not in path.read_text(encoding="utf-8", errors="replace"), path.name


def test_메모리_초과면_반복_솔버로_새_업로드_새_잡을_낸다(fake: FakeSte, work: Path) -> None:
    def runner(folder: Path, params: dict[str, Any]) -> Outcome:
        if solve_module.ITERATIVE_LINE not in (folder / "model.inp").read_text():
            return Outcome("FAILED", None, "out_of_memory", max_rss_mb=2100.0)
        return finished(folder, params)

    fake.runner = runner
    done = _solve(work)
    assert len(fake.jobs) == 2 and len(fake.uploads) == 2, "업로드는 한 번만 쓴다"
    assert done.summary["linear_solver"] == "iterative"
    assert "반복 솔버로 다시" in str(done.summary["solver_retry"])
    states = [one["ste_state"] for one in ste.read_ledger(work)]
    assert states == ["OUT_OF_MEMORY", "COMPLETED"], "일반 FAILED 에 실린 메모리 초과를 갈랐다"


def test_시간_초과는_재시도하지_않고_timeout(fake: FakeSte, work: Path) -> None:
    fake.runner = lambda folder, params: Outcome("TIMEOUT", None, "timeout")
    with pytest.raises(StageFailure) as caught:
        _solve(work)
    assert caught.value.code == "timeout"
    assert len(fake.jobs) == 1


def test_ERROR_덱은_로컬과_같은_실패_문장으로_끝난다(
    fake: FakeSte, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = " *ERROR in material: no elastic constants\n"

    def broken(folder: Path, params: dict[str, Any]) -> Outcome:
        (folder / "ccx.out").write_text(log, encoding="utf-8")
        return Outcome("FAILED", 0, "ccx_error")

    fake.runner = broken
    with pytest.raises(StageFailure) as on_ste:
        _solve(work)

    def local(_binary: Path, args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout=log, stderr="")

    monkeypatch.setattr(tools, "run", local)
    monkeypatch.setattr(tools, "ccx_bin", lambda: Path("/usr/bin/ccx"))
    with pytest.raises(StageFailure) as on_local:
        solve_module.solve(work)
    assert (on_ste.value.code, on_ste.value.message) == (
        on_local.value.code,
        on_local.value.message,
    )


def test_오류를_안_적은_FAILED_는_STE_사정이라고_말한다(fake: FakeSte, work: Path) -> None:
    fake.runner = lambda folder, params: Outcome("NODE_FAIL", None, "node_fail")
    with pytest.raises(StageFailure) as caught:
        _solve(work)
    assert caught.value.code == "solver_failed"
    assert "NODE_FAIL" in caught.value.message


def test_모드_찾기는_다시_풀_때마다_STE_잡을_내고_고유치는_한_스레드다(
    fake: FakeSte, work: Path
) -> None:
    spectrum = tables.frequencies(DAT.read_text(encoding="utf-8"))
    deck = (
        "*NODE\n1, 0, 0, 0\n*STEP\n*FREQUENCY, SOLVER=SPOOLES\n3\n*NODE FILE\nU\n*END STEP\n"
    )
    (work / "model.inp").write_text(deck, encoding="utf-8")
    wanted = search.ModeSearch(800, 3000, 3, "spec")
    (work / "boundary.json").write_text(
        json.dumps({search.KEY: wanted.as_boundary()}), encoding="utf-8"
    )

    def modal(folder: Path, params: dict[str, Any]) -> Outcome:
        count = solve_module.asked_modes((folder / "model.inp").read_text(encoding="utf-8"))
        assert count is not None
        (folder / "model.dat").write_text(_eigen_table(spectrum[:count]), encoding="utf-8")
        (folder / "ccx.out").write_text("Job finished\n", encoding="utf-8")
        return Outcome("COMPLETED", 0)

    fake.runner = modal
    done = _solve(work)
    assert [one["equation_solver_threads"] for one in fake.submitted_params] == [1, 1]
    assert len(fake.jobs) == 2
    assert done.summary["mode_search"] == "800~3000 Hz · 2번 풀어 모드 6개까지"


def _eigen_table(values: list[float]) -> str:
    """`.dat` 의 고유치 표(`test_mode_search` 와 같은 꼴)."""
    rows = "\n".join(
        f"{at:7d}   0.1000000E+07   0.1000000E+04   {value:.7E}   0.0000000E+00"
        for at, value in enumerate(values, start=1)
    )
    return f"     E I G E N V A L U E   O U T P U T\n\n{rows}\n\n"


def test_큰_덱은_어림만큼_메모리를_청하고_상한을_넘으면_반복_솔버다(
    fake: FakeSte, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 자유도 16.5만 → SPOOLES 2,370 MB x 1.5 → 4 GB.
    nodes = "".join(f"{n}, 0, 0, 0\n" for n in range(2, 55_001))
    (work / "model.inp").write_text(
        STATIC_DECK.replace("2, 1, 0, 0\n", nodes), encoding="utf-8"
    )
    done = _solve(work)
    assert fake.submitted_params[-1]["mem_gb"] == 4
    assert done.summary["linear_solver"] == "spooles"
    monkeypatch.setenv(ste.MEM_MAX_ENV, "2")
    (work / "model.inp").write_text(
        STATIC_DECK.replace("2, 1, 0, 0\n", nodes), encoding="utf-8"
    )
    done = _solve(work)
    assert fake.submitted_params[-1]["mem_gb"] == 2
    assert done.summary["linear_solver"] == "iterative", "청할 수 있는 메모리를 넘었다"


# --- 명의(E-3) -------------------------------------------------------------------------------


def test_STE_설정이_없으면_로컬로_풀지_않고_ste_auth(
    fake: FakeSte, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ste.SECRET_ENV)
    with pytest.raises(StageFailure) as caught:
        _solve(work)
    assert caught.value.code == "ste_auth"
    assert not fake.jobs and not fake.mints


def test_건_사람이_없는_작업은_STE_를_못_쓴다(fake: FakeSte, work: Path) -> None:
    with pytest.raises(StageFailure) as caught:
        solve_module.solve(work, solve_on="ste", requester_email=None)
    assert caught.value.code == "ste_auth"
    assert not fake.mints


def test_STE_가_그_사람을_거절하면_그_문장을_그대로_보인다(fake: FakeSte, work: Path) -> None:
    fake.denied[ME] = "STE 사용 권한이 없습니다 — 포털에서 STE 권한을 청하세요"
    with pytest.raises(StageFailure) as caught:
        _solve(work)
    assert caught.value.code == "ste_auth"
    assert "포털에서 STE 권한을 청하세요" in caught.value.message
    assert not fake.jobs


def test_비밀이_틀리면_ste_auth_이고_다른_client_비밀로는_안_된다(
    fake: FakeSte, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.secrets["hwax-portal"] = "portal-secret"
    monkeypatch.setenv(ste.SECRET_ENV, "portal-secret")
    with pytest.raises(StageFailure) as caught:
        _solve(work)
    assert caught.value.code == "ste_auth"
    assert "401" in caught.value.message


def test_401_이면_한_번만_다시_받는다(fake: FakeSte, work: Path) -> None:
    """잡이 도는 사이 같은 client 로 누가 새로 받아 내 토큰이 죽었다 — 결과 받기가 401 을 받고
    한 번 다시 받아 이어 간다."""

    def revoked(folder: Path, params: dict[str, Any]) -> Outcome:
        fake.revoke(ME)
        return finished(folder, params)

    fake.runner = revoked
    _solve(work)
    assert fake.mints == [(ME, CLIENT)] * 2
    assert (work / "model.frd").is_file()


def test_다시_받아도_401_이면_ste_auth(
    fake: FakeSte, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fake, "_owner", lambda request: None)
    with pytest.raises(StageFailure) as caught:
        _solve(work)
    assert caught.value.code == "ste_auth"
    assert len(fake.mints) == 2, "다시 받기는 한 번뿐"


def test_워커끼리_토큰을_나눠_쓰고_서로_죽이지_않는다(fake: FakeSte, tmp_path: Path) -> None:
    """STE 는 같은 (사람, client)의 직전 토큰을 지운다 — 워커 둘이 저마다 받으면 서로를
    죽인다."""
    config = ste.SteConfig.from_env()
    http = ste.http_client()
    first = ste.SteSession(config, ME, http=http, tokens=ste.Tokens(config, http))
    second = ste.SteSession(config, ME, http=http, tokens=ste.Tokens(config, http))

    assert first.call("POST", "/api/uploads", what="t").status_code == 200
    assert second.call("POST", "/api/uploads", what="t").status_code == 200
    assert len(fake.mints) == 1, "두 번째 워커는 나눠 둔 토큰을 썼다"

    fake.revoke(ME)  # 포털 · 다른 기계가 같은 client 로 받았다
    assert first.call("POST", "/api/uploads", what="t").status_code == 200
    assert second.call("POST", "/api/uploads", what="t").status_code == 200
    assert len(fake.mints) == 2, "두 번째 워커는 첫 워커가 새로 받은 것을 이어 썼다"

    folder = tmp_path / "tokens"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    for saved in folder.glob("*.json"):
        assert stat.S_IMODE(saved.stat().st_mode) == 0o600
        assert ME not in saved.name, "파일 이름에 이메일을 싣지 않는다"


def test_남이_읽을_수_있는_토큰_폴더는_쓰지_않는다(
    fake: FakeSte, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    loose.chmod(0o755)
    monkeypatch.setenv(ste.TOKEN_DIR_ENV, str(loose))
    config = ste.SteConfig.from_env()
    assert ste.Tokens(config, ste.http_client()).directory is None


# --- STE 가 아프면 ----------------------------------------------------------------------


def test_제출이_5xx_면_ste_unavailable_4xx_면_ste_rejected(fake: FakeSte, work: Path) -> None:
    fake.fault("submit", 503)
    with pytest.raises(StageFailure) as down:
        _solve(work)
    assert down.value.code == "ste_unavailable"
    fake.fault("submit", 400)
    with pytest.raises(StageFailure) as refused:
        _solve(work)
    assert refused.value.code == "ste_rejected"
    assert "가짜 STE 고장" in refused.value.message, "STE 의 사유를 그대로 싣는다"


def test_상태를_잠깐_못_읽어도_기다리고_오래가면_ste_unavailable(
    fake: FakeSte, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.fault("status", 502, 502)
    assert _solve(work).summary["ste_jobs"] == 1
    monkeypatch.setenv(ste.POLL_GRACE_ENV, "0")
    fake.fault("status", 502, 502)
    with pytest.raises(StageFailure) as caught:
        _solve(work)
    assert caught.value.code == "ste_unavailable"


def test_시간_안에_안_끝나면_STE_에서_취소하고_timeout(fake: FakeSte, work: Path) -> None:
    fake.lazy = False  # 뒤에서 돈다 — 이 시험의 러너는 안 끝난다
    fake.runner = lambda folder, params: Outcome("COMPLETED", 0)
    fake._run = lambda job: None  # type: ignore[method-assign]
    with pytest.raises(StageFailure) as caught:
        _solve(work, timeout_seconds=0)
    assert caught.value.code == "timeout"
    assert [one.state for one in fake.jobs.values()] == ["CANCELLED"]


# --- 스펙 · 실행기 ----------------------------------------------------------------------


def test_풀_곳은_기본이_이_서버이고_STE_는_CalculiX_만() -> None:
    assert parse_spec({"recipe": "modal"}).solve_on == "local"
    assert parse_spec({"recipe": "static", "solve_on": "ste"}).solve_on == "ste"
    with pytest.raises(ValidationError):
        parse_spec({"recipe": "modal", "solver": "ansys", "solve_on": "ste"})
    with pytest.raises(ValidationError):
        parse_spec({"recipe": "modal", "solve_on": "cluster"})


def test_실행기는_건_사람을_명령줄로_비밀을_환경으로_준다(tmp_path: Path) -> None:
    options = SubprocessOptions(ste_env=((ste.SECRET_ENV, SECRET), (ste.BASE_URL_ENV, "u")))
    runner = SubprocessExecutor("local", options)
    ctx = StageContext(
        stage="solving",
        spec={"recipe": "static", "solver": "calculix", "solve_on": "ste"},
        workdir=tmp_path,
        requester_email=ME,
        requester_name="김해석",
    )
    command = runner.command(ctx)
    assert command[command.index("--requester-email") + 1] == ME
    assert command[command.index("--requester-name") + 1] == "김해석"
    assert SECRET not in " ".join(command), "비밀은 명령줄(ps)에 싣지 않는다"
    assert runner.child_env(ctx)[ste.SECRET_ENV] == SECRET
    plain = StageContext(stage="solving", spec={"recipe": "static"}, workdir=tmp_path)
    assert "--requester-email" not in runner.command(plain)
    assert ste.SECRET_ENV not in runner.child_env(plain), (
        "로컬로 푸는 단계에는 비밀을 싣지 않는다"
    )
    modeling = StageContext(stage="modeling", spec=ctx.spec, workdir=tmp_path)
    assert ste.SECRET_ENV not in runner.child_env(modeling), "솔브 밖 단계에도"


def test_대기열_요약은_있는_칸만_읽고_남은_코어를_셈한다() -> None:
    assert ste._queue(
        {"partition": "alpha", "cpus_total": 2944, "cpus_allocated": 2722, "nodes": [1, 2]}
    ) == {"partition": "alpha", "cpus_total": 2944, "cpus_allocated": 2722, "cpus_idle": 222}
    assert ste._queue({"summary": {"jobs_pending": 3, "mine": {"pending": 2}}}) == {
        "jobs_pending": 3,
        "mine": {"pending": 2},
    }
    assert ste._queue({"nodes": []}) is None
    assert ste._queue(["alpha"]) is None
