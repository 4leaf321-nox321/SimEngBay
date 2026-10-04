/**
 * 공용 폴더 탐색기 — **CAD 가 내보낸 폴더를 서버가 보는 자리에서** 고른다(`DOE_ROOTS` 아래).
 *
 * DOE 가져오기 창과 새 작업 창이 함께 쓴다. 상태(지금 폴더)는 부르는 창이 쥔다 — 폴더에 들어간
 * 뒤에 할 일(DOE 훑기 · 설계점 하나 읽기)이 창마다 다르다.
 */

import { ChevronUp, Folder, FolderOpen } from 'lucide-react'

import type { DoeListing } from '@/modules/simulations/api'
import { Button } from '@/shared/components/ui/button'
import { Label } from '@/shared/components/ui/label'

interface Props {
  listing: DoeListing | null
  busy: boolean
  onBrowse: (path?: string) => void
  /** CAD 폴더(DOE · 설계 하나)에 붙이는 표시. */
  badge?: string
  /** 지금 폴더가 CAD 폴더일 때 목록 자리에 쓰는 말. */
  studyNote?: string
}

export function FolderBrowser({
  listing,
  busy,
  onBrowse,
  badge = 'DOE',
  studyNote = '이 폴더가 DOE 입니다. 아래에서 확인하고 실행하세요.',
}: Props) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <Label>공용 폴더</Label>
        {(listing?.roots?.length ?? 0) > 1 && (
          <div className="flex gap-1">
            {(listing?.roots ?? []).map((root) => (
              <Button
                key={root}
                variant={listing?.path.startsWith(root) ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => onBrowse(root)}
                className="font-mono text-xs"
              >
                {root}
              </Button>
            ))}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="icon"
          className="size-8 shrink-0"
          disabled={!listing?.parent || busy}
          onClick={() => listing?.parent && onBrowse(listing.parent)}
          aria-label="한 칸 위"
        >
          <ChevronUp className="size-4" />
        </Button>
        <p className="text-muted-foreground truncate font-mono text-xs" title={listing?.path}>
          {listing?.path ?? '…'}
        </p>
      </div>
      <div className="max-h-48 overflow-y-auto rounded-md border">
        {listing && listing.entries.length === 0 ? (
          <p className="text-muted-foreground p-3 text-sm">
            {listing.is_study ? studyNote : '하위 폴더가 없습니다.'}
          </p>
        ) : (
          <ul className="divide-y">
            {(listing?.entries ?? []).map((entry) => (
              <li key={entry.path}>
                <button
                  type="button"
                  onClick={() => onBrowse(entry.path)}
                  className="hover:bg-muted/50 flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm"
                >
                  {entry.is_study ? (
                    <FolderOpen className="size-4 shrink-0 text-emerald-600" />
                  ) : (
                    <Folder className="text-muted-foreground size-4 shrink-0" />
                  )}
                  <span className="truncate">{entry.name}</span>
                  {/* **눌러 보고 알게 하지 않는다** — CAD 폴더를 미리 표시한다. */}
                  {entry.is_study && <span className="text-muted-foreground ml-auto text-xs">{badge}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {listing?.truncated && (
        <p className="text-muted-foreground text-xs">
          폴더가 너무 많아 일부만 보여 줍니다. 하위 폴더로 들어가 좁히세요.
        </p>
      )}
    </div>
  )
}
