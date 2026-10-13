"""Standard Platform 코어 API 수신 — **받는 쪽의 반복문**(SP 연동 지침서 §4.2).

    GET {base}/core                       카탈로그 — 무엇이 공개되어 있나
    GET {base}/core/{type}                ?since=<지난 as_of> &cursor=<지난 next> &limit=
    GET {base}/core/{type}/relations      같은 규칙으로 그 타입에서 출발하는 선
    인증: Authorization: Bearer <PAT>, 범위 core:read

이 파일은 SP 를 부르고 받은 것을 표에 옮기는 일만 한다 — 언제 · 누가 부르나(타이머 · 화면),
잠금 · 기록은 `services.py` 가 한다. 그래서 가짜 SP(`httpx.MockTransport`)로 규칙을 하나씩
시험할 수 있다(`tests/unit/test_ontology_sync.py`).

지침서의 「받는 쪽 규칙」 을 그대로 따른다 — 번호는 지침서의 것이다:

1. `as_of` 는 **서버가 준 값 그대로** 다음 `since` 로 돌려준다.
2. `next` 가 남았으면 시각을 옮기지 않는다 — **끝까지 받은 뒤에만** 적는다.
3. `key` 로 가린다 — 다음 수신이 「새로 만들기」 가 아니라 「고침」 이 된다.
4. `deleted` 는 지우지 않고 끈다(`merged_into` 를 적는다). `renamed_from` 이면 옛 `key` 의 행을
   찾아 키를 옮긴다. `hidden` 이면 가진 값은 두고 끄기만 한다.
5. 모르는 칸은 해석하지 않는다(받아 두기만 한다).
6. 같은 행이 두 번 와도 덮어쓰면 그만이다.
7. `since` 없이(전량) 받으면 지운 것은 안 온다 — **끝까지 받은 뒤** 이번에 안 온 것을 끈다.
   한꺼번에 절반 넘게 안 오면 끄지 않고 그 타입을 실패로 적는다(토큰의 부서 · 공개 범위가 바뀐
   경우 — SP 의 형제 소스와 같은 안전장치).
8. 지운 것이 같은 `key` 로 다시 오면 되살린다.
9. 지워진(합쳐진) 객체를 끝점으로 하는 선은 우리가 끊는다 — 그 선은 「끊긴 선」 으로 안 온다.
11. 404 는 둘이다 — `APP-CORE-0001`(공개 안 된 타입 → 그 타입만 멈춘다)과
    `APP-CORE-0002`(커서를 못 읽음 → 커서 없이 지난 `as_of` 부터 다시).

선은 `reset: true` 가 오면 `since` 를 비우고 처음부터 받고, 끝까지 받은 뒤 이번에 안 온 선을
끊는다(객체도 그 말이 오면 따른다).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.modules.ontology.models import (
    OntologyObject,
    OntologyRelation,
    OntologySyncRun,
    OntologyType,
)

logger = logging.getLogger(__name__)

#: 한 쪽에 몇 행 — SP 의 기본값(최대 2000).
PAGE_SIZE = 500
#: 5xx · 429 · 네트워크 오류만 다시 시도한다(4xx 는 다시 보내도 같다 — 지침서 §8).
RETRIES = 3
TIMEOUT_SECONDS = 60.0
#: 전량 대조에서 가진 것 중 이 비율보다 많이 안 오면 끄지 않는다(규칙 7).
ABSENCE_GUARD = 0.5
#: 이보다 적게 가진 타입은 비율을 안 본다 — 몇 개뿐인 타입에서 절반은 흔한 변화다.
ABSENCE_GUARD_MIN = 10


class CoreError(Exception):
    """SP 를 못 읽었다 — `message` 는 사람에게 그대로 보여 줄 우리말 한 줄이다."""

    def __init__(
        self, message: str, *, status: int | None = None, request_id: str = ""
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.request_id = request_id


class TypeUnpublished(CoreError):
    """`APP-CORE-0001` — 그 타입이 공개되지 않았다(내렸다). 그 타입만 멈춘다."""


class CursorUnreadable(CoreError):
    """`APP-CORE-0002` — 커서를 못 읽었다. 커서 없이 지난 `as_of` 부터 다시 받는다."""


def core_base(url: str) -> str:
    """적은 주소 → 코어 창구의 뿌리(늘 `/` 로 끝난다).

    SP 화면은 창구를 `https://호스트/api/core` 로 건네고, 사람은 보통 `https://호스트/api` 를
    적는다 — **둘 다 받는다**(ReportArchive 의 수신과 같다).
    """
    base = (url or "").strip().rstrip("/")
    if not base:
        raise CoreError("주소가 비었습니다 — ONTOLOGY_SOURCE_URL 에 SP 주소를 적습니다.")
    if not urlparse(base).path.rstrip("/").endswith("/core"):
        base += "/core"
    return base + "/"


class CoreClient:
    """SP 코어 창구 — GET 한 가지와 실패를 **사람이 고칠 수 있는 말**로 바꾸는 일."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not token:
            raise CoreError(
                "토큰이 비었습니다 — ONTOLOGY_SOURCE_TOKEN 에 SP 가 발급한 토큰(범위 "
                "core:read)을 적습니다."
            )
        self.base = core_base(url)
        self._sleep = sleep
        self._http = httpx.Client(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            transport=transport,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    def close(self) -> None:
        self._http.close()

    def catalog(self) -> dict[str, Any]:
        return self._get("")

    def rows(
        self, type_slug: str, *, since: str | None, cursor: str | None, relations: bool = False
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if since:
            params["since"] = since
        if cursor:
            params["cursor"] = cursor
        return self._get(f"{type_slug}/relations" if relations else type_slug, params)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base + path
        for attempt in range(1, RETRIES + 1):
            try:
                response = self._http.get(url, params=params)
            except httpx.HTTPError as failure:
                if attempt == RETRIES:
                    raise CoreError(f"SP 에 닿지 못했습니다({url}): {failure}") from failure
                self._sleep(2.0 * attempt)
                continue
            if response.status_code >= 500 or response.status_code == 429:
                if attempt == RETRIES:
                    message, request_id = _said(response)
                    raise CoreError(
                        f"SP 서버 오류가 계속됩니다(HTTP {response.status_code}): {message}",
                        status=response.status_code,
                        request_id=request_id,
                    )
                self._sleep(2.0 * attempt)
                continue
            return _body(response, url)
        raise CoreError(f"SP 를 읽지 못했습니다({url}).")  # pragma: no cover - 위에서 끝난다


def _said(response: httpx.Response) -> tuple[str, str]:
    """SP 오류 봉투의 `message` · `request_id` — 봉투가 아니면 본문 앞부분."""
    try:
        error = (response.json() or {}).get("error") or {}
        return str(error.get("message") or "")[:300], str(error.get("request_id") or "")
    except ValueError:
        return response.text[:300], ""


def _error_code(response: httpx.Response) -> str:
    try:
        return str(((response.json() or {}).get("error") or {}).get("code") or "")
    except ValueError:
        return ""


def _body(response: httpx.Response, url: str) -> dict[str, Any]:
    status = response.status_code
    if status in (401, 403):
        message, request_id = _said(response)
        raise CoreError(
            "SP 가 거절했습니다(인증 · 범위) — 토큰이 유효한지, 범위에 core:read 가 있는지, "
            f"만료되지 않았는지 확인하세요. SP 의 말: {message}",
            status=status,
            request_id=request_id,
        )
    if status == 404:
        message, request_id = _said(response)
        code = _error_code(response)
        if code.endswith("CORE-0001"):
            raise TypeUnpublished(
                f"공개되지 않은 타입입니다 — {message}", status=404, request_id=request_id
            )
        if code.endswith("CORE-0002"):
            raise CursorUnreadable(
                f"커서를 못 읽었습니다 — {message}", status=404, request_id=request_id
            )
        raise CoreError(
            f"코어 창구를 못 찾았습니다({url}) — 주소가 SP 의 `/api` 인지 확인하세요.",
            status=404,
            request_id=request_id,
        )
    if status >= 400:
        message, request_id = _said(response)
        raise CoreError(
            f"SP 가 요청을 거절했습니다(HTTP {status}): {message}",
            status=status,
            request_id=request_id,
        )
    try:
        body = response.json()
    except ValueError as failure:
        raise CoreError(
            f"SP 가 JSON 이 아닌 답을 줬습니다({url}) — 주소가 코어 창구인지 확인하세요."
        ) from failure
    if not isinstance(body, dict):
        raise CoreError(f"SP 의 답이 예상한 모양이 아닙니다({url}).")
    return body


@dataclass
class TypeReport:
    """타입 하나를 받은 결과 — 수신 기록(`OntologySyncRun.summary`)에 그대로 남는다."""

    rows: int = 0
    created: int = 0
    updated: int = 0
    deactivated: int = 0
    reactivated: int = 0
    renamed: int = 0
    relations: int = 0
    relations_removed: int = 0
    full: bool = False
    relations_full: bool = False
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            key: value for key, value in asdict(self).items() if value not in (0, False, "")
        }


def run(
    db: Session,
    client: CoreClient,
    record: OntologySyncRun,
    *,
    now: datetime,
    full: bool = False,
    full_every: timedelta | None = timedelta(days=7),
) -> None:
    """한 번 받는다 — 카탈로그 → 켠 타입마다 객체 → 선. 결과는 `record` 에 적는다.

    카탈로그를 못 읽으면 `CoreError` 를 그대로 올린다(부른 쪽이 「실패」 로 적는다). 타입
    하나가 막히면 그 타입에만 까닭을 적고 나머지는 계속 받는다 — 한 타입의 문제로 전부가
    멈추면 안 된다.
    """
    catalog = client.catalog()
    revision = str(catalog.get("revision") or "")
    listed = [
        one for one in catalog.get("types") or [] if isinstance(one, dict) and one.get("slug")
    ]
    _apply_catalog(db, listed)
    record.revision = revision
    db.commit()

    reports: dict[str, TypeReport] = {}
    for kind in db.scalars(
        select(OntologyType)
        .where(OntologyType.published.is_(True), OntologyType.enabled.is_(True))
        .order_by(OntologyType.slug)
    ).all():
        report = TypeReport()
        reports[kind.slug] = report
        whole = full or kind.rows_as_of is None or _full_due(kind, now, full_every)
        # **객체와 선은 따로 맺는다** — 한 단계는 다 되거나 하나도 안 된다(받다 만 것을 맺으면
        # 반쯤 받은 상태가 정본처럼 보인다). 선이 막혀도 객체는 앞으로 간다.
        objects_ok = _attempt(
            db, kind, report, partial(_objects, db, client, kind, report, whole, now)
        )
        if objects_ok and kind.relations:
            _attempt(
                db,
                kind,
                report,
                partial(
                    _pull_relations,
                    db,
                    client,
                    kind,
                    report,
                    whole=whole or kind.relations_as_of is None,
                ),
            )
        if not report.error:
            kind.last_error = ""
        kind.synced_at = now
        db.commit()

    record.summary = {
        "types": {slug: report.as_dict() for slug, report in reports.items()},
        **({"revision_changed": True} if _revision_changed(db, record, revision) else {}),
    }
    record.status = "partial" if any(one.error for one in reports.values()) else "ok"


def _objects(
    db: Session,
    client: CoreClient,
    kind: OntologyType,
    report: TypeReport,
    whole: bool,
    now: datetime,
) -> None:
    _pull_objects(db, client, kind, report, whole=whole)
    if whole:
        kind.full_at = now


def _attempt(
    db: Session, kind: OntologyType, report: TypeReport, step: Callable[[], None]
) -> bool:
    """한 단계를 해 보고 맺는다. 막히면 되돌리고 그 타입에 까닭을 적는다 — 나머지 타입은
    계속."""
    try:
        step()
        db.commit()
        return True
    except TypeUnpublished as failure:
        db.rollback()
        kind.published = False
        kind.last_error = report.error = failure.message
    except CoreError as failure:
        db.rollback()
        kind.last_error = report.error = failure.message
        logger.warning("온톨로지 %s 수신 실패: %s", kind.slug, failure.message)
    db.commit()
    return False


def _full_due(kind: OntologyType, now: datetime, every: timedelta | None) -> bool:
    """처음부터 전량 받아 대조할 때가 됐나(`ontology_full_days`)."""
    if every is None or every <= timedelta(0):
        return False
    return kind.full_at is None or now - kind.full_at >= every


def _revision_changed(db: Session, record: OntologySyncRun, revision: str) -> bool:
    """지난 수신과 정의 판이 다른가 — 칸 · 자료형 · 참조 대상이 바뀌었다는 뜻이다."""
    before = db.scalar(
        select(OntologySyncRun.revision)
        .where(
            OntologySyncRun.id != record.id,
            OntologySyncRun.status.in_(("ok", "partial")),
            OntologySyncRun.revision != "",
        )
        .order_by(OntologySyncRun.started_at.desc())
        .limit(1)
    )
    return bool(before and revision and before != revision)


def _apply_catalog(db: Session, listed: list[dict[str, Any]]) -> None:
    """카탈로그를 타입 표에 옮긴다. 빠진 타입은 「공개 안 됨」 으로 — 받아 둔 것은 남긴다."""
    known = {one.slug: one for one in db.scalars(select(OntologyType))}
    present: set[str] = set()
    for entry in listed:
        slug = str(entry["slug"])
        present.add(slug)
        kind = known.get(slug)
        if kind is None:
            kind = OntologyType(slug=slug)
            db.add(kind)
        kind.label = str(entry.get("label") or slug)[:200]
        kind.properties = [
            one for one in entry.get("properties") or [] if isinstance(one, dict)
        ]
        kind.relations = [str(one) for one in entry.get("relations") or []]
        kind.relation_kinds = [
            one for one in entry.get("relation_kinds") or [] if isinstance(one, dict)
        ]
        count = entry.get("count")
        kind.source_count = count if isinstance(count, int) else None
        kind.published = True
    for slug, kind in known.items():
        if slug not in present and kind.published:
            kind.published = False
            kind.last_error = (
                "카탈로그에서 빠졌습니다 — SP 가 공개를 내렸습니다. 받아 둔 것은 남깁니다."
            )


def _pages(
    client: CoreClient, slug: str, since: str | None, *, relations: bool
) -> Iterable[tuple[dict[str, Any], bool]]:
    """쪽을 차례로 — `(본문, 처음부터 다시인가)`. 커서 · reset 의 규칙을 여기서 지킨다.

    `reset` 이 오면 `since` 를 비우고 처음부터 받는다(두 번째에도 오면 공개 측 문제다).
    커서를 못 읽으면(`APP-CORE-0002`) 커서 없이 지난 `since` 부터 한 번 더.
    """
    cursor: str | None = None
    restarted = False
    cursor_retried = False
    while True:
        try:
            body = client.rows(slug, since=since, cursor=cursor, relations=relations)
        except CursorUnreadable:
            if cursor_retried:
                raise
            cursor_retried, cursor = True, None
            continue
        if body.get("reset"):
            if restarted:
                raise CoreError(
                    "since 를 비웠는데도 처음부터 다시 받으라고 합니다 — 공개 측에 "
                    f"문의하세요: {body.get('reset_reason') or ''}"
                )
            restarted, since, cursor = True, None, None
            yield body, True
            continue
        yield body, False
        cursor = body.get("next")
        if not cursor:
            return


def _pull_objects(
    db: Session, client: CoreClient, kind: OntologyType, report: TypeReport, *, whole: bool
) -> None:
    """객체를 받는다 — 전량이면 끝까지 받은 뒤 안 온 것을 끈다(규칙 7)."""
    report.full = whole
    seen: set[str] | None = set() if whole else None
    last: dict[str, Any] = {}
    for body, restarted in _pages(
        client, kind.slug, None if whole else kind.rows_as_of, relations=False
    ):
        if restarted:
            report.full, seen = True, set()
            continue
        items = [one for one in body.get("items") or [] if isinstance(one, dict)]
        _apply_objects(db, kind.slug, items, report, seen)
        db.flush()
        last = body
    if seen is not None:
        _absent_objects(db, kind.slug, seen, report)
    as_of = last.get("as_of")
    if as_of:
        # **끝까지 받았을 때만 시각을 옮긴다**(규칙 2) — `next` 가 남은 쪽의 `as_of` 는
        # null 이다.
        kind.rows_as_of = str(as_of)


def _apply_objects(
    db: Session,
    slug: str,
    items: list[dict[str, Any]],
    report: TypeReport,
    seen: set[str] | None,
) -> None:
    keys = {str(one.get("key") or "") for one in items} | {
        str(one.get("renamed_from") or "") for one in items
    }
    keys.discard("")
    found = {
        one.key: one
        for one in db.scalars(
            select(OntologyObject).where(
                OntologyObject.type_slug == slug, OntologyObject.key.in_(keys)
            )
        )
    }
    for item in items:
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        report.rows += 1
        row = found.get(key)
        if item.get("hidden"):
            # 지운 것이 아니라 이 토큰으로 더 이상 안 보이게 됐다 — 이름 · 칸은 안
            # 온다(규칙 4).
            if row is not None and row.active:
                row.active, row.removed_reason = False, "hidden"
                report.deactivated += 1
            continue
        renamed_from = str(item.get("renamed_from") or "").strip()
        if row is None and renamed_from and renamed_from in found:
            # 옛 식별자의 행을 옮긴다 — 안 그러면 같은 것이 둘이 된다(규칙 4).
            row = found.pop(renamed_from)
            row.key = key
            found[key] = row
            report.renamed += 1
        deleted = bool(item.get("deleted"))
        if row is None:
            if deleted:
                continue  # 가진 적 없는 것의 무덤 — 끌 것이 없다.
            # 기본값은 넣을 때(flush) 채워진다 — 그 전에 `active` 를 읽으면 None 이라
            # 「되살림」 으로 세어진다. 처음부터 적어 둔다.
            row = OntologyObject(type_slug=slug, key=key, active=True, previous_keys=[])
            db.add(row)
            found[key] = row
            report.created += 1
        else:
            report.updated += 1
        if renamed_from and renamed_from not in (row.previous_keys or []):
            row.previous_keys = [*(row.previous_keys or []), renamed_from]
        previous = item.get("previous_keys")
        if isinstance(previous, list) and previous:
            row.previous_keys = [str(one) for one in previous]
        row.source_updated_at = str(item.get("updated_at") or "")
        if deleted:
            merged = str(item.get("merged_into") or "").strip() or None
            if row.active:
                report.deactivated += 1
            row.active = False
            row.removed_reason = "merged" if merged else "deleted"
            row.merged_into = merged
            row.status = str(item.get("status") or row.status)
            # 그 객체를 끝점으로 하는 선을 끊는다 — 「끊긴 선」 으로 안 온다(규칙 9).
            report.relations_removed += _cut_edges(db, slug, key)
            continue
        if row.active is False:
            report.reactivated += 1  # 지웠던 것이 다시 왔다(규칙 8).
        row.active, row.removed_reason, row.merged_into = True, "", None
        row.label = str(item.get("label") or "")[:500]
        row.status = str(item.get("status") or "")
        properties = item.get("properties")
        row.properties = dict(properties) if isinstance(properties, dict) else {}
        if seen is not None:
            seen.add(key)


def _absent_objects(db: Session, slug: str, seen: set[str], report: TypeReport) -> None:
    """전량을 끝까지 받은 뒤 **이번에 안 온 것을 끈다**(규칙 7) — 절반 넘게면 끄지 않는다."""
    active = list(
        db.scalars(
            select(OntologyObject).where(
                OntologyObject.type_slug == slug, OntologyObject.active.is_(True)
            )
        )
    )
    missing = [one for one in active if one.key not in seen]
    _guard(len(active), len(missing), "객체")
    for one in missing:
        one.active, one.removed_reason = False, "absent"
        report.deactivated += 1


def _guard(held: int, missing: int, what: str) -> None:
    if held >= ABSENCE_GUARD_MIN and missing > held * ABSENCE_GUARD:
        raise CoreError(
            f"전량 대조에서 가진 {what} {held}개 중 {missing}개가 안 왔습니다 — 절반이 넘어 "
            "끄지 않았습니다. SP 쪽 토큰의 부서 · 공개 범위가 바뀌었는지 확인하세요."
        )


def _cut_edges(db: Session, slug: str, key: str) -> int:
    """그 객체를 끝점으로 하는 선을 지운다."""
    result = db.execute(
        delete(OntologyRelation).where(
            or_(
                (OntologyRelation.src_type == slug) & (OntologyRelation.src_key == key),
                (OntologyRelation.dst_type == slug) & (OntologyRelation.dst_key == key),
            )
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


Edge = tuple[str, str, str, str]


def _pull_relations(
    db: Session, client: CoreClient, kind: OntologyType, report: TypeReport, *, whole: bool
) -> None:
    """그 타입에서 출발하는 선 — 객체와 **같은 규칙**, 기준 시각은 따로."""
    report.relations_full = whole
    seen: set[Edge] | None = set() if whole else None
    last: dict[str, Any] = {}
    for body, restarted in _pages(
        client, kind.slug, None if whole else kind.relations_as_of, relations=True
    ):
        if restarted:
            report.relations_full, seen = True, set()
            continue
        for item in body.get("items") or []:
            if isinstance(item, dict):
                _apply_edge(db, kind.slug, item, report, seen)
        db.flush()
        last = body
    if seen is not None:
        held = list(
            db.scalars(select(OntologyRelation).where(OntologyRelation.src_type == kind.slug))
        )
        missing = [
            one
            for one in held
            if (one.src_key, one.relation, one.dst_key, one.dst_type) not in seen
        ]
        _guard(len(held), len(missing), "선")
        for one in missing:
            db.delete(one)
            report.relations_removed += 1
    as_of = last.get("as_of")
    if as_of:
        kind.relations_as_of = str(as_of)


def _apply_edge(
    db: Session, slug: str, item: dict[str, Any], report: TypeReport, seen: set[Edge] | None
) -> None:
    src = str(item.get("src") or "").strip()
    relation = str(item.get("relation") or "").strip()
    dst = str(item.get("dst") or "").strip()
    dst_type = str(item.get("dst_type") or "").strip()
    if not (src and relation and dst):
        return
    report.relations += 1
    edge = db.scalar(
        select(OntologyRelation).where(
            OntologyRelation.src_type == slug,
            OntologyRelation.src_key == src,
            OntologyRelation.relation == relation,
            OntologyRelation.dst_key == dst,
            OntologyRelation.dst_type == dst_type,
        )
    )
    if item.get("deleted"):
        # 선은 상태가 아니라 있음/없음이다 — 끊긴 선은 지운다.
        if edge is not None:
            db.delete(edge)
            report.relations_removed += 1
        return
    if edge is None:
        edge = OntologyRelation(
            src_type=slug, src_key=src, relation=relation, dst_key=dst, dst_type=dst_type
        )
        db.add(edge)
    edge.evidence_note = str(item.get("evidence_note") or "")
    properties = item.get("properties")
    edge.properties = dict(properties) if isinstance(properties, dict) else {}
    edge.source_updated_at = str(item.get("updated_at") or "")
    if seen is not None:
        seen.add((src, relation, dst, dst_type))
