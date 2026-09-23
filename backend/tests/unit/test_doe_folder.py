"""DOE 폴더 읽기 — **CompCore 가 제 코드로 쓴 폴더**로 시험한다.

`tests/fixtures/doe/` 는 그쪽 `modules/doe/export.py` 와 `core/recipe/topology.py` 를 그대로
불러 만든 것이다. 손으로 지어낸 CSV 로 시험하면 BOM 같은 것이 빠지고, 그 차이는 **조용히
0건**으로 나타난다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.doe import read_folder
from app.core.doe.folder import FolderProblem

FOLDER = Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "브래킷_두께훑기-3f9a2177"


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


def test_형상과_지문_파일을_찾아_준다() -> None:
    first = read_folder(FOLDER).usable[0]
    assert first.step is not None and first.step.is_file()
    assert first.topology is not None and first.topology.is_file()
    # 같은 형상인지 되짚는 열쇠 — 조건만 훑는 DOE 에서 메시를 다시 만들지 않는 길이다.
    assert first.recipe_digest.startswith("sha256:")


def test_영역을_못_푼_점은_걸지_않는다(tmp_path: Path) -> None:
    """영역이 안 풀렸으면 경계조건을 붙일 자리가 없다 — 그대로 걸면 구속 없는 해석이 돈다."""
    import shutil

    copy = tmp_path / FOLDER.name
    shutil.copytree(FOLDER, copy)
    manifest = copy / "manifest.csv"
    text = manifest.read_text(encoding="utf-8-sig")
    text = text.replace(
        "1,ok,6.0,points/p0001.step,points/p0001.topology.json,,,",
        "1,ok,6.0,points/p0001.step,points/p0001.topology.json,fixed_base,,",
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
