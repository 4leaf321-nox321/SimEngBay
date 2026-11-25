/**
 * 풀 곳 — 「이 서버 / STE 클러스터」(요청서 E-2). 작업을 거는 창이 쓴다(새 작업 · DOE 가져오기).
 *
 * **STE 를 못 고르면 까닭을 그대로 보인다** — 서버가 그 사람 명의로 물어 본 답이다(설정 없음 ·
 * STE 가 그 사람을 거절함 · 응답 없음, `GET /simulations/solve-places`). 고를 수 있으면 대기열
 * 요약(남은 코어 · 내 대기 잡)을 옆에 둔다 — 92% 할당이면 기다릴 수 있다는 것을 미리 안다.
 *
 * STE 는 **CalculiX 의 솔브만** 보낸다 — Ansys 면 고를 수 없다. DOE 는 실행 한 번에 풀 곳 하나다
 * (점마다 다르면 설계점 비교가 흔들린다) — 이 칸이 모든 점의 스펙에 같이 실린다.
 */

import { useEffect, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type { SolvePlace } from '@/modules/simulations/api'
import { SOLVE_ON_LABELS } from '@/modules/simulations/labels'
import type { SolveOn } from '@/modules/simulations/labels'
import type { Solver } from '@/modules/simulations/SolverSelect'
import { Label } from '@/shared/components/ui/label'

interface Props {
  id: string
  value: SolveOn
  solver: Solver
  onChange: (next: SolveOn) => void
}

function queueLine(place: SolvePlace): string | null {
  const queue = place.queue
  if (!queue) return null
  const parts: string[] = []
  if (queue.cpus_idle != null)
    parts.push(
      `남은 코어 ${queue.cpus_idle.toLocaleString()}` +
        (queue.cpus_total != null ? ` / ${queue.cpus_total.toLocaleString()}` : ''),
    )
  if (queue.jobs_pending != null) parts.push(`대기 잡 ${queue.jobs_pending}`)
  if (queue.mine_pending != null || queue.mine_running != null)
    parts.push(`내 잡 대기 ${queue.mine_pending ?? 0} · 실행 ${queue.mine_running ?? 0}`)
  return parts.length ? parts.join(' · ') : null
}

export function SolveOnSelect({ id, value, solver, onChange }: Props) {
  const [places, setPlaces] = useState<SolvePlace[]>([])

  useEffect(() => {
    let disposed = false
    simulationApi
      .solvePlaces()
      .then((found) => {
        if (!disposed) setPlaces(found)
      })
      // **못 물어봐도 이 서버로는 건다** — STE 선택지만 빠진다.
      .catch(() => {})
    return () => {
      disposed = true
    }
  }, [])

  const ste = places.find((one) => one.place === 'ste')
  const calculix = solver === 'calculix'
  const steOk = calculix && ste?.available === true

  // 고를 수 없게 됐으면(솔버를 Ansys 로 바꿈) 이 서버로 돌린다 — 몰래 STE 로 남기지 않는다.
  useEffect(() => {
    if (value === 'ste' && !steOk && places.length > 0) onChange('local')
  }, [value, steOk, places.length, onChange])

  const why = !calculix
    ? 'STE 에서는 CalculiX 만 풉니다.'
    : ste && !ste.available
      ? ste.reason
      : null
  const chosen = value === 'ste' ? ste : places.find((one) => one.place === 'local')
  const queue = value === 'ste' && ste ? queueLine(ste) : null

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>풀 곳</Label>
      <select
        id={id}
        className="border-input bg-background h-9 w-full rounded-md border px-3 text-sm"
        value={value}
        onChange={(event) => onChange(event.target.value as SolveOn)}
      >
        <option value="local">{SOLVE_ON_LABELS.local} (기본)</option>
        <option value="ste" disabled={!steOk}>
          {SOLVE_ON_LABELS.ste}
          {steOk ? '' : ' — 지금 고를 수 없음'}
        </option>
      </select>
      {chosen?.note && <p className="text-muted-foreground text-xs">{chosen.note}</p>}
      {queue && <p className="text-muted-foreground text-xs">STE 지금: {queue}</p>}
      {why && value === 'local' && ste && (
        <p className="text-muted-foreground text-xs">STE 클러스터를 못 고르는 까닭: {why}</p>
      )}
    </div>
  )
}
