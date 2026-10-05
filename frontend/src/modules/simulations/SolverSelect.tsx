/**
 * 솔버 선택 — 작업을 만드는 자리가 **같은 칸**을 쓴다(새 해석 작업 창 · 메시 수렴 점검).
 *
 * 두 창이 각자 글을 들고 있으면 한쪽만 고쳐진다(실측: 새 작업 창은 CalculiX 가 정적 · 조화를
 * 풀게 된 뒤에도 「지금은 모달만 된다」 고 적고 있었다).
 *
 * 네이티브 `<select>` 다 — 고를 것이 둘이고, 시험이 `selectOptions` 로 바로 고를 수 있다.
 *
 * ## 집을 워커가 없으면 말한다
 *
 * 그 솔버를 집는 살아 있는 워커가 없으면 작업은 **대기에서 영원히 안 움직이고**, 아무도 그
 * 사실을 말해 주지 않는다. 그래서 고르는 자리에서 미리 말한다. 서버가 모르면(`-1` — 신호를
 * 적는 워커가 없는 옛 설치 · 요청 안에서 도는 설치) 말하지 않는다: 「모른다」 를 「없다」 로
 * 말하면 멀쩡한 설치에서 사람을 놀라게 한다.
 */

import { useEffect, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type { SolverAvailability } from '@/modules/simulations/api'
import { Label } from '@/shared/components/ui/label'

export type Solver = 'ansys' | 'calculix'

interface Props {
  id: string
  value: Solver
  onChange: (next: Solver) => void
}

export function SolverSelect({ id, value, onChange }: Props) {
  const [known, setKnown] = useState<SolverAvailability[]>([])

  useEffect(() => {
    let disposed = false
    simulationApi
      .solvers()
      .then((found) => {
        if (!disposed) setKnown(found)
      })
      // **못 물어봐도 고르는 일은 막지 않는다** — 경고만 빠진다.
      .catch(() => {})
    return () => {
      disposed = true
    }
  }, [])

  const chosen = known.find((one) => one.solver === value)
  const stranded = chosen !== undefined && chosen.workers_alive === 0

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>솔버</Label>
      <select
        id={id}
        className="border-input bg-background h-9 w-full rounded-md border px-3 text-sm"
        value={value}
        onChange={(event) => onChange(event.target.value as Solver)}
      >
        <option value="ansys">Ansys (기본)</option>
        <option value="calculix">CalculiX (오픈소스 · 서버에서 바로)</option>
      </select>
      <p className="text-muted-foreground text-xs">
        {value === 'ansys'
          ? '라이선스가 있는 PC 에서 실행합니다. 조건을 가장 많이 반영합니다.'
          : '라이선스 없이 서버에서 바로 실행하고 여러 건을 동시에 처리합니다. 요소 크기가 필요하고, 반영하지 못하는 조건은 까닭과 함께 거절합니다.'}
      </p>
      {stranded && (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          지금 이 솔버를 집는 워커가 없습니다 — 실행하면 워커가 뜰 때까지 대기합니다
          {chosen.queued > 0 ? `(이미 ${chosen.queued}건 대기 중)` : ''}.
        </p>
      )}
    </div>
  )
}
