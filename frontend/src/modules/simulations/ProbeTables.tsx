/**
 * **측정점 · 반력** — 결과 화면 셋(모달 · 정적 · 조화)이 함께 쓰는 표.
 *
 * 측정점은 CAD 가 점 그룹으로 보낸 자리, 곧 **실험에서 센서를 붙이는 자리**다. 전체 최대로는
 * 실측과 견줄 수 없다: 최대는 모델 어디서든 날 수 있고(구속 모서리의 수치적 첨두가 흔하다)
 * 센서는 그 자리에 없다. 그래서 그 자리의 값을 따로 보여 준다.
 *
 * **절점 거리와 경고를 숨기지 않는다.** 해석은 가장 가까운 절점의 값을 읽는다 — 멀면 그 값은
 * 다른 자리의 값이고, 백엔드가 그때 경고 문장을 적어 보낸다. 화면이 그것을 다시 판정하지 않고
 * 그대로 보여 준다.
 */

import type { ModeResult, ProbeRow } from '@/modules/simulations/api'
import { axisOf, magnitudeOf, shownForce, shownValue } from '@/modules/simulations/format'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'

/** 경고가 있는 측정점 — 표 아래에 한 줄씩. */
function ProbeWarnings({ probes }: { probes: ProbeRow[] }) {
  const seen = new Set<string>()
  const warned = probes.filter((one) => {
    if (!one.warning || seen.has(one.name)) return false
    seen.add(one.name)
    return true
  })
  if (warned.length === 0) return null
  return (
    <ul className="space-y-1 text-xs text-amber-700 dark:text-amber-400">
      {warned.map((one) => (
        <li key={one.name}>
          {one.name}: {one.warning}
        </li>
      ))}
    </ul>
  )
}

/** 같은 자리에 둔 측정점들(바디만 다르다) — 이음 입구처럼 두 판의 꼭짓점이 겹치는 자리. */
function colocated(probes: ProbeRow[]): [ProbeRow, ProbeRow][] {
  const pairs: [ProbeRow, ProbeRow][] = []
  for (let i = 0; i < probes.length; i += 1) {
    for (let j = i + 1; j < probes.length; j += 1) {
      const a = probes[i]
      const b = probes[j]
      const same = a.point.every((value, axis) => Math.abs(value - b.point[axis]) < 1e-6)
      if (same && a.body && b.body && a.body !== b.body && a.vector && b.vector) {
        pairs.push([a, b])
      }
    }
  }
  return pairs
}

