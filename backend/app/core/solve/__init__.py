"""솔버 — `.dat` 를 MAPDL 에 넘기고 `.rst` 를 받는다.

지금 있는 것은 **같은 기계에서 배치로 돌리는** 어댑터 하나다(개발 · PoC). Slurm 어댑터는
2단계에서 같은 인터페이스로 들어온다 — 그때 갈리는 것은 「제출하고 기다리는 방법」 뿐이다.
"""

from app.core.solve.mapdl import solve

__all__ = ["solve"]
