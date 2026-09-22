"""PyMechanical(임베디드) 위의 FE 모델링 — **이 패키지만 Ansys 를 안다.**

`build(spec, workdir)` 하나가 바깥이 쓰는 전부다: STEP 임포트 → 물성 → 메시 → 해석 설정 →
`model.dat`(+ `model.mechdb`). 솔브는 하지 않는다 — Mechanical 이 솔브 동안 라이선스를 물고
있으면 HPC 분산이 안 된다(로드맵의 결정).

**ansys import 는 함수 안에서 한다.** 모듈을 읽는 것만으로 Ansys 가 필요하면 Ansys 없는 PC 에서
`app.core` 를 import 하는 것 자체가 실패하고, 그러면 시험도 화면도 안 돈다.
"""

from app.core.mechanical.build import build

__all__ = ["build"]
