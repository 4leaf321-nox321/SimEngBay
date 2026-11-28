"""배포에 실려 온 판마다의 업데이트 안내 → 공지 **초안**.

    python scripts/import_notices.py          # 빠진 것만 초안으로 넣는다
    python scripts/import_notices.py --check  # 넣을 것이 무엇인지만 본다

CompCore · MatNexus 의 `import_notices.py` 와 같은 길이다(2026-11-28) — 같은 회사의 플랫폼끼리
공지가 같은 길로 들어와야 배포하는 사람이 헤매지 않는다.

## 왜

새 기능은 코드와 함께 도착하는데, 그것을 알리는 글은 사람이 공지 화면에서 따로 써야 한다.
그러면 「다음에 쓰지」 가 되고, 사용자는 소성 해석이 생긴 것도 결과 표가 바뀐 것도 모른다.
그래서 **판마다 안내 글을 코드 옆**(`seeds/notices/<날짜>-v<판>.md`)에 두고, 배포가 이
스크립트를 돌려 **초안**으로 넣는다. 초안은 시스템 관리자만 본다 — 읽고, 발행한다(공지
화면의 「발행」 · 「배포 안내 초안 모두 발행」). 자동 발행하지 않는 까닭: 배포한 사람이 글의
첫 독자여야 하고, 그 서버에 안 맞는 말이 있으면 거기서 걸러야 한다.

## 규칙

- 파일 이름이 키다(`2026-11-28-v0.39.0.md` → `2026-11-28-v0.39.0`). **같은 키는 두 번 안
  들어온다** — 운영에서 고친 글을 덮지 않는다. 고쳐서 다시 내려면 새 파일.
- **지운 초안도 다시 안 들어온다.** 넣은 키는 `notice_seed_keys` 가 기억한다.
- **만든 시각은 그 판의 날짜다**(키의 날짜, 한국 시각 오전 9시). 같은 날 낸 판이 여럿이면 판
  번호 순으로 1분씩 벌린다. 발행해도 그 시각을 쓴다(`routes._publish`) — 첫 배포에 수십 판이
  한꺼번에 들어와도 판 순서대로 선다.
- 첫 줄 `# 제목`, 나머지가 본문. 본문은 줄바꿈 · ■ 머리 · 「- 」 목록만 쓴다(`**굵게**` ·
  `` `코드` `` 는 화면이 그려 보인다). 급은 「안내」(info), 팝업 아님, 쓴 사람 없음(화면은
  「배포 안내」).
- 실패해도 배포를 세우지 않는다(`deploy.sh` 의 `run_notices`) — 안내가 비는 것은 불편이지
  장애가 아니다.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.all_models  # noqa: E402,F401
from app.database import SessionLocal  # noqa: E402
from app.modules.notices.models import Notice, NoticeSeedKey  # noqa: E402

SEED_DIR = BACKEND_DIR / "seeds" / "notices"

#: 판의 날짜는 한국 시각이다 — 자정 UTC 로 두면 화면(한국)에서 그날 오전 9시로 읽힌다.
KST = timezone(timedelta(hours=9))

#: 키의 꼴 — 날짜, 그리고 판(있으면).
KEY = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-v(\d+)\.(\d+)\.(\d+))?")


def read_seed(path: Path) -> tuple[str, str]:
    """`(제목, 본문)`. 첫 줄이 `# 제목` 이어야 한다 — 아니면 파일 이름이 제목이다."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    first, _, rest = text.partition("\n")
    if first.startswith("# "):
        return first[2:].strip(), rest.strip()
    return path.stem, text


def _order(key: str) -> tuple[str, tuple[int, ...], str]:
    """날짜 → 판 번호(문자 순이 아니라 수 순 — v0.10.0 이 v0.9.0 뒤다) → 키."""
    found = KEY.match(key)
    if not found:
        return ("9999-99-99", (), key)
    version = tuple(int(one) for one in found.groups()[1:] if one is not None)
    return (found.group(1), version, key)


def made_at(keys: list[str]) -> dict[str, datetime | None]:
    """키마다 만든 시각 — 그 날짜 오전 9시(한국)부터 같은 날 판 순으로 1분씩. 날짜가 없는
    키는 `None` — 넣는 그 순간(서버 기본값)이다."""
    out: dict[str, datetime | None] = {}
    per_day: dict[str, int] = {}
    for key in sorted(keys, key=_order):
        found = KEY.match(key)
        if not found:
            out[key] = None
            continue
        try:
            day = date.fromisoformat(found.group(1))
        except ValueError:
            out[key] = None
            continue
        rank = per_day.get(found.group(1), 0)
        per_day[found.group(1)] = rank + 1
        out[key] = datetime(day.year, day.month, day.day, 9, tzinfo=KST) + timedelta(
            minutes=rank
        )
    return out


def plan(db: Session, seed_dir: Path = SEED_DIR) -> list[tuple[str, str, str]]:
    """넣을 것 — `(키, 제목, 본문)`, 판 순. **넣은 적이 있는 키는 뺀다** — 그 공지를 지웠어도.

    넣은 키의 기억(`notice_seed_keys`)이 정본이고, 공지 행의 `seed_key` 도 함께 본다 — 기억
    밖에서 손으로 넣은 줄이 있어도 두 번 넣지 않는다."""
    if not seed_dir.exists():
        return []
    have = set(db.scalars(select(NoticeSeedKey.key)))
    have |= set(db.scalars(select(Notice.seed_key).where(Notice.seed_key.is_not(None))))
    out: list[tuple[str, str, str]] = []
    for path in sorted(seed_dir.glob("*.md"), key=lambda one: _order(one.stem)):
        key = path.stem
        if key in have:
            continue
        title, body = read_seed(path)
        if not body:
            continue
        out.append((key, title, body))
    return out


def run(db: Session, seed_dir: Path = SEED_DIR) -> list[str]:
    """빠진 씨앗을 초안으로 넣는다. 넣은 키를 돌려준다 — **키를 기억에 함께 적는다.**

    만든 시각은 **이 폴더의 모든 키**로 매긴다 — 같은 날 판이 이미 들어가 있어도 순번이
    같다."""
    todo = plan(db, seed_dir)
    if not todo:
        return []
    stamps = made_at([one.stem for one in seed_dir.glob("*.md")])
    made: list[str] = []
    for key, title, body in todo:
        notice = Notice(
            title=title[:200],
            body=body,
            level="info",
            is_popup=False,
            published_at=None,
            author_id=None,
            seed_key=key,
        )
        stamp = stamps.get(key)
        if stamp is not None:
            notice.created_at = stamp
        db.add(notice)
        # 공지를 지워도 남는다 — 다음 배포가 이 키를 다시 넣지 않는다.
        if db.get(NoticeSeedKey, key) is None:
            db.add(NoticeSeedKey(key=key))
        made.append(key)
    db.commit()
    return made


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="넣지 않고 무엇을 넣을지만 본다")
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.check:
            todo = plan(db)
            print(f"넣을 안내: {len(todo)}건")
            for key, title, _ in todo:
                print(f"  - {key}: {title}")
            return 0
        made = run(db)
        if made:
            print(f"공지 초안 {len(made)}건 — 시스템 관리자가 공지 화면에서 읽고 발행합니다:")
            for key in made:
                print(f"  - {key}")
        else:
            print("새로 넣을 안내가 없습니다.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
