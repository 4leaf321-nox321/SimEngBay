/**
 * CAD 가 보낸 해석 조건과 **우리가 그것을 어떻게 다뤘나**.
 *
 * 조건을 넣었는데 결과가 같을 때, 그것이 **무시된 것인지 원래 그런 것인지** 사람이 알 수
 * 있어야 한다. 그래서 줄마다 상태를 붙인다 — 반영 · 넘김(이 해석에서 답을 안 바꾼다) ·
 * 막음(아직 못 건다). 서버가 그 판단을 내리고 화면은 그대로 보여 준다.
 */
import type { components } from '@/shared/api/schema'

type Conditions = components['schemas']['ConditionsOut']
type Line = components['schemas']['ConditionLine']

/** 갈래마다 사람이 읽는 이름 — 모르는 갈래는 그대로 보여 준다. */
const KIND_LABELS: Record<string, string> = {
  constraint: '구속',
  contact: '접촉',
  load: '하중',
  mesh: '메시',
  body: '파트',
  frame: '좌표계',
  analysis: '해석 설정',
}

const STATUS_STYLES: Record<string, { label: string; className: string }> = {
  applied: { label: '반영', className: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950/60 dark:text-emerald-200' },
  skipped: { label: '넘김', className: 'bg-amber-100 text-amber-900 dark:bg-amber-950/60 dark:text-amber-200' },
  refused: { label: '막음', className: 'bg-rose-100 text-rose-900 dark:bg-rose-950/60 dark:text-rose-200' },
}

export function ConditionList({ conditions }: { conditions: Conditions }) {
  if (conditions.lines.length === 0) return null

  return (
    <section className="space-y-2">
      <h2 className="flex items-center gap-2 text-sm font-medium">
        CAD 가 보낸 조건
        <span className="text-muted-foreground text-xs font-normal">
          {conditions.unit_system && `단위계 ${conditions.unit_system}`}
          {conditions.prestressed && ' · 선응력'}
        </span>
      </h2>
      <ul className="divide-y rounded-md border text-sm">
        {conditions.lines.map((line: Line, index: number) => {
          const status = STATUS_STYLES[line.status] ?? STATUS_STYLES.applied
          return (
            <li key={`${line.kind}-${line.label}-${index}`} className="flex gap-3 px-4 py-2">
              <span className="text-muted-foreground w-14 shrink-0 text-xs">
                {KIND_LABELS[line.kind] ?? line.kind}
              </span>
              <span className="min-w-0 flex-1">
                <span className="font-medium">{line.label}</span>
                {line.detail && (
                  <span className="text-muted-foreground ml-2 font-mono text-xs">
                    {line.detail}
                  </span>
                )}
                {/* **왜 안 걸었는지를 같은 줄에서 읽게 한다** — 따로 찾게 하지 않는다. */}
                {line.why && <p className="text-muted-foreground text-xs">{line.why}</p>}
              </span>
              <span
                className={`h-fit shrink-0 rounded px-1.5 py-0.5 text-xs ${status.className}`}
              >
                {status.label}
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
