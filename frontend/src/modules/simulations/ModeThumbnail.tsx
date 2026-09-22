/**
 * 모드 썸네일 한 장 — **`<img src>` 로는 안 된다.**
 *
 * access 토큰이 메모리에만 있어서 브라우저가 스스로 여는 주소에는 안 실린다. blob 으로 받아
 * object URL 로 그리고, **떠날 때 해제한다** — 안 하면 모드를 넘길 때마다 쌓인다.
 */

import { useEffect, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import { cn } from '@/shared/lib/utils'

interface Props {
  simulationId: string
  artifactId: string
  label: string
  selected?: boolean
  onSelect?: () => void
  className?: string
}

export function ModeThumbnail({
  simulationId,
  artifactId,
  label,
  selected,
  onSelect,
  className,
}: Props) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let disposed = false
    let created: string | null = null
    simulationApi
      .image(simulationId, artifactId)
      .then((blob) => {
        if (disposed) return
        created = URL.createObjectURL(blob)
        setUrl(created)
      })
      .catch(() => {
        if (!disposed) setFailed(true)
      })
    return () => {
      disposed = true
      if (created) URL.revokeObjectURL(created)
    }
  }, [simulationId, artifactId])

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'group rounded-md border p-1 text-left transition',
        selected ? 'border-primary ring-primary/30 ring-2' : 'hover:border-foreground/30',
        className,
      )}
    >
      <div className="bg-muted/30 flex h-24 items-center justify-center overflow-hidden rounded">
        {url ? (
          <img src={url} alt={label} className="h-full w-full object-contain" />
        ) : (
          <span className="text-muted-foreground text-xs">{failed ? '그림 없음' : '…'}</span>
        )}
      </div>
      <p className="mt-1 text-center text-xs font-medium">{label}</p>
    </button>
  )
}
