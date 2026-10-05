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
 *
 * ## 두 가지로 본다 — 하나씩 크게 · 여러 개
 *
 * **하나씩 크게**는 왼쪽 모드 표에서 고르고 오른쪽 3D 뷰어로 그 모드만 본다(움직임까지). **여러
 * 개**는 같은 3D 뷰어를 4 · 6 · 9 개 작게 깔아 모드끼리 견준다 — 움직임은 위에서 한 번에, 제목을
 * 누르면 그 모드를 크게 연다. 처음에는 추출이 만든 그림(PNG)으로 그렸는데, CalculiX 는 그림을 안
 * 만들어(리눅스 워커에 pyvista 가 없다) 칸마다 「그림 없음」 이었다. 9 개면 브라우저의 WebGL 한도
 * (대개 16) 안이고, 뷰어가 닫힐 때 컨텍스트를 반납한다(`MeshViewer`).
 */

import { lazy, Suspense, useEffect, useMemo, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type { Artifact, ModeResult, SimulationResult } from '@/modules/simulations/api'
import { ModeCharts } from '@/modules/simulations/ModeCharts'
import { ModalProbeTable } from '@/modules/simulations/ProbeTables'
import { EmptyState } from '@/shared/components/EmptyState'
import { Pagination } from '@/shared/components/Pagination'
import { Alert, AlertDescription, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { CameraSync } from '@/shared/viewer/cameraSync'
import { ColormapSelect } from '@/shared/viewer/ColormapSelect'
import { DisplayToggles, PartPicker } from '@/shared/viewer/ViewerControls'
import type { ViewerPart } from '@/shared/viewer/ViewerControls'

// **vtk.js 는 여기서만, 그것도 쓸 때만.** 결과를 안 보는 화면까지 수백 KB 를 받을 이유가 없다.
const MeshViewer = lazy(() => import('@/shared/viewer/MeshViewer'))

/** 표 한 쪽에 몇 모드. 모달은 모드 수십 개가 흔해서 전부 늘어놓으면 표가 화면을 삼킨다. */
const PER_PAGE = 20

/** 「여러 개 보기」 한 화면에 깔 모드 수. */
const GRID_SIZES = [4, 6, 9] as const

type View = 'single' | 'grid'

/** 방향 이름 — 솔버는 X · ROTX 로 적고 사람은 「X 이동」 · 「X 회전」 으로 읽는다. */
const DIRECTION_LABELS: Record<string, string> = {
  X: 'X 이동',
  Y: 'Y 이동',
  Z: 'Z 이동',
  ROTX: 'X 회전',
  ROTY: 'Y 회전',
  ROTZ: 'Z 회전',
}

/** 그림 밑에 쓰는 한 줄 — 주 방향(유효질량)과 전역 · 국부. */
function modeNote(one: ModeResult): string {
  const parts: string[] = []
  if (one.dominant_direction) {
    const share =
      one.effective_mass_ratio != null ? ` ${(one.effective_mass_ratio * 100).toFixed(0)}%` : ''
    parts.push(`${DIRECTION_LABELS[one.dominant_direction] ?? one.dominant_direction}${share}`)
  } else if (one.dominant_axis) {
    parts.push(DIRECTION_LABELS[one.dominant_axis] ?? one.dominant_axis)
  }
  if (one.localization != null) parts.push(one.local_mode ? '국부' : '전역')
  return parts.join(' · ')
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
  const [view, setView] = useState<View>('single')
  const [gridSize, setGridSize] = useState<number>(6)
  const [gridOffset, setGridOffset] = useState(0)
  const [gridPlaying, setGridPlaying] = useState(true)
  // **시점 맞추기** — 한 칸에서 돌리거나 확대하면 모든 칸이 따른다. 견주려면 같은 쪽에서 봐야 한다.
  const [cameraSync] = useState(() => new CameraSync(true))
  const [synced, setSynced] = useState(true)
  // **숨긴 파트는 두 보기가 함께 쓴다** — 크게 보다 여러 개로 넘어가도 같은 파트가 숨는다. 파트
  // 목록은 그림을 읽은 뷰어가 알린다(모드마다 같은 겉면이다).
  const [hiddenParts, setHiddenParts] = useState<number[]>([])
  const [viewerParts, setViewerParts] = useState<ViewerPart[]>([])

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
  const gridShown = withShape.slice(gridOffset, gridOffset + gridSize)
  const gridColumns = gridSize === 4 ? 'sm:grid-cols-2' : 'sm:grid-cols-2 lg:grid-cols-3'

  useEffect(() => {
    // 「여러 개」 에서는 3D 를 안 그린다 — 받을 이유도 없다.
    if (current === null || view !== 'single') return
    const mode = result.modes.find((one) => one.number === current)
    const artifact = mode?.vtp ? byName.get(mode.vtp) : undefined
    // **앞 모드의 형상을 내린다** — 머리는 새 모드인데 다 받을 때까지 그림은 옛 모드였다.
    setMesh(null)
    setMeshError(null)
    if (!artifact) {
      // 스펙트럼에서는 형상이 없는 모드도 누를 수 있다(CalculiX 는 앞쪽 탄성 모드 몇 개만 낸다) —
      // 말하지 않으면 「불러오는 중」 에 멈춘다.
      setMeshError('이 모드는 3D 형상이 없습니다 — 형상은 앞쪽 탄성 모드 몇 개만 만듭니다.')
      return
    }
    let disposed = false
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
  }, [current, result.modes, byName, simulationId, view])

  /** 여러 개 · 막대에서 하나를 누르면 그 모드를 크게 연다. */
  function openSingle(number: number) {
    setSelected(number)
    setView('single')
  }

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

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-medium">고유진동수 · 모드 형상</h2>
            <p className="text-muted-foreground text-xs">
              {result.boundary === 'free-free' ? '자유-자유(구속 없음)' : '구속 조건 적용'} ·{' '}
              단위 {result.units.frequency}
              {result.units.system ? ` · ${result.units.system}` : ''} · 변위 정규화{' '}
              {result.normalization === 'mass' ? '질량' : result.normalization}
            </p>
          </div>
          {/* **두 가지로 본다** — 하나씩 크게 · 여러 개(둘 다 3D). */}
          <div className="flex gap-1" role="group" aria-label="모드 보기">
            <Button
              variant={view === 'single' ? 'secondary' : 'ghost'}
              size="sm"
              aria-pressed={view === 'single'}
              onClick={() => setView('single')}
            >
              하나씩 크게
            </Button>
            <Button
              variant={view === 'grid' ? 'secondary' : 'ghost'}
              size="sm"
              aria-pressed={view === 'grid'}
              onClick={() => setView('grid')}
              disabled={withShape.length === 0}
            >
              여러 개 보기
            </Button>
          </div>
        </div>

        {view === 'single' ? (
          <div className="grid gap-4 lg:grid-cols-5">
            <div className="space-y-2 lg:col-span-2">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>모드</TableHead>
                    <TableHead>주파수 ({result.units.frequency})</TableHead>
                    <TableHead>주 방향</TableHead>
                    <TableHead>성격</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {shown.map((one) => (
                    <TableRow
                      key={one.number}
                      // **행을 누르면 그 모드를 오른쪽에서 본다** — 형상이 있을 때만.
                      className={
                        current === one.number ? 'bg-muted/50' : one.vtp ? 'cursor-pointer' : undefined
                      }
                      aria-selected={current === one.number}
                      onClick={() => one.vtp && setSelected(one.number)}
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
            </div>

            <div className="space-y-2 lg:col-span-3">
              {withShape.length === 0 ? (
                <EmptyState
                  title="모드 형상이 없습니다"
                  hint="결과 추출이 그림을 만들지 못했거나, 모의(fake) 실행기로 돈 작업입니다."
                />
              ) : (
                <>
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
                      <MeshViewer
                        data={mesh}
                        heightClass="h-[32rem]"
                        partNames={result.parts}
                        hiddenParts={hiddenParts}
                        onHiddenPartsChange={setHiddenParts}
                        onParts={setViewerParts}
                      />
                    </Suspense>
                  ) : (
                    !meshError && (
                      <p className="text-muted-foreground py-8 text-center text-sm">
                        모드 형상을 불러오는 중…
                      </p>
                    )
                  )}
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-1" role="group" aria-label="한 화면에">
                <span className="text-muted-foreground mr-1 text-xs">한 화면에</span>
                {GRID_SIZES.map((size) => (
                  <Button
                    key={size}
                    variant={gridSize === size ? 'secondary' : 'ghost'}
                    size="sm"
                    aria-pressed={gridSize === size}
                    onClick={() => {
                      setGridSize(size)
                      setGridOffset(0)
                    }}
                  >
                    {size}개
                  </Button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-muted-foreground text-xs">끌어서 회전 · 휠로 확대 · 제목을 누르면 크게 엽니다.</p>
                {/* 칸에는 범례가 없다 — 여기서 고르고, 띠가 그 색(왼쪽 0 → 오른쪽 최대)이다. */}
                <ColormapSelect swatch />
                <DisplayToggles />
                <PartPicker parts={viewerParts} hidden={hiddenParts} onChange={setHiddenParts} />
                {/* **한 번에 멈추고 움직인다** — 하나씩 끄고 켜면 모드끼리 견주기 어렵다. */}
                <Button variant="outline" size="sm" onClick={() => setGridPlaying((on) => !on)}>
                  {gridPlaying ? '모두 멈추기' : '모두 움직이기'}
                </Button>
                <Button
                  variant={synced ? 'secondary' : 'outline'}
                  size="sm"
                  aria-pressed={synced}
                  title="켜면 한 칸에서 돌리거나 확대한 대로 모든 칸이 따라 움직입니다"
                  onClick={() => {
                    cameraSync.setEnabled(!synced)
                    setSynced(!synced)
                  }}
                >
                  시점 맞추기
                </Button>
                <Button variant="ghost" size="sm" onClick={() => cameraSync.resetAll()}>
                  시점 처음으로
                </Button>
              </div>
            </div>
            <div className={`grid gap-3 ${gridColumns}`}>
              {gridShown.map((one) => (
                <GridCell
                  key={one.number}
                  simulationId={simulationId}
                  artifact={one.vtp ? byName.get(one.vtp) : undefined}
                  mode={one}
                  unit={result.units.frequency}
                  playing={gridPlaying}
                  cameraSync={cameraSync}
                  selected={current === one.number}
                  onOpen={() => openSingle(one.number)}
                  partNames={result.parts}
                  hiddenParts={hiddenParts}
                  onParts={setViewerParts}
                />
              ))}
            </div>
            <Pagination
              total={withShape.length}
              limit={gridSize}
              offset={gridOffset}
              onChange={setGridOffset}
              unit="개 모드"
            />
          </div>
        )}
      </section>

      {/* 진동수 분포 · 유효질량 — 모드를 고르는 또 하나의 자리다(막대를 누르면 그 모드를 크게). */}
      <section className="space-y-2">
        <h2 className="text-sm font-medium">진동수 분포</h2>
        <ModeCharts result={result} selected={current} onPick={(mode) => openSingle(mode.number)} />
      </section>

      {/* **센서를 붙이는 자리에서 어느 모드가 보이나** — 실측과 견주는 첫 자리다. */}
      <ModalProbeTable probes={result.probes ?? []} modes={result.modes} />
    </div>
  )
}

/**
 * 「여러 개 보기」 의 칸 하나 — **하나씩 크게와 같은 3D 뷰어**를 작게(슬라이더 · 단추 없이).
 * 두 솔버가 똑같이 나온다: CalculiX 는 그림(PNG)을 안 만들고(리눅스 워커에 pyvista 가 없다),
 * 3D 형상(VTP)은 두 솔버 모두 낸다. 처음에는 그림으로 그려 CalculiX 작업이 「그림 없음」 이었다.
 */
function GridCell({
  simulationId,
  artifact,
  mode,
  unit,
  playing,
  cameraSync,
  selected,
  onOpen,
  partNames,
  hiddenParts,
  onParts,
}: {
  simulationId: string
  artifact: Artifact | undefined
  mode: ModeResult
  unit: string
  playing: boolean
  cameraSync: CameraSync
  selected: boolean
  onOpen: () => void
  partNames?: string[]
  hiddenParts: number[]
  onParts: (parts: ViewerPart[]) => void
}) {
  const [mesh, setMesh] = useState<ArrayBuffer | null>(null)
  const [failed, setFailed] = useState<string | null>(null)

  useEffect(() => {
    setMesh(null)
    setFailed(null)
    if (!artifact) {
      setFailed('형상 파일이 없습니다')
      return
    }
    let disposed = false
    simulationApi
      .mesh(simulationId, artifact.id)
      .then((bytes) => {
        if (!disposed) setMesh(bytes)
      })
      .catch((caught: unknown) => {
        if (!disposed) setFailed(caught instanceof Error ? caught.message : '형상을 받지 못했습니다')
      })
    return () => {
      disposed = true
    }
  }, [simulationId, artifact])

  return (
    <div
      className={`space-y-1 rounded-md border p-2 ${selected ? 'border-primary ring-primary/30 ring-2' : ''}`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <button type="button" onClick={onOpen} className="text-sm font-medium hover:underline">
          {mode.elastic_number}차 · {mode.frequency_hz.toLocaleString()} {unit}
        </button>
        <span className="text-muted-foreground truncate text-xs">{modeNote(mode)}</span>
      </div>
      {mesh ? (
        <Suspense
          fallback={<div className="text-muted-foreground flex aspect-[4/3] items-center justify-center text-xs">…</div>}
        >
          <MeshViewer
            data={mesh}
            controls={false}
            playing={playing}
            cameraSync={cameraSync}
            heightClass="aspect-[4/3]"
            partNames={partNames}
            hiddenParts={hiddenParts}
            onParts={onParts}
          />
        </Suspense>
      ) : (
        <div className="text-muted-foreground bg-muted/30 flex aspect-[4/3] items-center justify-center rounded-md text-xs">
          {failed ?? '형상을 불러오는 중…'}
        </div>
      )}
    </div>
  )
}
