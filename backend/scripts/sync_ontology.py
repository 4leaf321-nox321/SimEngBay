"""온톨로지를 Standard Platform 에서 받는다 — **타이머가 부르는 자리**.

    python scripts/sync_ontology.py --due     차례가 됐을 때만(타이머가 5분마다 이것을 부른다)
    python scripts/sync_ontology.py --now     지금 받는다(진단 · 첫 적재)
    python scripts/sync_ontology.py --full    처음부터 전량 받아 대조한다

systemd 타이머(`<slug>-sync.timer`, deploy.sh 가 설치)가 앱과 **같은 SIF · 같은 .env** 로 이
스크립트를 돌린다. 차례는 `ONTOLOGY_SYNC_MINUTES`(기본 하루 1회)가 정한다 — 타이머의 5분은
「차례가 됐나」 를 얼마나 촘촘히 묻느냐일 뿐이다.

설정(`ONTOLOGY_SOURCE_URL` · `ONTOLOGY_SOURCE_TOKEN`)이 없으면 **아무것도 안 하고 0 으로
끝난다** — 온톨로지를 안 쓰는 설치에서 타이머가 5분마다 실패로 적히면 진짜 실패가 묻힌다.
화면의 「지금 받기」 와 같은 길(`services.execute`)을 지나고, 수신 기록이 같은 표에 남는다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.all_models  # noqa: F401  (모델을 모두 올린다 — 외래 키가 사용자 표를 가리킨다)
from app.database import SessionLocal
from app.modules.ontology import services
from app.modules.ontology.models import OntologySyncRun
from app.shared.errors import AppError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--due", action="store_true", help="차례가 됐을 때만")
    group.add_argument("--now", action="store_true", help="지금 받는다")
    group.add_argument("--full", action="store_true", help="처음부터 전량 받아 대조한다")
    args = parser.parse_args()

    if not services.configured():
        print(
            "온톨로지 수신 설정이 없습니다(ONTOLOGY_SOURCE_URL · ONTOLOGY_SOURCE_TOKEN) — "
            "건너뜁니다."
        )
        return 0
    with SessionLocal() as db:
        if args.due and not services.due(db):
            return 0
        try:
            record = services.start(
                db, trigger="timer" if args.due else "script", full=bool(args.full)
            )
        except AppError as failure:
            # 다른 수신이 도는 중이면 이번 차례는 건너뛴다 — 실패가 아니다.
            print(failure.message)
            return 0
        run_id = record.id
    services.execute(run_id)
    with SessionLocal() as db:
        done = db.get(OntologySyncRun, run_id)
        if done is None:
            return 1
        print(f"온톨로지 수신 — {done.status}" + (f": {done.error}" if done.error else ""))
        for slug, report in ((done.summary or {}).get("types") or {}).items():
            print(f"  {slug}: {report}")
        return 0 if done.status in ("ok", "partial", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