/** 정적 — 측정점의 변위(크기 · 성분). */
export function StaticProbeTable({ probes }: { probes: ProbeRow[] }) {
  if (probes.length === 0) return null
  const pairs = colocated(probes)
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">측정점 변위</h3>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>측정점</TableHead>
            <TableHead>바디</TableHead>
            <TableHead className="text-right">변위</TableHead>
            <TableHead className="text-right">X</TableHead>
            <TableHead className="text-right">Y</TableHead>
            <TableHead className="text-right">Z</TableHead>
            <TableHead className="text-right">절점 거리</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {probes.map((one) => (
            <TableRow key={`${one.name}-${one.body ?? ''}`}>
              <TableCell className="font-medium">{one.name}</TableCell>
              <TableCell>{one.body ?? '—'}</TableCell>
              <TableCell className="text-right font-mono">{shownValue(one.value, one.unit)}</TableCell>
              {[0, 1, 2].map((axis) => (
                <TableCell key={axis} className="text-right font-mono">
                  {one.vector ? shownValue(one.vector[axis]) : '—'}
                </TableCell>
              ))}
              <TableCell className="text-right font-mono">{shownValue(one.distance_mm, 'mm')}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {pairs.map(([a, b]) => {
        // **같은 자리 두 바디의 차가 곧 미끄럼이다**(전단 이음). 크기만 보면 두 판이 함께 밀린
        // 것과 서로 미끄러진 것이 구별되지 않는다.
        const gap = [0, 1, 2].map((axis) => (a.vector?.[axis] ?? 0) - (b.vector?.[axis] ?? 0))
        return (
          <p key={`${a.name}-${b.name}`} className="text-muted-foreground text-xs">
            같은 자리 두 바디의 상대 변위({a.body} − {b.body}): X {shownValue(gap[0])} · Y{' '}
            {shownValue(gap[1])} · Z {shownValue(gap[2])} · 크기{' '}
            {shownValue(magnitudeOf(gap), a.unit)}
          </p>
        )
      })}
      <ProbeWarnings probes={probes} />
    </div>
  )
}

/** 정적 — 변위로 당긴 자리가 버틴 힘. */
export function ReactionTable({
  reactions,
  unit,
}: {
  reactions: Record<string, [number, number, number]>
  unit?: string
}) {
  const rows = Object.entries(reactions)
  if (rows.length === 0) return null
  // 옛 결과는 단위를 안 적었다 — 두 솔버 모두 N 으로 낸다(mm · t · s 와 MKS 의 힘).
  const force = unit || 'N'
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">반력</h3>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>영역</TableHead>
            <TableHead className="text-right">Fx</TableHead>
            <TableHead className="text-right">Fy</TableHead>
            <TableHead className="text-right">Fz</TableHead>
            <TableHead className="text-right">크기</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(([region, vector]) => (
            <TableRow key={region}>
              <TableCell className="font-medium">{region}</TableCell>
              {[0, 1, 2].map((axis) => (
                <TableCell key={axis} className="text-right font-mono">
                  {shownForce(vector[axis], force)}
                </TableCell>
              ))}
              <TableCell className="text-right font-mono">{shownForce(magnitudeOf(vector), force)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-muted-foreground text-xs">
        변위를 준 구속의 반력 합입니다. 같은 평면에 다른 구속이 있으면 함께 더해집니다.
      </p>
    </div>
  )
}

/** 잘 보이는 모드로 여기는 문턱 — 그 측정점에서 가장 크게 움직인 모드의 5%. */
const VISIBLE_SHARE = 0.05
const SHOWN_MODES = 3

/**
 * 모달 — **이 자리에 센서를 붙이면 어느 모드가 보이나.**
 *
 * 값은 질량 정규화된 모드 형상이라 절대 크기가 아니다. 그래서 같은 측정점 안에서 가장 크게
 * 움직인 모드를 100% 로 두고 견준다. 거의 안 움직이는 모드는 그 센서로 재면 안 보인다 —
 * 실측 공진과 짝을 지을 때 그것이 첫 거름망이다.
 */
export function ModalProbeTable({ probes, modes }: { probes: ProbeRow[]; modes: ModeResult[] }) {
  if (probes.length === 0) return null
  const byNumber = new Map(modes.map((one) => [one.number, one]))
  const names = [...new Set(probes.map((one) => one.name))]
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium">측정점에서 본 모드</h2>
      <p className="text-muted-foreground text-xs">
        이 자리에 센서를 붙이면 어느 모드가 잘 보이나 — 같은 측정점 안에서 가장 크게 움직인 모드를
        100% 로 두고 견줍니다(모드 형상은 질량 정규화라 절대 크기가 아닙니다).
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>측정점</TableHead>
            <TableHead>바디</TableHead>
            <TableHead className="text-right">절점 거리</TableHead>
            <TableHead>잘 보이는 모드</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {names.map((name) => {
            const rows = probes.filter((one) => one.name === name)
            const top = Math.max(...rows.map((one) => one.value))
            const ranked = [...rows]
              .filter((one) => top > 0 && one.value / top >= VISIBLE_SHARE)
              .sort((a, b) => b.value - a.value)
            const hidden = rows.length - ranked.length
            return (
              <TableRow key={name}>
                <TableCell className="font-medium">{name}</TableCell>
                <TableCell>{rows[0].body ?? '—'}</TableCell>
                <TableCell className="text-right font-mono">
                  {shownValue(rows[0].distance_mm, 'mm')}
                </TableCell>
                <TableCell>
                  {ranked.slice(0, SHOWN_MODES).map((one) => {
                    const mode = one.mode === undefined ? undefined : byNumber.get(one.mode)
                    const axis = axisOf(one.vector)
                    return (
                      <span key={one.mode ?? 0} className="mr-3 inline-block">
                        {mode?.elastic_number ? `${mode.elastic_number}차` : `모드 ${one.mode ?? '—'}`}{' '}
                        <span className="text-muted-foreground">
                          {mode ? `${Math.round(mode.frequency_hz).toLocaleString()} Hz` : ''}
                        </span>{' '}
                        <b>{Math.round((one.value / top) * 100)}%</b>
                        {axis && <span className="text-muted-foreground"> · {axis}</span>}
                      </span>
                    )
                  })}
                  {ranked.length > SHOWN_MODES && (
                    <span className="text-muted-foreground mr-3 text-xs">
                      외 {ranked.length - SHOWN_MODES}개
                    </span>
                  )}
                  {hidden > 0 && (
                    <span className="text-muted-foreground text-xs">
                      안 보이는 모드 {hidden}개(5% 미만)
                    </span>
                  )}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
      <ProbeWarnings probes={probes} />
    </section>
  )
}
