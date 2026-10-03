/**
 * 해석 작업 API. 타입은 서버가 낸 스키마에서 온다 — **손으로 적지 않는다.**
 *
 *     cd backend  ; python scripts/export_openapi.py
 *     cd frontend ; npm run api:types
 */

import { api, downloadFile, fetchBlob, fetchBytes } from '@/shared/api/client'
import type { Page } from '@/shared/api/paging'
import type { components } from '@/shared/api/schema'

export type Simulation = components['schemas']['SimulationOut']
export type SimulationSummary = components['schemas']['SimulationSummaryOut']
export type Stage = components['schemas']['StageOut']
export type Artifact = components['schemas']['ArtifactOut']
export type Recipe = components['schemas']['RecipeOut']
export type DoePreview = components['schemas']['DoePreviewOut']
export type DoePointPreview = components['schemas']['DoePointPreview']
export type DoeImport = components['schemas']['DoeImportOut']
export type DoeListing = components['schemas']['DoeListingOut']
export type DoeEntry = components['schemas']['DoeEntryOut']
export type StudySummary = components['schemas']['StudySummaryOut']
export type Study = components['schemas']['StudyOut']
export type StudyPoint = components['schemas']['StudyPointOut']
export type ModeTrack = components['schemas']['ModeTrackOut']
export type WorkersOverview = components['schemas']['WorkersOut']
export type WorkerRow = components['schemas']['WorkerOut']
export type SolverAvailability = components['schemas']['SolverAvailabilityOut']
export type Convergence = components['schemas']['ConvergenceOut']
export type Measurement = components['schemas']['MeasurementOut']
export type StudyMeasurement = components['schemas']['StudyMeasurementOut']
export type Comparison = components['schemas']['ComparisonOut']
export type FrfComparison = components['schemas']['FrfComparisonOut']
export type ConvergenceMetric = components['schemas']['ConvergenceMetricOut']

/**
 * `result.json` 의 모양 — **서버가 스키마로 굳히지 않는 것**이라 화면 쪽에 적는다.
 *
 * 해석이 낸 파일이 정본이고 레시피마다 칸이 다르다. 그래서 여기 적은 것은 「이만큼은 있다고
 * 보고 그린다」 는 뜻이고, 없을 수 있는 칸은 전부 optional 이다.
 */
export interface ModeResult {
  number: number
  elastic_number: number | null
  frequency_hz: number
  rigid_body: boolean
  /** 모드 형상 파일 이름. 산출물 목록에서 같은 이름을 찾아 내려받는다. */
  vtp?: string
  png?: string
  max_displacement?: number
  /** 유효질량이 가장 큰 방향(X · Y · Z · ROTX …). 전부 작으면 없다. */
  dominant_direction?: string
  effective_mass_ratio?: number
  /**
   * 축별 변위 에너지 비중 — **자유-자유에서 모드를 설명하는 값.**
   *
   * 유효질량비는 구속이 없으면 0 이다(강체 모드가 전부 가져간다). 이것은 변위장의 비율이라
   * 구속과 무관하게 「이 모드가 주로 어느 축으로 움직이나」 를 말한다.
   */
  direction_share?: { x: number; y: number; z: number }
  /** 위 비중에서 절반을 넘는 축. 섞인 모드면 없다. */
  dominant_axis?: string
  /** 전역(1)에서 국부(≈0)까지. 한 구석만 떠는 모드를 가려낸다. */
  localization?: number
  local_mode?: boolean
}

/**
 * **측정점 한 줄** — CAD 가 점 그룹으로 보낸 자리(센서를 붙이는 자리)의 값. 두 솔버가 같은
 * 모양을 낸다(`backend/app/core/probes.py` 의 `row`).
 *
 * `vector` · `body` · `warning` 은 **없을 수 있다** — 옛 결과에는 성분이 없고, 바디는 그 바디
 * 안에서만 찾았을 때만 적힌다. `point` 와 `distance_mm` 는 늘 mm 지만 `value` 는 `unit` 의
 * 단위다(Ansys 가 SI 로 돌면 m).
 */
