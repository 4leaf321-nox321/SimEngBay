"""영역 매칭 — CAD 가 이름으로 부른 자리를 **형상에서 다시 찾는다.**

CAD 플랫폼(CompCore)은 `topology.json` 에 영역을 **좌표 지문**으로 적어 보낸다. STEP 이
이름표를 못 나르기 때문이다 — 그쪽 실측: 한글 이름은 파일에 UTF-8 바이트조차 없었다. 면 번호로
적지 않는 이유는 더 크다. 실험계획(DOE)은 치수를 바꿔 형상을 여러 벌 만드는데, 「7번 면」 은
두께를 3 에서 10 으로 훑는 순간 다른 면을 가리킨다.

그래서 받는 쪽이 하는 일은 하나다: **지문으로 짝짓기.**
"""

from app.core.regions.match import FaceRecord, MatchFailure, RegionMatch, match_regions

__all__ = ["FaceRecord", "MatchFailure", "RegionMatch", "match_regions"]
