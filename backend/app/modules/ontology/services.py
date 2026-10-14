"""온톨로지 수신을 **언제 · 누가** 돌리나, 그리고 받아 둔 것을 읽는 자리.

수신은 두 길로 시작한다 — 둘 다 같은 `execute` 를 지난다:

- **타이머**: `<slug>-sync.timer`(deploy.sh 가 설치)가 5분마다 `scripts/sync_ontology.py --due`
  를 부른다. 차례(`ontology_sync_minutes`, 기본 하루)가 됐을 때만 받는다.
- **화면**: 시스템 관리자의 「지금 받기」. 새벽 수신이 실패했을 때 다음 날까지 기다리지 않게
  (지침서 §12-A 1 — 야간 1회 + 수동 실행을 함께 둔다).

**한 번에 하나만 돈다** — DB 자문 잠금(`pg_try_advisory_lock`)이 막는다. 두 서버의 타이머가
같은 시각에 돌거나, 타이머와 화면이 겹쳐도 한쪽만 받고 다른 쪽은 「건너뜀」 으로 적힌다.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import SessionLocal, engine
from app.modules.accounts.models import User
from app.modules.ontology import sync
from app.modules.ontology.models import (
    OntologyObject,
    OntologyRelation,
    OntologySyncRun,
    OntologyType,
)
from app.shared import audit
from app.shared.errors import AppError, NotFound, code

logger = logging.getLogger(__name__)

#: 자문 잠금 번호 — 이 설치에서 온톨로지 수신만 쓴다.
LOCK_KEY = 0x5EB0_0710
#: 「도는 중」 으로 남은 기록을 이만큼 지나면 죽은 것으로 본다(프로세스가 죽으면 기록이
#: 남는다).
STALE_AFTER = timedelta(hours=3)


def configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(
        settings.ontology_source_url.strip() and settings.ontology_source_token.strip()
    )


def make_client(settings: Settings | None = None) -> sync.CoreClient:
    """SP 클라이언트 — 시험은 이 함수를 갈아 가짜 SP 를 붙인다."""
    settings = settings or get_settings()
    return sync.CoreClient(settings.ontology_source_url, settings.ontology_source_token)


#: 수신을 어디서 돌리나. 화면의 「지금 받기」 는 요청을 붙잡지 않게 실을 띄운다 — 시험은 이
#: 자리를 갈아 그 자리에서 돌린다.
def spawn(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="ontology-sync", daemon=True).start()


@contextmanager
def held_lock() -> Iterator[bool]:
    """수신 잠금 — 잡았으면 `True`. 잡은 연결이 닫히면 잠금도 풀린다(죽어도 남지 않는다)."""
    with engine.connect() as connection:
        got = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}
            ).scalar()
        )
        try:
            yield got
        finally:
            if got:
                connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})


def _now() -> datetime:
    return datetime.now(UTC)


def running(db: Session, now: datetime | None = None) -> OntologySyncRun | None:
    """지금 도는 수신 — 오래된 「도는 중」 은 죽은 것으로 보고 안 센다."""
    now = now or _now()
    return db.scalar(
        select(OntologySyncRun)
        .where(
            OntologySyncRun.status == "running",
            OntologySyncRun.started_at > now - STALE_AFTER,
        )
        .order_by(OntologySyncRun.started_at.desc())
        .limit(1)
    )


def last_finished(db: Session) -> OntologySyncRun | None:
    return db.scalar(
        select(OntologySyncRun)
        .where(OntologySyncRun.status.in_(("ok", "partial", "failed")))
        .order_by(OntologySyncRun.started_at.desc())
        .limit(1)
    )


def next_due(
    db: Session, settings: Settings | None = None, now: datetime | None = None
) -> datetime | None:
    """타이머가 다음에 받을 때. 주기가 0 이거나 설정이 없으면 `None`(화면으로만 받는다).
    한 번도 안 받았으면 지금이다 — 부른 쪽의 `now` 를 그대로 쓴다(따로 시계를 읽으면 그만큼
    늦어 「아직」 으로 읽힌다)."""
    settings = settings or get_settings()
    if settings.ontology_sync_minutes <= 0 or not configured(settings):
        return None
    last = last_finished(db)
    if last is None or last.finished_at is None:
        return now or _now()
    return last.finished_at + timedelta(minutes=settings.ontology_sync_minutes)


def due(db: Session, settings: Settings | None = None, now: datetime | None = None) -> bool:
    now = now or _now()
    when = next_due(db, settings, now)
    return when is not None and when <= now


def start(
    db: Session, *, trigger: str, actor: User | None = None, full: bool = False
) -> OntologySyncRun:
    """수신 기록을 하나 연다 — 실제로 받는 일은 `execute` 가 한다."""
    if not configured():
        raise AppError(
            code("ONTOLOGY", 1),
            "Standard Platform 주소 · 토큰이 설정되지 않았습니다 — 서버의 .env 에 "
            "ONTOLOGY_SOURCE_URL · ONTOLOGY_SOURCE_TOKEN(범위 core:read)을 적습니다.",
            status=400,
        )
    busy = running(db)
    if busy is not None:
        raise AppError(
            code("ONTOLOGY", 2),
            "다른 수신이 도는 중입니다 — 끝난 뒤에 다시 받으세요.",
            status=409,
            details={"run_id": str(busy.id)},
        )
    record = OntologySyncRun(trigger=trigger, full=full, actor_id=actor.id if actor else None)
    db.add(record)
    db.commit()
    return record


def execute(
    run_id: uuid.UUID,
    *,
    client: sync.CoreClient | None = None,
    settings: Settings | None = None,
) -> None:
    """수신 한 번을 끝까지 — 자기 세션을 연다(요청 밖의 실에서도 돈다).

    잠금을 못 잡으면 「건너뜀」 으로 적고 끝난다. 카탈로그부터 못 읽으면 「실패」 와 그 까닭.
    무엇이 되든 끝난 시각을 적는다 — 「도는 중」 으로 남은 기록은 다음 수신을 막는다.
    """
    settings = settings or get_settings()
    with SessionLocal() as db, held_lock() as got:
        record = db.get(OntologySyncRun, run_id)
        if record is None:
            return
        if not got:
            record.status = "skipped"
            record.error = "다른 수신이 잠금을 쥐고 있어 이번 차례는 건너뛰었습니다."
            record.finished_at = _now()
            db.commit()
            return
        owned = client is None
        try:
            client = client or make_client(settings)
            full_every = (
                timedelta(days=settings.ontology_full_days)
                if settings.ontology_full_days > 0
                else None
            )
            sync.run(db, client, record, now=_now(), full=record.full, full_every=full_every)
        except sync.CoreError as failure:
            db.rollback()
            record.status = "failed"
            record.error = failure.message + (
                f" (SP 요청 번호 {failure.request_id})" if failure.request_id else ""
            )
            logger.warning("온톨로지 수신 실패: %s", record.error)
        except Exception as failure:  # pragma: no cover - 뜻밖의 실패도 기록은 닫는다
            db.rollback()
            record.status = "failed"
            record.error = f"뜻밖의 오류: {failure}"
            logger.exception("온톨로지 수신 중 뜻밖의 오류")
        finally:
            if owned and client is not None:
                client.close()
        record.finished_at = _now()
        actor = db.get(User, record.actor_id) if record.actor_id else None
        audit.record(
            db,
            action="ontology.sync",
            actor=actor,
            target_table="ontology_sync_runs",
            target_id=record.id,
            target_label=f"온톨로지 수신({record.trigger}) — {record.status}",
            changes={"status": record.status, "revision": record.revision},
            reason=record.error or None,
        )
        db.commit()


# --- 읽기 ---------------------------------------------------------------------------------


def type_counts(db: Session) -> dict[str, dict[str, int]]:
    """타입마다 받은 객체 수(살아 있음 · 꺼짐)와 그 타입에서 출발하는 선 수."""
    found: dict[str, dict[str, int]] = {}
    for slug, active, count in db.execute(
        select(OntologyObject.type_slug, OntologyObject.active, func.count()).group_by(
            OntologyObject.type_slug, OntologyObject.active
        )
    ):
        found.setdefault(slug, {"active": 0, "inactive": 0, "relations": 0})[
            "active" if active else "inactive"
        ] = int(count)
    for slug, count in db.execute(
        select(OntologyRelation.src_type, func.count()).group_by(OntologyRelation.src_type)
    ):
        found.setdefault(slug, {"active": 0, "inactive": 0, "relations": 0})["relations"] = (
            int(count)
        )
    return found


def get_type(db: Session, slug: str) -> OntologyType:
    kind = db.get(OntologyType, slug)
    if kind is None:
        raise NotFound(code("ONTOLOGY", 3), f"받아 둔 타입이 아닙니다: {slug}")
    return kind


def objects(
    db: Session,
    slug: str,
    *,
    q: str = "",
    include_inactive: bool = False,
    limit: int,
    offset: int,
) -> tuple[list[OntologyObject], int]:
    stmt = select(OntologyObject).where(OntologyObject.type_slug == slug)
    if not include_inactive:
        stmt = stmt.where(OntologyObject.active.is_(True))
    words = q.strip()
    if words:
        like = f"%{words}%"
        stmt = stmt.where(
            or_(OntologyObject.key.ilike(like), OntologyObject.label.ilike(like))
        )
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        db.scalars(
            stmt.order_by(OntologyObject.label, OntologyObject.key).limit(limit).offset(offset)
        )
    )
    return rows, total


def one_object(db: Session, slug: str, key: str) -> OntologyObject:
    row = db.scalar(
        select(OntologyObject).where(
            OntologyObject.type_slug == slug, OntologyObject.key == key
        )
    )
    if row is None:
        raise NotFound(code("ONTOLOGY", 4), f"「{key}」 은 {slug} 에 없습니다.")
    return row


def edges(
    db: Session, slug: str, key: str
) -> tuple[list[OntologyRelation], list[OntologyRelation]]:
    """나가는 선 · 들어오는 선."""
    outgoing = list(
        db.scalars(
            select(OntologyRelation)
            .where(OntologyRelation.src_type == slug, OntologyRelation.src_key == key)
            .order_by(OntologyRelation.relation, OntologyRelation.dst_key)
        )
    )
    incoming = list(
        db.scalars(
            select(OntologyRelation)
            .where(OntologyRelation.dst_type == slug, OntologyRelation.dst_key == key)
            .order_by(OntologyRelation.relation, OntologyRelation.src_key)
        )
    )
    return outgoing, incoming


def labels_for(db: Session, pairs: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """(타입, key) → 이름 — 선의 끝점을 사람 말로 보이려고."""
    if not pairs:
        return {}
    keys = {key for _, key in pairs}
    found: dict[tuple[str, str], str] = {}
    for slug, key, label in db.execute(
        select(OntologyObject.type_slug, OntologyObject.key, OntologyObject.label).where(
            OntologyObject.key.in_(keys)
        )
    ):
        if (slug, key) in pairs:
            found[(slug, key)] = label
    return found


def _references(kind: OntologyType) -> dict[str, str]:
    """참조 칸 → 가리키는 타입(카탈로그의 `object_ref` · `ref_type_slug`)."""
    return {
        str(one["key"]): str(one["ref_type_slug"])
        for one in kind.properties or []
        if one.get("data_type") == "object_ref" and one.get("ref_type_slug") and one.get("key")
    }


def _ref_values(row: OntologyObject, references: dict[str, str]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for prop, ref_type in references.items():
        value = (row.properties or {}).get(prop)
        for one in value if isinstance(value, list) else [value]:
            if isinstance(one, str) and one:
                found.add((ref_type, one))
    return found


def ref_labels(
    db: Session, kind: OntologyType, rows: list[OntologyObject]
) -> dict[tuple[str, str], str]:
    """그 행들의 참조 값 → 이름. 참조 칸의 값은 **보낼 때의 `key`** 라, 가리키는 쪽의 식별자가
    나중에 바뀌면 옛 값으로 남는다 — 그때는 `previous_keys` 로 풀어 찾는다(규칙 10)."""
    references = _references(kind)
    wanted: set[tuple[str, str]] = set()
    for row in rows:
        wanted |= _ref_values(row, references)
    found = labels_for(db, wanted)
    for ref_type, key in sorted(wanted - found.keys()):
        renamed = db.scalar(
            select(OntologyObject.label)
            .where(
                OntologyObject.type_slug == ref_type,
                OntologyObject.previous_keys.contains([key]),
            )
            .limit(1)
        )
        if renamed is not None:
            found[(ref_type, key)] = renamed
    return found


def row_ref_labels(
    kind: OntologyType, row: OntologyObject, found: dict[tuple[str, str], str]
) -> dict[str, str]:
    """한 행의 참조 값 → 이름(못 찾은 것은 뺀다)."""
    return {
        key: found[(ref_type, key)]
        for ref_type, key in _ref_values(row, _references(kind))
        if (ref_type, key) in found
    }


def source_shown(settings: Settings | None = None) -> str:
    """화면에 보일 SP 주소 — 토큰은 안 보인다. 주소의 사용자 · 암호도 지운다."""
    settings = settings or get_settings()
    url = settings.ontology_source_url.strip()
    if not url:
        return ""
    try:
        parsed = httpx.URL(url)
        return str(parsed.copy_with(username=None, password=None))
    except Exception:  # pragma: no cover - 주소가 망가졌으면 그대로 보인다
        return url


def run_summary(record: OntologySyncRun) -> dict[str, Any]:
    return dict(record.summary or {})
