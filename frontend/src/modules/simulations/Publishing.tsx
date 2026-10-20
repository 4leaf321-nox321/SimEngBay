/**
 * 게시 — **작업은 건 사람의 것이고, 게시해야 남이 본다**(2026-10-20).
 *
 * 게시한 결과는 조직의 누구나 읽는다(바꾸지는 못한다). 해석은 시행착오가 많아서, 실패 · 메시만
 * 바꿔 본 작업과 남이 믿고 쓸 결과를 가르는 표시가 이것이다. 작업 화면과 DOE 화면이 같은 단추를
 * 쓴다 — 누가 누를 수 있나는 서버가 판정하고, 화면은 「눌러 보고 403」 을 막을 뿐이다
 * (`ownsWork`).
 */

import { useState } from 'react'
import { EyeOff, Share2 } from 'lucide-react'

import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { Button } from '@/shared/components/ui/button'

export function PublishedBadge({ className = '' }: { className?: string }) {
  return (
    <span
      className={`rounded bg-emerald-100 px-1 text-xs text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200 ${className}`}
    >
      게시됨
    </span>
  )
}

export function PublishControl({
  published,
  subject,
  onPublish,
  onUnpublish,
  disabled = false,
}: {
  published: boolean
  /** 확인 창의 말 — 「이 작업」 · 「이 DOE 의 끝난 설계점」. */
  subject: string
  onPublish: () => Promise<void>
  onUnpublish: () => Promise<void>
  disabled?: boolean
}) {
  const [asking, setAsking] = useState(false)
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setAsking(true)}
        disabled={disabled}
      >
        {published ? <EyeOff className="size-4" /> : <Share2 className="size-4" />}
        {published ? '게시 해제' : '게시'}
      </Button>
      <ConfirmDialog
        open={asking}
        title={published ? '게시 해제' : '게시'}
        description={
          published ? (
            <>
              {subject}을 다른 사람에게 보이지 않게 합니다. 이 결과를 보고 있던 사람은 더 이상 열 수
              없습니다. 다시 게시할 수 있습니다.
            </>
          ) : (
            <>
              {subject}을 조직의 누구나 볼 수 있게 합니다 — 결과를 읽을 수만 있고 바꾸지는 못합니다.
              메시 수렴 점검 작업도 함께 게시됩니다.
            </>
          )
        }
        confirmLabel={published ? '해제' : '게시'}
        onConfirm={published ? onUnpublish : onPublish}
        onClose={() => setAsking(false)}
      />
    </>
  )
}
