"""서버에서 고치는 해석 설정 — **재시작 없이**, 결과를 바꾸는 값은 **작업을 만들 때 고정**.

2026-11-25 에 들였다.

`config.py` 머리글의 3단이다: **서버 설정(`runtime_settings` 표) → 환경 · `.env`(`Settings`) →
기본값.** `.env` 에 적은 값은 앱을 다시 띄워야 들었다 — 해석을 조정하는 값은 서버 화면에서
고친다.

무엇이 여기 오나(`KNOBS`):

- **결과를 바꾸는 값**(`frozen`) — 본딩 방식 · 정적 선형 솔버 · 형상 맞춤 허용오차 · 점당
  스레드 수 · STE 잡 메모리 상한. **작업을 만들 때 그 작업의 `run_settings` 에 적는다** — 다시
  돌려도 같은 값, DOE 한 번의 점들은 같은 값. 고친 값은 그 뒤에 거는 작업부터 듣는다.
- **결과를 안 바꾸는 STE 연결** — 주소 · 앱 이름 · 폴링 간격 · 참는 시간. 단계가 시작할 때
  지금 값을 읽는다(고정하면 STE 주소가 옮긴 뒤 다시 돌려도 옛 주소로 간다).

무엇이 여기 안 오나: **기계마다 다른 사실**(`CCX_BIN` · `GMSH_BIN` · `OPENSOLVER_LD_PATH` —
워커마다 이미지 · 경로가 다른데 이 표는 모든 워커가 같이 본다)과 **비밀**(`STE_SSO_SECRET` —
화면 · DB 백업에 두지 않는다). 그것들은 환경 · `.env` 에
남는다(`simulations.services.machine_env` · `ste_env`).

코어는 이 표를 모른다 — 값은 단계 자식의 **환경 변수**로 간다(`env` 이름, `StageContext.env`).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.calculix import bonding, ste, tools
from app.core.calculix.build import BOOLEAN_TOLERANCE_ENV
from app.core.calculix.solve import LINEAR_SOLVER_ENV
from app.modules.accounts.models import User
from app.modules.server.models import RuntimeSetting
from app.shared import audit
from app.shared.errors import AppError, code

Kind = Literal["choice", "integer", "number", "url", "name"]
Source = Literal["server", "env", "default"]

#: 감사 기록의 일.
SETTING_UPDATED = "runtime_setting.updated"
SETTING_CLEARED = "runtime_setting.cleared"


@dataclass(frozen=True)
class Knob:
    """서버에서 고칠 수 있는 값 하나. `key` 는 `Settings` 칸 이름이자 표의 열쇠, `env` 는
    코어가 읽는 환경 이름."""

    key: str
    env: str
    label: str
    group: Literal["calculix", "ste"]
    kind: Kind
    default: str
    """비었을 때 코어가 쓰는 값 — 화면에 그대로 보인다. 빈 글자면 「코어가 정한다」."""
    help: str
    frozen: bool = True
    """결과를 바꾸는 값 — 작업을 만들 때 고정한다. 아니면 단계 시작 때 읽는다."""
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    child: bool = True
    """단계 자식에 환경으로 넘기나 — 워커가 읽는 값(STE 동시 한도)은 넘기지 않는다."""


#: STE 동시 작업 한도(요청서 E-6) — 워커가 작업을 집을 때 읽는다(`claim_next`). 자식에는
#: 안 간다.
INFLIGHT_ENV = "STE_SOLVE_MAX_INFLIGHT"
INFLIGHT_PER_USER_ENV = "STE_SOLVE_MAX_INFLIGHT_PER_USER"


KNOBS: tuple[Knob, ...] = (
    Knob(
        "calculix_bonding",
        bonding.BONDING_ENV,
        "본딩 방식",
        "calculix",
        "choice",
        "lever",
        "lever — 바디를 따로 메시하고 간극을 둔 채 구속식(기본). tie · shared 는 견줄 때만.",
        choices=bonding.BONDING_MODES,
    ),
    Knob(
        "calculix_linear_solver",
        LINEAR_SOLVER_ENV,
        "정적 선형 솔버",
        "calculix",
        "choice",
        "auto",
        "auto — 메모리를 어림해 넘칠 것 같으면 반복 솔버. 강체 묶음 · 원통 지지가 든 덱은 "
        "늘 직접 솔버.",
        choices=("auto", "spooles", "iterative"),
    ),
    Knob(
        "calculix_boolean_tolerance_mm",
        BOOLEAN_TOLERANCE_ENV,
        "형상 맞춤 허용오차",
        "calculix",
        "number",
        "",
        "이보다 작은 바디 사이 겹침 · 틈은 맞닿은 것으로 붙인다. 비우면 CompCore 의 "
        "「바디 사이 틈」, "
        "0 이면 끈다.",
        minimum=0.0,
        maximum=1.0,
        unit="mm",
    ),
    Knob(
        "omp_num_threads",
        tools.THREADS_ENV,
        "점당 스레드 수",
        "calculix",
        "integer",
        "2",
        "CalculiX 한 점의 스레드 수(STE 잡의 threads). DOE 여러 점을 동시에 풀므로 작게 둔다.",
        minimum=1,
        maximum=64,
    ),
    Knob(
        "ste_mem_gb_max",
        ste.MEM_MAX_ENV,
        "STE 잡 메모리 상한",
        "ste",
        "integer",
        str(ste.MEM_GB_MAX),
        "SPOOLES 어림 x 1.5 가 이것을 넘으면 정적은 반복 솔버로 푼다.",
        minimum=ste.MEM_GB_MIN,
        maximum=750,
        unit="GB",
    ),
    Knob(
        "ste_base_url",
        ste.BASE_URL_ENV,
        "STE 주소",
        "ste",
        "url",
        "",
        "`/api/…` 앞까지(포털 경로면 https://…/ste). 비우면 STE 를 못 고른다.",
        frozen=False,
    ),
    Knob(
        "ste_calculix_app",
        ste.APP_ENV,
        "STE 앱 이름",
        "ste",
        "name",
        ste.DEFAULT_APP,
        "STE 의 `apps/<id>` — CalculiX 2.21 SIF 를 부르는 앱.",
        frozen=False,
    ),
    Knob(
        "ste_poll_seconds",
        ste.POLL_ENV,
        "STE 상태를 묻는 간격",
        "ste",
        "number",
        f"{ste.POLL_SECONDS:g}",
        "잡이 끝났나 묻는 간격.",
        frozen=False,
        minimum=1.0,
        maximum=600.0,
        unit="초",
    ),
    Knob(
        "ste_poll_grace_seconds",
        ste.POLL_GRACE_ENV,
        "STE 응답을 기다리는 시간",
        "ste",
        "number",
        f"{ste.POLL_GRACE_SECONDS:g}",
        "상태를 못 읽어도 이만큼은 참는다 — STE 재기동 한 번에 해석을 버리지 않게.",
        frozen=False,
        minimum=0.0,
        maximum=3600.0,
        unit="초",
    ),
    Knob(
        "ste_solve_max_inflight",
        INFLIGHT_ENV,
        "STE 동시 작업 한도",
        "ste",
        "integer",
        "0",
        "이 서버 전체에서 동시에 도는 STE 작업 수. 넘는 것은 이 서버 대기열에서 기다린다. "
        "0 이면 한도 없음(워커 수가 곧 한도).",
        frozen=False,
        minimum=0,
        maximum=10000,
        unit="개",
        child=False,
    ),
    Knob(
        "ste_solve_max_inflight_per_user",
        INFLIGHT_PER_USER_ENV,
        "STE 사람별 동시 작업 한도",
        "ste",
        "integer",
        "0",
        "한 사람이 동시에 돌리는 STE 작업 수 — DOE 한 번이 그 사람의 STE 몫을 다 쓰지 "
        "않게. 0 이면 한도 없음.",
        frozen=False,
        minimum=0,
        maximum=10000,
        unit="개",
        child=False,
    ),
)
BY_KEY: dict[str, Knob] = {knob.key: knob for knob in KNOBS}
FROZEN: tuple[str, ...] = tuple(knob.key for knob in KNOBS if knob.frozen)

_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")


def normalize(knob: Knob, raw: str) -> str:
    """받은 글자 → 저장할 글자. **틀리면 `ValueError`(사람이 읽을 한 줄).**"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("값이 비었습니다 — 되돌리려면 「기본으로」 를 누르세요.")
    if knob.kind == "choice":
        if text.lower() not in knob.choices:
            raise ValueError(f"{' · '.join(knob.choices)} 중 하나여야 합니다.")
        return text.lower()
    if knob.kind in ("integer", "number"):
        try:
            number = float(text)
        except ValueError:
            raise ValueError("수가 아닙니다.") from None
        if knob.kind == "integer" and number != int(number):
            raise ValueError("정수여야 합니다.")
        low = knob.minimum if knob.minimum is not None else float("-inf")
        high = knob.maximum if knob.maximum is not None else float("inf")
        if not low <= number <= high:
            raise ValueError(f"{low:g} ~ {high:g} {knob.unit}".rstrip() + " 안이어야 합니다.")
        return str(int(number)) if knob.kind == "integer" else f"{number:g}"
    if knob.kind == "url":
        if not re.fullmatch(r"https?://[^\s]+", text):
            raise ValueError("http:// 나 https:// 로 시작하는 주소여야 합니다.")
        return text.rstrip("/")
    if not _NAME.fullmatch(text):
        raise ValueError("영문 · 숫자 · . _ - 로 64자 안이어야 합니다.")
    return text


