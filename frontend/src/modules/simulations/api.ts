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

export interface SimulationResult {
  recipe: string
  boundary: 'free-free' | 'constrained'
  units: { frequency: string; system?: string }
  normalization: string
  rigid_body_modes: number
  mesh?: { nodes: number; elements: number }
  modes: ModeResult[]
  participation?: Record<string, Record<string, number>>
  warning?: string
  fake?: boolean
}

/** 끝난 상태 — 여기서는 더 안 움직이므로 폴링을 멈춘다. */
export const FINAL_STATUSES = new Set(['done', 'failed'])

/** 상태 기계의 순서. 화면의 타임라인이 이 순서로 선다. */
export const STAGE_NAMES = ['fetching', 'modeling', 'solving', 'extracting'] as const

export interface NewSimulation {
  file: File
  spec: Record<string, unknown>
  workspaceSlug: string | null
  name?: string
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
    form.append('spec', JSON.stringify(input.spec))
    if (input.workspaceSlug) form.append('workspace_slug', input.workspaceSlug)
    if (input.name) form.append('name', input.name)
    return api.postForm<Simulation>('/simulations', form)
  },
  retry: (id: string) => api.post<Simulation>(`/simulations/${id}/retry`),
  /** 모드 목록 · 단위계 · 참여계수. 아직 없으면 404 와 함께 **왜 없는지**가 온다. */
  result: (id: string) => api.get<SimulationResult>(`/simulations/${id}/result`),
  /** 썸네일 — `<img src>` 로는 안 된다(토큰이 메모리에만 있다). blob 으로 받아 그린다. */
  image: (simulationId: string, artifactId: string) =>
    fetchBlob(`/simulations/${simulationId}/artifacts/${artifactId}/content`),
  /** 모드 형상(VTP). vtk.js 가 ArrayBuffer 를 그대로 읽는다. */
  mesh: (simulationId: string, artifactId: string) =>
    fetchBytes(`/simulations/${simulationId}/artifacts/${artifactId}/content`),
  download: (simulationId: string, artifact: Artifact) =>
    downloadFile(`/simulations/${simulationId}/artifacts/${artifact.id}/content`, artifact.filename),
}
