/**
 * 온톨로지 API — Standard Platform 에서 받아 온 사본을 읽는다. 타입은 서버가 낸 스키마에서
 * 온다 — **손으로 적지 않는다.**
 *
 *     cd backend  ; python scripts/export_openapi.py
 *     cd frontend ; npm run api:types
 */

import { api } from '@/shared/api/client'
import type { Page } from '@/shared/api/paging'
import type { components } from '@/shared/api/schema'

export type OntologyStatus = components['schemas']['OntologyStatusOut']
export type OntologyRun = components['schemas']['OntologyRunOut']
export type OntologyType = components['schemas']['OntologyTypeOut']
export type OntologyProperty = components['schemas']['OntologyPropertyOut']
export type OntologyObject = components['schemas']['OntologyObjectOut']
export type OntologyObjectDetail = components['schemas']['OntologyObjectDetailOut']
export type OntologyEdge = components['schemas']['OntologyEdgeOut']

export interface ObjectQuery {
  q?: string
  includeInactive?: boolean
  limit?: number
  offset?: number
}

export const ontologyApi = {
  status: () => api.get<OntologyStatus>('/ontology/status'),
  types: () => api.get<OntologyType[]>('/ontology/types'),
  setEnabled: (slug: string, enabled: boolean) =>
    api.patch<OntologyType>(`/ontology/types/${encodeURIComponent(slug)}`, { enabled }),
  objects: (slug: string, query: ObjectQuery = {}) => {
    const params = new URLSearchParams()
    if (query.q) params.set('q', query.q)
    if (query.includeInactive) params.set('include_inactive', 'true')
    if (query.limit) params.set('limit', String(query.limit))
    if (query.offset) params.set('offset', String(query.offset))
    return api.get<Page<OntologyObject>>(`/ontology/types/${encodeURIComponent(slug)}/objects?${params}`)
  },
  /** 식별자에 `/` 가 들어 있을 수 있어 쿼리로 보낸다. */
  object: (slug: string, key: string) =>
    api.get<OntologyObjectDetail>(
      `/ontology/types/${encodeURIComponent(slug)}/object?${new URLSearchParams({ key })}`,
    ),
  runs: () => api.get<OntologyRun[]>('/ontology/runs'),
  sync: (full = false) => api.post<OntologyRun>('/ontology/sync', { full }),
}
