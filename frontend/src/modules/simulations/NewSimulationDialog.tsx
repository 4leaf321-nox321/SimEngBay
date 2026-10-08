/**
 * 새 해석 작업 — **CAD 폴더의 설계점을 골라 작업을 만든다.** 설계 하나든 DOE 든 같은 창이다.
 *
 * ## 하나냐 여럿이냐는 체크 수일 뿐이다
 *
 * 전에는 「새 해석 작업」(설계점 하나)과 「DOE 가져오기」(여럿)가 따로 있었다. 둘은 같은 폴더를 같은
 * 탐색기로 고르고 같은 길(`doe/import` 의 `numbers`)로 작업을 만들었다 — 다른 것은 고르는 점의
 * 수뿐이었다. 그래서 합쳤다(2026-10-05).
 *
 * - 왼쪽: 폴더와 설계점. **체크는 실행할 점**(폴더를 고르면 걸 수 있는 점 전부), **행은 오른쪽에 볼
 *   점**이다. CompCore 의 「설계 하나」(인자 0개 폴더)는 그 하나가 체크된 채 열린다.
 * - 오른쪽: 보는 점을 **서버가 읽은 그대로**(`GET /simulations/doe/point`) — 해석 종류 · 요소 크기 ·
 *   조건마다 반영 · 넘김 · 막음, 파트마다 붙을 재료 — 와 체크한 점 모두에 같은 설정.
 * - 1건이면 이름을 받고 만든 작업의 상세로 간다. 여러 건이면 목록으로 돌아가 건너뛴 점을 말한다.
 *
 * ## 모든 점에 같은 스펙
 *
 * 설계점끼리 견주려고 DOE 를 돌린다 — 솔버 · 해석 종류가 섞이면 그 차이(몇 %)가 변수의 효과로
 * 읽힌다. 요소 크기를 비우면 **점마다 CAD 의 「전체」 크기**로 돈다 — 채우면 그 값이 모든 점을 덮는다.
 * 해석 종류 · 모드 수 · 차수는 CAD 가 적은 것을 미리 채운다(조용히 쓰면 그쪽 값이 우리 것을 덮는다).
 *
 * ## 물성은 CompCore 가 파트마다 정한다
 *
 * 이 창은 물성을 받지 않고 「파트 → 재료」 표만 보인다. 한 벌을 모든 파트에 붙이는 것은 조립품에서
 * 뜻이 없고 결과가 CompCore 의 정의로 거슬러 올라가지 않는다. 물성을 안 보낸 폴더나 점 파일은
 * 실행하지 않고, 재료가 빠진 점은 서버가 까닭을 달아 건너뛴다.
 *
 * ## 파일 직접 업로드
 *
 * 공용 폴더(`DOE_ROOTS`)에 없는 파일용이다 — 서버는 그 폴더 아래만 볼 수 있다. 형상(STEP)과 점 파일
 * (쉘 파트가 있으면 중간면까지)을 올리면 같은 미리보기(`/simulations/conditions/preview`)를 보인다.
 * 폴더에서 고르면 그 셋이 **짝이 맞게 따라온다** — 손으로 고르면 p0001.step 에 p0002.json 을 섞어도
 * 올리는 자리에서는 모른다.
 */

