"""폴더 — 항목이 들고 있는 **경로**(`고객A/2026/브래킷`)로 나무를 세운다.

**CompCore 의 `app/shared/folders.py` 를 옮겼다**(docs/adr/0013) — 두 플랫폼을 오가는 사람이
같은 폴더 규칙(경로 다듬기 · 깊이 · 이름 길이 · 폴더째 옮기기)을 만나게. 폴더 표는 따로 없다 —
폴더는 그 안에 항목이 있을 때 있다. 그래서 여기 있는 것은 경로를 다듬고, 「이 폴더와 그
아래」 를 거르고, 경로들에서 나무를 세고, 폴더째 옮기는 규칙뿐이다. 누가 무엇을 옮길 수
있는지는 모듈이 정한다(해석 작업은 건 사람 · 시스템 관리자).
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.shared.errors import AppError

#: 폴더 깊이 · 이름 길이의 상한 — 경로가 칸(255)을 넘지 않게, 사람이 읽을 수 있게.
DEPTH = 8
NAME = 60
LENGTH = 255


class FolderOut(BaseModel):
    path: str
    """`고객A/2026` — 빈 것이 맨 위."""
    count: int
    """**바로 이 폴더에** 있는 항목 수(하위 폴더는 빼고)."""


class FolderRenameRequest(BaseModel):
    path: str = Field(min_length=1, max_length=LENGTH)
    """바꿀 폴더(그 아래 하위 폴더까지 함께 옮긴다)."""
    to: str = Field(default="", max_length=LENGTH)
    """새 경로 — 빈 문자열이면 맨 위로 합친다. 폴더 지우기는 위 폴더로 합치는 것이다."""


class FolderMoveRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    folder: str = Field(default="", max_length=LENGTH)


class MovedOut(BaseModel):
    moved: int


def normalize(raw: str, error_code: str) -> str:
    """사람이 적은 경로를 한 모양으로 — `/고객A//2026/ ` → `고객A/2026`. 역슬래시도 나눈다.
    빈 것은 맨 위다. 틀리면 `error_code` 로 말한다(모듈마다 제 코드가 있다)."""
    parts = [one.strip() for one in raw.replace("\\", "/").split("/")]
    parts = [one for one in parts if one]
    if len(parts) > DEPTH:
        raise AppError(error_code, f"폴더는 최대 {DEPTH}단계까지 생성할 수 있습니다.")
    for one in parts:
        if len(one) > NAME:
            raise AppError(
                error_code,
                f"폴더 이름은 최대 {NAME}자까지 입력할 수 있습니다(「{one[:20]}…」).",
            )
    path = "/".join(parts)
    if len(path) > LENGTH:
        raise AppError(error_code, "폴더 경로가 너무 깁니다.")
    return path


def under(column: Any, path: str) -> ColumnElement[bool]:
    """이 폴더와 그 아래 — `LIKE` 의 `%` · `_` 는 글자 그대로 읽게 막는다(`고객A_비슷` 이
    `고객A` 아래로 잡히지 않게)."""
    escaped = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return or_(column == path, column.like(f"{escaped}/%", escape="\\"))


def narrowed(
    query: Any, column: Any, folder: str | None, subfolders: bool, error_code: str
) -> Any:
    """목록 질의를 폴더로 거른다 — `folder` 가 None 이면 그대로, 빈 것이면 맨 위(하위까지면
    전부), 아니면 그 폴더(`subfolders` 면 그 아래까지)."""
    if folder is None:
        return query
    path = normalize(folder, error_code)
    if subfolders and path:
        return query.where(under(column, path))
    if not subfolders:
        return query.where(column == path)
    return query


def tree(db: Session, column: Any, *where: Any) -> list[FolderOut]:
    """보이는 항목이 놓인 폴더들과 **바로 그 폴더에** 있는 수. 위 폴더도 빠짐없이 —
    `고객A/2026` 만 있어도 `고객A` 가 나온다(0 개로). 맨 위(빈 경로)는 늘 있다."""
    rows = db.execute(select(column, func.count()).where(*where).group_by(column)).all()
    counts: dict[str, int] = {}
    for path, count in rows:
        counts[path] = counts.get(path, 0) + int(count)
        parts = path.split("/") if path else []
        for depth in range(1, len(parts)):
            counts.setdefault("/".join(parts[:depth]), 0)
    counts.setdefault("", 0)
    return [FolderOut(path=path, count=counts[path]) for path in sorted(counts)]


def checked_rename(path: str, to: str, error_code: str) -> tuple[str, str]:
    """폴더째 옮기기의 두 경로 — 맨 위는 못 옮기고, 제 하위로도 못 옮긴다."""
    old = normalize(path, error_code)
    new = normalize(to, error_code)
    if not old:
        raise AppError(
            error_code, "최상위 폴더는 이동할 수 없습니다. 이동할 폴더를 선택하십시오."
        )
    if new.startswith(old + "/"):
        raise AppError(error_code, "폴더를 자신의 하위 폴더로 이동할 수 없습니다.")
    return old, new


def renamed(current: str, old: str, new: str, error_code: str) -> str:
    """`old` 를 `new` 로 옮길 때 `current` 에 있던 항목이 갈 곳 — 하위 경로는 그대로
    따라간다."""
    rest = current[len(old) :].lstrip("/")
    return normalize(f"{new}/{rest}" if rest else new, error_code)
