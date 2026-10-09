"""JobSpec — 해석 작업의 입력. **레시피별로 허용 칸을 제한한다.**

Mechanical 의 모든 기능을 노출하지 않는다. 오케스트레이터(와 사람)가 줄 수 있는 것은 레시피가
받는 칸뿐이고, 그 밖의 것은 여기서 거절된다 — 워커가 집어 들고 나서 모르는 칸 때문에 실패하면
사람은 「왜 실패했나」 를 목록에서 찾아야 한다.

레시피는 셋이다 — `modal` · `static` · `harmonic`. 솔버도 둘이다(`ansys` · `calculix`).

## 단위

Mechanical 은 단위계를 여러 개 받지만 **이 스펙은 하나로 못 박는다** — 칸 이름에 단위가 있다
(`youngs_modulus_gpa` · `density_kg_m3` · `element_size_mm`). 이름에 단위가 없으면 값 하나가
1000배 틀려도 아무도 모르고, 그 사실은 고유진동수가 31.6배 어긋난 뒤에야 드러난다.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: 강체 모드 수 — 구속이 없는 3차원 물체는 자유도 6개(이동 3 · 회전 3)가 0 Hz 로 나온다.
RIGID_BODY_MODES = 6


class MaterialSpec(BaseModel):
    """등방성 선형 탄성 물성. 물성 DB 가 붙기 전엔 직접 준다."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    youngs_modulus_gpa: float = Field(gt=0, le=2000)
    poisson_ratio: float = Field(ge=0, lt=0.5)
    density_kg_m3: float = Field(gt=0, le=30000)


class _HasMaterial(Protocol):
    material: MaterialSpec | None
    material_from: Literal["cad", "spec"]


def _needs_material[S: _HasMaterial](spec: S) -> S:
    """「내 값으로」(`material_from="spec"`)를 골랐으면 그 값이 있어야 한다 — 없으면 무엇으로
    풀지 모른다. CAD 쪽으로 가는 경우는 여기서 못 본다(점 파일은 스펙 밖에 있다) — 작업을 만들
    때 본다."""
    if spec.material_from == "spec" and spec.material is None:
        raise ValueError("물성 출처가 「스펙」 이면 물성(material)이 있어야 합니다.")
    return spec


class MeshSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_size_mm: float | None = Field(default=None, gt=0)
    """비우면 Mechanical 의 기본 크기. Student 판은 절점 상한이 있어 개발 PC 에서는 크게
    준다."""
    order: Literal["quadratic", "linear"] = "quadratic"
    local_scale: float = Field(default=1.0, gt=0, le=10)
    """CAD 가 적은 **파트 요소 크기 · 면 국부 크기**에 곱하는 배율. 1 이면 CAD 값 그대로다.

    메시 수렴 점검이 쓴다(비례 정련) — 전체 크기만 줄이면 CAD 가 크기를 적은 파트 · 면은
    그대로라 정련이 고르지 않았다. 점검은 수준마다 「새 크기 / 원래 크기」 를 여기 적고,
    모델링이 조건을 읽은 직후 곱한다(`conditions.scaled`). 점 파일은 CAD 가 보낸 그대로 둔다 —
    출처를 따라가야 한다."""


class Constraint(BaseModel):
    """영역 하나에 거는 구속. 영역 이름은 CAD 가 준 `topology.json` 의 것이다(4단계)."""

    model_config = ConfigDict(extra="forbid")

    region: str = Field(min_length=1, max_length=80)
    kind: Literal["fixed"] = "fixed"