import { useEffect, useRef, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type {
  CadBody,
  CadMaterial,
  ConditionsPreview,
  DoeImport,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'

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
  /** 작업 하나를 만들었다 — 그 상세로 간다. */
  onCreated: (simulation: Simulation) => void
  /** 여러 건을 만들었다 — 목록이 만든 수와 건너뛴 점을 말한다. */
  onImported: (result: DoeImport) => void
}

export function NewSimulationDialog({ open, onClose, onCreated, onImported }: Props) {
  const { user } = useAuth()
  const admin = isSystemAdmin(user)
  const memberships = user?.memberships ?? []

  const [source, setSource] = useState<Source>('folder')
  // CAD 폴더 — 지금 보는 폴더, 누른 CAD 폴더(다 읽기 전에도 목록에 표시), 읽은 CAD 폴더.
  const [listing, setListing] = useState<DoeListing | null>(null)
  const [folderPath, setFolderPath] = useState<string | null>(null)
  const [folder, setFolder] = useState<DoePreview | null>(null)
  // **실행할 점과 보는 점은 다르다** — 여럿을 걸면서 그중 하나의 조건을 들여다본다.
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [focus, setFocus] = useState<number | null>(null)
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
  // **CalculiX 가 기본이다**(2026-10-08) — 라이선스 없이 서버에서 바로, 여러 점을 함께 푼다.
  const [solver, setSolver] = useState<Solver>('calculix')
  const [modes, setModes] = useState('10')
  const [largeDeflection, setLargeDeflection] = useState(false)
  const [harmonic, setHarmonic] = useState<HarmonicInput>(HARMONIC_DEFAULTS)
  const [elementSize, setElementSize] = useState('')
  const [order, setOrder] = useState<MeshOrder>('quadratic')
  // **CAD 가 보낸 조건이 먼저다** — 끄면 여기서 고른 영역만 완전 고정한다(conditions_from).
  const [conditionsFromCad, setConditionsFromCad] = useState(true)
  const [regions, setRegions] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  // 고른 점을 서버가 읽는 동안 — 오른쪽 칸이 무엇을 기다리는지 말한다.
  const [reading, setReading] = useState(false)
  // **폴더를 읽는 중과 작업을 만드는 중은 다르다** — 같은 글자를 띄우면 탐색만 해도 「생성 중」 이다.
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<ApiError | Error | null>(null)
  // 미리보기 물음의 번호 — 나중에 물은 것만 오른쪽에 쓴다(`ask`).
  const asking = useRef(0)
  // 폴더 목록 물음의 번호 — 늦게 온 목록이 뒤에 누른 폴더를 덮지 않게(`browse` · `pick`).
  const browsing = useRef(0)
  // 지금 출처 — 늦게 온 폴더 답이 그 사이 고른 업로드 쪽을 지우지 않게 비동기 함수가 읽는다.
  const sourceRef = useRef<Source>('folder')

  const usable = (folder?.points ?? []).filter((one) => one.usable).map((one) => one.number)
  // 여러 건 — 이름은 점마다 붙고, 만든 뒤에는 목록으로 돌아간다.
  const many = source === 'folder' && checked.size > 1
  const cadMaterials = preview?.materials ?? []
  const bodies = preview?.bodies ?? []
  const lines = preview?.conditions.lines ?? []
  const hasCadConditions = lines.length > 0
  const useCadConditions = hasCadConditions && conditionsFromCad
  // **재료가 빠진 파트** — 서버가 거절하고, 걸어도 모델링이 멈춘다. 해석에서 뺀 파트는 물성이
  // 없어도 된다(메시에도 안 나온다).
  const bare = bodies.filter((one) => !one.material && !one.suppressed)
  const shellParts = bodies.filter((one) => one.shell)
  // 폴더에서 고르면 중간면이 폴더에서 따라온다 — 올릴 때만 따로 받는다.
  const needsMid = source === 'upload' && shellParts.length > 0 && midFile === null
  const hasMaterials = cadMaterials.length > 0 && bare.length === 0
  const folderMaterials = folder?.materials ?? []
  const faceRegions = (preview?.regions ?? []).filter((one) => one.kind === 'face')
  const probes = (preview?.regions ?? []).filter((one) => one.kind === 'point')
  // **CAD 크기는 CAD 조건을 쓸 때만이다** — 끄면 모델링이 점 파일을 아예 안 읽어 「전체」 크기도
  // 안 쓴다(그대로 비워 두면 CalculiX 는 메시에서 멈춘다). 폴더의 크기는 폴더 쪽에서만 —
  // 업로드 쪽으로 넘어와서 옆 탭의 폴더 값을 쓰면 안 된다(2026-10-05 리뷰).
  const cadSize = useCadConditions
    ? (preview?.suggested_element_size_mm ??
      (source === 'folder' ? folder?.suggested_element_size_mm : null) ??
      null)
    : null
  const suggested = preview ? (isRecipe(preview.suggested_recipe) ? preview.suggested_recipe : null) : undefined
  // **정적 · 조화는 하중이 CAD 조건에서 온다** — 스펙에는 하중 칸이 없다. 정적은 강제 변위로
  // 당겨도 답이 있다(시편 시험 — `drives`).
  const hasLoads =
    useCadConditions &&
    (lines.some((one) => one.kind === 'load' && one.status === 'applied') ||
      (recipe === 'static' && preview?.conditions.drives === true))
  // **CalculiX 는 요소 크기 없이 돌지 않는다** — 설계점 수만큼 메시 실패가 쌓이기 전에 막는다.
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
  // **물성이 막는 자리** — 올린 점 파일, 물성을 안 보낸 폴더, 실행할 점 중 지금 보는 점에 빠진 재료.
  // 보지 않는 점은 서버가 까닭을 달아 건너뛴다(목록이 그것을 말한다).
  const materialsOk =
    source === 'upload'
      ? hasMaterials
      : folderMaterials.length > 0 && (focus === null || !checked.has(focus) || hasMaterials)
  // **막힌 CAD 조건** — 모델링이 그 자리에서 멈춘다(서버도 만들 때 거절한다 — SIMULATIONS-0030).
  // CAD 조건을 끄면 읽지 않으므로 막지 않는다. 여럿이면 보는 점이 실행할 점일 때만 막는다 — 나머지
  // 점은 서버가 까닭을 달아 건너뛴다.
  const refused = useCadConditions ? lines.filter((one) => one.status === 'refused') : []
  const conditionsOk =
    refused.length === 0 || (source === 'folder' && (focus === null || !checked.has(focus)))
  const picked = source === 'folder' ? folder !== null && checked.size > 0 : file !== null
  const ready =
    picked &&
    preview !== null &&
    materialsOk &&
    conditionsOk &&
    !needsMid &&
    !busy &&
    problem === null &&
    !needsSize

  /**
   * 오른쪽 미리보기를 묻는다 — **나중에 물은 것이 이긴다.** 점이나 해석 종류를 빨리 바꾸면 앞 물음의
   * 답이 늦게 와서 지금 보는 점의 조건을 덮었다(2026-10-05 리뷰). 늦은 답 · 늦은 오류는 버린다.
   */
  async function ask(
    load: Promise<ConditionsPreview>,
    fallback: string,
    use: (found: ConditionsPreview) => void,
    fail?: () => void,
  ) {
    const mine = ++asking.current
    setReading(true)
    try {
      const found = await load
      if (mine === asking.current) use(found)
    } catch (caught) {
      if (mine !== asking.current) return
      setError(caught instanceof Error ? caught : new Error(fallback))
      fail?.()
    } finally {
      if (mine === asking.current) setReading(false)
    }
  }

  /** 묻던 것을 거둔다 — 폴더 · 출처를 바꿔서 그 답이 와도 쓸 자리가 없다. */
  function forget() {
    asking.current += 1
    setReading(false)
  }

  const askFile = (
    next: File,
    asked: RecipeName | undefined,
    use: (found: ConditionsPreview) => void,
    fail?: () => void,
  ) => ask(simulationApi.previewConditions(next, asked), 'CAD 점 파일을 읽지 못했습니다.', use, fail)
  const askPoint = (
    path: string,
    point: number,
    asked: RecipeName | undefined,
    use: (found: ConditionsPreview) => void,
    fail?: () => void,
  ) => ask(simulationApi.previewDoePoint(path, point, asked), '설계점을 읽지 못했습니다.', use, fail)

  /** 서버가 읽은 점 — **CAD 가 적은 것을 미리 채운다**(조용히 쓰면 그쪽 값이 우리 것을 덮는다). */
  function adopt(found: ConditionsPreview) {
    setPreview(found)
    // **조건 줄을 편 종류로 맞춘다** — CAD 가 종류를 안 적었으면 서버는 모달로 폈다. 앞에서 고른
    // 종류를 그대로 두면 칸은 「정적」 인데 조건 · 막힘 판정은 모달 것이다(2026-10-05 리뷰).
    if (isRecipe(found.recipe)) setRecipe(found.recipe)
    if (found.suggested_modes) setModes(String(found.suggested_modes))
    if (isOrder(found.suggested_order)) setOrder(found.suggested_order)
    setConditionsFromCad(true)
  }

  async function pickPoint(next: File | null) {
    setPointFile(next)
    // **중간면은 점 파일의 짝이다** — 점을 바꾸면 앞 점의 중간면이 칸에서는 사라지고 상태에는
    // 남아 다른 점과 함께 올라갔다(2026-10-05 리뷰).
    setMidFile(null)
    setPreview(null)
    setRegions([])
    setError(null)
    if (!next) {
      forget()
      return
    }
    // 처음 읽기를 못 하면 그 파일은 쓸 수 없다 — 고른 것을 거둔다. 종류를 바꿔 다시 물을 때는
    // 거두지 않는다(파일은 멀쩡하고, 거두면 칸에는 파일이 보이는데 실행에는 빠진다).
    await askFile(next, undefined, adopt, () => setPointFile(null))
  }

  /**
   * 오른쪽에 볼 점을 바꾼다 — **지금 고른 해석 종류로** 읽는다. 설정은 건드리지 않는다(체크한 점
   * 모두에 같은 설정이다). 다 읽을 때까지 앞 점을 그대로 두고 머리에 「읽는 중」 을 단다.
   */
  async function focusPoint(next: number) {
    if (!folder || next === focus) return
    setFocus(next)
    setError(null)
    // 못 읽으면 앞 점의 조건을 이 점 이름 아래 두지 않는다 — 비우고 까닭(오류)을 보인다.
    await askPoint(folder.path, next, recipe, setPreview, () => setPreview(null))
  }

  /** CAD 폴더를 읽는다 — 실행할 점은 걸 수 있는 전부, 보는 점은 그 첫 점. */
  async function readFolder(path: string) {
    const mine = ++asking.current
    setFolderPath(path)
    setFolder(null)
    setChecked(new Set())
    setFocus(null)
    setPreview(null)
    setRegions([])
    setReading(true)
    const study = await simulationApi.previewDoe(path).finally(() => {
      if (mine === asking.current) setReading(false)
    })
    // 읽는 사이 다른 폴더를 골랐다 — 늦게 온 이 폴더가 그것을 덮으면 안 된다.
    if (mine !== asking.current) return
    setFolder(study)
    const ok = study.points.filter((one) => one.usable).map((one) => one.number)
    setChecked(new Set(ok))
    const first = ok[0]
    if (first === undefined) return
    setFocus(first)
    await askPoint(study.path, first, undefined, adopt)
  }

  async function browse(path?: string) {
    // **늦게 온 목록은 버린다** — 폴더를 누르고 바로 다른 뿌리를 누르면 앞 답이 뒤 목록을 덮었다.
    const mine = ++browsing.current
    setBusy(true)
    setError(null)
    try {
      const next = await simulationApi.browseDoe(path)
      if (mine !== browsing.current) return
      if (next.is_study) {
        // 경로가 CAD 폴더 자체였다(뿌리가 곧 CAD 폴더 등) — 그 위를 목록으로 두고 그것을 고른다.
        const above = next.parent ? await simulationApi.browseDoe(next.parent) : next
        if (mine !== browsing.current) return
        setListing(above)
        if (sourceRef.current === 'folder') await readFolder(next.path)
        return
      }
      setListing(next)
      // 그 사이 업로드 쪽으로 갔다 — 그쪽 미리보기를 지우지 않는다.
      if (sourceRef.current !== 'folder') return
      forget()
      setFolderPath(null)
      setFolder(null)
      setChecked(new Set())
      setFocus(null)
      setPreview(null)
    } catch (caught) {
      if (mine === browsing.current) setError(caught instanceof Error ? caught : new Error('폴더를 읽지 못했습니다.'))
    } finally {
      if (mine === browsing.current) setBusy(false)
    }
  }

  /** CAD 폴더를 고른다 — **목록은 그 자리에 둔다**(옆 폴더로 바꾸는 것이 한 번이다). */
  async function pick(path: string) {
    const mine = ++browsing.current
    setBusy(true)
    setError(null)
    try {
      await readFolder(path)
    } catch (caught) {
      if (mine === browsing.current) setError(caught instanceof Error ? caught : new Error('CAD 폴더를 읽지 못했습니다.'))
    } finally {
      if (mine === browsing.current) setBusy(false)
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
    sourceRef.current = next
    setPreview(null)
    setRegions([])
    setError(null)
    forget()
    // **돌아온 쪽이 고른 것을 다시 보인다** — 폴더의 보는 점 · 올린 점 파일은 남아 있는데 오른쪽이
    // 비면 「고르세요」 로 읽히고, 보는 점을 다시 눌러도 같은 점이라 아무 일이 없었다(2026-10-05 리뷰).
    if (next === 'folder' && folder && focus !== null) void askPoint(folder.path, focus, recipe, setPreview)
    if (next === 'upload' && pointFile) void askFile(pointFile, recipe, setPreview)
  }

  async function changeRecipe(next: RecipeName) {
    setRecipe(next)
    // 조건이 어떻게 다뤄지나는 해석 종류에 달렸다(모달이면 하중을 넘긴다) — 다시 묻는다.
    if (source === 'folder' && folder && focus !== null) {
      await askPoint(folder.path, focus, next, setPreview)
    } else if (source === 'upload' && pointFile) {
      await askFile(pointFile, next, setPreview)
    }
  }

  function toggle(number: number, on: boolean) {
    const next = new Set(checked)
    if (on) next.add(number)
    else next.delete(number)
    setChecked(next)
  }

  async function submitFolder() {
    if (!folder) return
    const numbers = [...checked].sort((a, b) => a - b)
    const result = await simulationApi.importDoe({
      path: folder.path,
      // **모든 점에 같은 스펙을 쓴다** — 그래야 결과를 견줄 수 있다.
      spec: buildSpec(input),
      workspace_slug: workspace === GLOBAL ? null : workspace,
      // 여럿을 다 고른 것이면 보내지 않는다 — 서버가 「걸 수 있는 전부」 로 받는다.
      numbers: numbers.length > 1 && numbers.length === usable.length ? null : numbers,
      name: numbers.length === 1 ? name.trim() || null : null,
    })
    if (numbers.length > 1) {
      onImported(result)
      return
    }
    const made = result.created[0]
    if (!made) {
      // **걸지 못한 까닭을 그대로 보인다**(이미 가져온 점 · 물성이 빠진 점 …).
      throw new Error(result.skipped[0]?.skip_reason || '작업을 만들지 못했습니다.')
    }
    onCreated(await simulationApi.get(made))
  }

  async function submit() {
    setBusy(true)
    setCreating(true)
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
      setCreating(false)
    }
  }

  // 오른쪽 머리 — 지금 무엇의 조건을 보고 있나.
  const pickedLabel =
    source === 'folder'
      ? folder
        ? folder.single
          ? folder.name
          : `${folder.name} · ${focus !== null ? pointName(focus) : '설계점 선택'}`
        : null
      : (pointFile?.name ?? file?.name ?? null)

  const placeholder = reading
    ? '설계점을 읽는 중…'
    : source === 'upload'
      ? '형상 파일과 CAD 점 파일을 올리면 서버가 읽은 조건 · 물성 · 해석 설정이 여기에 나옵니다.'
      : folder && usable.length === 0
        ? folder.single
          ? '이 설계는 실행할 수 없습니다 — 까닭은 왼쪽 폴더 이름 아래에 있습니다.'
          : '실행할 수 있는 설계점이 없습니다 — 왼쪽 표에서 까닭을 확인하세요.'
        : '왼쪽에서 CAD 폴더를 선택하면 그 설계점의 조건 · 물성 · 해석 설정이 여기에 나옵니다.'

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      {/* **화면의 80% — 왼쪽은 고르는 목록, 오른쪽은 고른 것의 조건.** 한 줄로 내리면 설계점을
          고르고 조건을 보려고 창 끝까지 굴렸다가 다시 올라와야 했다. */}
      <DialogContent className="h-[85vh] max-h-[85vh] w-[calc(100%-2rem)] max-w-none sm:h-[80vh] sm:max-h-[80vh] sm:w-[80vw] sm:max-w-none">
        <DialogHeader>
          <DialogTitle>새 해석 작업</DialogTitle>
          <DialogDescription>
            CompCore 가 내보낸 폴더에서 설계점을 선택해 해석 작업을 만듭니다 — 설계 하나든 DOE 든 같고,
            선택한 설계점마다 작업이 하나씩 생깁니다. 물성 · 조건은 각 설계점의 점 파일에서 옵니다.
          </DialogDescription>
        </DialogHeader>

        <div className="flex shrink-0 gap-1" role="tablist" aria-label="가져올 곳">
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

        <div className="grid grid-cols-1 gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:grid-rows-[minmax(0,1fr)]">
          {/* ── 왼쪽: 고르는 자리 ── */}
          <section aria-label="설계점 목록" className="flex flex-col gap-3 lg:min-h-0 lg:overflow-y-auto lg:pr-1">
            {source === 'folder' && (
              <>
                <FolderBrowser
                  listing={listing}
                  busy={busy}
                  onBrowse={(path) => void browse(path)}
                  onPick={(path) => void pick(path)}
                  selected={folderPath}
                  badge="CAD"
                  // 설계 하나면 아래에 고를 점이 없다 — 폴더 목록이 칸을 쓴다.
                  fill={!folderPath || folder?.single === true}
                />
                {folder &&
                  (folder.single ? (
                    <div className="rounded-md border p-3 text-sm">
                      <p>
                        <span className="font-medium">{folder.name}</span>{' '}
                        <span className="text-muted-foreground text-xs">설계 하나</span>
                      </p>
                      {/* 표가 없으니 걸 수 없는 까닭을 여기서 말한다 — 안 그러면 막힌 채 이유가 없다. */}
                      {folder.points[0] && !folder.points[0].usable && (
                        <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                          실행할 수 없습니다 — {folder.points[0].skip_reason}
                        </p>
                      )}
                    </div>
                  ) : (
                    <>
                      {/* **요약은 두 줄** — 아래 설계점 표가 칸을 써야 한다(세 덩어리로 두면 표가 한두 줄만 남았다). */}
                      <div className="rounded-md border px-3 py-2 text-sm">
                        <p className="truncate">
                          <span className="font-medium">{folder.name}</span>{' '}
                          <span className="text-muted-foreground text-xs">
                            변수 {folder.factors.join(' · ') || '없음'}
                            {folder.method ? ` · ${folder.method}` : ''}
                            {folder.seed != null ? ` · 시드 ${folder.seed}` : ''}
                          </span>
                        </p>
                        <p className="text-xs">
                          실행할 수 있는 점 <b>{folder.usable}</b>개
                          {folder.skipped > 0 && (
                            <span className="text-amber-700 dark:text-amber-400"> · 건너뜀 {folder.skipped}개</span>
                          )}{' '}
                          · 선택 <b>{checked.size}</b>건{' '}
                          <span className="text-muted-foreground">
                            — 체크한 점마다 작업을 하나씩 만들고, 행을 누르면 그 점을 오른쪽에서 봅니다.
                          </span>
                        </p>
                      </div>
                      <div className="max-h-72 overflow-auto rounded-md border lg:max-h-none lg:min-h-40 lg:flex-1">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-8">
                                <input
                                  type="checkbox"
                                  aria-label="설계점 전체 선택"
                                  checked={usable.length > 0 && checked.size === usable.length}
                                  onChange={(event) => setChecked(new Set(event.target.checked ? usable : []))}
                                />
                              </TableHead>
                              <TableHead>점</TableHead>
                              {folder.factors.map((one) => (
                                <TableHead key={one}>{one}</TableHead>
                              ))}
                              <TableHead>상태</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {folder.points.map((point) => (
                              <TableRow
                                key={point.number}
                                data-state={focus === point.number ? 'selected' : undefined}
                                // **행을 누르면 그 점을 오른쪽에서 본다** — 체크(실행할 점)와 따로.
                                className={point.usable ? 'cursor-pointer' : ''}
                                onClick={() => point.usable && !busy && void focusPoint(point.number)}
                              >
                                <TableCell onClick={(event) => event.stopPropagation()}>
                                  <input
                                    type="checkbox"
                                    aria-label={`${pointName(point.number)} 선택`}
                                    disabled={!point.usable}
                                    checked={checked.has(point.number)}
                                    onChange={(event) => toggle(point.number, event.target.checked)}
                                  />
                                </TableCell>
                                <TableCell>
                                  <button
                                    type="button"
                                    className="font-mono hover:underline disabled:no-underline"
                                    aria-pressed={focus === point.number}
                                    aria-label={`${pointName(point.number)} 보기`}
                                    disabled={!point.usable || busy}
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      void focusPoint(point.number)
                                    }}
                                  >
                                    {pointName(point.number)}
                                  </button>
                                </TableCell>
                                {folder.factors.map((one) => (
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
                                    <span className="text-amber-700 dark:text-amber-400">{point.skip_reason}</span>
                                  )}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </>
                  ))}
              </>
            )}

            {/* **내리지 않고 숨긴다** — 탭을 오가면 파일 칸이 비어 보이는데 고른 파일은 상태에 남아
                그대로 올라갔다(2026-10-05 리뷰). 숨겨 두면 칸과 상태가 늘 같다. */}
            <div hidden={source !== 'upload'} className="flex flex-col gap-3">
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
                {shellParts.length > 0 && (
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
                {!pointFile && (
                  <p className="text-muted-foreground text-xs">
                    CAD 점 파일이 있어야 실행합니다 — 파트마다 재료 · 조건 · 해석 설정이 그 파일에서 옵니다. 공용
                    폴더에 있는 파일이면 「CAD 폴더에서 선택」 이 짝을 맞춰 줍니다.
                  </p>
                )}
            </div>
          </section>

          {/* ── 오른쪽: 보는 점의 조건 · 체크한 점 모두에 같은 설정 ── */}
          <section
            aria-label="조건 · 설정"
            className="flex flex-col gap-4 lg:min-h-0 lg:overflow-y-auto lg:border-l lg:pl-4"
          >
            {!preview ? (
              <div className="text-muted-foreground flex flex-1 items-center justify-center rounded-md border border-dashed p-6 text-center text-sm">
                {placeholder}
              </div>
            ) : (
              <>
                <div className="space-y-0.5">
                  {pickedLabel && (
                    <p className="text-sm font-medium">
                      {pickedLabel}
                      {reading && <span className="text-muted-foreground font-normal"> — 읽는 중…</span>}
                    </p>
                  )}
                  {many && (
                    <p className="text-muted-foreground text-xs">
                      아래 설정은 선택한 {checked.size}건에 같게 적용합니다 — 설계점끼리 견주려면 솔버 · 해석
                      종류가 같아야 합니다.
                    </p>
                  )}
                </div>

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
                    {preview.suggested_element_size_mm != null && <> · 요소 크기 {preview.suggested_element_size_mm} mm</>}
                  </p>
                  {(preview.unresolved ?? []).length > 0 && (
                    // **CAD 가 못 푼 이름을 감추지 않는다.** 그 이름으로는 형상에 자리가 없다.
                    <p className="text-xs text-amber-700 dark:text-amber-400">
                      CAD 가 풀지 못한 영역: {(preview.unresolved ?? []).join(' · ')}
                    </p>
                  )}
                  <ConditionList conditions={preview.conditions} />
                  {!conditionsOk && (
                    <p className="text-xs text-amber-700 dark:text-amber-400">
                      걸 수 없는(막음) CAD 조건이 있어 이대로는 실행하지 않습니다 — 모델링이 그 자리에서
                      멈춥니다. CompCore 에서 고쳐 다시 내보내거나, 아래 「CAD 가 보낸 조건 사용」 을 끄고
                      고정할 면을 고르세요{many ? '. 이 점만 빼려면 왼쪽에서 체크를 풉니다' : ''}.
                    </p>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  {!many && (
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
                                : `${folder.name} ${pointName([...checked][0] ?? focus ?? 1)}`
                              : '비우면 폴더 이름'
                            : (file?.name ?? '비우면 파일 이름')
                        }
                      />
                    </div>
                  )}
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

                {recipe !== 'static' && (
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="sim-modes">{recipe === 'harmonic' ? '모드 중첩에 쓸 모드 수' : '탄성 모드 수'}</Label>
                      <Input
                        id="sim-modes"
                        type="number"
                        min={1}
                        max={100}
                        value={modes}
                        onChange={(event) => setModes(event.target.value)}
                      />
                      {preview.suggested_modes ? (
                        <p className="text-muted-foreground text-xs">CAD 가 적은 값 {preview.suggested_modes}</p>
                      ) : null}
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
                    idPrefix="sim-harmonic"
                    value={harmonic}
                    onChange={setHarmonic}
                    fromCad={preview.suggested_recipe === 'harmonic'}
                  />
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

                <fieldset className="space-y-3 rounded-md border p-3">
                  <legend className="px-1 text-sm font-medium">물성</legend>
                  {source === 'folder' && folderMaterials.length === 0 ? (
                    <p className="text-xs text-amber-700 dark:text-amber-400">
                      이 폴더는 물성을 보내지 않았습니다 — 실행할 수 없습니다. CompCore 에서 재료를 지정한 뒤 다시
                      내보내세요.
                    </p>
                  ) : cadMaterials.length > 0 ? (
                    <>
                      <p className="text-muted-foreground text-xs">
                        {many
                          ? `설계점마다 CompCore 가 파트에 지정한 재료로 실행합니다(이 폴더: ${folderMaterials.join(' · ')}). 재료가 빠진 설계점은 만들지 않고 까닭을 표시합니다. 아래는 보고 있는 점입니다.`
                          : 'CompCore 가 파트마다 지정한 재료로 실행합니다.'}
                      </p>
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
                          고른 영역만 완전 고정합니다{many ? ' — 선택한 모든 점에 같게' : ''}.
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
              </>
            )}

            {problem && preview && <p className="text-xs text-amber-700 dark:text-amber-400">{problem}</p>}
          </section>
        </div>

        <ErrorNotice error={error} />

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            취소
          </Button>
          <Button onClick={submit} disabled={!ready}>
            {creating
              ? source === 'upload'
                ? '업로드 중…'
                : '생성 중…'
              : many
                ? `${checked.size}건 실행`
                : '실행'}
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
