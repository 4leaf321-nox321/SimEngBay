/**
 * 해석 화면의 **두 번째 사이드바** — 개인 작업과 공용 작업공간을 가른다(2026-10-20).
 *
 * 해석 작업은 건 사람의 것이고, 게시해야 남이 본다(ADR 0008). 그 둘이 사람에게는 「내 책상」 과
 * 「게시판」 이라, 목록 위 선택 상자 하나로 두면 지금 어느 쪽을 보는지 잃는다 — 그래서 자리로
 * 가른다. 해석 작업 · DOE 비교 · 그 상세 화면이 모두 이 틀 안에 선다.
 *
 * 어느 쪽인지는 **주소가 정본이다**(`?scope=`) — 기본(내 작업)은 안 적는다. 상세 화면은 어느
 * 칸도 켜지 않는다(내 것인지 남의 게시 결과인지는 그 화면이 말한다).
 */

import { Suspense } from 'react'
import { Eye, GitCompare, LayoutGrid, Share2, UserRound } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Link, Outlet, useLocation, useSearchParams } from 'react-router-dom'

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

const PAGES: { label: string; path: string; icon: LucideIcon }[] = [
  { label: '해석 작업', path: '/simulations', icon: LayoutGrid },
  { label: 'DOE 비교', path: '/simulations/studies', icon: GitCompare },
]

/** 주소의 작업공간 — 없거나 모르는 값이면 개인 작업. */
export function workScope(params: URLSearchParams): ListScope {
  const value = params.get('scope')
  return value === 'published' || value === 'all' ? value : 'mine'
}

/** 그 작업공간의 그 화면 주소. 기본(개인 작업)은 `?scope=` 를 안 적는다. */
export function scopedPath(path: string, scope: ListScope): string {
  return scope === 'mine' ? path : `${path}?scope=${scope}`
}

/** 화면 제목에 붙일 말 — 「공용 작업공간 · 해석 작업」. */
export function scopeTitle(scope: ListScope, page: string): string {
  if (scope === 'published') return `공용 작업공간 · ${page}`
  if (scope === 'all') return `전체 · ${page}`
  return `개인 작업 · ${page}`
}

export default function SimulationsLayout() {
  const { user } = useAuth()
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const scope = workScope(params)
  const sections = WORK_SECTIONS.filter((one) => !one.adminOnly || isSystemAdmin(user))
  const isActive = (path: string, section: ListScope) => pathname === path && scope === section

  return (
    // 본문의 여백(p-6)을 걷어 메인 사이드바 바로 옆에 붙인다 — 본문 안의 상자로 보이면 「사이드바」
    // 가 아니라 화면의 한 조각으로 읽힌다.
    <div className="-m-6 flex">
      {/* **붙는 자리는 본문의 여백만큼 위다**(`-top-6`) — 스크롤 칸의 sticky 는 여백 안쪽에서 재므로
          `top-0` 이면 헤더 아래에 여백만 한 틈이 생겼다(실측 화면). */}
      <aside
        aria-label="작업공간"
        className="bg-sidebar sticky -top-6 hidden h-[calc(100svh-3.5rem)] w-52 shrink-0 overflow-y-auto border-r md:block"
      >
        <nav className="space-y-5 px-2 py-4">
          {sections.map((section) => (
            <div key={section.scope}>
              <p className="text-muted-foreground flex items-center gap-1.5 px-2 text-xs font-medium">
                <section.icon className="size-3.5" />
                {section.title}
              </p>
              <p className="text-muted-foreground/80 px-2 pb-1 text-[11px] leading-snug">
                {section.hint}
              </p>
              <ul className="space-y-0.5">
                {PAGES.map((page) => {
                  const active = isActive(page.path, section.scope)
                  return (
                    <li key={page.path}>
                      <Link
                        to={scopedPath(page.path, section.scope)}
                        aria-current={active ? 'page' : undefined}
                        className={cn(
                          'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors',
                          active
                            ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
                            : 'text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground',
                        )}
                      >
                        <page.icon className="size-4 shrink-0" />
                        <span className="truncate">{page.label}</span>
                      </Link>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </nav>
      </aside>

      <div className="min-w-0 flex-1 p-6">
        {/* **좁은 화면에는 옆자리가 없다** — 같은 칸을 본문 위에 단추로 늘어놓는다. */}
        <nav aria-label="작업공간 고르기" className="mb-4 flex flex-wrap gap-1 md:hidden">
          {sections.flatMap((section) =>
            PAGES.map((page) => (
              <Link
                key={`${section.scope}${page.path}`}
                to={scopedPath(page.path, section.scope)}
                className={cn(
                  'rounded-md border px-2 py-1 text-xs',
                  isActive(page.path, section.scope)
                    ? 'bg-sidebar-accent font-medium'
                    : 'text-muted-foreground',
                )}
              >
                {section.title} · {page.label}
              </Link>
            )),
          )}
        </nav>
        {/* 화면 조각을 받는 동안 · 화면이 터졌을 때도 **이 사이드바는 남긴다** — 다른 칸으로 나갈 길이다. */}
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
      </div>
    </div>
  )
}
