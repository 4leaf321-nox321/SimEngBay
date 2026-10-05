/**
 * 공용 폴더 탐색기 — **CAD 가 내보낸 폴더를 서버가 보는 자리에서** 고른다(`DOE_ROOTS` 아래).
 *
 * 새 해석 작업 창이 쓴다. 상태(지금 폴더 · 고른 CAD 폴더)는 창이 쥔다 — 고른 뒤에 할 일(폴더 훑기 ·
 * 설계점 읽기)이 창의 일이다.
 *
 * ## CAD 폴더는 「들어가지」 않고 「고른다」
 *
 * 전에는 CAD 폴더를 누르면 그 안으로 들어갔다. 목록이 그 폴더의 하위(points · shapes — 볼 일이
 * 없는 것)로 바뀌고 옆의 CAD 폴더가 사라져, 다른 것을 보려면 매번 「한 칸 위」 를 눌러야 했다.
 * 이제 CAD 폴더를 누르면 **목록은 그 자리에 두고 그 폴더에 표시만 한다** — 옆 폴더로 바꾸는 것이
 * 한 번이다. 일반 폴더는 전처럼 들어간다.
 *
 * ## 찾기
 *
 * 경로는 마디마다 누를 수 있다(몇 칸 위로도 한 번에). 이름 거르기 칸과 정렬(이름 · 최근)을 둔다 —
 * 방금 CompCore 에서 내보낸 폴더는 대개 「최근」 의 맨 위다.
 */

import { ChevronRight, ChevronUp, Folder, FolderOpen, Search } from 'lucide-react'
import { useState } from 'react'

import type { DoeEntry, DoeListing } from '@/modules/simulations/api'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { shownDate } from '@/shared/lib/datetime'

type Order = 'name' | 'recent'

interface Props {
  listing: DoeListing | null
  busy: boolean
  /** 일반 폴더로 들어간다 — 경로 마디 · 한 칸 위 · 뿌리도 이것이다. */
  onBrowse: (path?: string) => void
  /** CAD 폴더(DOE · 설계 하나)를 고른다 — 목록은 그 자리에 둔다. */
  onPick: (path: string) => void
  /** 지금 고른 CAD 폴더. */
  selected?: string | null
  /** CAD 폴더에 붙이는 표시. */
  badge?: string
  /**
   * 창의 왼쪽 칸 높이를 다 쓴다 — 아직 CAD 폴더를 안 골랐을 때. 고른 뒤에는 아래에 설계점
   * 목록이 오므로 탐색기는 작게 줄어든다.
   */
  fill?: boolean
}

/** 뿌리 단추에 쓰는 이름 — 경로의 마지막 마디. */
function rootName(root: string): string {
  return root.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || root
}

/** 지금 경로를 뿌리부터 마디로 — 마디마다 그 자리의 전체 경로를 든다. */
export function crumbs(path: string, roots: string[]): { name: string; path: string }[] {
  const root = roots
    .map((one) => one.replace(/[\\/]+$/, ''))
    .filter((one) => path === one || path.startsWith(`${one}/`) || path.startsWith(`${one}\\`))
    .sort((a, b) => b.length - a.length)[0]
  if (root === undefined) return [{ name: path, path }]
  const parts = path.slice(root.length).split(/[\\/]/).filter(Boolean)
  const out = [{ name: rootName(root), path: root }]
  let at = root
  for (const part of parts) {
    at = `${at}/${part}`
    out.push({ name: part, path: at })
  }
  return out
}

function ordered(entries: DoeEntry[], order: Order): DoeEntry[] {
  if (order === 'name') return entries
  // 시각이 없는 폴더는 뒤로 — 「최근」 의 맨 위에 날짜 모를 것이 오면 찾는 데 방해가 된다.
  return [...entries].sort((a, b) => (b.modified_at ?? '').localeCompare(a.modified_at ?? ''))
}

