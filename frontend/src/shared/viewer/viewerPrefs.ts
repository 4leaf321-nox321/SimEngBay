/**
 * **3D 뷰어의 보이기 설정** — 외곽선 · 요소 선. 색 지도(`colormaps.ts`)처럼 모든 뷰어가 함께
 * 쓰고 브라우저가 기억한다(어느 칸에서 켜도 다른 칸이 따른다 — 견주려면 같은 모양으로 봐야 한다).
 *
 * - **외곽선**(기본 켬) — 형상의 윤곽(꺾인 모서리 · 테두리). 색만으로는 판 두께 · 모서리가 잘
 *   안 읽힌다.
 * - **요소**(기본 끔) — 요소 경계 전부. 메시가 촘촘하면 색을 덮으므로 필요할 때 켠다.
 *
 * vtk.js 를 부르지 않는다.
 */

import { useSyncExternalStore } from 'react'

import { STORAGE_PREFIX } from '@/shared/branding'

export interface ViewerPrefs {
  outline: boolean
  edges: boolean
}

const DEFAULTS: ViewerPrefs = { outline: true, edges: false }
const STORAGE_KEY = `${STORAGE_PREFIX}.viewer.display`

function readStored(): ViewerPrefs {
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<ViewerPrefs>
    return {
      outline: typeof raw.outline === 'boolean' ? raw.outline : DEFAULTS.outline,
      edges: typeof raw.edges === 'boolean' ? raw.edges : DEFAULTS.edges,
    }
  } catch {
    // 사생활 보호 창 · 손댄 저장값 — 기본으로 그린다.
    return DEFAULTS
  }
}

let current: ViewerPrefs | null = null
const listeners = new Set<() => void>()

function snapshot(): ViewerPrefs {
  current ??= readStored()
  return current
}

export function setViewerPrefs(next: Partial<ViewerPrefs>): void {
  current = { ...snapshot(), ...next }
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(current))
  } catch {
    // 위와 같다 — 이 창에서만 바뀐다.
  }
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useViewerPrefs(): ViewerPrefs {
  return useSyncExternalStore(subscribe, snapshot, () => DEFAULTS)
}
