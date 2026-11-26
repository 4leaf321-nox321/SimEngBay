"""E-7 회귀 — **같은 덱을 이 서버와 STE 로 풀면 같은가**(요청서 2026-11-24 E-7 · 받아들임 2).

    python scripts/ste_regression.py --fake                       # 가짜 STE 로 틀만
    python scripts/ste_regression.py --email kim.cae@corp.example # 진짜 STE(.env 의 STE_*)
    python scripts/ste_regression.py --fake --only 조건_측면가진 --points 1 --element-size 6

`tests/fixtures/doe` 의 설계점마다 메시 · 덱을 **한 번만** 만들고(이 서버), 그 폴더를 둘로 떠서
솔브 · 추출만 이 서버와 STE 로 따로 푼다 — 덱이 같으니 다른 것은 ccx 빌드 · BLAS · 노드뿐이다.

받아들임(요청서 E-7):

- 고유진동수는 `.dat` 에 찍힌 자릿수까지 같다(`tables.frequencies`).
- 결과(`result.json` 의 수 — 변위 · 응력 · 반력 · 질량 …)는 상대차 1e-6 안이다(STE 의 시간 ·
  잡 기록 칸은 뺀다).
- 판정(성공 · 실패 · 실패 코드 · 실패 문장)이 같다.

진짜 STE 로 돌리려면 `.env`(또는 환경)에 `STE_BASE_URL` · `STE_SSO_SECRET` 이 있어야 하고, 잡은
`--email` 의 사람 명의로 낸다(그 사람이 STE 권한을 가져야 한다 — 요청서 P-2). `--fake` 는 가짜
STE 를 이 프로세스에 띄워 이 기계의 ccx 로 푼다 — 틀이 맞는지 보는 용도(늘 같아야 한다).

보고는 `--out`(기본 임시 폴더)의 `report.json` 과 표준 출력의 표. 종료 코드: 모두 같으면 0,
하나라도 다르면 1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.core.calculix import ste, tables
from app.core.doe.folder import DoePoint, read_folder
from app.core.run import run_stage
from app.core.spec import parse_spec
from app.core.stages import MIDSURFACE_NAME, StageFailure

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "doe"
INPUT_NAME = "input.step"
#: 결과의 수 가운데 견주지 않는 칸 — 어디서 · 얼마나 걸려 풀었나(같을 까닭이 없다).
SKIP_KEYS = re.compile(
    r"(seconds|elapsed|_at$|^at$|time|ste_|solved_on|path|file|host|worker|version|threads)",
    re.IGNORECASE,
)
REL_TOLERANCE = 1e-6
#: 이 틀이 이 프로세스에 심는 STE 환경 — 끝나면 되돌린다.
STE_ENV = (
    ste.BASE_URL_ENV,
    ste.SECRET_ENV,
    ste.CLIENT_ENV,
    ste.APP_ENV,
    ste.POLL_ENV,
    ste.TOKEN_DIR_ENV,
)


@dataclass
class Outcome:
    """한 쪽(이 서버 · STE)의 끝."""

    ok: bool
    code: str = ""
    message: str = ""
    frequencies: list[float] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0


@dataclass
class Row:
    folder: str
    point: int
    recipe: str
    same: bool | None
    """`None` 은 견주지 못함(메시 · 덱을 못 만들었다)."""
    differences: list[str] = field(default_factory=list)
    local: Outcome | None = None
    ste: Outcome | None = None
    note: str = ""


def _recipe(point_file: Path) -> str:
    payload = json.loads(point_file.read_text(encoding="utf-8"))
    kind = str(((payload.get("conditions") or {}).get("analysis") or {}).get("type") or "")
    return kind if kind in ("modal", "static", "harmonic", "random") else "modal"


def _spec(recipe: str, element_size: float | None, *, on_ste: bool) -> dict[str, Any]:
    spec: dict[str, Any] = {"recipe": recipe, "solver": "calculix"}
    if element_size:
        spec["mesh"] = {"element_size_mm": element_size}
    if on_ste:
        spec["solve_on"] = "ste"
    parse_spec(spec)  # 틀린 스펙이면 여기서 멈춘다
    return spec


def _stage(stage: str, spec: dict[str, Any], workdir: Path, email: str | None) -> Any:
    return run_stage(
        stage,  # type: ignore[arg-type]
        parse_spec(spec),
        workdir,
        input_name=INPUT_NAME,
        version=252,
        ansys_root=None,
        solver_processes=2,
        timeout_seconds=6 * 3600,
        visual_modes=6,
        requester_email=email,
    )


def _prepare(point: DoePoint, base: Path, spec: dict[str, Any], checks: Any) -> Path:
    """이 서버 쪽 폴더 — 형상 · 지문 · 스펙을 놓고 형상 확인 · 모델링까지."""
    from app.modules.simulations.services import _with_checks

    here = base / "local"
    here.mkdir(parents=True)
    assert point.step is not None and point.point_file is not None
    shutil.copy(point.step, here / INPUT_NAME)
    topology = point.point_file.read_bytes()
    if checks:
        topology = _with_checks(topology, checks)
    (here / "topology.json").write_bytes(topology)
    if point.mid_step is not None:
        shutil.copy(point.mid_step, here / MIDSURFACE_NAME)
    (here / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    for stage in ("fetching", "modeling"):
        _stage(stage, spec, here, None)
    return here


def _solve(workdir: Path, spec: dict[str, Any], email: str | None) -> Outcome:
    began = time.monotonic()
    try:
        for stage in ("solving", "extracting"):
            _stage(stage, spec, workdir, email)
    except StageFailure as failure:
        return Outcome(False, failure.code, failure.message, seconds=time.monotonic() - began)
    dat = workdir / "model.dat"
    found = workdir / "result.json"
    return Outcome(
        True,
        frequencies=tables.frequencies(dat.read_text(encoding="utf-8"))
        if dat.is_file()
        else [],
        result=json.loads(found.read_text(encoding="utf-8")) if found.is_file() else {},
        seconds=time.monotonic() - began,
    )


def _leaves(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, inner in value.items():
            if SKIP_KEYS.search(str(key)):
                continue
            yield from _leaves(inner, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield from _leaves(inner, f"{path}[{index}]")
    else:
        yield path, value


def compare(local: Outcome, remote: Outcome) -> list[str]:
    """받아들임 셋 — 다른 것을 사람이 읽을 줄로. 비면 같다."""
    if (local.ok, local.code, local.message) != (remote.ok, remote.code, remote.message):
        return [
            f"판정: 이 서버 {local.code or '성공'}({local.message[:80]}) ↔ STE "
            f"{remote.code or '성공'}({remote.message[:80]})"
        ]
    if not local.ok:
        return []
    found: list[str] = []
    if local.frequencies != remote.frequencies:
        found.append(f"고유진동수: {local.frequencies[:6]} ↔ {remote.frequencies[:6]}")
    ours, theirs = dict(_leaves(local.result)), dict(_leaves(remote.result))
    vectors = _scales(ours, theirs, _vector_of)
    groups = _scales(ours, theirs, _group_of)
    for key in sorted(set(ours) | set(theirs)):
        a, b = ours.get(key), theirs.get(key)
        if _number(a) and _number(b):
            assert isinstance(a, int | float) and isinstance(b, int | float)
            # **0 에 가까운 성분은 그 벡터의 크기로 견준다** — 반력 x 가 -3.3e-10 ↔ -3.6e-10 N
            # 인 것은 같은 답의 잡음이다(실측: SPOOLES 여러 스레드는 끝자리가 돌 때마다
            # 다르다). 벡터가 통째로 잡음이면(하중 없는 지지) 같은 칸의 큰 값으로.
            scale = max(abs(a), abs(b), vectors.get(_vector_of(key), 0.0))
            allowed = REL_TOLERANCE * scale + FLOOR * groups.get(_group_of(key), 0.0)
            if abs(a - b) > allowed:
                found.append(f"{key}: {a!r} ↔ {b!r}")
        elif a != b:
            found.append(f"{key}: {a!r} ↔ {b!r}")
    return found


#: 벡터가 통째로 잡음일 때 — 같은 칸(맨 위 열쇠)의 가장 큰 값에 대한 몫.
FLOOR = 1e-9


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _vector_of(key: str) -> str:
    """`reactions.구멍[2]` → `reactions.구멍` — 같은 목록의 성분끼리."""
    return re.sub(r"\[\d+\]$", "", key)


def _group_of(key: str) -> str:
    """`reactions.구멍[2]` → `reactions` — 같은 양(단위)끼리."""
    return re.split(r"[.\[]", key, maxsplit=1)[0]


def _scales(
    ours: dict[str, Any], theirs: dict[str, Any], key_of: Callable[[str], str]
) -> dict[str, float]:
    """묶음(`key_of`) → 두 쪽을 통틀은 가장 큰 크기."""
    found: dict[str, float] = {}
    for side in (ours, theirs):
        for key, value in side.items():
            if _number(value):
                name = key_of(key)
                found[name] = max(found.get(name, 0.0), abs(float(value)))
    return found


def run_point(
    folder: str,
    point: DoePoint,
    root: Path,
    *,
    checks: Any,
    element_size: float | None,
    email: str,
) -> Row:
    assert point.point_file is not None
    recipe = _recipe(point.point_file)
    base = root / folder / f"p{point.number:04d}"
    local_spec = _spec(recipe, element_size, on_ste=False)
    try:
        here = _prepare(point, base, local_spec, checks)
    except StageFailure as failure:
        return Row(
            folder, point.number, recipe, None, note=f"덱을 못 만들었다: {failure.message}"
        )
    there = base / "ste"
    shutil.copytree(here, there)
    ste_spec = _spec(recipe, element_size, on_ste=True)
    (there / "spec.json").write_text(
        json.dumps(ste_spec, ensure_ascii=False), encoding="utf-8"
    )
    local = _solve(here, local_spec, None)
    remote = _solve(there, ste_spec, email)
    differences = compare(local, remote)
    return Row(folder, point.number, recipe, not differences, differences, local, remote)


def _points(only: list[str], numbers: list[int]) -> Iterator[tuple[str, Any, DoePoint]]:
    for path in sorted(FIXTURES.iterdir()):
        if not path.is_dir() or (only and path.name not in only):
            continue
        try:
            doe = read_folder(path)
        except Exception as failure:  # 폴더 꼴이 아닌 것(시험규격 묶음 등)
            print(f"건너뜀 {path.name}: {failure}", file=sys.stderr)
            continue
        for point in doe.points:
            if point.usable and (not numbers or point.number in numbers):
                yield path.name, doe.checks, point


def _use_fake(root: Path) -> tuple[Any, str]:
    from tests.fake_ste import CLIENT, FakeSte, serve

    fake = FakeSte(secrets_by_client={CLIENT: "fake-ste-secret"}, lazy=False)
    server, url = serve(fake)
    os.environ.update(
        {
            ste.BASE_URL_ENV: url,
            ste.SECRET_ENV: "fake-ste-secret",
            ste.CLIENT_ENV: CLIENT,
            ste.POLL_ENV: "0.2",
            ste.TOKEN_DIR_ENV: str(root / "tokens"),
        }
    )
    return server, url


def _use_real(base_url: str | None) -> str:
    settings = get_settings()
    values = {
        ste.BASE_URL_ENV: (base_url or settings.ste_base_url).strip().rstrip("/"),
        ste.SECRET_ENV: settings.ste_sso_secret.strip(),
        ste.CLIENT_ENV: settings.ste_sso_client.strip(),
        ste.APP_ENV: settings.ste_calculix_app.strip(),
    }
    missing = [name for name in (ste.BASE_URL_ENV, ste.SECRET_ENV) if not values[name]]
    if missing:
        raise SystemExit(f"진짜 STE 로 돌리려면 {' · '.join(missing)} 가 있어야 합니다(.env).")
    for name, value in values.items():
        os.environ.setdefault(name, value)
    return values[ste.BASE_URL_ENV]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="E-7 — 같은 덱을 이 서버와 STE 로 풀어 견준다"
    )
    parser.add_argument("--fake", action="store_true", help="가짜 STE(이 기계의 ccx)로")
    parser.add_argument("--email", help="진짜 STE 에 잡을 낼 사람(그 사람 명의)")
    parser.add_argument("--base-url", help="STE 주소(비우면 .env 의 STE_BASE_URL)")
    parser.add_argument("--only", nargs="*", default=[], help="이 폴더들만")
    parser.add_argument("--points", nargs="*", type=int, default=[], help="이 점 번호만")
    parser.add_argument("--element-size", type=float, help="메시 크기(mm) — 빨리 돌릴 때")
    parser.add_argument("--out", type=Path, help="작업 폴더 · 보고(비우면 임시 폴더)")
    args = parser.parse_args(argv)

    root = args.out or Path(tempfile.mkdtemp(prefix="ste-regression-"))
    root.mkdir(parents=True, exist_ok=True)
    # **STE 환경은 끝나면 되돌린다** — 이 프로세스에서 뒤에 띄우는 자식(같은 시험 세션의 다른
    # 시험)이 내린 가짜 STE 주소를 물려받으면 「닿지 못함」 으로 깨진다(실측 2026-11-27).
    saved = {name: os.environ.get(name) for name in STE_ENV}
    server = None
    if args.fake:
        server, where = _use_fake(root)
        email = args.email or "regression@fake-ste.example"
    else:
        if not args.email:
            raise SystemExit("진짜 STE 로 돌리려면 --email(잡을 낼 사람)을 주세요.")
        where, email = _use_real(args.base_url), args.email
    print(f"STE {where} · {email} 명의 · 폴더 {root}", flush=True)

    rows: list[Row] = []
    try:
        for folder, checks, point in _points(args.only, args.points):
            row = run_point(
                folder, point, root, checks=checks, element_size=args.element_size, email=email
            )
            rows.append(row)
            mark = {True: "같음", False: "다름", None: "못 견줌"}[row.same]
            took = (
                f" · 이 서버 {row.local.seconds:.0f}초 · STE {row.ste.seconds:.0f}초"
                if row.local and row.ste
                else ""
            )
            print(f"{mark:6} {folder} p{point.number:04d} ({row.recipe}){took}", flush=True)
            for line in row.differences[:5] or ([row.note] if row.note else []):
                print(f"         {line}", flush=True)
    finally:
        if server is not None:
            server.shutdown()
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    report = root / "report.json"
    report.write_text(
        json.dumps([asdict(one) for one in rows], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    differ = [one for one in rows if one.same is False]
    print(
        f"\n{len(rows)}점 — 같음 {sum(one.same is True for one in rows)} · "
        f"다름 {len(differ)} · 못 견줌 {sum(one.same is None for one in rows)}. 보고 {report}",
        flush=True,
    )
    return 1 if differ else 0


if __name__ == "__main__":
    raise SystemExit(main())
