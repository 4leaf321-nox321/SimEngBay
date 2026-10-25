/**
 * DOE 한 벌을 **한 장으로** — 모드를 하나씩 눌러 봐야 아는 화면은 「전반적으로 어떤가」 에
 * 답하지 못한다.
 *
 * 순서가 곧 사람이 묻는 순서다:
 *
 *   1. 한 줄 요약   — 변수를 이만큼 움직였더니 1차와 질량이 이만큼 변했다
 *   2. 모드 지도    — 모드 전부를 한 그림에. 어느 것이 빨리 오르고 어디서 엇갈리나
 *   3. 트레이드오프 — 질량 대 주파수. 점마다 설계점 이름을 적는다
 *   4. 최적점 찾기 — 목표 · 조건을 골라 「최적」 · 「후보」(파레토)를 짚는다(`StudyChoice`)
 *   5. 행렬        — 모드 x 설계점 숫자표. 눈으로 훑고 값을 집어 가는 자리
 *
 * 설계 변수가 여럿이면 1 의 「끝 점 둘」 은 다른 변수까지 다른 두 점이라 그 변수의 효과가 아니다 —
 * 그때는 범위 · 그 점 · 영향 순위로 적는다(`StudySummary`).
 *
 * **모드는 형상으로 이어져 있다**(`core/modes` 의 MAC). 순번으로 이으면 치수가 바뀌는 순간
 * 다른 모드를 잇는다 — 실측으로 2차와 4차가 자리를 바꿨다.
 *
 * ## 숫자가 아닌 변수
 *
 * 재료처럼 **고르는 인자**가 온다(CompCore 가 물성 DOE 를 붙이면서). 「SS400」 을 가로축의
 * 좌표로 놓을 수는 없으므로, 그때는 선이 아니라 **막대**로 그린다 — 사이를 잇는 선은 「그
 * 중간」 이 있다는 말이고 재료에는 중간이 없다.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import type { ModeTrack, Study, StudyPoint } from '@/modules/simulations/api'
import { massScale, shownMass } from '@/modules/simulations/format'
import { AxisPicker, useAxis } from '@/modules/simulations/StudyAxis'
import { ChoiceMark, ChoicePanel, useChoice } from '@/modules/simulations/StudyChoice'
import { FactorSummary } from '@/modules/simulations/StudySummary'
import { caseName, caseTicks } from '@/modules/simulations/studyTable'
import { Chart, Spectrum } from '@/shared/charts'
import type { SpectrumLine, SpectrumPoint } from '@/shared/charts'
import { colorAt } from '@/shared/charts'
import { StatusBadge } from '@/shared/components/StatusBadge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { cn } from '@/shared/lib/utils'

/** 한 그림에 그릴 모드 수. 여섯을 넘으면 선이 서로를 가린다. */
const MAX_LINES = 6
/** 서버가 점마다 이을 후보로 보는 탄성 모드 수(`services.COMPARE_MODES`) — 더 구해도 이 안에서만 찾는다. */
const SEARCHED = 10
/** 닮은 정도(MAC)가 이보다 낮으면 「구한 모드 안에 닮은 것이 없다」 — `core/modes/track.py` 의 문턱. */
const UNLIKE = 0.3

/**
 * **못 이은 칸의 까닭과 할 일**(2026-10-25) — 「같은 모드를 못 찾았다」 만으로는 다음에 무엇을 할지
 * 모른다. 닮은 정도의 최고값(`track.confidence`, 못 이었어도 적힌다)으로 가른다:
 *
 *   - `range` — 구한 모드 안에 닮은 모양이 아예 없다(0.3 미만). 대개 그 모드가 이 점에서 더 높은
 *     차수로 밀려난 것이다(실측: 외팔보 폭 20 이상에서 폭 방향 2차 굽힘이 6번째 위로). 모드 수를
 *     늘려 다시 걸면 이어진다 — 단 서버는 앞 `SEARCHED` 개 안에서만 찾는다.
 *   - `shape` — 닮았지만 문턱(0.6) 아래. 모양이 바뀌었거나 두 모드가 섞였다 — 늘려도 안 이어질 수
 *     있고, 그 점의 모드 형상을 사람이 봐야 한다.
 */
