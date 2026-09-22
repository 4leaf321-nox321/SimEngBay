"""단계 — 해석 작업이 지나는 네 걸음과, 각 걸음이 남기는 것.

    fetching    입력 형상을 작업 폴더로 (업로드 · CAD 플랫폼 · DOE 폴더)
    modeling    PyMechanical: 임포트 → 물성 → 접촉 → 메시 → 해석 설정 → .dat (+ .mechdb)
    solving     솔버에 .dat 를 넘기고 .rst 를 받는다
    extracting  DPF: .rst → result.json · 모드별 PNG · VTP

상태 기계는 `queued → fetching → modeling → solving → extracting → done | failed`. 단계 이름이
곧 「지금 무엇을 하고 있나」 의 상태다 — 상태와 단계를 따로 두면 둘이 어긋나는 날이 온다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Stage = Literal["fetching", "modeling", "solving", "extracting"]

#: 지나는 순서. 워커는 이 순서대로 돌리고, 하나가 실패하면 뒤는 안 돈다.
STAGES: tuple[Stage, ...] = ("fetching", "modeling", "solving", "extracting")

#: 실패 원인 — 사람이 목록에서 읽고 무엇을 고칠지 아는 단위. **메시지가 아니라 코드다.**
#: 같은 원인이 워커마다 다른 문장으로 적히면 「라이선스 때문에 몇 건 실패했나」 를 셀 수 없다.
FailureCode = Literal[
    "geometry_import",  # STEP 을 못 읽었다 — CAD 쪽 파일 문제
    "region_unresolved",  # topology.json 의 영역을 형상에서 못 찾았다(4단계)
    "mesh_failed",
    "solver_failed",
    "license",  # Mechanical · 솔버 라이선스를 못 받았다
    "timeout",
    "worker_lost",  # 워커가 죽어 되살리다 한도를 넘겼다
    "internal",  # 코어의 버그 — 트레이스백이 로그에 있다
]

#: 산출물 종류. 화면이 이것으로 아이콘 · 이름 · 「뷰어로 열기」 를 가른다.
ArtifactKind = Literal[
    "input_step",
    "spec",
    "mechdb",
    "dat",
    "solve_out",
    "rst",
    "result_json",
    "mode_png",
    "mode_vtp",
    "log",
]

CONTENT_TYPES: dict[str, str] = {
    "input_step": "model/step",
    "spec": "application/json",
    "mechdb": "application/octet-stream",
    "dat": "text/plain",
    "solve_out": "text/plain",
    "rst": "application/octet-stream",
    "result_json": "application/json",
    "mode_png": "image/png",
    "mode_vtp": "application/octet-stream",
    "log": "text/plain",
}


@dataclass(frozen=True)
class ArtifactSpec:
    """단계가 남긴 파일 하나. 서비스가 이것을 표의 행으로 만든다."""

    kind: ArtifactKind
    path: Path

    @property
    def content_type(self) -> str:
        return CONTENT_TYPES[self.kind]


@dataclass
class StageResult:
    artifacts: list[ArtifactSpec] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    """이 단계가 알아낸 것 — 바디 수 · 절점 수 · 고유진동수. 작업의 `summary` 에 합쳐진다."""
    detail: str = ""
    """한 줄. 화면의 타임라인에 그 단계 옆에 선다."""


class StageFailure(Exception):
    """**사람이 읽고 고칠 수 있는** 실패. 코드와 한 줄 메시지가 그대로 화면에 간다.

    다른 예외는 코어의 버그다 — 서비스가 `internal` 로 적고 트레이스백을 로그에 남긴다.
    """

    def __init__(
        self, code: FailureCode, message: str, *, details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.code: FailureCode = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class StageContext:
    """실행기가 한 단계를 돌리는 데 필요한 전부. **DB 를 모른다** — 경로와 스펙뿐이다."""

    stage: Stage
    spec: dict[str, Any]
    """`ModalSpec.model_dump()` — 실행기가 다른 프로세스(Windows 파이썬)일 수 있어 dict 로
    넘긴다."""
    workdir: Path
    """이 작업의 폴더. 앞 단계의 산출물이 여기 있고, 이 단계도 여기 쓴다."""
    input_name: str = "input.step"
