/**
 * 고른 계정의 메일 주소를 한 번에 복사 — 여러 사람에게 메일 한 통을 쓸 때.
 *
 * **운영은 http 다.** `copyText` 가 그때 옛 방식(execCommand)으로 복사하고, 그것마저 브라우저가
 * 막으면 주소를 칸에 띄워 Ctrl+C 로 가져가게 한다 — 「복사 실패」 만 띄우면 사람은 주소를 한 줄씩
 * 옮겨 적는다.
 */

import { useState } from 'react'
import { Mail } from 'lucide-react'

import { Button } from '@/shared/components/ui/button'
import { Textarea } from '@/shared/components/ui/textarea'
import { copyText } from '@/shared/lib/clipboard'
import { mailLine } from '@/shared/lib/mail'

export function CopyMailAddresses({ ids }: { ids: string[] }) {
  const mail = mailLine(ids)
  // 무엇을 복사했는지 붙들어, 고른 것이 바뀌면 옛 결과를 안 보인다.
  const [done, setDone] = useState<{ line: string; ok: boolean } | null>(null)
  const shown = done && done.line === mail.line ? done : null

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={mail.count === 0}
          onClick={() =>
            copyText(mail.line)
              .then(() => setDone({ line: mail.line, ok: true }))
              .catch(() => setDone({ line: mail.line, ok: false }))
          }
        >
          <Mail className="size-4" />
          메일 주소 복사{mail.count > 0 && ` (${mail.count}명)`}
        </Button>
        {ids.length === 0 && (
          <span className="text-muted-foreground text-xs">표에서 계정을 고르세요</span>
        )}
        {shown?.ok && (
          <span className="text-muted-foreground text-xs">
            {mail.count}명의 주소를 복사했습니다 — 메일의 받는 사람 칸에 붙여 넣으세요.
          </span>
        )}
        {mail.skipped.length > 0 && (
          <span className="text-xs text-amber-700 dark:text-amber-400">
            메일 주소가 아닌 아이디 {mail.skipped.length}개는 뺐습니다: {mail.skipped.join(', ')}
          </span>
        )}
      </div>
      {shown && !shown.ok && (
        <div className="max-w-2xl space-y-1">
          <p className="text-destructive text-xs">
            이 브라우저가 자동 복사를 막았습니다 — 아래 칸을 누르고 Ctrl+C 로 복사하세요.
          </p>
          <Textarea
            aria-label="복사할 메일 주소"
            className="min-h-16 font-mono text-xs"
            readOnly
            autoFocus
            value={shown.line}
            onFocus={(event) => event.currentTarget.select()}
          />
        </div>
      )}
    </div>
  )
}
