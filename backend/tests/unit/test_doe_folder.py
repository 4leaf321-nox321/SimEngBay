"""DOE 폴더 읽기 — **CompCore 가 제 코드로 쓴 폴더**로 시험한다.

`tests/fixtures/doe/` 는 그쪽 `modules/doe/export.py` 와 `core/recipe/topology.py` 를 그대로
불러 만든 것이다. 손으로 지어낸 CSV 로 시험하면 BOM 같은 것이 빠지고, 그 차이는 **조용히
0건**으로 나타난다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.core.doe import read_folder
from app.core.doe.folder import FolderProblem

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "doe"
FOLDER = FIXTURES_ROOT / "브래킷_두께훑기-3f9a2177"


def test_스터디와_설계점을_읽는다() -> None:
    doe = read_folder(FOLDER)
    assert doe.name == "브래킷_두께훑기"
    assert doe.study_id.startswith("3f9a2177")
    assert doe.factors == ["두께"]
    assert len(doe.points) == 4
    assert [one.params["두께"] for one in doe.usable] == [6.0, 12.0, 20.0]


def test_BOM_이_붙은_CSV_를_읽는다() -> None:
    """**엑셀이 한글을 깨지 않게 CompCore 가 BOM 을 붙인다.** utf-8 로 읽으면 첫 열 이름이
    `﻿point` 가 되고 점 번호를 못 찾는다 — 오류가 아니라 조용한 0건이 된다."""
    raw = (FOLDER / "manifest.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "붙박이 파일에 BOM 이 없다면 이 시험은 무의미하다"
    assert [one.number for one in read_folder(FOLDER).points] == [1, 2, 3, 4]


def test_못_쓰는_점은_이유와_함께_건너뛴다() -> None:
    """설계점 200개를 보내 놓고 「왜 절반이 실패했지」 를 로그에서 찾게 하지 않는다."""
    doe = read_folder(FOLDER)
    skipped = doe.skipped
    assert len(skipped) == 1
    assert skipped[0].number == 4
    assert "벽이 판을 넘습니다" in skipped[0].skip_reason


def test_형상과_점_파일을_찾아_준다() -> None:
    first = read_folder(FOLDER).usable[0]
    assert first.step is not None and first.step.is_file()
    assert first.point_file is not None and first.point_file.is_file()
    # 점 파일 하나에 영역 · 바디 · 설계점 메타가 다 있다(2026-09-24 계약).
    loaded = json.loads(first.point_file.read_text(encoding="utf-8"))
    assert {"regions", "bodies", "point"} <= set(loaded)
    assert loaded["point"]["params"] == {"두께": 6.0}


def test_나눠_쓰는_형상은_같은_열쇠를_갖는다() -> None:
    """**파일 이름을 짐작하지 않는다.** 조건만 훑으면 CAD 가 형상 한 벌만 두고 `shapes/` 를
    가리킨다 — 점 번호로 이름을 지으면 그 폴더에서 파일을 못 찾는다.

    같은 경로를 가리키는 점들은 같은 형상이므로 **모델링 · 메시도 한 번만** 하면 된다.
    """
    doe = read_folder(CATEGORY_FOLDER)
    keys = {one.shape_key for one in doe.usable}
    assert keys == {"shapes/8f3a1c92.step"}
    assert all(one.step is not None and one.step.is_file() for one in doe.usable)
    # 조건이 점 파일에 실려 온다(CompCore 해석 조건 단계가 끝났다).
    assert all(one.has_conditions for one in doe.usable)


def test_영역을_못_푼_점은_걸지_않는다(tmp_path: Path) -> None:
    """영역이 안 풀렸으면 경계조건을 붙일 자리가 없다 — 그대로 걸면 구속 없는 해석이 돈다."""
    import shutil

    copy = tmp_path / FOLDER.name
    shutil.copytree(FOLDER, copy)
    manifest = copy / "manifest.csv"
    text = manifest.read_text(encoding="utf-8-sig")
    text = text.replace(
        "1,ok,6.0,points/p0001.step,points/p0001.json,,,",
        "1,ok,6.0,points/p0001.step,points/p0001.json,fixed_base,,",
    )
    manifest.write_text("﻿" + text, encoding="utf-8")

    doe = read_folder(copy)
    first = next(one for one in doe.points if one.number == 1)
    assert not first.usable
    assert "fixed_base" in first.skip_reason


def test_DOE_폴더가_아니면_말한다(tmp_path: Path) -> None:
    with pytest.raises(FolderProblem, match=re.escape("manifest.csv")):
        read_folder(tmp_path)
    with pytest.raises(FolderProblem, match="폴더가 없습니다"):
        read_folder(tmp_path / "없는곳")


def test_표가_폴더_밖을_가리키면_없는_것으로_본다(tmp_path: Path) -> None:
    """표는 **남이 만든 파일**이다. 그 값을 그대로 열면 폴더 밖의 파일을 읽는 문이 된다."""
    import shutil

    copy = tmp_path / FOLDER.name
    shutil.copytree(FOLDER, copy)
    manifest = copy / "manifest.csv"
    text = manifest.read_text(encoding="utf-8-sig").replace(
        "points/p0001.step", "../../../etc/passwd"
    )
    manifest.write_text("﻿" + text, encoding="utf-8")

    first = next(one for one in read_folder(copy).points if one.number == 1)
    assert first.step is None
    assert not first.usable


CATEGORY_FOLDER = FIXTURES_ROOT / "재료훑기-7c1d3a44"


def test_숫자가_아닌_인자를_버리지_않는다() -> None:
    """**재료처럼 고르는 인자가 온다**(CompCore 가 물성 DOE 를 붙이면서).

    숫자로 못 읽는다고 버리면 두 설계점이 화면에서 **똑같아 보이고**, 사람은 왜 결과가 다른지
    알 방법이 없다 — 실측으로 그 상태를 만들어 봤다(`재료` 칸이 통째로 사라졌다).
    """
    doe = read_folder(CATEGORY_FOLDER)
    assert doe.factors == ["재료"]
    assert [one.params["재료"] for one in doe.usable] == ["SS400", "AL6061"]
    # 숫자 인자는 숫자로 읽는다(그림의 가로축이 되어야 한다).
    numbers = read_folder(FOLDER)
    assert numbers.usable[0].params["두께"] == 6.0


def test_빈_칸은_없는_값이다() -> None:
    doe = read_folder(FOLDER)
    # 두께만 있는 스터디에 `재료` 칸은 아예 없다.
    assert all("재료" not in one.params for one in doe.points)


def test_없는_뿌리는_건너뛰고_있는_것부터_연다(tmp_path: Path) -> None:
    """공유 스토리지가 아직 안 마운트된 서버에서 첫 뿌리를 고집하면 창을 열자마자 오류가 뜨고,
    **다른 뿌리에 있는 것도 못 고른다.**"""
    from app.core.doe import resolve_inside

    missing = tmp_path / "없는곳"
    assert resolve_inside([missing, FIXTURES_ROOT], None) == FIXTURES_ROOT
    # 전부 없으면 첫 뿌리를 돌려준다 — 그때는 「그 경로가 없다」 가 정확한 진단이다.
    assert resolve_inside([missing], None) == missing


def test_뿌리_밖은_거절한다(tmp_path: Path) -> None:
    from app.core.doe import resolve_inside
    from app.core.doe.browse import OutsideRoots

    with pytest.raises(OutsideRoots):
        resolve_inside([FIXTURES_ROOT], "/etc")
    # `..` 으로 빠져나가는 길도 — **푼 다음에** 견줘야 막힌다.
    with pytest.raises(OutsideRoots):
        resolve_inside([FIXTURES_ROOT], str(FIXTURES_ROOT / ".." / ".." / ".."))
