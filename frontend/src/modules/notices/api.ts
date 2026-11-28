/** 공지 API. */

import { api } from '@/shared/api/client'
import type { Notice } from '@/shared/api/types'

export type { Notice }

export const noticeApi = {
  /** 시스템 관리자는 초안(배포가 넣은 업데이트 안내 포함)까지 본다. */
  list: (includeDrafts = false) => api.get<Notice[]>(`/notices${includeDrafts ? '?include_drafts=true' : ''}`),
  /** 읽지 않은 팝업. 앱 껍데기가 띄운다. */
  popup: () => api.get<Notice[]>('/notices/popup'),
  create: (body: Record<string, unknown>) => api.post<Notice>('/notices', body),
  markRead: (id: string) => api.post<Notice>(`/notices/${id}/read`),
  /** 초안 하나를 발행한다 — 배포 안내는 그 판의 날짜에 선다. */
  publish: (id: string) => api.post<Notice>(`/notices/${id}/publish`),
  /** 배포 안내 초안 모두 발행 — 배포마다 들어온 업데이트 안내만 한 번에(손 글 초안은 하나씩). */
  publishDrafts: () => api.post<{ published: number }>('/notices/publish-drafts'),
  remove: (id: string) => api.delete<void>(`/notices/${id}`),
}
