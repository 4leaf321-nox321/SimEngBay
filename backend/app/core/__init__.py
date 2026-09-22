"""해석 코어 — **웹 · DB 를 모르는 순수 파이썬.**

`fastapi` · `sqlalchemy` · `app.modules` · `app.shared` 를 import 하지 않는다. 그래야 모델링
스크립트를 서버 없이 `python -m app.core.<…>` 로 돌리고, 단위 시험이 DB 없이 코어만 본다.
`tests/architecture/test_boundaries.py` 가 지킨다.

    spec.py        JobSpec — 레시피별로 허용 칸을 제한한 입력
    stages.py      단계 이름 · 산출물 · 단계 결과 · 실패 코드
    executors/     단계를 **어디서** 돌리느냐 — fake(시험) · local · windows-bridge
"""
