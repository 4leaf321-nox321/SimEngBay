/**
 * 해석 화면의 틀 — 「해석」 목록 · 단일 해석 · DOE 화면이 이 안에 선다.
 *
 * **작업공간(개인 작업 · 공용 작업공간 · 전체)은 목록 위의 탭이다**(2026-10-23, ADR 0014). 전에는 두
 * 번째 사이드바가 작업공간 × 화면(해석 작업 · DOE 비교)을 늘어놓아, 목록 하나를 고르는 데 사이드바 ·
 * 메뉴 · 폴더 세 단을 거쳐야 했다. 이제 목록이 하나라 사이드바 자리에는 폴더 나무가 서고(목록 안),
 * 작업공간은 탭 하나로 고른다. 상세 화면은 넓게 쓴다.
 *
 * 해석 작업은 건 사람의 것이고, 게시해야 남이 본다(ADR 0008). 어느 쪽인지는 **주소가 정본이다**
 * (`?scope=`) — 기본(개인 작업)은 안 적는다.
 */

import { Suspense } from 'react'
import { Eye, Share2, UserRound } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Link, Outlet, useLocation } from 'react-router-dom'

import type { ListScope } from '@/modules/simulations/api'
import { useAuth } from '@/shared/auth/AuthContext'
import { isSystemAdmin } from '@/shared/auth/roles'
import { ErrorBoundary } from '@/shared/components/ErrorBoundary'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { cn } from '@/shared/lib/utils'

interface WorkSection {
  scope: ListScope
  title: string
  hint: string
  icon: LucideIcon
  /** 시스템 관리자에게만 — 모두의 작업이다. */
  adminOnly?: boolean
}

export const WORK_SECTIONS: WorkSection[] = [
  {
    scope: 'mine',
    title: '개인 작업',
    hint: '내가 실행한 것 — 나와 시스템 관리자만 봅니다.',
    icon: UserRound,
  },
  {
    scope: 'published',
    title: '공용 작업공간',
    hint: '게시된 결과 — 누구나 읽습니다.',
    icon: Share2,
  },
  {
    scope: 'all',
    title: '전체',
    hint: '모든 사람의 작업(시스템 관리자).',
    icon: Eye,
    adminOnly: true,
  },
]

/** 주소의 작업공간 — 없거나 모르는 값이면 개인 작업. */
export function workScope(params: URLSearchParams): ListScope {
  const value = params.get('scope')
  return value === 'published' || value === 'all' ? value : 'mine'
}

/** 「해석」 목록의 주소 — 기본(개인 작업 · 종류 전체)은 안 적는다. */
export function listPath(scope: ListScope, kind?: 'job' | 'doe'): string {
  const params = new URLSearchParams()
  if (scope !== 'mine') params.set('scope', scope)
  if (kind) params.set('kind', kind)
  const query = params.toString()
  return query ? `/simulations?${query}` : '/simulations'
}

/** 목록 위의 작업공간 탭 — 고른 칸이 주소의 `?scope=` 다. 바꾸면 거르개는 새로 시작한다. */
export function ScopeTabs({ scope }: { scope: ListScope }) {
  const { user } = useAuth()
  const sections = WORK_SECTIONS.filter((one) => !one.adminOnly || isSystemAdmin(user))
  return (
    <nav aria-label="작업공간" className="flex flex-wrap gap-1 border-b">
      {sections.map((section) => {
        const active = section.scope === scope
        return (
          <Link
            key={section.scope}
            to={listPath(section.scope)}
            aria-current={active ? 'page' : undefined}
            title={section.hint}
            className={cn(
              '-mb-px flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm transition-colors',
              active
                ? 'border-primary text-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground border-transparent',
            )}
          >
            <section.icon className="size-4" />
            {section.title}
          </Link>
        )
      })}
    </nav>
  )
}

export default function SimulationsLayout() {
  const { pathname } = useLocation()
  return (
    // 화면 조각을 받는 동안 · 화면이 터졌을 때도 메인 사이드바는 남는다 — 다른 칸으로 나갈 길이다.
    <ErrorBoundary resetKey={pathname}>
      <Suspense
        fallback={
          <div className="space-y-3">
            <Skeleton className="h-8 w-56" />
            <Skeleton className="h-64 w-full" />
          </div>
        }
      >
        <Outlet />
      </Suspense>
    </ErrorBoundary>
  )
}