export function FolderBrowser({
  listing,
  busy,
  onBrowse,
  onPick,
  selected = null,
  badge = 'DOE',
  fill = false,
}: Props) {
  const [filter, setFilter] = useState('')
  const [order, setOrder] = useState<Order>('name')
  // **폴더를 옮기면 거르기를 비운다** — 앞 폴더에서 친 글자가 새 폴더를 텅 비게 보이게 한다.
  const [filteredAt, setFilteredAt] = useState(listing?.path)
  if (filteredAt !== listing?.path) {
    setFilteredAt(listing?.path)
    setFilter('')
  }

  const needle = filter.trim().toLowerCase()
  const entries = ordered(listing?.entries ?? [], order).filter(
    (one) => !needle || one.name.toLowerCase().includes(needle),
  )
  const trail = listing ? crumbs(listing.path, listing.roots ?? []) : []

  function open(entry: DoeEntry) {
    if (entry.is_study) onPick(entry.path)
    else onBrowse(entry.path)
  }

  return (
    <div className={fill ? 'flex flex-col gap-1.5 lg:min-h-0 lg:flex-1' : 'space-y-1.5'}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Label className="shrink-0">공용 폴더</Label>
        {(listing?.roots?.length ?? 0) > 1 && (
          // **뿌리는 마지막 이름만 보인다** — 전체 경로(`/mnt/f/data/0_Program/73_CompCore`)를 단추에
          // 쓰면 창의 왼쪽 칸보다 길어 제목을 찌그러뜨리고 칸을 밀어냈다. 전체 경로는 말풍선에.
          <div className="flex min-w-0 flex-wrap gap-1">
            {(listing?.roots ?? []).map((root) => (
              <Button
                key={root}
                variant={listing?.path.startsWith(root) ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => onBrowse(root)}
                className="max-w-full font-mono text-xs"
                title={root}
              >
                <span className="truncate">{rootName(root)}</span>
              </Button>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon"
          className="size-7 shrink-0"
          disabled={!listing?.parent || busy}
          onClick={() => listing?.parent && onBrowse(listing.parent)}
          aria-label="한 칸 위"
        >
          <ChevronUp className="size-4" />
        </Button>
        {/* **경로는 마디마다 누른다** — 몇 칸 위로도 한 번에 간다. */}
        <nav aria-label="경로" className="flex min-w-0 flex-wrap items-center gap-0.5 text-xs" title={listing?.path}>
          {trail.length === 0 && <span className="text-muted-foreground">…</span>}
          {trail.map((crumb, index) => {
            const last = index === trail.length - 1
            return (
              <span key={crumb.path} className="flex min-w-0 items-center gap-0.5">
                {index > 0 && <ChevronRight className="text-muted-foreground size-3 shrink-0" />}
                {last ? (
                  <span className="truncate px-1 font-medium" aria-current="location">
                    {crumb.name}
                  </span>
                ) : (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onBrowse(crumb.path)}
                    className="text-muted-foreground hover:text-foreground truncate rounded px-1 hover:underline"
                  >
                    {crumb.name}
                  </button>
                )}
              </span>
            )
          })}
        </nav>
      </div>

      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
          <Input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            onKeyDown={(event) => {
              // 하나만 남으면 Enter 로 연다 — 이름 몇 글자 치고 바로.
              if (event.key === 'Enter' && entries.length === 1) {
                event.preventDefault()
                open(entries[0])
              }
            }}
            placeholder="이름으로 찾기"
            aria-label="폴더 이름으로 찾기"
            className="h-8 pl-7 text-sm"
          />
        </div>
        <div className="flex shrink-0 gap-0.5" role="group" aria-label="정렬">
          <Button
            variant={order === 'name' ? 'secondary' : 'ghost'}
            size="sm"
            aria-pressed={order === 'name'}
            onClick={() => setOrder('name')}
          >
            이름
          </Button>
          <Button
            variant={order === 'recent' ? 'secondary' : 'ghost'}
            size="sm"
            aria-pressed={order === 'recent'}
            onClick={() => setOrder('recent')}
          >
            최근
          </Button>
        </div>
      </div>

      <div
        className={
          fill
            ? 'max-h-72 overflow-y-auto rounded-md border lg:max-h-none lg:min-h-0 lg:flex-1'
            : 'max-h-36 overflow-y-auto rounded-md border'
        }
      >
        {listing && entries.length === 0 ? (
          <p className="text-muted-foreground p-3 text-sm">
            {needle ? `「${filter.trim()}」 이 들어간 폴더가 없습니다.` : '하위 폴더가 없습니다.'}
          </p>
        ) : (
          <ul className="divide-y">
            {entries.map((entry) => {
              const picked = entry.is_study && entry.path === selected
              return (
                <li key={entry.path}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => open(entry)}
                    aria-pressed={entry.is_study ? picked : undefined}
                    className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm ${
                      picked ? 'bg-muted font-medium' : 'hover:bg-muted/50'
                    }`}
                  >
                    {entry.is_study ? (
                      <FolderOpen className="size-4 shrink-0 text-emerald-600" />
                    ) : (
                      <Folder className="text-muted-foreground size-4 shrink-0" />
                    )}
                    <span className="truncate">{entry.name}</span>
                    <span className="text-muted-foreground ml-auto flex shrink-0 items-center gap-2 text-xs">
                      {/* **눌러 보고 알게 하지 않는다** — CAD 폴더를 미리 표시한다. */}
                      {entry.is_study && <span>{badge}</span>}
                      {entry.modified_at && <span className="tabular-nums">{shownDate(entry.modified_at)}</span>}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
      {listing?.truncated && (
        <p className="text-muted-foreground text-xs">
          폴더가 너무 많아 일부만 보여 줍니다. 하위 폴더로 들어가거나 이름으로 찾으세요.
        </p>
      )}
    </div>
  )
}