class ModalSpec(BaseModel):
    """모달 해석. **구속이 비면 자유-자유** — 앞 6개 모드가 강체(≈0 Hz)로 나온다."""

    model_config = ConfigDict(extra="forbid")

    recipe: Literal["modal"] = "modal"
    solver: Literal["ansys", "calculix"] = "calculix"
    """무엇으로 풀까. **`calculix` 가 기본**이다(2026-10-08 — 그 전에는 `ansys`).

    `calculix` 는 오픈소스 솔버로, **깔린 서버에서 바로 돌고 동시에 여러 점을 푼다**(라이선스
    노드락이 없다). CompCore 시험 규격 20개(가속도 · 모멘트 · 원격 변위까지)가 끝까지 풀린 뒤
    기본으로 바꿨다. 못 거는 조건은 모델링이 **까닭을 달아 거절**한다(`calculix/deck.py` 의
    능력표). `ansys` 는 라이선스가 있는 PC 에서 돈다. 두 솔버의 수는 몇 % 갈리므로 결과에
    **어느 쪽으로 풀었는지 도장**을 찍는다. 칸이 없는 **옛 작업은 Ansys 다**(`solver_of`) —
    기본값을 바꿔도 이미 저장된 작업의 솔버는 바뀌지 않는다(저장한 스펙에는 늘 이 칸이
    있다)."""
    material: MaterialSpec | None = None
    """물성 한 벌 — **모든 바디에 같은 것이 붙는다.** 화면은 이 칸을 보내지 않는다: 물성은
    CompCore 가 점 파일에 파트마다 정해 보내고, 한 벌을 조립품 전체에 붙이는 것은 뜻이 없다.
    점 파일 없이 부르는 시험 · 스크립트를 위해 남겨 둔 칸이다. CAD 물성도 이것도 없으면
    작업을 만들 때 거절한다."""
    material_from: Literal["cad", "spec"] = "cad"
    """물성을 어디서 가져오나. `cad` 면 **CAD 가 보낸 것이 먼저**고 없으면 `material` 을 쓴다.

    `spec` 은 「내가 지정한 값으로 풀어라」 다 — CAD 가 보낸 것을 일부러 무시한다(그때는
    `material` 이 있어야 한다). 어느 쪽으로 풀었는지는 모델링 단계 요약에 적힌다(안 적으면
    나중에 결과를 믿을 수 없다)."""
    conditions_from: Literal["cad", "spec"] = "cad"
    """구속 · 접촉을 어디서 가져오나. `cad` 면 **CAD 가 보낸 조건이 먼저**고, 없으면 아래
    `constraints` 를 쓴다. `spec` 은 「내가 고른 영역만 완전 고정으로」 다."""
    mesh: MeshSpec = Field(default_factory=MeshSpec)
    modes: int = Field(default=10, ge=1, le=100)
    """찾을 **탄성** 모드 수. 강체 모드는 여기 세지 않는다 — 실행기가 6개를 더해 찾는다."""
    constraints: list[Constraint] = Field(default_factory=list)

    @model_validator(mode="after")
    def _own_material(self) -> Self:
        return _needs_material(self)

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
    solver: Literal["ansys", "calculix"] = "calculix"
    """무엇으로 풀까 — `ModalSpec.solver` 참고."""
    material: MaterialSpec | None = None
    """`ModalSpec.material` 참고."""
    material_from: Literal["cad", "spec"] = "cad"
    conditions_from: Literal["cad", "spec"] = "cad"
    mesh: MeshSpec = Field(default_factory=MeshSpec)
    constraints: list[Constraint] = Field(default_factory=list)
    """사람이 고른 구속. **CAD 조건이 있으면 그것이 먼저다**(`conditions_from`)."""
    large_deflection: bool | None = None
    """변형이 커서 모양이 바뀌면 켠다 — 비선형이라 느리다. **비우면 CAD 가 적은 대로**
    (`analysis.large_deflection`, 없으면 끈다 — `statics.static_plan`). 새 작업 창은 CAD 값을
    미리 채워 늘 적어 보낸다."""

    @model_validator(mode="after")
    def _own_material(self) -> Self:
        return _needs_material(self)


class HarmonicSpec(BaseModel):
    """조화 응답 — **주파수를 훑으며 흔든다.** 모달이 「어디서 떠는가」 라면 이것은 「그 떨림이
    얼마나 크게 나오는가」 다.

    감쇠가 없으면 공진에서 응답이 **끝없이 커진다** — 그래서 감쇠비를 안 주면 거절한다.
    수치가 무한대로 가는 그림은 「해석이 됐다」 처럼 보인다.
    """

    model_config = ConfigDict(extra="forbid")

    recipe: Literal["harmonic"] = "harmonic"
    solver: Literal["ansys", "calculix"] = "calculix"
    """무엇으로 풀까 — `ModalSpec.solver` 참고."""
    material: MaterialSpec | None = None
    """`ModalSpec.material` 참고."""
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

    @model_validator(mode="after")
    def _own_material(self) -> Self:
        return _needs_material(self)


JobSpec = Annotated[ModalSpec | StaticSpec | HarmonicSpec, Field(discriminator="recipe")]

#: 실행기가 있는 레시피. 여기 없는 것은 API 가 만들기 전에 거절한다.
RUNNABLE_RECIPES: tuple[str, ...] = ("modal", "static", "harmonic")


class _SpecEnvelope(BaseModel):
    spec: JobSpec


def parse_spec(raw: object) -> ModalSpec | StaticSpec | HarmonicSpec:
    """dict(JSON) → 스펙. 레시피 판별과 칸 검증을 한 번에 — 오류는 pydantic 의 것 그대로."""
    return _SpecEnvelope.model_validate({"spec": raw}).spec


#: 솔버 칸이 생기기 전(2026-10-02)의 작업이 쓴 솔버.
LEGACY_SOLVER = "ansys"


def parse_stored_spec(raw: object) -> ModalSpec | StaticSpec | HarmonicSpec:
    """**저장된** 스펙(작업 행 · `spec.json`)을 읽는다 — 솔버 칸이 없으면 옛 작업이라 Ansys 다.

    새 요청은 `parse_spec` 으로 읽어 기본값(CalculiX)을 받는다. 저장된 스펙에 칸이 없는 것은
    솔버 칸이 생기기 전의 작업뿐이고 그때는 Ansys 로 풀었다 — 큐(`claim_next`)도 그렇게 집는다.
    기본값을 바꾼 뒤(2026-10-08) 이것 없이 읽으면 Ansys 워커가 집은 옛 작업을 CalculiX 로
    풀었다(재시도 · 메시 수렴 점검).
    """
    if isinstance(raw, dict) and "solver" not in raw:
        raw = {**raw, "solver": LEGACY_SOLVER}
    return parse_spec(raw)
