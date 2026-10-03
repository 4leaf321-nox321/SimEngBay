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
 * 변수의 효과로 읽힌다.
 */

type Recipe = 'modal' | 'static' | 'harmonic'

const RECIPES: Recipe[] = ['modal', 'static', 'harmonic']

function isRecipe(value: string | null | undefined): value is Recipe {
  return RECIPES.includes(value as Recipe)
}

import { useEffect, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type { DoeImport, DoeListing, DoePreview } from '@/modules/simulations/api'
import { RECIPE_LABELS } from '@/modules/simulations/labels'
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
import { Folder, FolderOpen, ChevronUp } from 'lucide-react'
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
  const [material, setMaterial] = useState('SS400')
  // **CAD 가 보낸 물성이 먼저다.** 끄면 아래 칸의 값으로 모든 점을 돌린다 — 재료를 훑는 DOE
  // 에서는 그러면 이름만 다른 결과가 나온다(그 사실을 화면이 말해 준다).
  const [fromCad, setFromCad] = useState(true)
  const [modes, setModes] = useState('10')
  const [region, setRegion] = useState('bolt_holes')
  const [recipe, setRecipe] = useState<Recipe>('modal')
  const [solver, setSolver] = useState<Solver>('ansys')
  // 비워 두면 **점마다 CAD 의 「전체」 크기**로 돈다 — 미리 채우면 그 값이 모든 점을 덮는다.
  const [elementSize, setElementSize] = useState('')
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
  // **CalculiX 는 요소 크기 없이 돌지 않는다**(gmsh 가 제 나름으로 잡으면 같은 형상이 실행마다
  // 다른 메시가 된다). 미리 막는다 — 안 막으면 설계점 수만큼 메시 실패가 쌓인다.
  const needsSize = solver === 'calculix' && !elementSize.trim() && suggestedSize === null

  // **CAD 가 적은 모드 수를 미리 채운다** — 조용히 쓰면 그쪽 기본값이 우리 것을 말없이
  // 덮는다. 채워 두고 사람이 고치게 한다.
  useEffect(() => {
    if (suggestedModes) setModes(String(suggestedModes))
  }, [suggestedModes])

  // **CAD 가 적은 해석 종류를 미리 고른다.** 안 적었으면 모달이다.
  useEffect(() => {
    setRecipe(suggestedRecipe ?? 'modal')
  }, [suggestedRecipe])

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
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('폴더를 읽지 못했습니다.'))
    } finally {
      setBusy(false)
    }
  }

  /** **모든 점에 같은 스펙을 쓴다** — 그래야 결과를 견줄 수 있다(그러려고 DOE 를 돌린다). */
  function specOf(): Record<string, unknown> {
    const spec: Record<string, unknown> = {
      recipe,
      solver,
      material: {
        name: material.trim(),
        youngs_modulus_gpa: 200,
        poisson_ratio: 0.3,
        density_kg_m3: 7850,
      },
      material_from: fromCad ? 'cad' : 'spec',
      mesh: elementSize.trim() ? { element_size_mm: Number(elementSize) } : {},
      constraints: region.trim() ? [{ region: region.trim(), kind: 'fixed' }] : [],
    }
    // **정적에는 모드 수 칸이 없다** — 스펙이 모르는 칸은 서버가 통째로 거절한다.
    if (recipe !== 'static') spec.modes = Number(modes)
    return spec
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
        spec: specOf(),
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
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>DOE 가져오기</DialogTitle>
          <DialogDescription>
            CAD 플랫폼이 내보낸 폴더를 읽어 설계점마다 해석 작업을 만듭니다. <b>공용 폴더</b>
            아래만 보입니다(관리자가 <span className="font-mono">DOE_ROOTS</span> 로 정합니다).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 탐색기 — 뿌리 아래를 눌러 들어간다. 「고를 수 있는 폴더」 는 표시가 다르다. */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <Label>공용 폴더</Label>
              {(listing?.roots?.length ?? 0) > 1 && (
                <div className="flex gap-1">
                  {(listing?.roots ?? []).map((root) => (
                    <Button
                      key={root}
                      variant={listing?.path.startsWith(root) ? 'secondary' : 'ghost'}
                      size="sm"
                      onClick={() => void browse(root)}
                      className="font-mono text-xs"
                    >
                      {root}
                    </Button>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="icon"
                className="size-8 shrink-0"
                disabled={!listing?.parent || busy}
                onClick={() => listing?.parent && void browse(listing.parent)}
                aria-label="한 칸 위"
              >
                <ChevronUp className="size-4" />
              </Button>
              <p className="text-muted-foreground truncate font-mono text-xs" title={listing?.path}>
                {listing?.path ?? '…'}
              </p>
            </div>
            <div className="max-h-48 overflow-y-auto rounded-md border">
              {listing && listing.entries.length === 0 ? (
                <p className="text-muted-foreground p-3 text-sm">
                  {listing.is_study
                    ? '이 폴더가 DOE 입니다. 아래에서 확인하고 실행하세요.'
                    : '하위 폴더가 없습니다.'}
                </p>
              ) : (
                <ul className="divide-y">
                  {(listing?.entries ?? []).map((entry) => (
                    <li key={entry.path}>
                      <button
                        type="button"
                        onClick={() => void browse(entry.path)}
                        className="hover:bg-muted/50 flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm"
                      >
                        {entry.is_study ? (
                          <FolderOpen className="size-4 shrink-0 text-emerald-600" />
                        ) : (
                          <Folder className="text-muted-foreground size-4 shrink-0" />
                        )}
                        <span className="truncate">{entry.name}</span>
                        {/* **눌러 보고 알게 하지 않는다** — 가져올 수 있는 폴더를 미리 표시한다. */}
                        {entry.is_study && (
                          <span className="text-muted-foreground ml-auto text-xs">DOE</span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {listing?.truncated && (
              <p className="text-muted-foreground text-xs">
                폴더가 너무 많아 일부만 보여 줍니다. 하위 폴더로 들어가 좁히세요.
              </p>
            )}
          </div>

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

              <fieldset className="space-y-3 rounded-md border p-3">
                <legend className="px-1 text-sm font-medium">모든 점에 같은 조건</legend>
                {/* **물성은 점마다 다를 수 있다** — CAD 가 재료를 훑었으면 그 값으로 돈다. */}
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={fromCad}
                    disabled={cadMaterials.length === 0}
                    onChange={(event) => setFromCad(event.target.checked)}
                  />
                  <span>
                    <span className="font-medium">CAD 가 보낸 물성 쓰기</span>
                    <span className="text-muted-foreground block text-xs">
                      {cadMaterials.length > 0
                        ? `이 폴더가 함께 보낸 재료: ${cadMaterials.join(' · ')}`
                        : '이 폴더는 물성을 보내지 않았습니다 — 아래 값으로 돕니다.'}
                    </span>
                  </span>
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="doe-recipe">해석 종류</Label>
                    <select
                      id="doe-recipe"
                      className="border-input bg-background h-9 w-full rounded-md border px-3 text-sm"
                      value={recipe}
                      onChange={(event) => setRecipe(event.target.value as Recipe)}
                    >
                      {RECIPES.map((one) => (
                        <option key={one} value={one}>
                          {RECIPE_LABELS[one] ?? one}
                        </option>
                      ))}
                    </select>
                    {suggestedRecipe === null ? (
                      <p className="text-muted-foreground text-xs">
                        이 폴더는 해석 종류를 적지 않았습니다.
                      </p>
                    ) : suggestedRecipe === recipe ? (
                      <p className="text-muted-foreground text-xs">CAD 가 적은 해석입니다.</p>
                    ) : (
                      // **다르게 실행하는 것은 막지 않는다** — 다만 무엇이 빠지는지 말한다.
                      <p className="text-xs text-amber-700 dark:text-amber-400">
                        CAD 가 적은 해석: {RECIPE_LABELS[suggestedRecipe]} — CAD 의 하중 · 해석
                        설정 일부가 반영되지 않습니다.
                      </p>
                    )}
                  </div>
                  <SolverSelect id="doe-solver" value={solver} onChange={setSolver} />
                </div>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="doe-material">재료</Label>
                    <Input
                      id="doe-material"
                      value={material}
                      onChange={(event) => setMaterial(event.target.value)}
                      disabled={fromCad && cadMaterials.length > 0}
                    />
                  </div>
                  {recipe !== 'static' && (
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
                  )}
                  <div className="space-y-1.5">
                    <Label htmlFor="doe-element">요소 크기 (mm)</Label>
                    <Input
                      id="doe-element"
                      type="number"
                      step="any"
                      min={0}
                      value={elementSize}
                      onChange={(event) => setElementSize(event.target.value)}
                      placeholder={
                        suggestedSize !== null
                          ? `CAD 값 ${suggestedSize}`
                          : solver === 'calculix'
                            ? '필수'
                            : '비우면 자동'
                      }
                    />
                    {suggestedSize !== null && !elementSize.trim() && (
                      <p className="text-muted-foreground text-xs">
                        비우면 점마다 CAD 가 적은 크기를 사용합니다.
                      </p>
                    )}
                    {needsSize && (
                      <p className="text-xs text-amber-700 dark:text-amber-400">
                        CalculiX 는 요소 크기가 필요합니다 — 이 폴더는 「전체」 크기를 보내지
                        않았습니다.
                      </p>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="doe-region">구속 영역</Label>
                    <Input
                      id="doe-region"
                      value={region}
                      onChange={(event) => setRegion(event.target.value)}
                      placeholder="비우면 자유-자유"
                      className="font-mono"
                    />
                  </div>
                </div>
              </fieldset>
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            취소
          </Button>
          <Button onClick={run} disabled={!preview || preview.usable === 0 || busy || needsSize}>
            {creating ? '생성 중…' : `${preview?.usable ?? 0}건 실행`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
