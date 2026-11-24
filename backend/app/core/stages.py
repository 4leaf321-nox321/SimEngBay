"""단계 — 해석 작업이 지나는 네 걸음과, 각 걸음이 남기는 것.

    fetching    입력 형상을 작업 폴더로 (업로드 · CAD 플랫폼 · DOE 폴더)
    modeling    PyMechanical: 임포트 → 물성 → 접촉 → 메시 → 해석 설정 → .dat (+ .mechdb)
    solving     솔버에 .dat 를 넘기고 .rst 를 받는다
    extracting  DPF: .rst → result.json · 모드별 PNG · VTP

상태 기계는 `queued → fetching → modeling → solving → extracting → done | failed`. 단계 이름이
곧 「지금 무엇을 하고 있나」 의 상태다 — 상태와 단계를 따로 두면 둘이 어긋나는 날이 온다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Stage = Literal["fetching", "modeling", "solving", "extracting"]

#: 「지금 취소됐나」 를 묻는 함수. **워커가 DB 를 본다** — 코어는 그 사정을 모른다.
CancelCheck = Callable[[], bool]

#: 지나는 순서. 워커는 이 순서대로 돌리고, 하나가 실패하면 뒤는 안 돈다.
STAGES: tuple[Stage, ...] = ("fetching", "modeling", "solving", "extracting")

#: 쉘 파트의 **중간면 형상** — 작업 폴더에서의 이름. CAD 폴더의 `pNNNN_mid.step` 이 이 이름으로
#: 들어온다(쉘 파트가 있을 때만). 두 솔버의 모델링이 같은 이름을 본다.
MIDSURFACE_NAME = "input_mid.step"

#: 실패 원인 — 사람이 목록에서 읽고 무엇을 고칠지 아는 단위. **메시지가 아니라 코드다.**
#: 같은 원인이 워커마다 다른 문장으로 적히면 「라이선스 때문에 몇 건 실패했나」 를 셀 수 없다.
FailureCode = Literal[
    "geometry_import",  # STEP 을 못 읽었다 — CAD 쪽 파일 문제
    "region_unresolved",  # topology.json 의 영역을 형상에서 못 찾았다(4단계)
    "mesh_failed",
    "solver_failed",
    "license",  # Mechanical · 솔버 라이선스를 못 받았다
    "timeout",
    # 메모리가 모자라 운영체제(OOM)가 솔버를 강제로 멈췄다 — 요소 크기 · 동시 실행 수를 본다.
    "out_of_memory",
    "worker_lost",  # 워커가 죽어 되살리다 한도를 넘겼다
    # STE(Slurm 클러스터)에서 풀도록 건 작업 — 요청서 2026-11-24 E-1 · E-3(`calculix/ste.py`).
    # **어느 것이든 로컬로 물러서지 않는다.**
    "ste_auth",  # 건 사람 명의의 STE 토큰을 못 받았다(설정 없음 · 건 사람 없음 · STE 거절)
    "ste_unavailable",  # STE 가 응답이 없거나 5xx 다
    "ste_rejected",  # STE 가 업로드 · 제출을 4xx 로 거절했다
    "internal",  # 코어의 버그 — 트레이스백이 로그에 있다
]

#: 산출물 종류. 화면이 이것으로 아이콘 · 이름 · 「뷰어로 열기」 를 가른다.
ArtifactKind = Literal[
    "input_step",
    # 쉘 파트의 중간면(CAD 의 `pNNNN_mid.step`).
    "input_mid_step",
    "spec",
    "topology",
    "mechdb",
    "dat",
    "solve_out",
    "rst",
    # CalculiX 의 결과 파일 — `.rst` 와 같은 자리다(솔버만 다르다).
    "frd",
    "result_json",
    "mode_png",
    "mode_vtp",
    "log",
]

CONTENT_TYPES: dict[str, str] = {
    "input_step": "model/step",
    "input_mid_step": "model/step",
    "spec": "application/json",
    "topology": "application/json",
    "mechdb": "application/octet-stream",
    "dat": "text/plain",
    "frd": "text/plain",
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


class StageCanceled(Exception):
    """사람이 취소했다. **실패가 아니다** — 세지도, 「남은 일」 에 올리지도 않는다."""


def out_of_memory_message(what: str) -> str:
    """메모리가 모자라 운영체제가 끊은 것의 한 줄(`out_of_memory`) — 사람이 할 일까지."""
    return (
        f"{what} 가 메모리가 모자라 강제로 멈췄습니다(운영체제가 끊었습니다). 요소 크기를 "
        "키우거나 동시에 도는 해석 수(워커 수)를 줄이세요 — 메시 수렴 점검의 촘촘한 수준이 "
        "특히 큽니다."
    )


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
    requester_email: str | None = None
    """작업을 건 사람 — **STE 에서 풀 때만** 싣는다(그 사람 명의로만 잡을 낸다,
    `calculix/ste.py`). 토큰이 아니라 이메일이다 — 토큰은 자식이 그 자리에서 받는다."""
    requester_name: str = ""
    env: tuple[tuple[str, str], ...] = ()
    """**이 작업의 단계 설정**(코어가 읽는 환경 이름 · 값) — 앱이 서버 설정에서 정한다(작업을
    만들 때 고정한 본딩 · 선형 솔버 · 허용오차 · 스레드, STE 연결). 자식 환경에서 **프로세스
    환경을 이긴다** — 워커 하나의 환경이 다르다고 같은 작업이 다르게 풀리면 안 된다."""
