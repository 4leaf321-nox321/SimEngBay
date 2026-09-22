"""JobSpec — 해석 작업의 입력. **레시피별로 허용 칸을 제한한다.**

Mechanical 의 모든 기능을 노출하지 않는다. 오케스트레이터(와 사람)가 줄 수 있는 것은 레시피가
받는 칸뿐이고, 그 밖의 것은 여기서 거절된다 — 워커가 집어 들고 나서 모르는 칸 때문에 실패하면
사람은 「왜 실패했나」 를 목록에서 찾아야 한다.

지금은 `modal` 하나다. `static` 은 스펙만 자리를 잡아 두고 실행기는 없다(계획서 「그 뒤」).

## 단위

Mechanical 은 단위계를 여러 개 받지만 **이 스펙은 하나로 못 박는다** — 칸 이름에 단위가 있다
(`youngs_modulus_gpa` · `density_kg_m3` · `element_size_mm`). 이름에 단위가 없으면 값 하나가
1000배 틀려도 아무도 모르고, 그 사실은 고유진동수가 31.6배 어긋난 뒤에야 드러난다.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

#: 강체 모드 수 — 구속이 없는 3차원 물체는 자유도 6개(이동 3 · 회전 3)가 0 Hz 로 나온다.
RIGID_BODY_MODES = 6


class MaterialSpec(BaseModel):
    """등방성 선형 탄성 물성. 물성 DB 가 붙기 전엔 직접 준다."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    youngs_modulus_gpa: float = Field(gt=0, le=2000)
    poisson_ratio: float = Field(ge=0, lt=0.5)
    density_kg_m3: float = Field(gt=0, le=30000)


class MeshSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_size_mm: float | None = Field(default=None, gt=0)
    """비우면 Mechanical 의 기본 크기. Student 판은 절점 상한이 있어 개발 PC 에서는 크게
    준다."""
    order: Literal["quadratic", "linear"] = "quadratic"


class Constraint(BaseModel):
    """영역 하나에 거는 구속. 영역 이름은 CAD 가 준 `topology.json` 의 것이다(4단계)."""

    model_config = ConfigDict(extra="forbid")

    region: str = Field(min_length=1, max_length=80)
    kind: Literal["fixed"] = "fixed"


class ModalSpec(BaseModel):
    """모달 해석. **구속이 비면 자유-자유** — 앞 6개 모드가 강체(≈0 Hz)로 나온다."""

    model_config = ConfigDict(extra="forbid")

    recipe: Literal["modal"] = "modal"
    material: MaterialSpec
    mesh: MeshSpec = Field(default_factory=MeshSpec)
    modes: int = Field(default=10, ge=1, le=100)
    """찾을 **탄성** 모드 수. 강체 모드는 여기 세지 않는다 — 실행기가 6개를 더해 찾는다."""
    constraints: list[Constraint] = Field(default_factory=list)

    @property
    def is_free_free(self) -> bool:
        return not self.constraints

    @property
    def modes_to_find(self) -> int:
        """Mechanical 에 줄 수. 자유-자유면 강체 6개를 얹어야 탄성 모드가 `modes` 개 나온다."""
        return self.modes + (RIGID_BODY_MODES if self.is_free_free else 0)


class StaticSpec(BaseModel):
    """정적 해석 — **자리만 있다.** 실행기가 없어 지금은 걸 수 없다(services 가 거절한다)."""

    model_config = ConfigDict(extra="forbid")

    recipe: Literal["static"] = "static"
    material: MaterialSpec
    mesh: MeshSpec = Field(default_factory=MeshSpec)
    constraints: list[Constraint] = Field(min_length=1)


JobSpec = Annotated[ModalSpec | StaticSpec, Field(discriminator="recipe")]

#: 실행기가 있는 레시피. 여기 없는 것은 API 가 만들기 전에 거절한다.
RUNNABLE_RECIPES: tuple[str, ...] = ("modal",)


class _SpecEnvelope(BaseModel):
    spec: JobSpec


def parse_spec(raw: object) -> ModalSpec | StaticSpec:
    """dict(JSON) → 스펙. 레시피 판별과 칸 검증을 한 번에 — 오류는 pydantic 의 것 그대로."""
    return _SpecEnvelope.model_validate({"spec": raw}).spec
