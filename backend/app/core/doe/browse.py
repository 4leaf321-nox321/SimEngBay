"""공용 폴더 훑기 — **정해 둔 뿌리 아래만.**

DOE 폴더를 가져오려면 그 경로를 알아야 하는데, 사람이 `/mnt/f/data/0_Program/73_CompCore/
브래킷_튜닝-3f9a21` 같은 것을 외워서 칠 수는 없다. 그렇다고 **아무 경로나 받으면** 그 칸이
서버의 모든 폴더를 여는 문이 된다 — 이 저장소가 데이터 소스 폴더에 이미 같은 규칙을 적어
두었다(`config.py` 의 `datasource_dir`).

그래서 둘을 함께 둔다: **설정이 뿌리를 정하고, 사람은 그 아래를 탐색기처럼 고른다.**

## 무엇이 DOE 폴더인가

`manifest.csv` 가 있는 폴더다(`folder.py` 의 계약). 그것이 없으면 그냥 지나가는 폴더이므로,
목록에서 **들어갈 수는 있되 고를 수는 없게** 표시한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.doe.folder import MANIFEST

#: 한 번에 보여 줄 폴더 수. 공유 스토리지에는 수천 개가 있을 수 있고, 그것을 다 보내면
#: 화면이 멈춘다 — 목록이 잘렸다는 사실은 화면이 말한다.
MAX_ENTRIES = 300


@dataclass(frozen=True)
class Entry:
    """폴더 하나."""

    name: str
    path: str
    is_study: bool
    """`manifest.csv` 가 있나 — 즉 **가져올 수 있는가.**"""
    modified_at: datetime | None = None


@dataclass(frozen=True)
class Listing:
    path: str
    parent: str | None
    """한 칸 위. **뿌리 밖으로는 못 올라간다** — 그때는 None."""
    entries: list[Entry]
    truncated: bool = False
    is_study: bool = False


class OutsideRoots(Exception):
    """뿌리 밖을 가리켰다. **없는 폴더와 다른 말이다** — 설정을 고쳐야 하는 일이다."""


def resolve_inside(roots: list[Path], target: str | None) -> Path:
    """뿌리 안의 경로로 푼다. 비우면 첫 뿌리. **밖이면 거절한다.**

    `resolve()` 로 푼 뒤에 견준다 — `..` 이나 심볼릭 링크로 밖을 가리키는 길을 막으려면
    **푼 다음에** 봐야 한다.
    """
    if not roots:
        raise OutsideRoots("공용 폴더가 설정돼 있지 않습니다(DOE_ROOTS).")
    if not target:
        # **있는 뿌리부터 연다.** 공유 스토리지가 아직 안 마운트된 서버에서 첫 뿌리를 고집하면
        # 창을 열자마자 오류가 뜨고, 다른 뿌리에 있는 것도 못 고른다. 전부 없으면 첫 뿌리를
        # 그대로 돌려준다 — 그때는 「그 경로가 없다」 가 정확한 진단이다.
        return next((one for one in roots if one.is_dir()), roots[0])
    path = Path(target).expanduser().resolve()
    for root in roots:
        base = root.resolve()
        if path == base or base in path.parents:
            return path
    raise OutsideRoots(f"공용 폴더 밖입니다: {target}")


def is_study(path: Path) -> bool:
    return (path / MANIFEST).is_file()


def listing(roots: list[Path], target: str | None = None) -> Listing:
    """그 폴더 아래의 폴더들. **파일은 안 보여 준다** — 고를 수 있는 것은 폴더뿐이다."""
    path = resolve_inside(roots, target)
    if not path.is_dir():
        raise FileNotFoundError(f"폴더가 없습니다: {path}")

    found: list[Entry] = []
    for child in sorted(path.iterdir(), key=lambda one: one.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            modified = datetime.fromtimestamp(child.stat().st_mtime, tz=UTC)
        except OSError:  # pragma: no cover - 권한 없는 폴더
            modified = None
        found.append(
            Entry(
                name=child.name,
                path=str(child),
                is_study=is_study(child),
                modified_at=modified,
            )
        )
        if len(found) >= MAX_ENTRIES:
            break

    parent: str | None = None
    if path.parent != path and any(
        root.resolve() == path.parent or root.resolve() in path.parent.parents
        for root in roots
    ):
        parent = str(path.parent)

    return Listing(
        path=str(path),
        parent=parent,
        entries=found,
        truncated=len(found) >= MAX_ENTRIES,
        is_study=is_study(path),
    )
