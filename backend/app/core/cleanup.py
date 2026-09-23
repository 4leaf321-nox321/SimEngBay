"""작업 폴더 정리 — **결과는 남기고 중간 파일만 지운다.**

해석 한 건이 남기는 것 중 대부분은 **다시 만들 수 있거나 이미 다 읽은 것**이다.

실측(브래킷 한 건, 2026-09-24): `.mechdb` 4.8MB · `.rst` 0.5~4.7MB · MAPDL scratch
(`file.db` · `file.mode` · `file.DSP` …)가 폴더의 대부분이고, 사람이 보는 것(고유진동수 ·
모드 그림)은 수십 KB 다. 설계점 200개 DOE 면 그 차이가 2~3GB 가 된다.

## 무엇을 남기나

| 남긴다 | 왜 |
| --- | --- |
| `input.step` · `topology.json` · `spec.json` | **무엇으로 돌렸나** — 없으면 못 되짚는다 |
| `result.json` · `mode_*.png` · `mode_*.vtp` | 사람이 보는 것 |
| `model.dat` | 솔버 입력. 작고, 이것만 있으면 다시 풀 수 있다 |
| `solve.out` | 왜 그렇게 풀렸나(라이선스 · 경고 · 시간) |

## 무엇을 지우나

`.mechdb`(Mechanical 디버깅용) · `.rst`(결과 원본) · MAPDL scratch.

**`.rst` 를 지우면 모드를 더 뽑을 수 없다** — 그림을 6개만 만들어 두고 나중에 12개로 늘리려면
다시 풀어야 한다. 그래서 정리는 **사람이 누르는 일**이고 자동으로 돌지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: 지울 파일 이름의 꼴. MAPDL 은 잡 이름(`file`)으로 여러 벌을 쓴다.
SCRATCH_PATTERNS = (
    "file.db",
    "file.DSP",
    "file.ce",
    "file.mlv",
    "file.mode",
    "file.esav",
    "file.full",
    "file.emat",
    "file.stat",
    "file.rdb",
    "file*.err",
    "file*.log",
    "file*WBINFO.xml",
    "file1.out",
    "*.mechdb",
    "*.rst",
    "*.rth",
    ".stage-*.json",
)

#: 이 이름은 무슨 일이 있어도 남긴다 — 위 꼴에 걸리더라도.
KEEP_NAMES = frozenset(
    {"input.step", "topology.json", "spec.json", "result.json", "model.dat", "solve.out"}
)


@dataclass(frozen=True)
class Tidied:
    files: list[Path]
    bytes_freed: int


def plan(workdir: Path) -> Tidied:
    """지울 것과 그 크기. **지우지는 않는다** — 먼저 얼마나 줄어드는지 말할 수 있어야 한다."""
    if not workdir.is_dir():
        return Tidied(files=[], bytes_freed=0)
    found: dict[Path, int] = {}
    for pattern in SCRATCH_PATTERNS:
        for path in workdir.glob(pattern):
            if not path.is_file() or path.name in KEEP_NAMES:
                continue
            found[path] = path.stat().st_size
    # 모드 그림은 남긴다 — 위 `*.vtp` 꼴에 안 걸리지만 분명히 해 둔다.
    return Tidied(files=sorted(found), bytes_freed=sum(found.values()))


def run(workdir: Path) -> Tidied:
    """정리하고 실제로 지운 것을 돌려준다.

    **못 지운 파일은 넘어간다** — 지우기가 실패했다고 다 끝난 해석을 실패로 적을 이유가 없다.
    """
    planned = plan(workdir)
    removed: list[Path] = []
    freed = 0
    for path in planned.files:
        try:
            size = path.stat().st_size
            path.unlink()
        except OSError:
            continue
        removed.append(path)
        freed += size
    return Tidied(files=removed, bytes_freed=freed)


def folder_bytes(workdir: Path) -> int:
    if not workdir.is_dir():
        return 0
    return sum(path.stat().st_size for path in workdir.rglob("*") if path.is_file())
