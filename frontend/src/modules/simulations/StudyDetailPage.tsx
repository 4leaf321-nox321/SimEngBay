/**
 * 설계점 비교 — **이것이 DOE 를 돌린 이유다.**
 *
 * 「두께 6 · 12 · 20 중 1차 공진이 가장 높은 것」, 그리고 「그 대가로 질량이 얼마나 늘었나」.
 * CAD 플랫폼은 결과를 받지 않으므로(CompCore 0장) 고르는 일이 여기서 끝나야 한다.
 *
 * ## 축을 사람이 고른다
 *
 * 변수가 여럿이고 결과도 여럿(1차 · 2차 … · 질량)이라 「무엇 대 무엇」 이 하나로 정해지지
 * 않는다. 그래서 가로 · 세로를 고르게 두고, **무엇을 보고 있는지 축 이름에 적는다.**
 *
 * ## 아직 안 끝난 점은 안 끝난 대로 보인다
 *
 * DOE 하나가 다 도는 데 점 수 x 1분이 걸린다. 다 끝나야 보여 주면 그동안 아무것도 못 본다.
 */

import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import type { StudyPoint } from '@/modules/simulations/api'
import { Spectrum } from '@/shared/charts'
import type { SpectrumPoint } from '@/shared/charts'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { PageHeader } from '@/shared/components/PageHeader'
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
import { useResource } from '@/shared/hooks/useResource'

/** 세로축 후보 — 결과 쪽. `mode:k` 는 k 차 탄성 모드. */
const MASS = '__mass__'

function valueOf(point: StudyPoint, key: string): number | null {
  if (key === MASS) return point.mass_kg ?? null
  const index = Number(key.replace('mode:', ''))
  return point.frequencies?.[index - 1] ?? null
}

function labelOf(key: string): string {
  return key === MASS ? '질량 (kg)' : `${key.replace('mode:', '')}차 모드 (Hz)`
}

export default function StudyDetailPage() {
  const { id = '' } = useParams()
  const study = useResource(() => simulationApi.study(id), [id])
  const [xKey, setXKey] = useState<string | null>(null)
  const [yKey, setYKey] = useState<string>('mode:1')

  const points = study.data?.points ?? []
  const factors = study.data?.factors ?? []
  const x = xKey ?? factors[0] ?? ''

  /** 결과가 있는 점만 그린다 — 아직 안 끝난 점은 표에서 상태로 보인다. */
  const drawn = useMemo<SpectrumPoint[]>(() => {
    const made: SpectrumPoint[] = []
    for (const one of points) {
      const value = valueOf(one, yKey)
      const across = one.params[x]
      if (value == null || across == null) continue
      made.push({
        key: String(one.number),
        x: across,
        y: value,
        label: `p${String(one.number).padStart(4, '0')}`,
      })
    }
    return made.sort((first, second) => first.x - second.x)
  }, [points, x, yKey])

  const modeCount = Math.max(0, ...points.map((one) => one.frequencies?.length ?? 0))
  const yOptions = [
    ...Array.from({ length: Math.min(modeCount, 5) }, (_, index) => `mode:${index + 1}`),
    ...(points.some((one) => one.mass_kg != null) ? [MASS] : []),
  ]

  if (study.error) {
    return (
      <div className="space-y-6">
        <PageHeader title="DOE 비교" back={{ to: '/simulations/studies', label: 'DOE 비교' }} />
        <ErrorNotice error={study.error} />
      </div>
    )
  }
  if (!study.data) return null

  return (
    <div className="space-y-6">
      <PageHeader
        title={study.data.name}
        description={`설계점 ${points.length}개 · 변수 ${factors.join(' · ') || '없음'}`}
        back={{ to: '/simulations/studies', label: 'DOE 비교' }}
      />

      {drawn.length === 0 ? (
        <EmptyState
          title="그릴 결과가 아직 없습니다"
          hint="설계점이 차례로 돕니다. 한 건에 1~2분 걸리고, 끝난 것부터 여기에 나타납니다."
        />
      ) : (
        <section className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Select value={x} onValueChange={setXKey}>
              <SelectTrigger className="h-8 w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {factors.map((one) => (
                  <SelectItem key={one} value={one}>
                    {one}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-muted-foreground text-sm">대</span>
            <Select value={yKey} onValueChange={setYKey}>
              <SelectTrigger className="h-8 w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {yOptions.map((one) => (
                  <SelectItem key={one} value={one}>
                    {labelOf(one)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Spectrum
            points={drawn}
            // 점을 이어 추세를 보인다 — 설계점 셋으로도 「두꺼울수록 높아지나」 는 읽힌다.
            lines={[{ key: 'trend', label: labelOf(yKey), points: drawn }]}
            stems={false}
            xLabel={x}
            yLabel={labelOf(yKey)}
            title={`${x} 대 ${labelOf(yKey)}`}
          />
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-medium">설계점</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>점</TableHead>
              {factors.map((one) => (
                <TableHead key={one}>{one}</TableHead>
              ))}
              <TableHead>상태</TableHead>
              <TableHead>1차 (Hz)</TableHead>
              <TableHead>질량 (kg)</TableHead>
              <TableHead>절점</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {points.map((one) => (
              <TableRow key={one.simulation_id}>
                <TableCell>
                  <Link
                    to={`/simulations/${one.simulation_id}`}
                    className="font-mono hover:underline"
                  >
                    p{String(one.number).padStart(4, '0')}
                  </Link>
                </TableCell>
                {factors.map((name) => (
                  <TableCell key={name} className="font-mono">
                    {one.params[name] ?? '—'}
                  </TableCell>
                ))}
                <TableCell>
                  <StatusBadge kind="simulation" value={one.status} />
                  {one.error_code && (
                    <span className="text-destructive ml-1 font-mono text-xs">
                      {one.error_code}
                    </span>
                  )}
                </TableCell>
                <TableCell className="font-mono">
                  {one.first_elastic_hz?.toLocaleString() ?? '—'}
                </TableCell>
                <TableCell className="font-mono">{one.mass_kg?.toFixed(3) ?? '—'}</TableCell>
                <TableCell className="font-mono">
                  {one.nodes?.toLocaleString() ?? '—'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  )
}