type Gap = { kind: 'range' | 'shape'; best: number; computed: number }

function gapOf(point: StudyPoint, track: ModeTrack): Gap | null {
  if (point.status !== 'done' || track.numbers[point.number] != null) return null
  const best = (track.confidence as Record<string, number>)[String(point.number)]
  if (best == null) return null
  return { kind: best < UNLIKE ? 'range' : 'shape', best, computed: point.frequencies?.length ?? 0 }
}

/** 고칠 길 — 같은 폴더는 한 번만 가져오므로 다시 걸려면 이 DOE 를 지우고 다시 가져온다. */
function remedyOf(gap: Gap): string {
  if (gap.kind === 'shape') {
    return '모양이 바뀌었거나 두 모드가 섞였습니다 — 모드 수를 늘려도 이어지지 않을 수 있으니 그 점의 모드 형상을 직접 보세요.'
  }
  if (gap.computed >= SEARCHED) {
    return `비교는 점마다 앞 ${SEARCHED}개 안에서만 찾습니다 — 이 점에서는 그 모드가 훨씬 높은 차수입니다.`
  }
  return `이 점에서는 그 모드가 더 높은 차수로 밀려났을 가능성이 큽니다 — 모드 수를 ${SEARCHED}개로 늘려 다시 걸면 이어질 수 있습니다(같은 폴더는 한 번만 가져오므로 이 DOE 를 지우고 다시 가져옵니다).`
}

function gapTitle(gap: Gap): string {
  const head =
    gap.kind === 'range'
      ? `구한 모드 ${gap.computed}개 안에 닮은 모양이 없습니다(닮은 정도 ${gap.best.toFixed(2)}).`
      : `닮은 모드가 있지만 확실하지 않습니다(닮은 정도 ${gap.best.toFixed(2)}, 0.6 이상이어야 잇습니다).`
  return `${head} ${remedyOf(gap)}`
}

/** 표 아래 — 모드마다 못 이은 점 수와 까닭 · 할 일. 툴팁은 손을 올려야 보인다. */
function GapNote({ points, tracks }: { points: StudyPoint[]; tracks: ModeTrack[] }) {
  const lines: { key: string; text: string }[] = []
  for (const track of tracks) {
    const gaps = points.map((point) => gapOf(point, track)).filter((one): one is Gap => one !== null)
    for (const kind of ['range', 'shape'] as const) {
      const found = gaps.filter((one) => one.kind === kind)
      if (!found.length) continue
      const computed = Math.max(...found.map((one) => one.computed))
      const head =
        kind === 'range'
          ? `${track.reference}차 — ${found.length}점에서 구한 모드(${computed}개) 안에 닮은 모양이 없습니다.`
          : `${track.reference}차 — ${found.length}점에서 닮은 모드가 있지만 확실하지 않습니다.`
      lines.push({ key: `${track.reference}-${kind}`, text: `${head} ${remedyOf({ kind, best: 0, computed })}` })
    }
  }
  if (!lines.length) return null
  return (
    <div className="text-muted-foreground space-y-0.5 text-xs" aria-label="못 이은 자리">
      <p className="text-foreground font-medium">못 이은 자리(—)</p>
      {lines.map((one) => (
        <p key={one.key}>{one.text}</p>
      ))}
    </div>
  )
}

/** 추적된 모드가 그 설계점에서 몇 Hz인가. 못 이었으면 없다. */
function frequency(point: StudyPoint, track: ModeTrack): number | null {
  const number = track.numbers[point.number]
  if (number == null) return null
  return point.frequencies?.[number - 1] ?? null
}

function change(first: number | null, last: number | null): string {
  if (first == null || last == null || first === 0) return '—'
  const ratio = ((last - first) / first) * 100
  return `${ratio >= 0 ? '+' : ''}${ratio.toFixed(0)}%`
}

