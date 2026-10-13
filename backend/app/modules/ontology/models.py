"""온톨로지 — **정본은 Standard Platform 이고, 여기는 받아 온 사본이다.**

SP 가 온톨로지(타입 · 속성 · 관계 종류)를 정의하고 객체 · 관계를 들고 있다. 우리는 SP 가 코어로
공개한 타입을 주기적으로 받아(`sync.py`) 여기 둔다. 규약은 SP 의 연동 지침서 §4.2 다.

**여기서는 고치지 않는다**(지침서 §12-A 2 — 공개한 쪽이 이긴다). 양쪽에서 고칠 수 있게 두면
다음 수신이 한쪽 수정을 말없이 덮는다. 화면은 읽기 전용이고, 바뀌는 길은 수신 하나다.

**지우지 않는다.** SP 가 지웠다고 알려 와도 행은 남기고 `active` 만 끈다 — 그것을 가리키는 것이
이미 있을 수 있고, 행이 사라지면 그 참조는 빈 칸이 된다(지침서 §2-3). 선은 예외다: 선은 상태가
아니라 있음/없음이라 끊으면 지운다.

칸(`properties`)은 펼치지 않고 JSON 으로 둔다 — 타입마다 칸이 다르고, SP 가 칸을 늘려도 여기
스키마를 안 바꾸게(지침서 §12-A 7 — 모르는 칸은 무시한다가 아니라, 받아 두되 해석하지 않는다).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OntologyType(Base):
    """SP 가 코어로 공개한 타입 하나 — 카탈로그(`GET /api/core`)가 말한 그대로.

    **타입 이름 · 칸 이름을 코드에 박지 않는다**(지침서 §11) — 여기 카탈로그를 받아 두고 화면도
    이것을 읽는다.
    """

    __tablename__ = "ontology_types"

    slug: Mapped[str] = mapped_column(String(120), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), default="", server_default="")
    properties: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    """칸 — `key` · `label` · `data_type` · `unit` · `enum_options` · `ref_type_slug` ·
    `multi`."""
    relations: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    """이 타입에서 출발하는 관계 종류(slug). 비어 있지 않으면 선도 받는다."""
    relation_kinds: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    source_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """SP 쪽의 건수(카탈로그의 `count`) — 받은 건수와 견줘 「다 받았나」 를 본다."""

    published: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    """지금 카탈로그에 있나. 공개를 내리면 거짓이 되고 수신을 멈춘다 — 받아 둔 것은 남긴다."""
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    """받나 — 시스템 관리자가 끌 수 있다. 공개된 새 타입은 켜진 채로 들어온다."""

    rows_as_of: Mapped[str | None] = mapped_column(String(40), nullable=True)
    """객체를 **끝까지 받은** 마지막 `as_of` — 다음 수신의 `since` 다. **서버가 준 값 그대로**
    둔다(우리 시계로 만들면 그 사이 행이 새고, 샌 줄은 아무도 모른다 — 지침서 §4.2 규칙 1)."""
    relations_as_of: Mapped[str | None] = mapped_column(String(40), nullable=True)
    """선의 `as_of` — 객체와 **따로** 적는다(지침서 §4.2 「선 가져오기」)."""
    full_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """마지막으로 **처음부터 전량** 받아 대조한 때(`ontology_full_days` 마다)."""
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", server_default="")
    """마지막 수신에서 이 타입이 막힌 까닭 — 비면 잘 받았다."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OntologyObject(Base):
    """객체 하나 — SP 의 `key` 로 가린다(타입 안에서만 하나다)."""

    __tablename__ = "ontology_objects"
    __table_args__ = (
        UniqueConstraint("type_slug", "key", name="uq_ontology_objects_type_key"),
        Index("ix_ontology_objects_type_active", "type_slug", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type_slug: Mapped[str] = mapped_column(
        String(120), ForeignKey("ontology_types.slug", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(255))
    """SP 의 식별자 — **안 바뀐다**(바뀌면 `renamed_from` 으로 알려 오고 여기서 옮긴다)."""
    label: Mapped[str] = mapped_column(String(500), default="", server_default="")
    status: Mapped[str] = mapped_column(String(40), default="", server_default="")
    """SP 의 상태(`active` · `deprecated` …) 그대로."""
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    """칸 값 — 참조 칸은 상대의 `key`, 여러 값은 배열(지침서 §4.2 「값의 표기」)."""

    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    """지금도 SP 에 있나. 끄는 까닭은 `removed_reason` 에."""
    removed_reason: Mapped[str] = mapped_column(String(20), default="", server_default="")
    """`deleted`(SP 가 지움) · `merged`(합쳐짐 — `merged_into`) · `hidden`(토큰으로 안 보이게
    됨) · `absent`(전량 대조에서 안 옴). 비면 살아 있다."""
    merged_into: Mapped[str | None] = mapped_column(String(255), nullable=True)
    previous_keys: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    """옛 식별자들(오래된 것부터) — 옛 `key` 로 남은 참조 값을 풀 때 쓴다(규칙 10)."""

    source_updated_at: Mapped[str] = mapped_column(String(40), default="", server_default="")
    """SP 가 적은 `updated_at` 그대로."""
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OntologyRelation(Base):
    """선 하나 — `(출발 타입, 출발 key, 관계, 도착 key, 도착 타입)` 다섯으로 가린다.

    `key` 는 타입 안에서만 하나라 도착 타입까지 키다 — 끝이 인터페이스인 관계는 같은 도착
    `key` 가 두 타입에 있을 수 있다(지침서 §4.2).
    """

    __tablename__ = "ontology_relations"
    __table_args__ = (
        UniqueConstraint(
            "src_type",
            "src_key",
            "relation",
            "dst_key",
            "dst_type",
            name="uq_ontology_relations_edge",
        ),
        Index("ix_ontology_relations_src", "src_type", "src_key"),
        Index("ix_ontology_relations_dst", "dst_type", "dst_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    src_type: Mapped[str] = mapped_column(
        String(120), ForeignKey("ontology_types.slug", ondelete="CASCADE")
    )
    src_key: Mapped[str] = mapped_column(String(255))
    relation: Mapped[str] = mapped_column(String(120))
    dst_type: Mapped[str] = mapped_column(String(120), default="", server_default="")
    dst_key: Mapped[str] = mapped_column(String(255))
    evidence_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    source_updated_at: Mapped[str] = mapped_column(String(40), default="", server_default="")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


#: 수신 한 번의 끝 상태.
#:   running  도는 중
#:   ok       공개 타입 전부를 받았다
#:   partial  일부 타입이 막혔다(나머지는 받았다) — `summary` 에 타입마다 까닭
#:   failed   카탈로그부터 못 읽었다(주소 · 토큰 · 범위)
#:   skipped  설정이 없거나 다른 수신이 도는 중
SYNC_STATUSES = ("running", "ok", "partial", "failed", "skipped")


class OntologySyncRun(Base):
    """수신 한 번의 기록 — 「어제 받았는데 값이 없다」 를 SP 의 조회 이력과 맞대 보는 자리
    (지침서 §12-A 10)."""

    __tablename__ = "ontology_sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trigger: Mapped[str] = mapped_column(String(20), default="timer", server_default="timer")
    """`timer`(주기) · `manual`(화면의 「지금 받기」) · `script`(명령)."""
    full: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    """처음부터 전량을 받으라고 시켰나(타입마다의 전량 대조는 `summary` 에)."""
    status: Mapped[str] = mapped_column(
        String(20), default="running", server_default="running"
    )
    revision: Mapped[str] = mapped_column(String(80), default="", server_default="")
    """그때 카탈로그의 정의 판 — 바뀌면 「구조가 달라졌다」 다(지침서 §4.2)."""
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    """타입마다 받은 행 · 바꾼 행 · 끈 행 · 선 · 까닭."""
    error: Mapped[str] = mapped_column(Text, default="", server_default="")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
