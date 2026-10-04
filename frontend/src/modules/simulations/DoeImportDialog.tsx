/**
 * DOE 폴더 가져오기 — **폴더 한 벌이 계약이다.**
 *
 * CAD 플랫폼(CompCore)이 설계점 N 벌을 폴더로 내놓고 그 뒤로는 아무것도 주고받지 않는다.
 * 결과도 되돌려 보내지 않으므로, 「이 결과가 두께 몇짜리인가」 를 이 플랫폼이 들고 있어야 한다 —
 * 가져올 때 스터디 · 점 번호 · 바꾼 변수를 작업에 함께 적는다.
 *
 * ## 경로를 외워서 치게 하지 않는다
 *
 * 공유 스토리지의 자리는 `/mnt/f/data/0_Program/73_CompCore/브래킷_튜닝-3f9a21` 같은 것이라
 * 사람이 외울 수 없다. 그렇다고 **아무 경로나 받으면** 그 칸이 서버의 모든 폴더를 여는 문이
 * 된다(서버가 막는다 — `DOE_ROOTS`). 그래서 **설정된 공용 폴더 아래를 탐색기처럼 고른다.**
 *
 * ## 먼저 보여 주고 나서 건다
 *
 * 200개를 잘못 걸면 되돌리기 어렵고, 그 사이 Mechanical 라이선스를 계속 문다. 그래서 폴더를
 * 고르면 **훑어 본 결과**(점 몇 개 · 변수 무엇 · 건너뛸 것 몇 개와 그 이유)를 먼저 보인다.
 *
 * ## 해석 종류와 솔버
 *
 * **해석 종류는 CAD 가 점 파일에 적어 보낸다**(`conditions.analysis.type`) — 미리 고르고 사람이
 * 바꾸게 한다. 모달로 못 박아 두면 전단 이음 같은 정적 DOE 가 하중을 건너뛴 채 모달로 돈다.
 * 솔버는 모든 점에 같다: 설계점끼리 견주려고 DOE 를 돌리는데 솔버가 섞이면 그 차이(몇 %)가
 * 변수의 효과로 읽힌다. 고른 해석 종류에서 **첫 점의 조건이 어떻게 다뤄지나**(반영 · 넘김 ·
 * 막음)를 서버가 읽어 보여 준다.
 *
 * ## 물성은 CompCore 가 정한다
 *
 * 설계점마다 점 파일이 파트별 재료를 싣고 온다(재료를 훑는 DOE 는 점마다 다르다). 이 창은 물성을
 * 받지 않는다 — 한 벌을 모든 점 · 모든 파트에 붙이는 길은 뜻이 없어 없앴다. 물성을 안 보낸 폴더는
 * 실행하지 않고, 재료가 빠진 점은 서버가 까닭을 달아 건너뛴다.
 *
 * ## 설계점을 골라 건다
 *
 * 다 걸 필요는 없다 — 몇 점만 먼저 돌려 보거나, 설계점 하나만 해석 작업으로 만들 때 쓴다.
 * 서버가 `numbers` 로 받는다.
 */