export function StudyOverview({ study }: { study: Study }) {
  const factors = study.factors
  // 처음 가로축은 1차를 가장 크게 움직이는 변수, 선은 나머지를 고정한 단면만(`StudyAxis`).
  const primary = study.tracks?.[0] ? `mode:${study.tracks[0].reference}` : 'first_elastic_hz'
  const axis = useAxis(study, primary)
  const x = axis.x

  const points = useMemo(() => {
    const rows = [...study.points]
    // 숫자면 값 순서, 글자면 **가져온 순서**(설계점 번호) — 재료 이름을 사전순으로 늘어놓으면
    // DOE 표와 순서가 달라져 대조하기 어렵다.
    return rows.sort((first, second) => {
      const a = first.params[x]
      const b = second.params[x]
      if (typeof a === 'number' && typeof b === 'number') return a - b
      return first.number - second.number
    })
  }, [study.points, x])
  const done = points.filter((one) => one.status === 'done')
  const tracks = (study.tracks ?? []).slice(0, MAX_LINES)
  // **비어 있는 까닭을 맞게 말한다** — 끝난 점이 있는데 이은 모드가 없으면 지문이 없는 작업이다
  // (2026-10-24 전의 CalculiX). 「차례로 돕니다」 라고 하면 기다리면 된다는 말이 된다.
  const emptyMap =
    done.length > 0 && tracks.length === 0
      ? '모드 지문이 없는 작업이라 모드를 잇지 못합니다 — 다시 걸면 그려집니다.'
      : '아직 그릴 결과가 없습니다. 설계점이 차례로 돕니다.'

  /**
   * 이 변수가 숫자인가. **하나라도 글자면 범주로 본다** — 섞여 있으면 좌표를 못 매긴다.
   */
  const numeric = useMemo(
    () => points.every((one) => typeof one.params[x] !== 'string'),
    [points, x],
  )

  /** 범주 변수일 때 — 가로는 값(재료 이름), 계열은 모드. **잇지 않는다.** */
  const bars = useMemo(() => {
    if (numeric) return []
    return points.map((point) => {
      const row: Record<string, unknown> = { name: String(point.params[x] ?? '—') }
      for (const track of tracks) {
        const hz = frequency(point, track)
        if (hz != null) row[`${track.reference}차`] = hz
      }
      return row
    })
  }, [numeric, points, tracks, x])

  /** 모드 지도 — 선 하나가 **추적된 모드 하나**다. */
  const lines = useMemo<SpectrumLine[]>(
    () =>
      tracks
        .map((track, index) => ({
          key: `mode-${track.reference}`,
          label: `${track.reference}차`,
          color: colorAt(index),
          connect: axis.connect,
          points: points
            .filter(axis.shows)
            .map((point) => {
              const hz = frequency(point, track)
              const across = point.params[x]
              return hz != null && typeof across === 'number'
                ? { x: across, y: hz, label: caseName(point.number) }
                : null
            })
            .filter((one): one is { x: number; y: number; label: string } => one !== null),
        }))
        .filter((one) => one.points.length > 0),
    [tracks, points, x, axis.connect, axis.shows],
  )

  /** 트레이드오프 — 질량 대 그 모드. 점마다 설계점 이름. */
  const [tradeMode, setTradeMode] = useState('1')
  const track = tracks.find((one) => String(one.reference) === tradeMode) ?? tracks[0]
  // **질량은 그 DOE 에 맞는 한 단위로** — 작은 부품을 kg 으로 그리면 축 눈금이 모두 0 근처다.
  const mass = massScale(points.map((one) => one.mass_kg))
  const rows = points.map((one) => ({
    number: one.number,
    hz: track ? frequency(one, track) : (one.first_elastic_hz ?? null),
    mass: one.mass_kg != null && one.mass_kg > 0 ? one.mass_kg * mass.factor : null,
  }))
  // 표의 「최적」 · 「후보」 는 최적점 찾기의 답이다 — 처음 모양은 예전 후보(1차 크게 · 질량 작게).
  const choice = useChoice(study)
  const tradePoints = useMemo<SpectrumPoint[]>(
    () =>
      rows
        .filter((one) => one.hz != null && one.mass != null)
        .map((one) => ({
          key: String(one.number),
          x: one.mass as number,
          y: one.hz as number,
          label: caseName(one.number),
        })),
    [rows],
  )

  const first = done[0]
  const last = done[done.length - 1]
  const firstHz = first?.first_elastic_hz ?? null
  const lastHz = last?.first_elastic_hz ?? null

  return (
    <div className="space-y-6">
      <AxisPicker study={study} axis={axis} />

      {/* 1. 한 줄 요약 — **무엇을 얼마나 바꿨더니 무엇이 얼마나 변했나.** 변수가 여럿이면 끝 점
          둘이 그 변수의 효과가 아니다 — 범위 · 그 점 · 영향 순위로. */}
      {factors.length > 1 ? (
        <FactorSummary
          study={study}
          primary={primary}
        />
      ) : (
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-md border p-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground text-xs">설계점</dt>
          <dd className="font-medium">
            {done.length} / {points.length} 완료
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">{x}</dt>
          <dd className="font-medium">
            {/* 숫자면 범위(6 → 20), 고르는 값이면 목록(SS400 · AL6061) — 「→」 는 사이가
                있다는 말이고 재료에는 사이가 없다. */}
            {numeric
              ? `${first?.params[x] ?? '—'} → ${last?.params[x] ?? '—'}`
              : [...new Set(points.map((one) => String(one.params[x] ?? '—')))].join(' · ')}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">1차 모드</dt>
          <dd className="font-medium">
            {firstHz?.toLocaleString() ?? '—'} → {lastHz?.toLocaleString() ?? '—'} Hz{' '}
            <span className="text-muted-foreground">{change(firstHz, lastHz)}</span>
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">질량</dt>
          <dd className="font-medium">
            {shownMass(first?.mass_kg)} → {shownMass(last?.mass_kg)}{' '}
            <span className="text-muted-foreground">
              {change(first?.mass_kg ?? null, last?.mass_kg ?? null)}
            </span>
          </dd>
        </div>
      </dl>
      )}

      {/* 2 · 3. 두 그림을 **나란히** — 가로로 긴 그림 하나는 축이 멀어 값을 못 읽는다.
          좁은 화면에서는 위아래로 쌓인다(그때는 폭이 곧 높이 대비 과하지 않다). */}
      <div className="grid gap-6 xl:grid-cols-2">
        <section className="space-y-2">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-sm font-medium">모드 지도</h2>
            <p className="text-muted-foreground text-xs">
              {axis.connect ? '선 하나가 모드 하나' : '색 하나가 모드 하나 — 잇지 않음'}
              {axis.slice && ` · ${axis.slice.label}`}
            </p>
          </div>
          {numeric ? (
            <Spectrum
              lines={lines}
              stems={false}
              xLabel={x}
              yLabel="주파수 (Hz)"
              height={320}
              title="설계 변수에 따른 모드별 고유진동수"
              emptyText={emptyMap}
              // 가로축 값마다 그 설계점 — 점 위에 적으면 모드 수만큼 겹친다.
              xTicks={caseTicks(done.filter(axis.shows), x)}
            />
          ) : (
            // **잇지 않는다.** 선은 「그 중간이 있다」 는 말인데 재료에는 중간이 없다.
            <Chart
              kind="bar"
              data={bars}
              x="name"
              series={tracks.map((one) => ({ key: `${one.reference}차` }))}
              height={320}
              title="값별 모드 고유진동수"
              emptyText={emptyMap}
            />
          )}
          <p className="text-muted-foreground text-xs">
            모드는 <b>형상으로 이어</b> 견줍니다 — 순번으로 이으면 치수가 바뀌는 순간 다른
            모드를 잇습니다.
            {!numeric && ' 값 사이를 잇지 않는 이유는 그 중간이 없기 때문입니다.'}
            {done.some((point) => tracks.some((track) => gapOf(point, track))) &&
              ' 선이 끊긴 자리의 까닭과 할 일은 아래 표 밑에 적었습니다.'}
          </p>
        </section>

        <section className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium">질량 대 주파수</h2>
            {tracks.length > 0 ? (
              <Select value={tradeMode} onValueChange={setTradeMode}>
                <SelectTrigger className="h-7 w-24">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {tracks.map((one) => (
                    <SelectItem key={one.reference} value={String(one.reference)}>
                      {one.reference}차
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              // 이은 모드가 없으면 고를 것도 없다 — 빈 칸 대신 무엇을 그렸는지 적는다.
              <p className="text-muted-foreground text-xs">1차 탄성 모드</p>
            )}
          </div>
          <Spectrum
            points={tradePoints}
            stems={false}
            xLabel={`질량 (${mass.unit})`}
            yLabel="주파수 (Hz)"
            height={320}
            title="질량 대 주파수"
            emptyText="질량이 없는 작업입니다(옛 작업은 질량을 안 냅니다)."
            pointLabels
          />
          <p className="text-muted-foreground text-xs">
            오른쪽 아래일수록 무겁고 무릅니다 — 주파수를 높이려면 <b>왼쪽 위</b>가 좋습니다. 무엇을
            기준으로 고를지는 아래 「최적점 찾기」 에서 정합니다.
          </p>
        </section>
      </div>

      {/* 4. 최적점 찾기 — 표의 「최적」 · 「후보」 가 이 답이다. */}
      <ChoicePanel model={choice} />

      {/* 5. 행렬 — 눈으로 훑고 값을 집어 가는 자리. */}
      <section className="space-y-2">
        <h2 className="text-sm font-medium">설계점 × 모드 (Hz)</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>점</TableHead>
              {factors.map((one) => (
                <TableHead key={one}>{one}</TableHead>
              ))}
              <TableHead>상태</TableHead>
              {tracks.map((one) => (
                <TableHead key={one.reference}>{one.reference}차</TableHead>
              ))}
              <TableHead>질량 ({mass.unit})</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {points.map((point) => (
              <TableRow
                key={point.simulation_id}
                className={cn(choice.outcome.marks.has(point.number) && 'bg-emerald-500/5')}
              >
                <TableCell>
                  <Link
                    to={`/simulations/${point.simulation_id}`}
                    className="font-mono hover:underline"
                  >
                    {caseName(point.number)}
                  </Link>
                  {/* **고를 가치가 있는 점을 짚어 준다** — 최적점 찾기의 답(최적 · 후보). */}
                  <ChoiceMark mark={choice.outcome.marks.get(point.number)} />
                </TableCell>
                {factors.map((one) => (
                  <TableCell key={one} className="font-mono">
                    {point.params[one] ?? '—'}
                  </TableCell>
                ))}
                <TableCell>
                  <StatusBadge kind="simulation" value={point.status} />
                </TableCell>
                {tracks.map((one) => {
                  const hz = frequency(point, one)
                  return (
                    <TableCell key={one.reference} className="font-mono">
                      {hz?.toLocaleString() ?? (
                        // 못 이은 자리는 비운다 — 숫자를 채우면 그 값이 같은 모드로 읽힌다. 끝난 점이면
                        // 까닭과 할 일을 적는다(아래 `GapNote` 에도).
                        <span
                          className="text-muted-foreground"
                          title={(() => {
                            const gap = gapOf(point, one)
                            return gap ? gapTitle(gap) : '아직 끝나지 않은 점입니다'
                          })()}
                        >
                          —
                        </span>
                      )}
                    </TableCell>
                  )
                })}
                <TableCell className="font-mono">
                  {shownMass(point.mass_kg, mass).replace(` ${mass.unit}`, '')}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <GapNote points={points} tracks={tracks} />
      </section>
    </div>
  )
}
