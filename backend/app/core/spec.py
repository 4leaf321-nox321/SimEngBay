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
    solver: Literal["ansys", "calculix"] = "ansys"
    """무엇으로 풀까. **`ansys` 가 기본**이다 — 보고서에 쓰는 값은 거기서 나온다.

    `calculix` 는 오픈소스 솔버로, **깔린 서버에서 바로 돌고 동시에 여러 점을 푼다**(라이선스
    노드락이 없다). 대신 걸 수 있는 조건이 적다 — 못 거는 것은 모델링이 **까닭을 달아 거절**
    한다(`app/core/calculix/deck.py` 의 능력표). 두 솔버의 수는 몇 % 갈리므로 결과에 **어느
    쪽으로 풀었는지 도장**을 찍는다."""
    material: MaterialSpec
    material_from: Literal["cad", "spec"] = "cad"
    conditions_from: Literal["cad", "spec"] = "cad"
    """구속 · 접촉을 어디서 가져오나. `cad` 면 **CAD 가 보낸 조건이 먼저**고, 없으면 아래
    `constraints` 를 쓴다. `spec` 은 「내가 고른 영역만 완전 고정으로」 다."""
    """물성을 어디서 가져오나. `cad` 면 **CAD 가 보낸 것이 먼저**고 없으면 `material` 을 쓴다.

    `spec` 은 「내가 넣은 값으로 돌려라」 다 — CAD 가 보낸 것을 일부러 무시한다. 어느 쪽으로
    돌았는지는 모델링 단계 요약에 적힌다(안 적으면 나중에 결과를 믿을 수 없다)."""
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
    """정적 해석 — 하중을 걸고 **변형과 응력**을 본다.

    모달과 달리 **하중이 답을 만든다.** 그래서 조건에 하중이 하나도 없으면 풀어도 전부 0 이
    나오는데, 그 그림은 「해석이 됐다」 처럼 보인다 — 모델링이 그때 멈춘다.
    """

    model_config = ConfigDict(extra="forbid")

    recipe: Literal["static"] = "static"
    solver: Literal["ansys", "calculix"] = "ansys"
    """무엇으로 풀까 — `ModalSpec.solver` 참고. 이 레시피는 아직 `ansys` 만 된다."""
    material: MaterialSpec
    material_from: Literal["cad", "spec"] = "cad"
    conditions_from: Literal["cad", "spec"] = "cad"
    mesh: MeshSpec = Field(default_factory=MeshSpec)
    constraints: list[Constraint] = Field(default_factory=list)
    """사람이 고른 구속. **CAD 조건이 있으면 그것이 먼저다**(`conditions_from`)."""
    large_deflection: bool = False
    """변형이 커서 모양이 바뀌면 켠다 — 비선형이라 느리다."""


class HarmonicSpec(BaseModel):
    """조화 응답 — **주파수를 훑으며 흔든다.** 모달이 「어디서 떠는가」 라면 이것은 「그 떨림이
    얼마나 크게 나오는가」 다.

    감쇠가 없으면 공진에서 응답이 **끝없이 커진다** — 그래서 감쇠비를 안 주면 거절한다.
    수치가 무한대로 가는 그림은 「해석이 됐다」 처럼 보인다.
    """

    model_config = ConfigDict(extra="forbid")

    recipe: Literal["harmonic"] = "harmonic"
    solver: Literal["ansys", "calculix"] = "ansys"
    """무엇으로 풀까 — `ModalSpec.solver` 참고. 이 레시피는 아직 `ansys` 만 된다."""
    material: MaterialSpec
    material_from: Literal["cad", "spec"] = "cad"
    conditions_from: Literal["cad", "spec"] = "cad"
    mesh: MeshSpec = Field(default_factory=MeshSpec)
    constraints: list[Constraint] = Field(default_factory=list)
    frequency_range_hz: tuple[float, float] = (0.0, 2000.0)
    """훑을 범위. CAD 조건이 있으면 그것이 먼저다."""
    intervals: int = Field(default=10, ge=1, le=1000)
    """범위를 몇 점으로 나눠 푸나 — 공진 근처를 자세히 보려면 늘린다."""
    modes: int = Field(default=10, ge=1, le=100)
    """모드 중첩에 쓸 모드 수."""
    damping_ratio: float = Field(default=0.02, gt=0, lt=1)
    """임계 감쇠에 대한 비. 강 구조는 0.01 ~ 0.03."""


JobSpec = Annotated[ModalSpec | StaticSpec | HarmonicSpec, Field(discriminator="recipe")]

#: 실행기가 있는 레시피. 여기 없는 것은 API 가 만들기 전에 거절한다.
RUNNABLE_RECIPES: tuple[str, ...] = ("modal", "static", "harmonic")


class _SpecEnvelope(BaseModel):
    spec: JobSpec


def parse_spec(raw: object) -> ModalSpec | StaticSpec | HarmonicSpec:
    """dict(JSON) → 스펙. 레시피 판별과 칸 검증을 한 번에 — 오류는 pydantic 의 것 그대로."""
    return _SpecEnvelope.model_validate({"spec": raw}).spec