import { useEffect, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type { DoeImport, DoeListing, DoePreview } from '@/modules/simulations/api'
import { ConditionList } from '@/modules/simulations/ConditionList'
import { FolderBrowser } from '@/modules/simulations/FolderBrowser'
import { buildSpec, HARMONIC_DEFAULTS, isOrder, isRecipe, specProblem } from '@/modules/simulations/spec'
import type { HarmonicInput, MeshOrder, RecipeName } from '@/modules/simulations/spec'
import { HarmonicFields, MeshFields, RecipeSelect } from '@/modules/simulations/SpecFields'
import { SolverSelect } from '@/modules/simulations/SolverSelect'
import type { Solver } from '@/modules/simulations/SolverSelect'
import { ApiError } from '@/shared/api/client'
import { useAuth } from '@/shared/auth/AuthContext'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'

interface Props {
  open: boolean
  onClose: () => void
  onImported: (result: DoeImport) => void
}

export function DoeImportDialog({ open, onClose, onImported }: Props) {
  const { user } = useAuth()
  const [listing, setListing] = useState<DoeListing | null>(null)
  const [preview, setPreview] = useState<DoePreview | null>(null)
  const [modes, setModes] = useState('10')
  const [region, setRegion] = useState('bolt_holes')
  const [recipe, setRecipe] = useState<RecipeName>('modal')
  const [solver, setSolver] = useState<Solver>('ansys')
  // 비워 두면 **점마다 CAD 의 「전체」 크기**로 돈다 — 미리 채우면 그 값이 모든 점을 덮는다.
  const [elementSize, setElementSize] = useState('')
  const [order, setOrder] = useState<MeshOrder>('quadratic')
  const [harmonic, setHarmonic] = useState<HarmonicInput>(HARMONIC_DEFAULTS)
  const [largeDeflection, setLargeDeflection] = useState(false)
  // 고른 설계점 — `null` 이면 **걸 수 있는 점 전부**(새 폴더를 훑으면 그리로 돌아간다).
  const [picked, setPicked] = useState<Set<number> | null>(null)
  // 첫 점의 조건을 **고른 해석 종류로** 편 것 — 종류를 바꾸면 다시 묻는다.
  const [asked, setAsked] = useState<{
    path: string
    recipe: string
    conditions: DoePreview['conditions']
  } | null>(null)
  const [busy, setBusy] = useState(false)
  // **폴더를 읽는 중과 작업을 만드는 중은 다르다** — 같은 글자를 띄우면 탐색만 해도 「생성
  // 중」 으로 보인다.
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const workspace = user?.home_workspace_slug ?? user?.memberships[0]?.slug ?? null
  const cadMaterials = preview?.materials ?? []
  const suggestedModes = preview?.suggested_modes ?? null
  const suggestedRecipe = isRecipe(preview?.suggested_recipe) ? preview.suggested_recipe : null
  const suggestedSize = preview?.suggested_element_size_mm ?? null
  const suggestedOrder = isOrder(preview?.suggested_order) ? preview.suggested_order : null
  const usable = (preview?.points ?? []).filter((one) => one.usable).map((one) => one.number)
  const chosen = picked ?? new Set(usable)
  const conditions =
    asked && asked.path === preview?.path && asked.recipe === recipe
      ? asked.conditions
      : (preview?.conditions ?? null)
  const hasCadConditions = (conditions?.lines ?? []).length > 0
  // **CalculiX 는 요소 크기 없이 돌지 않는다**(gmsh 가 제 나름으로 잡으면 같은 형상이 실행마다
  // 다른 메시가 된다). 미리 막는다 — 안 막으면 설계점 수만큼 메시 실패가 쌓인다.
  const needsSize = solver === 'calculix' && !elementSize.trim() && suggestedSize === null
  const input = {
    recipe,
    solver,
    conditionsFrom: 'cad' as const,
    elementSize,
    order,
    modes,
    constraints: region.trim() ? [region.trim()] : [],
    largeDeflection,
    harmonic,
  }
  const problem = preview ? specProblem(input) : null

  // **CAD 가 적은 모드 수를 미리 채운다** — 조용히 쓰면 그쪽 기본값이 우리 것을 말없이
  // 덮는다. 채워 두고 사람이 고치게 한다.
  useEffect(() => {
    if (suggestedModes) setModes(String(suggestedModes))
  }, [suggestedModes])
  // 요소 차수도 같다 — CAD 가 「전체」 에 적었으면 채워 둔다.
  useEffect(() => {
    if (suggestedOrder) setOrder(suggestedOrder)
  }, [suggestedOrder])

  // **CAD 가 적은 해석 종류를 미리 고른다.** 안 적었으면 모달이다.
  useEffect(() => {
    setRecipe(suggestedRecipe ?? 'modal')
  }, [suggestedRecipe])

  // 해석 종류를 바꾸면 첫 점의 조건을 그 종류로 다시 편다(모달이면 하중을 넘긴다).
  const previewPath = preview?.path
  useEffect(() => {
    if (!previewPath) return
    let disposed = false
    simulationApi
      .previewDoe(previewPath, recipe)
      .then((next) => {
        if (!disposed)
          setAsked({ path: previewPath, recipe, conditions: next.conditions ?? null })
      })
      .catch(() => {})
    return () => {
      disposed = true
    }
  }, [previewPath, recipe])

  // 창을 열면 첫 뿌리부터 보여 준다 — 사람이 아무것도 안 쳐도 고를 것이 있어야 한다.
  useEffect(() => {
    if (!open) return
    setPreview(null)
    setError(null)
    void browse()
    // 창이 열릴 때 한 번. 그 뒤로는 사람이 폴더를 누를 때만 움직인다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  async function browse(path?: string) {
    setBusy(true)
    setError(null)
    try {
      const next = await simulationApi.browseDoe(path)
      setListing(next)
      // **DOE 폴더로 들어갔으면 곧바로 훑어 본다** — 한 번 더 누르게 하지 않는다.
      setPreview(next.is_study ? await simulationApi.previewDoe(next.path) : null)
      setPicked(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('폴더를 읽지 못했습니다.'))
    } finally {
      setBusy(false)
    }
  }

  async function run() {
    if (!preview) return
    setBusy(true)
    setCreating(true)
    setError(null)
    try {
      const result = await simulationApi.importDoe({
        path: preview.path,
        workspace_slug: workspace,
        // **모든 점에 같은 스펙을 쓴다** — 그래야 결과를 견줄 수 있다(그러려고 DOE 를 돌린다).
        spec: buildSpec(input),
        // 다 고른 것이면 보내지 않는다 — 서버가 「걸 수 있는 전부」 로 받는다.
        numbers: chosen.size < usable.length ? [...chosen].sort((a, b) => a - b) : null,
      })
      onImported(result)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('가져오지 못했습니다.'))
    } finally {
      setBusy(false)
      setCreating(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>DOE 가져오기</DialogTitle>
          <DialogDescription>
            CAD 플랫폼이 내보낸 폴더를 읽어 설계점마다 해석 작업을 만듭니다. <b>공용 폴더</b>
            아래만 보입니다(관리자가 <span className="font-mono">DOE_ROOTS</span> 로 정합니다).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 탐색기 — 뿌리 아래를 눌러 들어간다. CAD 폴더는 표시가 다르다. */}
          <FolderBrowser listing={listing} busy={busy} onBrowse={(path) => void browse(path)} />

          <ErrorNotice error={error} />

          {preview && (
            <>
              <div className="rounded-md border p-3 text-sm">
                <p className="font-medium">{preview.name}</p>
                <p className="text-muted-foreground text-xs">
                  변수 {preview.factors.join(' · ') || '없음'}
                  {preview.method ? ` · ${preview.method}` : ''}
                  {preview.seed != null ? ` · 시드 ${preview.seed}` : ''}
                </p>
                <p className="mt-1">
                  실행할 수 있는 점 <b>{preview.usable}</b>개
                  {preview.skipped > 0 && (
                    <span className="text-amber-700 dark:text-amber-400">
                      {' '}
                      · 건너뜀 {preview.skipped}개
                    </span>
                  )}
                </p>
              </div>

              <div className="max-h-56 overflow-y-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-8">
                        <input
                          type="checkbox"
                          aria-label="설계점 전체 선택"
                          checked={usable.length > 0 && chosen.size === usable.length}
                          onChange={(event) =>
                            setPicked(event.target.checked ? null : new Set())
                          }
                        />
                      </TableHead>
                      <TableHead>점</TableHead>
                      {preview.factors.map((one) => (
                        <TableHead key={one}>{one}</TableHead>
                      ))}
                      <TableHead>상태</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.points.map((point) => (
                      <TableRow key={point.number}>
                        <TableCell>
                          <input
                            type="checkbox"
                            aria-label={`p${String(point.number).padStart(4, '0')} 선택`}
                            disabled={!point.usable}
                            checked={chosen.has(point.number)}
                            onChange={(event) => {
                              const next = new Set(chosen)
                              if (event.target.checked) next.add(point.number)
                              else next.delete(point.number)
                              setPicked(next)
                            }}
                          />
                        </TableCell>
                        <TableCell className="font-mono">
                          p{String(point.number).padStart(4, '0')}
                        </TableCell>
                        {preview.factors.map((one) => (
                          <TableCell key={one} className="font-mono">
                            {point.params[one] ?? '—'}
                          </TableCell>
                        ))}
                        <TableCell>
                          {point.usable ? (
                            <span className="text-muted-foreground">실행 가능</span>
                          ) : (
                            // **왜 못 거는지 그대로 보여 준다** — 「절반이 실패」 를 로그에서
                            // 찾게 하지 않는다.
                            <span className="text-amber-700 dark:text-amber-400">
                              {point.skip_reason}
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

{conditions && conditions.lines.length > 0 && (
                // **첫 점의 조건이 고른 해석 종류에서 어떻게 다뤄지나** — 서버가 판정한 그대로.
                <ConditionList conditions={conditions} />
              )}

              <fieldset className="space-y-3 rounded-md border p-3">
                <legend className="px-1 text-sm font-medium">모든 점에 같은 조건</legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  <RecipeSelect
                    id="doe-recipe"
                    value={recipe}
                    onChange={setRecipe}
                    suggested={suggestedRecipe}
                  />
                  <SolverSelect id="doe-solver" value={solver} onChange={setSolver} />
                </div>

                {recipe !== 'static' && (
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="doe-modes">모드 수</Label>
                      <Input
                        id="doe-modes"
                        type="number"
                        min={1}
                        value={modes}
                        onChange={(event) => setModes(event.target.value)}
                      />
                      {suggestedModes !== null && (
                        <p className="text-muted-foreground text-xs">
                          CAD 가 적은 값 {suggestedModes}
                        </p>
                      )}
                    </div>
                  </div>
                )}
                {recipe === 'static' && (
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={largeDeflection}
                      onChange={(event) => setLargeDeflection(event.target.checked)}
                    />
                    <span>
                      <span className="font-medium">큰 변형</span>
                      <span className="text-muted-foreground block text-xs">
                        변형이 커서 모양이 바뀌면 켭니다 — 비선형이라 느립니다.
                      </span>
                    </span>
                  </label>
                )}
                {recipe === 'harmonic' && (
                  <HarmonicFields
                    idPrefix="doe-harmonic"
                    value={harmonic}
                    onChange={setHarmonic}
                    fromCad={suggestedRecipe === 'harmonic'}
                  />
                )}

                <MeshFields
                  idPrefix="doe"
                  size={elementSize}
                  onSize={setElementSize}
                  order={order}
                  onOrder={setOrder}
                  cadSize={suggestedSize}
                  needsSize={needsSize}
                />

                {/* **물성은 CompCore 가 파트마다 정한다** — 재료를 훑는 DOE 는 점마다 다르다. */}
                {cadMaterials.length > 0 ? (
                  <p className="text-sm">
                    <span className="font-medium">물성</span>{' '}
                    <span>{cadMaterials.join(' · ')}</span>
                    <span className="text-muted-foreground block text-xs">
                      설계점마다 CompCore 가 파트에 지정한 재료로 실행합니다. 재료가 빠진 설계점은
                      가져오지 않고 까닭을 표시합니다.
                    </span>
                  </p>
                ) : (
                  <p className="text-xs text-amber-700 dark:text-amber-400">
                    이 폴더는 물성을 보내지 않았습니다 — 실행할 수 없습니다. CompCore 에서 재료를 지정한
                    뒤 다시 내보내세요.
                  </p>
                )}

                <div className="space-y-1.5">
                  <Label htmlFor="doe-region">구속 영역</Label>
                  <Input
                    id="doe-region"
                    value={region}
                    onChange={(event) => setRegion(event.target.value)}
                    placeholder="비우면 자유-자유"
                    className="font-mono"
                  />
                  <p className="text-muted-foreground text-xs">
                    {hasCadConditions
                      ? 'CAD 가 보낸 구속이 있으면 그것이 먼저입니다 — 이 칸은 구속이 없는 점에만 사용합니다.'
                      : '이 영역을 완전 고정합니다. 점 파일에 그 이름의 영역이 있어야 합니다.'}
                  </p>
                </div>
              </fieldset>

              {problem && <p className="text-xs text-amber-700 dark:text-amber-400">{problem}</p>}
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            취소
          </Button>
          <Button
            onClick={run}
            disabled={
              !preview ||
              chosen.size === 0 ||
              busy ||
              needsSize ||
              problem !== null ||
              cadMaterials.length === 0
            }
          >
            {creating ? '생성 중…' : `${preview ? chosen.size : 0}건 실행`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
