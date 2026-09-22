/**
 * 모달 해석 결과 — 고유진동수 표 · 막대 · 모드 형상.
 *
 * ## 강체 모드를 숨기지 않고 접는다
 *
 * 자유-자유 해석의 앞 여섯은 0 Hz 다(물체가 통째로 움직이는 것). 지우면 사람은 「왜 7번부터
 * 시작하지」 를 묻고, 그대로 늘어놓으면 표의 절반이 0 이다. 그래서 **접어 두고 수를 적는다** —
 * 그 수가 6이 아니면 모델이 붙어 있지 않다는 신호이기도 하다.
 *
 * ## 단위와 정규화를 함께 적는다
 *
 * 변위는 질량 정규화된 상대값이라 「몇 mm 움직인다」 가 아니다. 그 말이 없으면 뷰어의 흔들림을
 * 실제 크기로 읽는다.
 */

import { lazy, Suspense, useEffect, useMemo, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type { Artifact, ModeResult, SimulationResult } from '@/modules/simulations/api'
import { ModeCharts } from '@/modules/simulations/ModeCharts'
import { ModeThumbnail } from '@/modules/simulations/ModeThumbnail'
import { EmptyState } from '@/shared/components/EmptyState'
import { Pagination } from '@/shared/components/Pagination'
import { Alert, AlertDescription, AlertTitle } from '@/shared/components/ui/alert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'

// **vtk.js 는 여기서만, 그것도 쓸 때만.** 결과를 안 보는 화면까지 수백 KB 를 받을 이유가 없다.
const MeshViewer = lazy(() => import('@/shared/viewer/MeshViewer'))

/** 표 한 쪽에 몇 모드. 모달은 모드 수십 개가 흔해서 전부 늘어놓으면 표가 화면을 삼킨다. */
const PER_PAGE = 20

/** 방향 이름 — 솔버는 X · ROTX 로 적고 사람은 「X 이동」 · 「X 회전」 으로 읽는다. */
const DIRECTION_LABELS: Record<string, string> = {
  X: 'X 이동',
  Y: 'Y 이동',
  Z: 'Z 이동',
  ROTX: 'X 회전',
  ROTY: 'Y 회전',
  ROTZ: 'Z 회전',
}

interface Props {
  simulationId: string
  result: SimulationResult
  artifacts: Artifact[]
}

export function ModalResult({ simulationId, result, artifacts }: Props) {
  const elastic = useMemo(() => result.modes.filter((one) => !one.rigid_body), [result.modes])
  const rigid = useMemo(() => result.modes.filter((one) => one.rigid_body), [result.modes])
  const withShape = useMemo(() => elastic.filter((one) => one.vtp), [elastic])
  const [selected, setSelected] = useState<number | null>(null)
  const [offset, setOffset] = useState(0)
  const [mesh, setMesh] = useState<ArrayBuffer | null>(null)
  const [meshError, setMeshError] = useState<string | null>(null)

  /** 파일 이름 → 산출물. 결과 파일은 이름을 적고, 내려받기는 id 로 한다. */
  const byName = useMemo(() => {
    const map = new Map<string, Artifact>()
    for (const one of artifacts) map.set(one.filename, one)
    return map
  }, [artifacts])

  const current = selected ?? withShape[0]?.number ?? null
  const currentMode = useMemo(
    () => result.modes.find((one) => one.number === current) ?? null,
    [result.modes, current],
  )

  // **고른 모드가 다른 쪽에 있으면 그 쪽으로 넘어간다.** 스펙트럼에서 40번째 모드를 눌렀는데
  // 표가 1쪽에 머물러 있으면, 화면은 아무 일도 안 일어난 것처럼 보인다.
  useEffect(() => {
    if (current === null) return
    const index = elastic.findIndex((one) => one.number === current)
    if (index < 0) return
    setOffset(Math.floor(index / PER_PAGE) * PER_PAGE)
  }, [current, elastic])

  const shown = elastic.slice(offset, offset + PER_PAGE)

  useEffect(() => {
    if (current === null) return
    const mode = result.modes.find((one) => one.number === current)
    const artifact = mode?.vtp ? byName.get(mode.vtp) : undefined
    if (!artifact) {
      setMesh(null)
      return
    }
    let disposed = false
    setMeshError(null)
    simulationApi
      .mesh(simulationId, artifact.id)
      .then((bytes) => {
        if (!disposed) setMesh(bytes)
      })
      .catch((caught: unknown) => {
        if (!disposed) {
          setMesh(null)
          setMeshError(caught instanceof Error ? caught.message : '모드 형상을 받지 못했습니다.')
        }
      })
    return () => {
      disposed = true
    }
  }, [current, result.modes, byName, simulationId])

  return (
    <div className="space-y-6">
      {result.fake && (
        <Alert>
          <AlertTitle>모의 결과입니다</AlertTitle>
          <AlertDescription>
            이 작업은 <span className="font-mono">fake</span> 실행기로 돌았습니다. 단계와 산출물의
            모양은 실제와 같지만 고유진동수는 계산한 값이 아닙니다.
          </AlertDescription>
        </Alert>
      )}
      {result.warning && (
        <Alert variant="destructive">
          <AlertTitle>확인이 필요합니다</AlertTitle>
          <AlertDescription>{result.warning}</AlertDescription>
        </Alert>
      )}

      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-medium">고유진동수</h2>
          <p className="text-muted-foreground text-xs">
            {result.boundary === 'free-free' ? '자유-자유(구속 없음)' : '구속 조건 적용'} ·{' '}
            단위 {result.units.frequency}
            {result.units.system ? ` · ${result.units.system}` : ''} · 변위 정규화{' '}
            {result.normalization === 'mass' ? '질량' : result.normalization}
          </p>
        </div>

        <ModeCharts
          result={result}
          selected={current}
          onPick={(mode) => setSelected(mode.number)}
        />

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>모드</TableHead>
              <TableHead>주파수 ({result.units.frequency})</TableHead>
              <TableHead>주 방향</TableHead>
              <TableHead>성격</TableHead>
              <TableHead>형상</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((one) => (
              <TableRow
                key={one.number}
                className={current === one.number ? 'bg-muted/50' : undefined}
              >
                <TableCell className="font-medium">
                  {one.elastic_number}차
                  <span className="text-muted-foreground ml-1 text-xs">(전체 {one.number}번)</span>
                </TableCell>
                <TableCell className="font-mono">{one.frequency_hz.toLocaleString()}</TableCell>
                <TableCell>
                  {/* 유효질량비가 있으면 그것이 정본이다. 자유-자유라 없을 때만 변위 비중으로
                      말하고, **무엇으로 잰 값인지 함께 적는다** — 둘은 다른 뜻이다. */}
                  {one.dominant_direction ? (
                    <>
                      {DIRECTION_LABELS[one.dominant_direction] ?? one.dominant_direction}
                      {one.effective_mass_ratio != null && (
                        <span className="text-muted-foreground ml-1 text-xs">
                          {(one.effective_mass_ratio * 100).toFixed(0)}%
                        </span>
                      )}
                    </>
                  ) : one.dominant_axis ? (
                    <>
                      {DIRECTION_LABELS[one.dominant_axis] ?? one.dominant_axis}
                      <span className="text-muted-foreground ml-1 text-xs">
                        변위 {Math.round((one.direction_share?.[
                          one.dominant_axis.toLowerCase() as 'x' | 'y' | 'z'
                        ] ?? 0) * 100)}%
                      </span>
                    </>
                  ) : one.direction_share ? (
                    <span className="text-muted-foreground text-sm">섞임</span>
                  ) : (
                    '—'
                  )}
                </TableCell>
                <TableCell>
                  {/* **값을 함께 보여 준다.** 「전역/국부」 는 경계가 하나인 판정이고, 경계
                      근처의 모드는 숫자를 봐야 판단이 선다(참여비: 1=전체, 0에 가까울수록 국부). */}
                  {one.localization == null ? (
                    <span className="text-muted-foreground text-sm">—</span>
                  ) : (
                    <span
                      className={
                        one.local_mode
                          ? 'text-amber-700 dark:text-amber-400'
                          : 'text-muted-foreground'
                      }
                      title={`참여비 ${one.localization} — 1 이면 전체가 함께 움직이고, 0 에 가까울수록 한 구석만 떱니다`}
                    >
                      {one.local_mode ? '국부' : '전역'}{' '}
                      <span className="font-mono text-xs">{one.localization.toFixed(2)}</span>
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  {one.vtp ? (
                    <button
                      type="button"
                      className="text-primary text-sm hover:underline"
                      onClick={() => setSelected(one.number)}
                    >
                      보기
                    </button>
                  ) : (
                    <span className="text-muted-foreground text-sm">—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {/* **없으면 20개가 넘는 순간 나머지를 볼 방법이 없다** — 모달은 모드 수십 개가 흔하다. */}
        <Pagination
          total={elastic.length}
          limit={PER_PAGE}
          offset={offset}
          onChange={setOffset}
          unit="개 모드"
        />

        {rigid.length > 0 && (
          <details className="text-muted-foreground text-sm">
            <summary className="cursor-pointer">
              강체 모드 {rigid.length}개 (≈0 {result.units.frequency})
            </summary>
            <p className="mt-1">
              구속이 없으면 물체가 통째로 움직이는 방식 여섯 가지가 0 Hz 로 나옵니다. 여섯이
              아니면 부품이 서로 붙어 있지 않다는 뜻입니다.
            </p>
            <ul className="mt-1 font-mono text-xs">
              {rigid.map((one: ModeResult) => (
                <li key={one.number}>
                  {one.number}번 · {one.frequency_hz}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium">모드 형상</h2>
        {withShape.length === 0 ? (
          <EmptyState
            title="모드 형상이 없습니다"
            hint="결과 추출이 그림을 만들지 못했거나, 모의(fake) 실행기로 돈 작업입니다."
          />
        ) : (
          // **고르는 자리와 보는 자리를 나눈다.** 썸네일을 가로로 깔면 모드가 늘어날수록
          // 줄이 접히고, 그때 「지금 무엇을 보고 있나」 가 그림 위쪽으로 밀려 올라간다.
          <div className="grid gap-4 lg:grid-cols-4">
            <div className="max-h-[calc(100vh-14rem)] min-h-[24rem] space-y-2 overflow-y-auto pr-1 lg:col-span-1">
              {withShape.map((one) => {
                const artifact = one.png ? byName.get(one.png) : undefined
                if (!artifact) return null
                return (
                  <ModeThumbnail
                    key={one.number}
                    simulationId={simulationId}
                    artifactId={artifact.id}
                    label={`${one.elastic_number}차 · ${one.frequency_hz.toLocaleString()} Hz`}
                    selected={current === one.number}
                    onSelect={() => setSelected(one.number)}
                    className="w-full"
                  />
                )
              })}
            </div>

            <div className="space-y-2 lg:col-span-3">
              {currentMode && (
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="font-medium">
                    {currentMode.elastic_number}차 모드 ·{' '}
                    <span className="font-mono">
                      {currentMode.frequency_hz.toLocaleString()} {result.units.frequency}
                    </span>
                  </h3>
                  <p className="text-muted-foreground text-xs">
                    전체 {currentMode.number}번
                    {currentMode.direction_share &&
                      ` · 변위 X ${Math.round(currentMode.direction_share.x * 100)}% ·
                       Y ${Math.round(currentMode.direction_share.y * 100)}% ·
                       Z ${Math.round(currentMode.direction_share.z * 100)}%`}
                    {currentMode.localization != null &&
                      ` · ${currentMode.local_mode ? '국부' : '전역'} 모드(${currentMode.localization.toFixed(2)})`}
                  </p>
                </div>
              )}
              {meshError && <p className="text-destructive text-sm">{meshError}</p>}
              {mesh ? (
                <Suspense
                  fallback={
                    <p className="text-muted-foreground py-8 text-center text-sm">
                      뷰어를 불러오는 중…
                    </p>
                  }
                >
                  <MeshViewer data={mesh} />
                </Suspense>
              ) : (
                !meshError && (
                  <p className="text-muted-foreground py-8 text-center text-sm">
                    모드 형상을 불러오는 중…
                  </p>
                )
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
