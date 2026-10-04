/**
 * 새 해석 작업 — **CAD 폴더의 설계점 하나**(기본) 또는 직접 올린 STEP · 점 파일.
 *
 * ## CAD 폴더에서 선택(기본)
 *
 * CompCore 는 설계 하나도 DOE 와 같은 폴더로 내보낸다(v0.9.0 「해석용으로 내보내기」 — 인자
 * 0개). 그래서 이 창도 DOE 창과 같은 탐색기로 폴더를 열고 설계점 하나를 고른다 — STEP · 점
 * 파일 · 중간면이 **폴더에서 짝이 맞게 따라온다.** 파일 셋을 손으로 고르면 p0001.step 에
 * p0002.json 을 섞어도 올리는 자리에서는 모른다. 작업은 DOE 가져오기와 같은 길(`doe/import` 의
 * `numbers`)로 만든다.
 *
 * ## 파일 직접 업로드
 *
 * 공용 폴더(`DOE_ROOTS`)에 없는 파일용이다 — 서버는 그 폴더 아래만 볼 수 있다.
 *
 * 점 파일에는 영역 지문(형상의 어느 면이 무엇인가)과 함께 **CAD 가 정한 해석 조건** — 구속 ·
 * 접촉 · 하중 · 물성 · 메시 힌트 · 해석 설정 — 이 들어 있다. 서버는 그 파일을 받으면 **CAD 가
 * 보낸 것을 먼저** 쓴다(DOE 가져오기와 같은 코드). 그래서 이 창은 그 파일을 올리는 즉시 **서버가
 * 읽은 결과**를 보여 준다(`/simulations/conditions/preview` — 작업은 만들지 않는다): 해석 종류 ·
 * 요소 크기 · 조건마다 반영 · 넘김 · 막음, 그리고 **파트마다 붙을 재료.**
 *
 * **물성은 CompCore 가 파트마다 정한다** — 이 창은 물성을 받지 않고 「파트 → 재료」 표만 보인다.
 * 전에는 물성 칸이 있었지만, 한 벌을 STEP 의 모든 파트에 붙이는 것은 조립품에서 뜻이 없고
 * 결과가 CompCore 의 정의로 거슬러 올라가지 않는다. 그래서 **점 파일이 있어야 실행한다**:
 * 물성이 없는 점 파일이나 재료가 빠진 파트가 있으면 실행을 막는다(모델링이 그 자리에서 멈춘다).
 */

