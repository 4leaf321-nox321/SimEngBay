"""온톨로지 응답 — **받아 온 사본**을 보이는 모양. 여기서 고치는 칸은 「받나」 하나뿐이다."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class OntologyRunOut(BaseModel):
    id: uuid.UUID
    trigger: str
    full: bool
    status: str
    revision: str
    summary: dict[str, Any]
    """`types` — 타입마다 받은 행 · 만든 · 고친 · 끈 · 되살린 · 옮긴 · 선 · 까닭. 정의 판이
    지난 수신과 다르면 `revision_changed`."""
    error: str
    actor_name: str | None = None
    started_at: datetime
    finished_at: datetime | None


class OntologyStatusOut(BaseModel):
    configured: bool
    """주소 · 토큰이 다 있나. 없으면 화면이 무엇을 적어야 하는지 말한다."""
    source: str
    """SP 주소(토큰 · 사용자 · 암호는 안 보인다)."""
    sync_minutes: int
    full_days: int
    next_due_at: datetime | None
    """타이머가 다음에 받을 때. 주기가 0 이면 비고, 화면으로만 받는다."""
    running: OntologyRunOut | None
    last_run: OntologyRunOut | None
    revision: str
    """마지막으로 받은 정의 판."""
    types: int
    objects: int
    relations: int


class OntologyPropertyOut(BaseModel):
    key: str
    label: str = ""
    data_type: str = ""
    unit: str | None = None
    enum_options: list[str] | None = None
    ref_type_slug: str | None = None
    multi: bool | None = None


class OntologyTypeOut(BaseModel):
    slug: str
    label: str
    properties: list[OntologyPropertyOut]
    relations: list[str]
    source_count: int | None
    """SP 쪽 건수 — 받은 건수(`active_count`)와 견준다."""
    active_count: int
    inactive_count: int
    relation_count: int
    published: bool
    enabled: bool
    synced_at: datetime | None
    full_at: datetime | None
    last_error: str


class OntologyTypePatch(BaseModel):
    enabled: bool


class OntologySyncRequest(BaseModel):
    full: bool = False
    """처음부터 전량을 받아 대조한다(지운 것을 듣는 길)."""


class OntologyObjectOut(BaseModel):
    type_slug: str
    key: str
    label: str
    status: str
    properties: dict[str, Any]
    active: bool
    removed_reason: str
    merged_into: str | None
    previous_keys: list[str]
    source_updated_at: str
    synced_at: datetime
    ref_labels: dict[str, str] = {}
    """참조 칸의 값(상대 `key`) → 그 이름. 가리키는 타입도 받아 두었으면 채운다 — 옛 식별자로
    남은 값도 `previous_keys` 로 풀어 찾는다(지침서 §4.2 규칙 10)."""


class OntologyEdgeOut(BaseModel):
    relation: str
    src_type: str
    src_key: str
    src_label: str | None = None
    dst_type: str
    dst_key: str
    dst_label: str | None = None
    evidence_note: str
    properties: dict[str, Any]


class OntologyObjectDetailOut(OntologyObjectOut):
    outgoing: list[OntologyEdgeOut]
    incoming: list[OntologyEdgeOut]
