/**
 * 패널 화면들이 함께 쓰는 조각 — 머리 줄 · 불러오는 중 · 못 불러옴. 화면 부품은 웹의 것을 그대로 쓰고,
 * 웹의 페이지 머리(뒤로 가기 · 게시 · 삭제 단추)는 패널에 없으므로 이 짧은 머리로 대신한다.
 */

import type { ReactNode } from 'react'

import { ErrorNotice } from '@/shared/components/ErrorNotice'
import type { Resource } from '@/shared/hooks/useResource'

export function PanelTitle({ title, line }: { title: ReactNode; line: (ReactNode | null | false | undefined)[] }) {
  const parts = line.filter((one) => one !== null && one !== false && one !== undefined && one !== '')
  return (
    <header className="space-y-0.5">
      <h1 className="text-base font-semibold">{title}</h1>
      {parts.length > 0 && (
        <p className="text-muted-foreground flex flex-wrap items-center gap-x-1 text-xs">
          {parts.map((one, at) => (
            <span key={at} className="inline-flex items-center gap-1">
              {at > 0 && <span aria-hidden>·</span>}
              {one}
            </span>
          ))}
        </p>
      )}
    </header>
  )
}

/** 아직 못 받았거나 못 받은 자원 — 오류면 서버의 말 그대로. */
export function Loaded<T>({ resource, what }: { resource: Resource<T>; what: string }) {
  if (resource.error) return <ErrorNotice error={resource.error} />
  return <p className="text-muted-foreground text-sm">{what}을(를) 불러오는 중…</p>
}