import { useEffect, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type {
  CadBody,
  CadMaterial,
  ConditionsPreview,
  DoeListing,
  DoePreview,
  Simulation,
} from '@/modules/simulations/api'
import { ConditionList } from '@/modules/simulations/ConditionList'
import { FolderBrowser } from '@/modules/simulations/FolderBrowser'
import { buildSpec, HARMONIC_DEFAULTS, isOrder, isRecipe, specProblem } from '@/modules/simulations/spec'
import type { HarmonicInput, MeshOrder, RecipeName } from '@/modules/simulations/spec'
import { HarmonicFields, MeshFields, RecipeSelect } from '@/modules/simulations/SpecFields'
import { SolverSelect } from '@/modules/simulations/SolverSelect'
import type { Solver } from '@/modules/simulations/SolverSelect'
import { ApiError } from '@/shared/api/client'
import { useAuth } from '@/shared/auth/AuthContext'
import { isSystemAdmin } from '@/shared/auth/roles'
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'

/** 전역(부서 없음)을 뜻하는 Select 값. 빈 문자열은 Select 가 못 받는다. */
const GLOBAL = '__global__'

/** 어디서 가져오나 — CAD 폴더(기본) · 파일 직접 업로드. */
type Source = 'folder' | 'upload'

function pointName(number: number): string {
  return `p${String(number).padStart(4, '0')}`
}

interface Props {
  open: boolean
  onClose: () => void
  onCreated: (simulation: Simulation) => void
}

export function NewSimulationDialog({ open, onClose, onCreated }: Props) {
  const { user } = useAuth()
  const admin = isSystemAdmin(user)
  const memberships = user?.memberships ?? []

  const [source, setSource] = useState<Source>('folder')
  // CAD 폴더 — 지금 보는 폴더, 고른 CAD 폴더(DOE · 설계 하나), 고른 설계점.
  const [listing, setListing] = useState<DoeListing | null>(null)
  const [folder, setFolder] = useState<DoePreview | null>(null)
  const [number, setNumber] = useState<number | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [pointFile, setPointFile] = useState<File | null>(null)
  // **쉘 파트가 있으면 중간면 형상도** — CAD 가 점마다 pNNNN_mid.step 으로 낸다.
  const [midFile, setMidFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ConditionsPreview | null>(null)
  const [name, setName] = useState('')
  const [workspace, setWorkspace] = useState<string>(
    user?.home_workspace_slug ?? memberships[0]?.slug ?? GLOBAL,
  )
  const [recipe, setRecipe] = useState<RecipeName>('modal')
  const [solver, setSolver] = useState<Solver>('ansys')
  const [modes, setModes] = useState('10')
  const [largeDeflection, setLargeDeflection] = useState(false)
  const [harmonic, setHarmonic] = useState<HarmonicInput>(HARMONIC_DEFAULTS)
  const [elementSize, setElementSize] = useState('')
  const [order, setOrder] = useState<MeshOrder>('quadratic')
  // **CAD 가 보낸 조건이 먼저다** — 끄면 이 창에서 고른 영역만 완전 고정한다(conditions_from).
  const [conditionsFromCad, setConditionsFromCad] = useState(true)
  const [regions, setRegions] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | Error | null>(null)

  const cadMaterials = preview?.materials ?? []
  const bodies = preview?.bodies ?? []
  const lines = preview?.conditions.lines ?? []
  const hasCadConditions = lines.length > 0
  const useCadConditions = hasCadConditions && conditionsFromCad
  // **재료가 빠진 파트** — 서버가 거절하고, 걸어도 모델링이 멈춘다. 어느 파트를 무엇으로
  // 볼지는 CompCore 가 정한다.
  // 해석에서 뺀 파트는 물성이 없어도 된다(메시에도 안 나온다).
  const bare = bodies.filter((one) => !one.material && !one.suppressed)
  const shellParts = bodies.filter((one) => one.shell)
  // 폴더에서 고르면 중간면이 폴더에서 따라온다 — 올릴 때만 따로 받는다.
  const needsMid = source === 'upload' && shellParts.length > 0 && midFile === null
  const hasMaterials = cadMaterials.length > 0 && bare.length === 0
  const faceRegions = (preview?.regions ?? []).filter((one) => one.kind === 'face')
  const probes = (preview?.regions ?? []).filter((one) => one.kind === 'point')
  const cadSize = preview?.suggested_element_size_mm ?? null
  const suggested = preview ? (isRecipe(preview.suggested_recipe) ? preview.suggested_recipe : null) : undefined
  // **정적 · 조화는 하중이 CAD 조건에서 온다** — 스펙에는 하중 칸이 없다.
  const hasLoads = useCadConditions && lines.some((one) => one.kind === 'load' && one.status === 'applied')
  const needsSize = solver === 'calculix' && !elementSize.trim() && cadSize === null

  const input = {
    recipe,
    solver,
    conditionsFrom: useCadConditions ? ('cad' as const) : ('spec' as const),
    elementSize,
    order,
    modes,
    constraints: useCadConditions ? [] : regions,
    largeDeflection,
    harmonic,
  }
  const problem = specProblem(input)
  const picked = source === 'folder' ? folder !== null && number !== null : file !== null
  const ready =
    picked && preview !== null && hasMaterials && !needsMid && !busy && problem === null && !needsSize

  async function read(next: File, asked?: RecipeName): Promise<ConditionsPreview | null> {
    try {
      return await simulationApi.previewConditions(next, asked)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('CAD 점 파일을 읽지 못했습니다.'))
      return null
    }
  }

  async function readPoint(
    path: string,
    point: number,
    asked?: RecipeName,
  ): Promise<ConditionsPreview | null> {
    try {
      return await simulationApi.previewDoePoint(path, point, asked)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('설계점을 읽지 못했습니다.'))
      return null
    }
  }

  /** 서버가 읽은 점 — **CAD 가 적은 것을 미리 채운다**(조용히 쓰면 그쪽 값이 우리 것을 덮는다). */
  function adopt(found: ConditionsPreview) {
    setPreview(found)
    if (isRecipe(found.suggested_recipe)) setRecipe(found.suggested_recipe)
    if (found.suggested_modes) setModes(String(found.suggested_modes))
    if (isOrder(found.suggested_order)) setOrder(found.suggested_order)
    setConditionsFromCad(true)
  }

  async function pickPoint(next: File | null) {
    setPointFile(next)
    setPreview(null)
    setRegions([])
    setError(null)
    if (!next) return
    const found = await read(next)
    if (!found) {
      setPointFile(null)
      return
    }
    adopt(found)
  }

  async function choosePoint(path: string, next: number) {
    setNumber(next)
    setPreview(null)
    setRegions([])
    setError(null)
    const found = await readPoint(path, next)
    if (found) adopt(found)
  }

  async function browse(path?: string) {
    setBusy(true)
    setError(null)
    try {
      const next = await simulationApi.browseDoe(path)
      setListing(next)
      setFolder(null)
      setNumber(null)
      setPreview(null)
      if (next.is_study) {
        // **CAD 폴더로 들어갔으면 곧바로 첫 설계점을 읽는다** — 설계 하나면 그것뿐이다.
        const study = await simulationApi.previewDoe(next.path)
        setFolder(study)
        const first = study.points.find((one) => one.usable)
        if (first) await choosePoint(study.path, first.number)
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('폴더를 읽지 못했습니다.'))
    } finally {
      setBusy(false)
    }
  }

  // 창을 열면 첫 뿌리부터 보여 준다 — 사람이 아무것도 안 쳐도 고를 것이 있어야 한다.
  useEffect(() => {
    if (open && source === 'folder' && listing === null) void browse()
    // 창이 열릴 때 · 폴더 쪽으로 돌아올 때 한 번.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, source])

  function switchSource(next: Source) {
    if (next === source) return
    setSource(next)
    setPreview(null)
    setRegions([])
    setError(null)
  }

  async function changeRecipe(next: RecipeName) {
    setRecipe(next)
    // 조건이 어떻게 다뤄지나는 해석 종류에 달렸다(모달이면 하중을 넘긴다) — 다시 묻는다.
    if (source === 'folder' && folder && number !== null) {
      const found = await readPoint(folder.path, number, next)
      if (found) setPreview(found)
    } else if (pointFile) {
      const found = await read(pointFile, next)
      if (found) setPreview(found)
    }
  }

  async function submitFolder() {
    if (!folder || number === null) return
    const result = await simulationApi.importDoe({
      path: folder.path,
      spec: buildSpec(input),
      workspace_slug: workspace === GLOBAL ? null : workspace,
      numbers: [number],
      name: name.trim() || null,
    })
    const made = result.created[0]
    if (!made) {
      // **걸지 못한 까닭을 그대로 보인다**(이미 가져온 점 · 물성이 빠진 점 …).
      throw new Error(result.skipped[0]?.skip_reason || '작업을 만들지 못했습니다.')
    }
    onCreated(await simulationApi.get(made))
  }

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      if (source === 'folder') {
        await submitFolder()
        return
      }
      if (!file) return
      const created = await simulationApi.create({
        file,
        topology: pointFile,
        midsurface: shellParts.length > 0 ? midFile : null,
        name: name.trim() || undefined,
        workspaceSlug: workspace === GLOBAL ? null : workspace,
        spec: buildSpec(input),
      })
      onCreated(created)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('알 수 없는 오류'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>새 해석 작업</DialogTitle>
          <DialogDescription>
            CompCore 가 내보낸 폴더에서 설계점 하나를 선택해 해석 작업을 실행합니다. 물성 · 조건 · 해석
            설정은 그 설계점의 점 파일에서 옵니다. 설계점 여러 개는 「DOE 가져오기」 를 사용합니다.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="flex gap-1" role="tablist" aria-label="가져올 곳">
            <Button
              role="tab"
              aria-selected={source === 'folder'}
              variant={source === 'folder' ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => switchSource('folder')}
            >
              CAD 폴더에서 선택
            </Button>
            <Button
              role="tab"
              aria-selected={source === 'upload'}
              variant={source === 'upload' ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => switchSource('upload')}
            >
              파일 직접 업로드
            </Button>
          </div>

          {source === 'folder' && (
            <div className="space-y-3">
              <FolderBrowser
                listing={listing}
                busy={busy}
                onBrowse={(path) => void browse(path)}
                badge="CAD"
                studyNote="이 폴더가 CAD 폴더입니다. 아래에서 설계점을 확인하세요."
              />
              {folder && (
                <div className="space-y-2 rounded-md border p-3 text-sm">
                  <p>
                    <span className="font-medium">{folder.name}</span>{' '}
                    <span className="text-muted-foreground text-xs">
                      {folder.single ? '설계 하나' : `설계점 ${folder.points.length}개 · 변수 ${folder.factors.join(' · ')}`}
                    </span>
                  </p>
                  {!folder.single && (
                    <div className="max-h-40 space-y-1 overflow-y-auto" role="radiogroup" aria-label="설계점">
                      {folder.points.map((point) => (
                        <label key={point.number} className="flex items-center gap-2 text-sm">
                          <input
                            type="radio"
                            name="design-point"
                            checked={number === point.number}
                            disabled={!point.usable || busy}
                            onChange={() => void choosePoint(folder.path, point.number)}
                          />
                          <span className="font-mono">{pointName(point.number)}</span>
                          <span className="text-muted-foreground text-xs">
                            {Object.entries(point.params)
                              .map(([key, value]) => `${key} ${value}`)
                              .join(' · ')}
                            {!point.usable && ` — ${point.skip_reason}`}
                          </span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {source === 'upload' && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="sim-file">형상 파일 (STEP)</Label>
              <Input
                id="sim-file"
                type="file"
                accept=".step,.stp,.x_t,.xt"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sim-point">CAD 점 파일 (pNNNN.json)</Label>
              <Input
                id="sim-point"
                type="file"
                accept=".json,application/json"
                onChange={(event) => void pickPoint(event.target.files?.[0] ?? null)}
              />
            </div>
          </div>

          )}

          {source === 'upload' && shellParts.length > 0 && (
            <div className="space-y-1.5">
              <Label htmlFor="sim-mid">중간면 형상 (pNNNN_mid.step)</Label>
              <Input
                id="sim-mid"
                type="file"
                accept=".step,.stp"
                onChange={(event) => setMidFile(event.target.files?.[0] ?? null)}
              />
              <p className={needsMid ? 'text-xs text-amber-700 dark:text-amber-400' : 'text-muted-foreground text-xs'}>
                쉘 파트({shellParts.map((one) => one.name).join(' · ')})는 중간면과 두께로 풉니다 — CAD 가 점
                파일과 함께 낸 중간면 형상을 올려야 실행합니다.
              </p>
            </div>
          )}

          {source === 'upload' && !pointFile && (
            <p className="text-muted-foreground text-xs">
              CAD 점 파일이 있어야 실행합니다 — 파트마다 재료 · 조건 · 해석 설정이 그 파일에서 옵니다. 공용
              폴더에 있는 파일이면 「CAD 폴더에서 선택」 이 짝을 맞춰 줍니다.
            </p>
          )}

          {preview && (
            <div className="space-y-2 rounded-md border p-3 text-sm">
              <p>
                파트 <b>{bodies.length}</b>
                {bodies.length > 1 && (
                  <span className="text-muted-foreground"> ({bodies.map((one) => one.name).join(' · ')})</span>
                )}{' '}
                · 영역 <b>{preview.regions.length}</b>
                {probes.length > 0 && (
                  <>
                    {' '}
                    · 측정점 <b>{probes.length}</b>
                    <span className="text-muted-foreground"> ({probes.map((one) => one.name).join(' · ')})</span>
                  </>
                )}
                {cadSize !== null && <> · 요소 크기 {cadSize} mm</>}
              </p>
              {(preview.unresolved ?? []).length > 0 && (
                // **CAD 가 못 푼 이름을 감추지 않는다.** 그 이름으로는 형상에 자리가 없다.
                <p className="text-xs text-amber-700 dark:text-amber-400">
                  CAD 가 풀지 못한 영역: {(preview.unresolved ?? []).join(' · ')}
                </p>
              )}
              <ConditionList conditions={preview.conditions} />
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sim-name">이름</Label>
              <Input
                id="sim-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={
                  source === 'folder'
                    ? folder
                      ? folder.single
                        ? folder.name
                        : `${folder.name} ${pointName(number ?? 1)}`
                      : '비우면 폴더 이름'
                    : (file?.name ?? '비우면 파일 이름')
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label>부서</Label>
              <Select value={workspace} onValueChange={setWorkspace}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {memberships.map((one) => (
                    <SelectItem key={one.slug} value={one.slug}>
                      {one.name}
                    </SelectItem>
                  ))}
                  {/* 전역은 여러 부서가 함께 보는 자리 — 시스템 관리자만 만든다. */}
                  {admin && <SelectItem value={GLOBAL}>전역(부서 없음)</SelectItem>}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <RecipeSelect id="sim-recipe" value={recipe} onChange={(next) => void changeRecipe(next)} suggested={suggested} />
            <SolverSelect id="sim-solver" value={solver} onChange={setSolver} />
          </div>

          {recipe !== 'modal' && !hasLoads && (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              {RECIPE_HINT[recipe]} 하중은 CAD 점 파일의 조건에서 옵니다 — 하중이 반영되지 않으면 모델링
              단계에서 멈춥니다.
            </p>
          )}

          {recipe === 'modal' && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="sim-modes">탄성 모드 수</Label>
                <Input
                  id="sim-modes"
                  type="number"
                  min={1}
                  max={100}
                  value={modes}
                  onChange={(event) => setModes(event.target.value)}
                />
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
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="sim-harmonic-modes">모드 중첩에 쓸 모드 수</Label>
                  <Input
                    id="sim-harmonic-modes"
                    type="number"
                    min={1}
                    max={100}
                    value={modes}
                    onChange={(event) => setModes(event.target.value)}
                  />
                </div>
              </div>
              <HarmonicFields
                idPrefix="sim-harmonic"
                value={harmonic}
                onChange={setHarmonic}
                fromCad={preview?.suggested_recipe === 'harmonic'}
              />
            </div>
          )}

          <MeshFields
            idPrefix="sim"
            size={elementSize}
            onSize={setElementSize}
            order={order}
            onOrder={setOrder}
            cadSize={cadSize}
            needsSize={needsSize}
          />

          {preview && (
            <fieldset className="space-y-3 rounded-md border p-3">
              <legend className="px-1 text-sm font-medium">물성</legend>
              {cadMaterials.length > 0 ? (
                <>
                  <p className="text-muted-foreground text-xs">CompCore 가 파트마다 지정한 재료로 실행합니다.</p>
                  <CadMaterialTable bodies={bodies} materials={cadMaterials} />
                  {bare.length > 0 && (
                    <p className="text-xs text-amber-700 dark:text-amber-400">
                      재료가 지정되지 않은 파트가 있습니다: {bare.map((one) => one.name).join(' · ')} — 이대로는
                      실행할 수 없습니다. CompCore 에서 재료를 지정한 뒤 점 파일을 다시 내보내세요.
                    </p>
                  )}
                </>
              ) : (
                <p className="text-xs text-amber-700 dark:text-amber-400">
                  {preview.material_error
                    ? `CAD 가 보낸 물성을 읽지 못했습니다: ${preview.material_error} — CompCore 에서 재료를 확인한 뒤 점 파일을 다시 내보내세요.`
                    : '이 점 파일에는 물성이 없습니다 — 실행할 수 없습니다. CompCore 에서 재료를 지정한 뒤 점 파일을 다시 내보내세요.'}
                </p>
              )}
            </fieldset>
          )}

          {preview && (
            <fieldset className="space-y-3 rounded-md border p-3">
              <legend className="px-1 text-sm font-medium">구속 · 조건</legend>
              {hasCadConditions && (
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={useCadConditions}
                    onChange={(event) => setConditionsFromCad(event.target.checked)}
                  />
                  <span>
                    <span className="font-medium">CAD 가 보낸 조건 사용</span>
                    <span className="text-muted-foreground block text-xs">
                      위 목록의 구속 · 접촉 · 하중을 그대로 겁니다. 끄면 CAD 조건을 전부 버리고 아래에서
                      고른 영역만 완전 고정합니다.
                    </span>
                  </span>
                </label>
              )}
              {!useCadConditions &&
                (faceRegions.length === 0 ? (
                  <p className="text-muted-foreground text-xs">
                    고정할 수 있는 면 영역이 없습니다 — 구속 없는 자유-자유로 실행합니다.
                  </p>
                ) : (
                  <div className="space-y-1">
                    {faceRegions.map((one) => (
                      <label key={one.name} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={regions.includes(one.name)}
                          onChange={(event) =>
                            setRegions((current) =>
                              event.target.checked
                                ? [...current, one.name]
                                : current.filter((region) => region !== one.name),
                            )
                          }
                        />
                        <span className="font-mono">{one.name}</span>
                        <span className="text-muted-foreground text-xs">면 {one.count}장 · 완전 고정</span>
                      </label>
                    ))}
                  </div>
                ))}
            </fieldset>
          )}

          {problem && file && <p className="text-xs text-amber-700 dark:text-amber-400">{problem}</p>}
          <ErrorNotice error={error} />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            취소
          </Button>
          <Button onClick={submit} disabled={!ready}>
            {busy ? '업로드 중…' : '실행'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** 파트마다 붙을 재료 — 서버가 모델링과 같은 규칙으로 짝지은 것이다. */
function CadMaterialTable({ bodies, materials }: { bodies: CadBody[]; materials: CadMaterial[] }) {
  const byName = new Map(materials.map((one) => [one.name, one]))
  // 점 파일에 파트 목록이 없으면(옛 내보내기) 재료가 가리키는 이름을 그대로 보인다.
  const rows =
    bodies.length > 0
      ? bodies.map((body) => ({
          part: body.name,
          material: body.material ? (byName.get(body.material) ?? null) : null,
          suppressed: body.suppressed ?? false,
          setting: body.setting ?? '',
        }))
      : materials.map((one) => ({
          part: one.bodies.length > 0 ? one.bodies.join(' · ') : '전체',
          material: one,
          suppressed: false,
          setting: '',
        }))
  const anySetting = rows.some((row) => row.setting)
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-muted-foreground text-left text-xs">
          <th className="py-1 font-normal">파트</th>
          <th className="py-1 font-normal">재료</th>
          <th className="py-1 text-right font-normal">E (GPa)</th>
          <th className="py-1 text-right font-normal">ν</th>
          <th className="py-1 text-right font-normal">ρ (kg/m³)</th>
          {anySetting && <th className="py-1 pl-3 font-normal">파트 설정</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.part} className="border-t">
            <td className="py-1">{row.part}</td>
            {row.suppressed ? (
              // 뺀 파트는 물성을 보지 않는다 — 「재료 없음」 으로 보이면 고칠 것처럼 읽힌다.
              <td colSpan={4} className="text-muted-foreground py-1">
                해석에서 제외
              </td>
            ) : row.material ? (
              <>
                <td className="py-1">{row.material.name}</td>
                <td className="py-1 text-right tabular-nums">{shown(row.material.youngs_modulus_gpa)}</td>
                <td className="py-1 text-right tabular-nums">{shown(row.material.poisson_ratio)}</td>
                <td className="py-1 text-right tabular-nums">{shown(row.material.density_kg_m3)}</td>
              </>
            ) : (
              <td colSpan={4} className="py-1 text-amber-700 dark:text-amber-400">
                재료 없음
              </td>
            )}
            {anySetting && <td className="text-muted-foreground py-1 pl-3 text-xs">{row.setting}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** 유효숫자 넷 — 환산한 값의 끝자리(206.00000001)를 감춘다. */
function shown(value: number): string {
  return Number(value.toPrecision(4)).toLocaleString('ko-KR')
}

const RECIPE_HINT: Record<string, string> = {
  static: '정적 해석은 하중이 답을 만듭니다.',
  harmonic: '조화 응답은 가진력이 있어야 흔들립니다.',
}