@dataclass(frozen=True)
class Effective:
    """한 값이 지금 무엇이고 어디서 왔나."""

    knob: Knob
    value: str
    source: Source
    server: str | None
    env: str | None
    problem: str | None = None
    """환경 · `.env` 의 값이 틀려 기본값을 쓰는 까닭 — 화면에 보인다."""
    updated_at: datetime | None = None
    updated_by_id: uuid.UUID | None = None


def _from_env(settings: Settings, knob: Knob) -> str | None:
    """환경 · `.env` 가 준 값 — **안 준 칸은 `None`**. 준 것은 환경 · `.env` 에서
    읽었거나(`model_fields_set`) `Settings` 의 기본값과 다른 것이다."""
    raw = getattr(settings, knob.key)
    if (
        knob.key not in settings.model_fields_set
        and raw == Settings.model_fields[knob.key].default
    ):
        return None
    text = f"{raw:g}" if isinstance(raw, float) else str(raw if raw is not None else "")
    return text.strip() or None


def effective(db: Session, settings: Settings | None = None) -> dict[str, Effective]:
    """열쇠마다 지금 값 — 서버 설정 → 환경 · `.env` → 기본값."""
    settings = settings or get_settings()
    rows = {row.key: row for row in db.scalars(select(RuntimeSetting))}
    found: dict[str, Effective] = {}
    for knob in KNOBS:
        row = rows.get(knob.key)
        given = _from_env(settings, knob)
        if row is not None:
            found[knob.key] = Effective(
                knob,
                row.value,
                "server",
                row.value,
                given,
                None,
                row.updated_at,
                row.updated_by_id,
            )
            continue
        if given is not None:
            try:
                found[knob.key] = Effective(knob, normalize(knob, given), "env", None, given)
                continue
            except ValueError as failure:
                problem = (
                    f"환경 · .env 의 {knob.env}={given!r} 가 틀려 기본값을 씁니다: {failure}"
                )
                found[knob.key] = Effective(
                    knob, knob.default, "default", None, given, problem
                )
                continue
        found[knob.key] = Effective(knob, knob.default, "default", None, None)
    return found


