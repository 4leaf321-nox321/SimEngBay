"""가짜 실행기 — 단계마다 잠깐 쉬고 **모양만 맞는** 산출물을 남긴다.

시험과 Ansys 없는 PC 가 쓴다. 상태 기계 · 산출물 등록 · 화면 타임라인 · PAT 경로가 전부 이것
검증되고, 1.5단계는 실행기만 진짜로 갈아끼운다. 그래서 파일 이름과 `result.json` 의 모양은
진짜 실행기와 **같아야 한다** — 화면이 이 모양을 보고 만들어지기 때문이다.

고유진동수는 지어낸 값이다. 스펙의 물성으로 그럴듯하게(강성/밀도 제곱근에 비례) 만들어, 화면이
「값이 바뀌는 것」 을 볼 수 있게만 한다. 자유-자유면 앞 6개를 0 근처로 둔다.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from app.core.spec import RIGID_BODY_MODES, ModalSpec, parse_spec
from app.core.stages import (
    ArtifactSpec,
    StageContext,
    StageFailure,
    StageResult,
)


class FakeExecutor:
    name = "fake"

    def __init__(self, *, stage_seconds: float = 0.0) -> None:
        self.stage_seconds = stage_seconds

    def run(self, ctx: StageContext) -> StageResult:
        if self.stage_seconds > 0:
            time.sleep(self.stage_seconds)
        spec = parse_spec(ctx.spec)
        if not isinstance(spec, ModalSpec):
            raise StageFailure("internal", f"가짜 실행기는 {spec.recipe} 를 모릅니다.")
        handler = getattr(self, f"_{ctx.stage}")
        result: StageResult = handler(ctx, spec)
        return result

    # --- 단계 -----------------------------------------------------------------

    def _fetching(self, ctx: StageContext, spec: ModalSpec) -> StageResult:
        source = ctx.workdir / ctx.input_name
        if not source.is_file():
            raise StageFailure("geometry_import", f"입력 형상이 없습니다: {ctx.input_name}")
        if source.stat().st_size == 0:
            raise StageFailure("geometry_import", "입력 형상이 빈 파일입니다.")
        return StageResult(
            summary={"input_bytes": source.stat().st_size},
            detail=f"{ctx.input_name} ({source.stat().st_size:,} B)",
        )

    def _modeling(self, ctx: StageContext, spec: ModalSpec) -> StageResult:
        dat = ctx.workdir / "model.dat"
        dat.write_text(
            "/PREP7\n! fake input — 진짜 실행기가 오면 WriteInputFile 의 것으로 바뀐다\n"
            f"! material {spec.material.name}\n/SOLU\nANTYPE,MODAL\n"
            f"MODOPT,LANB,{spec.modes_to_find}\nSOLVE\nFINISH\n",
            encoding="utf-8",
        )
        mechdb = ctx.workdir / "model.mechdb"
        mechdb.write_bytes(b"fake mechdb\n")
        nodes = 12_345
        return StageResult(
            artifacts=[ArtifactSpec("dat", dat), ArtifactSpec("mechdb", mechdb)],
            summary={"bodies": 1, "nodes": nodes, "elements": 6_789},
            detail=f"바디 1 · 절점 {nodes:,}",
        )

    def _solving(self, ctx: StageContext, spec: ModalSpec) -> StageResult:
        if not (ctx.workdir / "model.dat").is_file():
            raise StageFailure(
                "solver_failed", "model.dat 이 없습니다 — 모델링 단계가 남긴 것이 없습니다."
            )
        rst = ctx.workdir / "model.rst"
        rst.write_bytes(b"fake rst\n")
        out = ctx.workdir / "solve.out"
        out.write_text("*** FAKE SOLVE ***\nELAPSED TIME 0.0 s\n", encoding="utf-8")
        return StageResult(
            artifacts=[ArtifactSpec("rst", rst), ArtifactSpec("solve_out", out)],
            detail="fake 솔브",
        )

    def _extracting(self, ctx: StageContext, spec: ModalSpec) -> StageResult:
        modes: list[dict[str, Any]] = []
        elastic_index = 0
        for index, value in enumerate(_fake_frequencies(spec)):
            rigid = spec.is_free_free and index < RIGID_BODY_MODES
            if not rigid:
                elastic_index += 1
            # **진짜 실행기와 같은 칸을 낸다.** 화면이 이 모양을 보고 만들어지므로, 여기가
            # 한 칸 모자라면 fake 로 본 화면과 진짜로 본 화면이 다르다.
            modes.append(
                {
                    "number": index + 1,
                    "elastic_number": None if rigid else elastic_index,
                    "frequency_hz": round(value, 3),
                    "rigid_body": rigid,
                }
            )
        result: dict[str, Any] = {
            "recipe": "modal",
            "boundary": "free-free" if spec.is_free_free else "constrained",
            # **단위계와 정규화 방식을 반드시 싣는다.** 값만 보면 mm-t-s 와 SI 가 구별되지
            # 않고, 그 차이는 고유진동수를 31.6배 틀리게 한다.
            "units": {"frequency": "Hz", "length": "mm", "mass": "t"},
            "normalization": "mass",
            "rigid_body_modes": RIGID_BODY_MODES if spec.is_free_free else 0,
            "mesh": {"nodes": 12_345, "elements": 6_789},
            "modes": modes,
            # 모드 형상 · 참여계수는 **안 만든다.** 가짜 그림을 그리면 화면에서 진짜와
            # 구별되지 않는다 — 없으면 화면이 「그림이 없습니다」 라고 말한다.
            "participation": {},
            "fake": True,
        }
        result_path = ctx.workdir / "result.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        elastic = [one for one in modes if not one["rigid_body"]]
        first: float | None = elastic[0]["frequency_hz"] if elastic else None
        return StageResult(
            artifacts=[ArtifactSpec("result_json", result_path)],
            summary={"modes": len(modes), "first_elastic_hz": first},
            detail=f"모드 {len(modes)}개" + (f" · 1차 {first} Hz" if first else ""),
        )


def _fake_frequencies(spec: ModalSpec) -> list[float]:
    """지어낸 고유진동수. 강성/밀도 제곱근에 비례하게 만들어 물성을 바꾸면 값이 따라오게
    한다."""
    scale = (
        math.sqrt(spec.material.youngs_modulus_gpa * 1e9 / spec.material.density_kg_m3) / 1000
    )
    values: list[float] = []
    if spec.is_free_free:
        values.extend(0.0001 * (index + 1) for index in range(RIGID_BODY_MODES))
    values.extend(scale * (0.05 * (index + 1) ** 1.5) for index in range(spec.modes))
    return values


def write_fixture_step(path: Path) -> None:
    """시험용 STEP 흉내. 진짜 STEP 헤더만 있어 fake 실행기가 「비지 않은 파일」 로 받는다."""
    path.write_text(
        "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('fake'),'2;1');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n",
        encoding="utf-8",
    )
