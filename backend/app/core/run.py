"""단계 하나를 **다른 프로세스에서** 돌리는 진입점.

    python -m app.core.run <단계> <작업폴더>

작업 폴더에 `spec.json` 이 있어야 하고, 결과는 `<작업폴더>/.stage-<단계>.json` 에 쓴다.
성공이면 종료 코드 0, 사람이 읽을 수 있는 실패면 1, 코어의 버그면 2.

## 왜 파일로 주고받나

이 프로세스는 **다른 파이썬일 수 있다** — 개발 PC 에서는 WSL 의 워커가 Windows 의 파이썬을
부른다(Ansys 가 거기 있다). 객체를 넘길 수 없고, stdout 은 Ansys 가 제 로그로 채운다.
그래서 약속을 파일 하나로 둔다: **마지막 줄을 파싱하지 않는다.**

## 스펙을 왜 다시 읽나

부르는 쪽이 이미 검증한 스펙이지만, 이 프로세스는 그 사실을 모른다. 여기서 다시 읽으면
「손으로 이 명령을 쳐서 모델링만 다시 해 보는」 길이 그대로 열린다 — 모델링을 고칠 때마다
서버와 DB 를 띄우면 아무도 안 고친다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.core.spec import ModalSpec, parse_spec
from app.core.stages import STAGES, ArtifactSpec, Stage, StageFailure, StageResult

#: 결과 파일 이름. 단계마다 따로 둔다 — 한 폴더에서 네 단계가 차례로 돌고, 지난 단계의 기록이
#: 남아 있어야 「어디서 멈췄나」 를 폴더만 보고도 안다.
RESULT_PREFIX = ".stage-"


def result_path(workdir: Path, stage: str) -> Path:
    return workdir / f"{RESULT_PREFIX}{stage}.json"


def run_stage(
    stage: Stage,
    spec: ModalSpec,
    workdir: Path,
    *,
    input_name: str,
    version: int,
    ansys_root: Path | None,
    solver_processes: int,
    timeout_seconds: int,
    visual_modes: int,
) -> StageResult:
    """단계 하나. **Ansys import 는 그 단계에 들어갈 때** — 없는 것을 미리 부르지 않는다."""
    if stage == "fetching":
        step = workdir / input_name
        if not step.is_file():
            raise StageFailure("geometry_import", f"입력 형상이 없습니다: {input_name}")
        size = step.stat().st_size
        if size == 0:
            raise StageFailure("geometry_import", "입력 형상이 빈 파일입니다.")
        return StageResult(summary={"input_bytes": size}, detail=f"{input_name} ({size:,} B)")

    if stage == "modeling":
        from app.core.mechanical import build

        return build(spec, workdir, input_name=input_name, version=version)

    if stage == "solving":
        from app.core.solve import solve

        return solve(
            workdir,
            version=version,
            root=ansys_root,
            processes=solver_processes,
            timeout_seconds=timeout_seconds,
        )

    if stage == "extracting":
        from app.core.dpf import extract

        return extract(spec, workdir, visual_modes=visual_modes)

    raise StageFailure("internal", f"모르는 단계입니다: {stage}")


def _dump(result: StageResult, workdir: Path) -> dict[str, Any]:
    return {
        "ok": True,
        "summary": result.summary,
        "detail": result.detail,
        # 경로는 **작업 폴더 기준 상대**로 준다. 부르는 쪽은 다른 OS 라 절대경로가 그쪽에서
        # 성립하지 않는다(`C:\...` 를 WSL 이 열 수 없다).
        "artifacts": [
            {"kind": one.kind, "path": _relative(one.path, workdir)}
            for one in result.artifacts
        ],
    }


def _relative(path: Path, workdir: Path) -> str:
    try:
        return str(path.resolve().relative_to(workdir.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="해석 단계 하나를 돌린다")
    parser.add_argument("stage", choices=list(STAGES))
    parser.add_argument("workdir", type=Path)
    parser.add_argument("--input-name", default="input.step")
    parser.add_argument("--ansys-version", type=int, default=252)
    parser.add_argument("--ansys-root", type=Path, default=None)
    parser.add_argument("--solver-processes", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=10800)
    parser.add_argument("--visual-modes", type=int, default=6)
    args = parser.parse_args(argv)

    workdir: Path = args.workdir
    target = result_path(workdir, args.stage)
    target.unlink(missing_ok=True)

    try:
        raw = json.loads((workdir / "spec.json").read_text(encoding="utf-8"))
        spec = parse_spec(raw)
        if not isinstance(spec, ModalSpec):
            raise StageFailure("internal", f"{spec.recipe} 레시피는 실행기가 없습니다.")
        result = run_stage(
            args.stage,
            spec,
            workdir,
            input_name=args.input_name,
            version=args.ansys_version,
            ansys_root=args.ansys_root,
            solver_processes=args.solver_processes,
            timeout_seconds=args.timeout_seconds,
            visual_modes=args.visual_modes,
        )
    except StageFailure as failure:
        target.write_text(
            json.dumps(
                {
                    "ok": False,
                    "code": failure.code,
                    "message": failure.message,
                    "details": failure.details,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[{failure.code}] {failure.message}", file=sys.stderr)
        return 1
    except Exception as failure:  # 코어의 버그 — 부르는 쪽이 트레이스백을 로그에 남긴다
        import traceback

        target.write_text(
            json.dumps(
                {
                    "ok": False,
                    "code": "internal",
                    "message": f"{type(failure).__name__}: {failure}",
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        traceback.print_exc()
        return 2

    target.write_text(
        json.dumps(_dump(result, workdir), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[ok] {args.stage}: {result.detail}")
    return 0


def read_result(workdir: Path, stage: str) -> StageResult:
    """`main` 이 쓴 성공 결과를 읽어 `StageResult` 로. 실패는 `StageFailure` 로 던진다."""
    path = result_path(workdir, stage)
    if not path.is_file():
        raise StageFailure(
            "internal",
            f"{stage} 단계가 결과 파일을 남기지 않았습니다 — 프로세스가 도중에 죽었습니다.",
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("ok"):
        raise StageFailure(
            payload.get("code", "internal"),
            payload.get("message", "실행기가 이유를 남기지 않았습니다."),
            details=payload.get("details") or {},
        )
    return StageResult(
        artifacts=[
            ArtifactSpec(one["kind"], workdir / one["path"])
            for one in payload.get("artifacts", [])
        ],
        summary=payload.get("summary") or {},
        detail=payload.get("detail", ""),
    )


if __name__ == "__main__":
    raise SystemExit(main())
