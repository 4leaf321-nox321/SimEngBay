/**
 * 대기 중인 작업이 **줄의 어디쯤인가**(ADR 0011).
 *
 * 「대기」 배지만 보이면 사람은 얼마나 기다릴지 모른다. 워커는 같은 솔버 안에서 **사람마다 번갈아**
 * 집으므로, 내 차례는 「내 앞의 내 작업」 과 「줄을 나눠 쓰는 사람 수」 로 가늠한다 — 앞에 선 남의
 * 작업 수로 말하면 DOE 수백 점 뒤에 선 것처럼 읽힌다.
 */

import type { Simulation } from '@/modules/simulations/api'
import { SOLVER_LABELS } from '@/modules/simulations/labels'
import { Alert, AlertDescription, AlertTitle } from '@/shared/components/ui/alert'

export type Queue = NonNullable<Simulation['queue']>

export function queueLine(queue: Queue): string {
  const parts = [
    `${SOLVER_LABELS[queue.solver] ?? queue.solver} 줄에 ${queue.queued}건 대기`,
    queue.mine_ahead > 0 ? `내 앞의 내 작업 ${queue.mine_ahead}건` : '내 작업 중 다음 차례',
    queue.people > 1 ? `${queue.people}명이 번갈아 씁니다` : '',
    `지금 도는 것 ${queue.running}건`,
    queue.workers_alive > 0 ? `워커 ${queue.workers_alive}개` : '',
  ]
  return parts.filter(Boolean).join(' · ')
}

export function QueueNotice({ queue }: { queue: Queue }) {
  if (queue.workers_alive === 0) {
    // **영원히 대기한다** — 집을 워커가 없다는 사실을 아무도 말해 주지 않는다.
    return (
      <Alert variant="destructive">
        <AlertTitle>이 솔버를 집는 워커가 없습니다</AlertTitle>
        <AlertDescription>
          {queueLine(queue)}. 워커가 뜰 때까지 움직이지 않습니다 — 관리자에게 알리거나, 작업을 멈추고
          다른 솔버로 다시 거세요.
        </AlertDescription>
      </Alert>
    )
  }
  return (
    <div className="bg-muted/40 text-muted-foreground rounded-md border px-3 py-2 text-sm">
      대기 중 — {queueLine(queue)}
    </div>
  )
}