export interface ProbeRow {
  name: string
  point: [number, number, number]
  node: number
  distance_mm: number
  value: number
  unit: string
  vector?: [number, number, number]
  body?: string
  /** 가장 가까운 절점이 1 mm 넘게 떨어졌을 때 백엔드가 적는 문장 — 그대로 보여 준다. */
  warning?: string
  /** 모달 — 그 값을 읽은 모드의 **전체** 번호(`modes[].number`). */
  mode?: number
  /** 조화 — 그 자리 곡선의 봉우리 주파수. */
  frequency_hz?: number
}

/** 조화 응답의 결과 — **주파수 점마다 최대 변위**, 곧 곡선이다. */
export interface HarmonicResult {
  recipe: 'harmonic'
  solver?: string
  units: { frequency: string; displacement?: string; system?: string }
  mesh?: { nodes: number; elements: number }
  /** 감쇠비. **봉우리 높이를 거의 이 값이 정한다**(1/2ζ) — 그래서 곡선과 같이 보여 준다. */
  damping_ratio: number
  /** `probes` 는 측정점 이름 → 그 주파수에서의 진폭(단위는 `units.displacement`). */
  points: { frequency_hz: number; max_displacement: number; probes?: Record<string, number> }[]
  /** 가장 크게 흔들린 점. 창 끝에 붙어 있으면 공진의 옆구리만 본 것이다. */
  peak: { frequency_hz: number; max_displacement: number; probes?: Record<string, number> }
  /** 측정점마다 **그 자리 곡선의 봉우리** 한 줄(절점 거리 · 경고가 여기 실린다). 옛 결과엔 없다. */
  probes?: ProbeRow[]
  material?: string
  warning?: string
  fake?: boolean
}

/** 정적 해석의 결과 — **모드가 아니라 변형 · 응력**이다. */
export interface StaticResult {
  recipe: 'static'
  solver?: string
  units: { system?: string; displacement?: string; stress?: string; force?: string }
  mesh?: { nodes: number; elements: number }
  max_displacement: number
  max_von_mises: number | null
  material?: string
  shape?: { vtp: string; png?: string; points?: number }
  /** 측정점의 변위 — 크기(`value`)와 성분(`vector`). */
  probes?: ProbeRow[]
  /** 변위로 당긴 영역 → 그 자리가 버틴 **반력 합** `[Fx, Fy, Fz]`(단위는 `units.force`). */
  reactions?: Record<string, [number, number, number]>
  warning?: string
  fake?: boolean
}

export interface SimulationResult {
  recipe: string
  solver?: string
  boundary: 'free-free' | 'constrained'
  units: { frequency: string; system?: string }
  normalization: string
  rigid_body_modes: number
  mesh?: { nodes: number; elements: number }
  modes: ModeResult[]
  participation?: Record<string, Record<string, number>>
  /**
   * 측정점마다 · **탄성 모드마다** 한 줄(`mode` 로 가른다). 질량 정규화된 값이라 절대 크기가
   * 아니다 — 같은 측정점 안에서 모드끼리 견준다. 옛 결과는 1차 탄성 모드 한 줄뿐이다.
   */
  probes?: ProbeRow[]
  warning?: string
  fake?: boolean
}

/** 끝난 상태 — 여기서는 더 안 움직이므로 폴링을 멈춘다. */
export const FINAL_STATUSES = new Set(['done', 'failed', 'canceled'])

/** 상태 기계의 순서. 화면의 타임라인이 이 순서로 선다. */
export const STAGE_NAMES = ['fetching', 'modeling', 'solving', 'extracting'] as const

export interface NewSimulation {
  file: File
  /** CAD 가 보낸 영역 지문. **구속을 걸려면 있어야 한다** — 서버가 걸기 전에 막는다. */
  topology?: File | null
  spec: Record<string, unknown>
  workspaceSlug: string | null
  name?: string
}

