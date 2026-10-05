/**
 * 3D 뷰어 막대의 **보이기 단추들** — 외곽선 · 요소 선 켜고 끄기(`viewerPrefs`), 파트 보이기 ·
 * 숨기기(`PartPicker`). 뷰어 아래 막대와 「여러 개 보기」 막대가 함께 쓴다.
 *
 * vtk.js 를 부르지 않는다.
 */

import { Layers } from 'lucide-react'

import { Button } from '@/shared/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/shared/components/ui/popover'
import { setViewerPrefs, useViewerPrefs } from '@/shared/viewer/viewerPrefs'

/** 외곽선 · 요소 — 누른 상태가 켬이다. */
export function DisplayToggles() {
  const prefs = useViewerPrefs()
  return (
    <div className="flex items-center gap-1" role="group" aria-label="선 보이기">
      <Button
        variant={prefs.outline ? 'secondary' : 'ghost'}
        size="sm"
        aria-pressed={prefs.outline}
        title="형상의 윤곽(꺾인 모서리 · 테두리)을 선으로 그립니다"
        onClick={() => setViewerPrefs({ outline: !prefs.outline })}
      >
        외곽선
      </Button>
      <Button
        variant={prefs.edges ? 'secondary' : 'ghost'}
        size="sm"
        aria-pressed={prefs.edges}
        title="요소 경계를 모두 선으로 그립니다"
        onClick={() => setViewerPrefs({ edges: !prefs.edges })}
      >
        요소
      </Button>
    </div>
  )
}

export interface ViewerPart {
  id: number
  name: string
}

/** 파트 보이기 · 숨기기 — 파트가 둘 이상일 때만 쓴다. */
export function PartPicker({
  parts,
  hidden,
  onChange,
}: {
  parts: ViewerPart[]
  hidden: number[]
  onChange: (next: number[]) => void
}) {
  if (parts.length < 2) return null
  const off = new Set(hidden)
  const shown = parts.filter((one) => !off.has(one.id)).length
  const toggle = (id: number) => onChange(off.has(id) ? hidden.filter((one) => one !== id) : [...hidden, id])
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant={shown < parts.length ? 'secondary' : 'outline'} size="sm">
          <Layers className="size-4" />
          파트 {shown}/{parts.length}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-2" align="end">
        <div className="mb-1 flex items-center justify-between gap-2 px-1">
          <span className="text-muted-foreground text-xs">보일 파트</span>
          <Button variant="ghost" size="sm" disabled={hidden.length === 0} onClick={() => onChange([])}>
            모두 보이기
          </Button>
        </div>
        <ul className="max-h-72 space-y-0.5 overflow-y-auto">
          {parts.map((one) => (
            <li key={one.id} className="hover:bg-muted/50 flex items-center gap-2 rounded px-1 py-0.5">
              <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-sm">
                <input type="checkbox" checked={!off.has(one.id)} onChange={() => toggle(one.id)} />
                <span className="truncate">{one.name}</span>
              </label>
              {/* 하나만 보기 — 파트가 많으면 하나씩 끄는 것보다 빠르다. */}
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground shrink-0 text-xs"
                onClick={() => onChange(parts.filter((other) => other.id !== one.id).map((other) => other.id))}
              >
                이것만
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
