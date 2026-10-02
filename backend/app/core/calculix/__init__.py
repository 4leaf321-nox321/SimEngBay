"""CalculiX 경로 — **오픈소스 솔버로도 같은 폴더를 푼다.**

Ansys 경로(`app/core/mechanical` · `solve` · `dpf`)와 **역할이 일대일로 맞는다**:

    build.py   모델링 — gmsh 로 메시, 조건을 걸고 `.inp` 를 쓴다   (mechanical/build.py)
    solve.py   솔브 — `ccx` 를 부른다                              (solve/mapdl.py)
    read.py    추출 — `.dat` 에서 고유진동수를 읽는다              (dpf/extract.py)
    deck.py    덱 쓰기와 **능력표**(무엇을 걸 수 있나)
    mesh.py    메시와 면 · 바디 지문
    tools.py   gmsh · ccx 를 **딴 프로세스로** 부르는 자리(GPL 경계)

조건 읽기 · 물성 · 바디 짝짓기 · 영역 매칭은 **둘이 같은 코드를 쓴다** — 그래서 두 솔버가 같은
조건을 같은 자리에 걸고, 수를 견주는 것이 뜻을 가진다.

**왜 이 경로가 있나.** Ansys 는 노드락 라이선스 하나라 DOE 를 한 점씩 줄 세워 푼다. CalculiX 는
깔린 서버에서 **코어 수만큼 동시에** 돌 수 있다 — 설계점 수십 개를 훑는 이 플랫폼에서 그것이
처리량이다. 그리고 CI 가 Ansys 없이 **형상부터 주파수까지** 검사할 수 있게 된다.
"""

from app.core.calculix.build import build
from app.core.calculix.read import extract
from app.core.calculix.solve import solve

__all__ = ["build", "extract", "solve"]
