"""워커가 집을 솔버 — **설정이 비면 깔린 도구로 고른다.**

전에는 비면 무조건 전부 집었다. gmsh 가 없는 개발 PC 의 워커가 CalculiX 작업을 집어 1초
만에 「gmsh 를 찾지 못했습니다」 로 실패시켰다(2026-10-04, 재료훑기 p0002). 못 돌리는 작업은
대기열에 남아야 한다 — 그래야 다른 워커가 집고, 작업을 거는 화면이 「집을 워커가 없다」 고 미리
말한다.
"""

from __future__ import annotations

from typing import Any

from app.worker import solvers_for

BRIDGE = {"version": 252, "path": None, "checked": False, "note": "Windows 쪽"}


def _tools(gmsh: str | None, ccx: str | None, ansys: dict[str, Any]) -> dict[str, Any]:
    return {"gmsh": gmsh, "ccx": ccx, "ansys": ansys}


def test_설정이_있으면_그대로_따른다() -> None:
    tools = _tools(None, None, BRIDGE)
    assert solvers_for(" calculix ", executor="local", tools=tools) == ("calculix",)
    assert solvers_for("ansys,calculix", executor="local", tools=tools) == (
        "ansys",
        "calculix",
    )


def test_gmsh_가_없으면_CalculiX_를_집지_않는다() -> None:
    # 개발 PC — Ansys 는 다리 건너 Windows 에 있고(여기서 확인 못 함), WSL 에 gmsh 가 없다.
    tools = _tools(None, "/usr/bin/ccx", BRIDGE)
    assert solvers_for("", executor="windows-bridge", tools=tools) == ("ansys",)


def test_둘_다_깔렸으면_둘_다_집는다() -> None:
    tools = _tools("/usr/bin/gmsh", "/usr/bin/ccx", BRIDGE)
    assert solvers_for("", executor="windows-bridge", tools=tools) == ("ansys", "calculix")


def test_Ansys_를_확인했는데_없으면_빼고_아무것도_없으면_빈_것이다() -> None:
    missing = {"version": 252, "path": None, "checked": True, "note": "실행 파일이 없습니다"}
    assert solvers_for(
        "", executor="local", tools=_tools("/usr/bin/gmsh", "/usr/bin/ccx", missing)
    ) == ("calculix",)
    # 빈 것은 「아무것도 안 집는다」 — 워커가 까닭을 적고 뜨지 않는다(`Worker.run`).
    assert solvers_for("", executor="local", tools=_tools(None, None, missing)) == ()


def test_모의_실행기는_전부_집는다() -> None:
    # 솔버를 부르지 않는다 — 도구가 없어도 돈다.
    assert solvers_for("", executor="fake", tools=_tools(None, None, BRIDGE)) is None
