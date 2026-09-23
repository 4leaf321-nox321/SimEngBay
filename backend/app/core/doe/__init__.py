"""DOE 폴더 읽기 — **폴더 한 벌이 계약이다.**

CAD 플랫폼(CompCore)은 설계점 N 벌을 폴더 하나로 내놓고, 그 뒤로는 **아무것도 주고받지
않는다.**
되물을 API 가 없다(그쪽 「해석-조건-설계」 0장) — 연계할 해석 플랫폼이 하나가 아니고, 그중에는
그쪽 API 를 부를 수 없는 자리도 있기 때문이다. 결과도 되돌려 보내지 않는다. 설계점을 고르는
일(필터 · 파레토)이 이쪽 화면의 몫이다.

그래서 이 모듈이 하는 일은 하나다: **폴더를 읽어 「무엇을 몇 건 걸 수 있나」 를 말한다.**
"""

from app.core.doe.folder import DoeFolder, DoePoint, read_folder

__all__ = ["DoeFolder", "DoePoint", "read_folder"]
