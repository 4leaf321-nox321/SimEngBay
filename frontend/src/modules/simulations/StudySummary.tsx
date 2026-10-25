/**
 * DOE 요약 — **설계 변수가 여럿일 때**(2026-10-25).
 *
 * 변수가 하나면 「두께 2 → 4 · 1차 +100%」 처럼 끝 점 둘을 견주는 것이 곧 그 변수의 효과다. 변수가
 * 여럿이면 그 두 점은 **다른 변수도 다르다** — +100% 가 누구 몫인지 말하지 못하고, 다섯 변수면 아무
 * 두 점을 견주는 셈이다. 그래서 여럿이면 끝 점 대신 셋을 적는다:
 *
 *   - 변수마다 훑은 범위
 *   - 결과의 최소 ~ 최대와 **그 점**
 *   - 결과를 **가장 크게 움직인 변수**(주효과의 폭 %) — 서버 `analysis.py` · MCP `study_analyze`
 *     와 같은 셈이다(`studyTable.sensitivityOf`)
 */

import type { Study } from '@/modules/simulations/api'
import {
  caseName,
  columnsOf,
  labelOf,
  rowsOf,
  sensitivityOf,
  spanOf,
} from '@/modules/simulations/studyTable'
import type { Column } from '@/modules/simulations/studyTable'
import { shownNumber } from '@/shared/charts'

/** 영향 순위에 적을 변수 수 — 넘는 것은 「외 n」 으로. */
const TOP = 3
/** 고르는 값(재료)을 몇 개까지 적나. */
const LEVELS = 3
/** 상관이 이만큼 뚜렷하면 방향(↑ · ↓)을 붙인다 — 약하면 방향이 오히려 거짓말을 한다. */
const CLEAR = 0.5

function rangeOf(study: Study, name: string): string {
  const values = study.points.map((one) => one.params[name]).filter((one) => one != null)
  const numbers = values.filter((one): one is number => typeof one === 'number')
  if (numbers.length === values.length && numbers.length > 0) {
    const low = Math.min(...numbers)
    const high = Math.max(...numbers)
    return low === high ? shownNumber(low) : `${shownNumber(low)} ~ ${shownNumber(high)}`
  }
  const levels = [...new Set(values.map(String))]
  return (
    levels.slice(0, LEVELS).join(' · ') + (levels.length > LEVELS ? ` 외 ${levels.length - LEVELS}` : '')
  )
}

function Span({ study, column }: { study: Study; column: Column | undefined }) {
  const span = column ? spanOf(rowsOf(study), column) : null
  if (!column || !span) return <dd className="font-medium">—</dd>
  const unit = column.unit ? ` ${column.unit}` : ''
  return (
    <dd className="font-medium">
      {shownNumber(span.min)} ~ {shownNumber(span.max)}
      {unit}
      <span className="text-muted-foreground block text-xs font-normal">
        최소 {caseName(span.minPoint)} · 최대 {caseName(span.maxPoint)}
      </span>
    </dd>
  )
}

/** 「1차 모드 ← 두께 66% ↑ › 폭 12% ↓」 — 그 결과를 크게 움직인 차례. */
function Ranking({ study, result }: { study: Study; result: Column | undefined }) {
  if (!result) return null
  const columns = columnsOf(study)
  const factors = columns.filter((one) => one.kind === 'factor')
  const ranked = sensitivityOf(rowsOf(study), factors, result).filter((one) => one.spreadPct != null)
  return (
    <p>
      <span className="text-muted-foreground">{result.label}</span> ←{' '}
      {ranked.length === 0
        ? '끝난 점이 적어 아직 말할 수 없습니다'
        : ranked.slice(0, TOP).map((one, index) => {
            const r = one.correlation
            const arrow = r != null && r >= CLEAR ? ' ↑' : r != null && r <= -CLEAR ? ' ↓' : ''
            return (
              <span key={one.factor.key}>
                {index > 0 && ' › '}
                <b>{one.factor.label}</b> {Math.round(one.spreadPct ?? 0)}%{arrow}
              </span>
            )
          })}
      {ranked.length > TOP && <span className="text-muted-foreground"> 외 {ranked.length - TOP}</span>}
    </p>
  )
}

export function FactorSummary({ study, primary }: { study: Study; primary: string }) {
  const columns = columnsOf(study)
  const results = columns.filter((one) => one.kind === 'result')
  const lead = results.find((one) => one.key === primary) ?? results[0]
  const mass = results.find((one) => one.key === 'mass_kg')
  const done = study.points.filter((one) => one.status === 'done').length
  return (
    <div className="space-y-3 rounded-md border p-4 text-sm">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground text-xs">설계점</dt>
          <dd className="font-medium">
            {done} / {study.points.length} 완료
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">설계 변수 {study.factors.length}개</dt>
          <dd className="space-y-0.5">
            {study.factors.map((name) => (
              <span key={name} className="block">
                <span className="text-muted-foreground">{name}</span> {rangeOf(study, name)}
              </span>
            ))}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">{lead ? labelOf(lead) : '결과'}</dt>
          <Span study={study} column={lead} />
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">{mass ? labelOf(mass) : '질량'}</dt>
          <Span study={study} column={mass} />
        </div>
      </dl>
      <div className="space-y-0.5 border-t pt-3">
        <p className="text-muted-foreground text-xs">가장 크게 움직인 변수</p>
        <Ranking study={study} result={lead} />
        {mass && <Ranking study={study} result={mass} />}
        <p className="text-muted-foreground text-xs">
          % 는 그 변수의 수준별 평균이 벌어진 폭 ÷ 전체 평균, ↑ · ↓ 는 함께 오르나 · 반대로 가나입니다.
          다른 변수는 섞인 채로 평균합니다 — 자세히는 「다변수」 탭의 주효과.
        </p>
      </div>
    </div>
  )
}