/** `topology.json` 에서 화면이 읽는 것 — 고를 수 있는 영역 이름과 CAD 가 못 푼 이름. */
export interface TopologyPreview {
  regions: { name: string; faces: number }[]
  unresolved: string[]
  bodies: number
}

/**
 * 올린 지문을 **브라우저에서 읽어** 고를 목록을 만든다. 서버에 먼저 보내고 물어보면, 영역을
 * 고르기도 전에 작업이 하나 생긴다.
 */
export async function readTopology(file: File): Promise<TopologyPreview> {
  const parsed: unknown = JSON.parse(await file.text())
  const document = parsed as {
    regions?: Record<string, unknown[]>
    unresolved?: string[]
    bodies?: unknown[]
  }
  if (!document.regions || typeof document.regions !== 'object') {
    throw new Error('영역 지문이 아닙니다 — regions 가 없습니다.')
  }
  return {
    regions: Object.entries(document.regions).map(([name, faces]) => ({
      name,
      faces: Array.isArray(faces) ? faces.length : 0,
    })),
    unresolved: document.unresolved ?? [],
    bodies: document.bodies?.length ?? 0,
  }
}

export const simulationApi = {
  list: (query: { status?: string; workspaceSlug?: string; limit: number; offset: number }) => {
    const params = new URLSearchParams({
      limit: String(query.limit),
      offset: String(query.offset),
    })
    if (query.status) params.set('status', query.status)
    if (query.workspaceSlug) params.set('workspace_slug', query.workspaceSlug)
    return api.get<Page<SimulationSummary>>(`/simulations?${params}`)
  },
  get: (id: string) => api.get<Simulation>(`/simulations/${id}`),
  /** 폴링용 — 상세와 같지만 접근 로그에 안 남는다. */
  status: (id: string) => api.get<Simulation>(`/simulations/${id}/status`),
  recipes: () => api.get<Recipe[]>('/simulations/recipes'),
  create: (input: NewSimulation) => {
    const form = new FormData()
    form.append('file', input.file)
    if (input.topology) form.append('topology', input.topology)
    form.append('spec', JSON.stringify(input.spec))
    if (input.workspaceSlug) form.append('workspace_slug', input.workspaceSlug)
    if (input.name) form.append('name', input.name)
    return api.postForm<Simulation>('/simulations', form)
  },
  retry: (id: string) => api.post<Simulation>(`/simulations/${id}/retry`),
  /** 멈춘다 — 대기 중이면 곧바로, 돌고 있으면 워커가 몇 초 안에 본다. */
  cancel: (id: string) => api.post<Simulation>(`/simulations/${id}/cancel`),
  /** 중간 파일(.mechdb · .rst · 솔버 scratch)을 지운다. **결과는 남는다.** */
  tidy: (id: string) =>
    api.post<{ bytes_freed: number; files: number }>(`/simulations/${id}/tidy`),
  tidyStudy: (studyId: string) =>
    api.post<{ bytes_freed: number; files: number; points: number }>(
      `/simulations/studies/${studyId}/tidy`,
    ),
  /**
   * DOE 폴더 훑어 보기 — **걸기 전에** 점 몇 개 · 변수 무엇 · 건너뛸 것 몇 개인지.
   *
   * 폴더는 **서버가 보는 경로**다(공유 스토리지). 브라우저가 올리는 것이 아니다 — 설계점
   * 200개면 STEP 만 수십 MB 다.
   */
  /** 가져온 DOE 목록. **작업 표에서 모은다** — 스터디를 따로 저장하지 않는다. */
  studies: () => api.get<StudySummary[]>('/simulations/studies'),
  study: (studyId: string) => api.get<Study>(`/simulations/studies/${studyId}`),
  /**
   * 공용 폴더 훑기 — **설정된 뿌리 아래만.** 경로를 안 주면 첫 뿌리부터.
   *
   * 아무 경로나 받으면 그 칸이 서버의 모든 폴더를 여는 문이 된다(서버가 막는다).
   */
  browseDoe: (path?: string) =>
    api.get<DoeListing>(
      `/simulations/doe/browse${path ? `?path=${encodeURIComponent(path)}` : ''}`,
    ),
  previewDoe: (path: string) =>
    api.get<DoePreview>(`/simulations/doe/preview?path=${encodeURIComponent(path)}`),
  importDoe: (body: {
    path: string
    spec: Record<string, unknown>
    workspace_slug?: string | null
    numbers?: number[] | null
  }) => api.post<DoeImport>('/simulations/doe/import', body),
  /** 모드 목록 · 단위계 · 참여계수. 아직 없으면 404 와 함께 **왜 없는지**가 온다. */
  result: (id: string) =>
    api.get<SimulationResult | StaticResult | HarmonicResult>(`/simulations/${id}/result`),
  /** 썸네일 — `<img src>` 로는 안 된다(토큰이 메모리에만 있다). blob 으로 받아 그린다. */
  image: (simulationId: string, artifactId: string) =>
    fetchBlob(`/simulations/${simulationId}/artifacts/${artifactId}/content`),
  /** 모드 형상(VTP). vtk.js 가 ArrayBuffer 를 그대로 읽는다. */
  mesh: (simulationId: string, artifactId: string) =>
    fetchBytes(`/simulations/${simulationId}/artifacts/${artifactId}/content`),
  /** 그 작업(과 그 스터디)에 붙은 실측 — 이 결과와 견준 것을 함께. */
  measurements: (id: string) => api.get<Measurement[]>(`/simulations/${id}/measurements`),
  addMeasurement: (id: string, file: File, label: string) => {
    const form = new FormData()
    form.append('file', file)
    if (label.trim()) form.append('label', label.trim())
    return api.postForm<Measurement>(`/simulations/${id}/measurements`, form)
  },
  studyMeasurements: (studyId: string) =>
    api.get<StudyMeasurement[]>(`/simulations/studies/${encodeURIComponent(studyId)}/measurements`),
  addStudyMeasurement: (studyId: string, file: File, label: string) => {
    const form = new FormData()
    form.append('file', file)
    if (label.trim()) form.append('label', label.trim())
    return api.postForm<StudyMeasurement>(
      `/simulations/studies/${encodeURIComponent(studyId)}/measurements`,
      form,
    )
  },
  removeMeasurement: (measurementId: string) =>
    api.delete<void>(`/simulations/measurements/${measurementId}`),
  /** 실측 양식 — 종류 넷(공진 · FRF · 변위 · 변형률)을 한 표에. */
  measurementTemplate: () => downloadFile('/simulations/measurements/template.csv', '실측양식.csv'),
  /** 메시 수렴 묶음 — 원래 작업이나 수준 작업 어느 쪽으로 물어도 같다. */
  convergence: (id: string) => api.get<Convergence>(`/simulations/${id}/convergence`),
  /** 끝난 작업을 요소 크기만 바꿔 다시 건다 — 크기마다 작업 하나. */
  requestConvergence: (id: string, body: { sizes_mm: number[]; solver?: string | null }) =>
    api.post<Convergence>(`/simulations/${id}/convergence`, body),
  /** 워커 · 솔버별 줄 · 라이선스를 쥔 작업(시스템 관리자). 서버 화면이 10초마다 묻는다. */
  workers: () => api.get<WorkersOverview>('/simulations/workers'),
  /** 솔버마다 집을 워커가 살아 있나 — 작업을 거는 창이 경고에 쓴다. */
  solvers: () => api.get<SolverAvailability[]>('/simulations/solvers'),
  /** 스터디를 CSV 로 — 화면과 같은 값 · 같은 단위(mm · MPa · N · Hz). */
  exportStudy: (studyId: string, filename: string) =>
    downloadFile(`/simulations/studies/${encodeURIComponent(studyId)}/export.csv`, filename),
  download: (simulationId: string, artifact: Artifact) =>
    downloadFile(`/simulations/${simulationId}/artifacts/${artifact.id}/content`, artifact.filename),
}