def snapshot(db: Session, settings: Settings | None = None) -> dict[str, str]:
    """**작업을 만들 때 고정할 값** — 결과를 바꾸는 열쇠(`frozen`)의 지금 값."""
    now = effective(db, settings)
    return {key: now[key].value for key in FROZEN}


def env_pairs(values: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """열쇠 → 값을 코어가 읽는 환경 이름으로. 빈 값은 싣지 않는다(코어의 기본값)."""
    return tuple(
        (BY_KEY[key].env, value)
        for key, value in values.items()
        if key in BY_KEY and BY_KEY[key].child and value
    )


def _knob(key: str) -> Knob:
    knob = BY_KEY.get(key)
    if knob is None:
        raise AppError(
            code("SERVER", 1),
            f"서버에서 고칠 수 없는 설정입니다: {key}",
            status=404,
            details={"keys": list(BY_KEY)},
        )
    return knob


def update(db: Session, *, user: User, key: str, raw: str) -> Effective:
    """한 값을 서버 설정으로 둔다. **결과를 바꾸는 값은 그 뒤에 거는 작업부터 듣는다.**"""
    knob = _knob(key)
    try:
        value = normalize(knob, raw)
    except ValueError as failure:
        raise AppError(
            code("SERVER", 2), f"{knob.label}: {failure}", status=400, details={"key": key}
        ) from failure
    before = effective(db)[key]
    row = db.get(RuntimeSetting, key)
    if row is None:
        row = RuntimeSetting(key=key, value=value, updated_by_id=user.id)
        db.add(row)
    else:
        row.value = value
        row.updated_by_id = user.id
    audit.record(
        db,
        action=SETTING_UPDATED,
        actor=user,
        target_table="runtime_settings",
        target_id=None,
        target_label=key,
        changes={"before": before.value, "before_source": before.source, "after": value},
    )
    db.commit()
    return effective(db)[key]


def clear(db: Session, *, user: User, key: str) -> Effective:
    """서버 설정을 지운다 — 환경 · `.env` · 기본값으로 돌아간다."""
    knob = _knob(key)
    row = db.get(RuntimeSetting, knob.key)
    if row is not None:
        audit.record(
            db,
            action=SETTING_CLEARED,
            actor=user,
            target_table="runtime_settings",
            target_id=None,
            target_label=key,
            changes={"before": row.value},
        )
        db.delete(row)
        db.commit()
    return effective(db)[key]
