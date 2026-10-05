/**
 * VTP 하나를 그리는 3D 뷰어 — 회전 · 컬러바 · **모드 형상 애니메이션.**
 *
 * ## 왜 변위를 화면에서 흔드나
 *
 * 모달의 변위는 **질량 정규화된 상대값**이다(절대 크기가 아니다). 그대로 그리면 아무것도 안
 * 움직인 그림이 나오고, 고정 배율로 과장하면 모델마다 다르게 보인다. 그래서 모델 크기 대비
 * 비율로 배율을 정하고, `sin(t)` 로 흔든다 — **정지 화면으로는 굽힘과 비틀림이 잘 안 갈린다.**
 *
 * ## 여러 개를 함께 띄울 수 있다
 *
 * 모달 결과의 「여러 개 보기」 는 이 뷰어를 4 · 6 · 9 개 함께 띄운다(`controls={false}` — 슬라이더 ·
 * 단추 없이 작게, 움직임은 위에서 한 번에 `playing`). 브라우저는 WebGL 컨텍스트를 한 페이지에 대략
 * 16 개까지만 주므로, **닫을 때 컨텍스트를 명시적으로 반납한다**(`WEBGL_lose_context`) — 객체만 지우면
 * 가비지 수거를 기다리는 동안 컨텍스트가 남아, 쪽을 몇 번 넘기면 앞 뷰어가 꺼진다.
 *
 * ## 선과 파트
 *
 * - **외곽선**(형상의 윤곽) · **요소**(요소 경계 전부)를 켜고 끈다 — 모든 뷰어가 함께(`viewerPrefs`).
 *   외곽선은 꺾인 모서리 · 테두리를 셈으로 찾아 선으로 그리고(`surfaceParts.featureEdges`), 요소는
 *   vtk 의 면 테두리(edge visibility)다.
 * - **파트마다 따로 그린다**(점은 함께 쓰고 셀만 나눈다) — 보이기 · 숨기기를 파트마다 한다. 서버가
 *   그림에 셀 배열 `part` 를 적어 보내고 이름은 결과의 `parts` 다. 그 전에 만든 그림은 이어진
 *   덩어리로 나눈다(`surfaceParts.components` — 이름은 「파트 N」).
 *
 * ## vtk.js 를 여기서만 import 한다
 *
 * 이 파일은 `lazy()` 로만 불린다(`shared/viewer/index.ts`). 화면이 직접 vtk.js 를 부르면 그
 * 덩어리가 첫 로드에 실린다.
 */

import { useEffect, useRef, useState } from 'react'

import { Button } from '@/shared/components/ui/button'
import { cn } from '@/shared/lib/utils'
import type { CameraMember, CameraState, CameraSync } from '@/shared/viewer/cameraSync'
import { ColormapSelect } from '@/shared/viewer/ColormapSelect'
import { gradientOf, useColormap } from '@/shared/viewer/colormaps'
import type { Colormap } from '@/shared/viewer/colormaps'
import { cellCount, components, featureEdges, groupCells } from '@/shared/viewer/surfaceParts'
import { DisplayToggles, PartPicker } from '@/shared/viewer/ViewerControls'
import type { ViewerPart } from '@/shared/viewer/ViewerControls'
import { useViewerPrefs } from '@/shared/viewer/viewerPrefs'
import type { ViewerPrefs } from '@/shared/viewer/viewerPrefs'

export interface MeshViewerProps {
  /** VTP 파일 내용. 서버가 추출 시점에 만들어 둔 것을 그대로 받는다. */
  data: ArrayBuffer
  /** 변위를 모델 크기의 몇 배까지 과장하나. 사람이 아래 슬라이더로 바꾼다. */
  warpRatio?: number
  /** 한 번 흔드는 데 걸리는 시간(ms). */
  periodMs?: number
  /** 그림 높이(Tailwind 클래스). 기본은 화면 높이에 맞춘다 — 모드 형상은 작으면 못 읽는다. */
  heightClass?: string
  className?: string
  /** 아래 막대(범례 · 배율 · 재생 · 전체 화면)를 그리나. 여러 개를 깔 때는 끈다. */
  controls?: boolean
  /** 움직임을 밖에서 정한다 — 여러 개를 한 번에 멈추고 움직인다. 안 주면 뷰어가 스스로 쥔다. */
  playing?: boolean
  /** 시점을 함께 쓰는 뷰어 묶음 — 여기서 돌리거나 확대하면 묶음의 다른 뷰어가 따른다. */
  cameraSync?: CameraSync
  /** 그림의 셀 배열 `part` 번호의 이름(결과의 `parts`). 없으면 「파트 N」. */
  partNames?: string[]
  /** 숨긴 파트 번호들 — 밖에서 쥔다(여러 칸이 함께). 안 주면 뷰어가 스스로 쥔다. */
  hiddenParts?: number[]
  onHiddenPartsChange?: (next: number[]) => void
  /** 그림을 읽고 나면 파트 목록을 알린다 — 밖의 막대가 고르는 칸을 그린다. */
  onParts?: (parts: ViewerPart[]) => void
}

/** WebGL2 가 되나 — 한 번만 본다(물어본 캔버스의 컨텍스트도 한도를 먹으므로 바로 반납한다). */
let webgl2: boolean | null = null
function hasWebgl2(): boolean {
  if (webgl2 === null) {
    const context = document.createElement('canvas').getContext('webgl2')
    webgl2 = context !== null
    context?.getExtension('WEBGL_lose_context')?.loseContext()
  }
  return webgl2
}

/**
 * 캔버스들의 WebGL 컨텍스트를 반납한다 — 객체를 지운 뒤에도 수거 전까지 남아 한도를 먹는다.
 *
 * **캔버스는 지우기 전에 집어 둔다.** vtk.js 의 `delete` 는 캔버스를 상자에서 떼어 내고(컨텍스트는
 * 반납하지 않는다 — 개수만 센다), 그 뒤에 상자를 뒤지면 아무것도 없다. 처음에는 지운 뒤에 뒤져서
 * 반납이 한 번도 안 일어났다(2026-10-05 리뷰).
 */
function releaseContexts(canvases: HTMLCanvasElement[]) {
  for (const canvas of canvases) {
    for (const kind of ['webgl2', 'webgl'] as const) {
      const context = canvas.getContext(kind) as WebGLRenderingContext | null
      context?.getExtension('WEBGL_lose_context')?.loseContext()
      if (context) break
    }
  }
}

/** 값 배열의 최댓값. 컬러바 범위와 배율 계산에 쓴다. */
function maxOf(values: Float32Array | Float64Array | number[]): number {
  let top = 0
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index]
    if (value > top) top = value
  }
  return top
}

export default function MeshViewer({
  data,
  warpRatio = 0.15,
  periodMs = 1600,
  heightClass = 'h-[calc(100vh-14rem)] min-h-[24rem]',
  className,
  controls = true,
  playing: controlledPlaying,
  cameraSync,
  partNames,
  hiddenParts,
  onHiddenPartsChange,
  onParts,
}: MeshViewerProps) {
  const host = useRef<HTMLDivElement>(null)
  const frame = useRef<HTMLDivElement>(null)
  /** 변위 과장 배율. **사람이 바꿀 수 있어야 한다** — 얇은 판과 두꺼운 블록은 적정 배율이 다르다. */
  const [ratio, setRatio] = useState(warpRatio)
  const ratioRef = useRef(ratio)
  ratioRef.current = ratio
  const [playing, setPlaying] = useState(true)
  const [error, setError] = useState<string | null>(null)
  /** 색 범위의 위쪽 — 아래 범례가 이 값을 적는다. 0 이면 아직 안 그려졌다. */
  const [peak, setPeak] = useState(0)
  const playingRef = useRef(playing)
  playingRef.current = controlledPlaying ?? playing
  // **색 지도는 모든 뷰어가 함께 쓴다**(`colormaps.ts`). 바꿔도 창을 다시 만들지 않고 색만 다시
  // 칠한다 — 시점 · 움직임이 그대로 남는다.
  const colormap = useColormap()
  const colormapRef = useRef(colormap)
  colormapRef.current = colormap
  const recolor = useRef<((map: Colormap) => void) | null>(null)
  // 선 · 파트 — 바꿔도 창을 다시 만들지 않고 보이기만 바꾼다.
  const prefs = useViewerPrefs()
  const [parts, setParts] = useState<ViewerPart[]>([])
  const [ownHidden, setOwnHidden] = useState<number[]>([])
  const hidden = hiddenParts ?? ownHidden
  const setHidden = onHiddenPartsChange ?? setOwnHidden
  const shownRef = useRef({ hidden, prefs })
  shownRef.current = { hidden, prefs }
  const partNamesRef = useRef(partNames)
  partNamesRef.current = partNames
  const onPartsRef = useRef(onParts)
  onPartsRef.current = onParts
  const reshow = useRef<((hidden: number[], prefs: ViewerPrefs) => void) | null>(null)

  useEffect(() => {
    if (!host.current) return
    const container = host.current
    let disposed = false
    let cleanup: (() => void) | undefined
    // 앞 파일의 오류를 다음 파일 밑에 두지 않는다.
    setError(null)

    async function draw() {
      try {
        // **프로파일을 먼저 받는다.** vtk.js 의 Actor · Mapper 는 「무엇을 그리나」 만 알고,
        // 「어떻게 그리나」(OpenGL)는 프로파일이 등록한다. 빠뜨리면 렌더 트리를 걷다가 짝이
        // 없는 자리에서 `Cannot read properties of undefined (reading 'traverse')` 로 죽는다 —
        // 그 메시지는 무엇이 빠졌는지 말해 주지 않는다(실측으로 겪었다).
        await import('@kitware/vtk.js/Rendering/Profiles/Geometry')

        // **여기서 받는다.** 위에서 import 하면 이 파일을 쓰지 않는 화면도 vtk.js 를 받는다.
        const [
          { default: vtkFullScreenRenderWindow },
          { default: vtkXMLPolyDataReader },
          { default: vtkMapper },
          { default: vtkActor },
          { default: vtkColorTransferFunction },
          { default: vtkPolyData },
        ] = await Promise.all([
          import('@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow'),
          import('@kitware/vtk.js/IO/XML/XMLPolyDataReader'),
          import('@kitware/vtk.js/Rendering/Core/Mapper'),
          import('@kitware/vtk.js/Rendering/Core/Actor'),
          import('@kitware/vtk.js/Rendering/Core/ColorTransferFunction'),
          import('@kitware/vtk.js/Common/DataModel/PolyData'),
        ])
        if (disposed) return

        const reader = vtkXMLPolyDataReader.newInstance()
        reader.parseAsArrayBuffer(data)
        const polyData = reader.getOutputData(0)

        const points = polyData.getPoints()
        const rest = Float64Array.from(points.getData())
        const displacement = polyData.getPointData().getArrayByName('displacement')
        const magnitude = polyData.getPointData().getArrayByName('magnitude')
        if (!displacement || !magnitude) {
          setError('이 파일에는 변위가 없습니다.')
          return
        }
        const vectors = displacement.getData()
        const scalars = magnitude.getData()

        // 모델 크기 대비 배율 — 고정 배율로 과장하면 모델마다 다르게 보인다.
        const bounds = polyData.getBounds()
        const span = Math.max(
          bounds[1] - bounds[0],
          bounds[3] - bounds[2],
          bounds[5] - bounds[4],
        )
        const peak = maxOf(scalars as Float32Array)
        // 배율은 **매 프레임 읽는다** — 슬라이더를 움직이면 다시 그리지 않고 바로 따라온다.
        const scaleFor = (value: number) => (peak > 0 ? (value * span) / peak : 0)

        // **WebGL 이 없으면 미리 말한다.** vtk.js 는 컨텍스트를 못 얻으면 「Cannot create proxy …」
        // 같은 알아볼 수 없는 TypeError 를 던지고, 반쯤 만든 창(캔버스 · 창 크기 처리기)을 남긴다.
        if (!hasWebgl2()) {
          setError(
            '3D 뷰어를 띄울 수 없습니다 — 이 브라우저에서 WebGL2 를 쓸 수 없습니다(원격 데스크톱 · ' +
              '그래픽 드라이버). 고유진동수 · 유효질량 표와 그래프는 그대로 볼 수 있습니다.',
          )
          return
        }
        const view = vtkFullScreenRenderWindow.newInstance({
          container,
          containerStyle: { height: '100%', width: '100%', position: 'relative' },
          background: [0, 0, 0, 0],
        })
        const renderer = view.getRenderer()
        const renderWindow = view.getRenderWindow()

        const lookup = vtkColorTransferFunction.newInstance()
        // 0 → 최대 변위를 고른 색 지도의 마디로 칠한다(기본 Ansys 식 무지개).
        const paint = (map: Colormap) => {
          lookup.removeAllPoints()
          for (const [at, r, g, b] of map.stops) lookup.addRGBPoint(at * peak, r, g, b)
        }
        paint(colormapRef.current)

        // **파트마다 따로 그린다** — 점(좌표 · 변위)은 함께 쓰고 셀만 나눈다. 흔들 때 점 한 벌만
        // 고치고, 파트마다 보이기만 바꾼다.
        const flat = polyData.getPolys().getData()
        const total = cellCount(flat)
        // 셀 배열은 점 · 선 셀 다음에 면 셀이 온다 — 면만 쓴다.
        const before = polyData.getVerts().getNumberOfCells() + polyData.getLines().getNumberOfCells()
        const marked = polyData.getCellData().getArrayByName('part')
        const fromServer = marked !== null && marked !== undefined && marked.getNumberOfTuples() === before + total
        const labels = fromServer
          ? Int32Array.from({ length: total }, (_, index) => Number(marked.getData()[before + index]))
          : components(flat, points.getNumberOfPoints())
        const groups = groupCells(flat, labels)
        const ids = [...groups.keys()].sort((a, b) => a - b)
        const found: ViewerPart[] = ids.map((id) => ({
          id,
          name: (fromServer ? partNamesRef.current?.[id] : undefined) ?? `파트 ${id + 1}`,
        }))
        const pieces = ids.map((id) => {
          const cells = groups.get(id) as Uint32Array
          const piece = vtkPolyData.newInstance()
          piece.setPoints(points)
          piece.getPolys().setData(cells)
          piece.getPointData().addArray(magnitude)
          piece.getPointData().setActiveScalars('magnitude')
          const mapper = vtkMapper.newInstance({ interpolateScalarsBeforeMapping: true })
          mapper.setInputData(piece)
          mapper.setLookupTable(lookup)
          mapper.setScalarRange(0, peak)
          // **면을 조금 뒤로 민다** — 외곽선이 면과 같은 자리에 있어 그대로면 반쯤 묻힌다.
          mapper.setResolveCoincidentTopology(1)
          mapper.setRelativeCoincidentTopologyPolygonOffsetParameters(1, 1)
          const actor = vtkActor.newInstance()
          actor.setMapper(mapper)
          actor.getProperty().setEdgeColor(0.15, 0.15, 0.15)
          renderer.addActor(actor)

          const outline = vtkPolyData.newInstance()
          outline.setPoints(points)
          outline.getLines().setData(featureEdges(cells, rest))
          const lineMapper = vtkMapper.newInstance()
          lineMapper.setInputData(outline)
          lineMapper.setScalarVisibility(false)
          lineMapper.setResolveCoincidentTopology(1)
          lineMapper.setRelativeCoincidentTopologyLineOffsetParameters(-1, -1)
          const lineActor = vtkActor.newInstance()
          lineActor.setMapper(lineMapper)
          lineActor.getProperty().setColor(0.1, 0.1, 0.1)
          lineActor.getProperty().setLighting(false)
          renderer.addActor(lineActor)
          return { id, piece, outline, actor, mapper, lineActor, lineMapper }
        })
        const show = (hiddenIds: number[], shown: ViewerPrefs) => {
          const off = new Set(hiddenIds)
          for (const one of pieces) {
            const visible = !off.has(one.id)
            one.actor.setVisibility(visible)
            one.actor.getProperty().setEdgeVisibility(shown.edges)
            one.lineActor.setVisibility(visible && shown.outline)
          }
        }
        show(shownRef.current.hidden, shownRef.current.prefs)
        setParts(found)
        onPartsRef.current?.(found)

        // 컬러바는 **HTML 로 그린다**(아래 범례). 캔버스 안에 그리면 테마(밝게 · 어둡게)를
        // 따라가지 않아 어두운 화면에서 검은 글씨가 된다.
        setPeak(peak)

        // **비스듬히 본다(아이소메트릭).** vtk 의 기본은 위에서 내려다보는 것이라, 판 위의 기둥 ·
        // 브래킷이 선 하나로 보여 굽힘과 비틀림이 안 갈렸다(여러 개를 깔면 더 그렇다). Ansys 그림
        // (PyVista)과 같은 쪽에서 본다.
        const camera = renderer.getActiveCamera()
        const isometric = () => {
          camera.setPosition(0, 0, 1)
          camera.setFocalPoint(0, 0, 0)
          camera.setViewUp(0, 1, 0)
          renderer.resetCamera()
          camera.azimuth(-45)
          camera.elevation(30)
          camera.orthogonalizeViewUp()
          renderer.resetCamera()
        }
        isometric()
        renderWindow.render()
        recolor.current = (map: Colormap) => {
          paint(map)
          renderWindow.render()
        }
        reshow.current = (hiddenIds: number[], shown: ViewerPrefs) => {
          show(hiddenIds, shown)
          renderWindow.render()
        }

        // **시점 묶음** — 여기서 돌리거나 확대하면 묶음의 다른 뷰어가 따른다. 옮겨 받는 동안은
        // 다시 퍼뜨리지 않는다(서로 되받아 돈다).
        let applying = false
        let leave: (() => void) | undefined
        let watching: { unsubscribe: () => void } | undefined
        // **시점이 정말 바뀌었을 때만 퍼뜨린다.** 카메라는 그릴 때마다 클리핑 범위만 바뀌어도
        // 「바뀌었다」 고 알린다 — 그대로 퍼뜨리면 움직이는 동안 매 프레임 아홉 칸이 서로를 다시 그린다.
        let sent = ''
        const keyOf = (state: CameraState) =>
          [...state.position, ...state.focalPoint, ...state.viewUp, state.viewAngle, state.parallelScale]
            .map((value) => value.toFixed(6))
            .join(',')
        if (cameraSync) {
          const member: CameraMember = {
            apply: (state: CameraState) => {
              sent = keyOf(state)
              applying = true
              camera.setPosition(...(state.position as [number, number, number]))
              camera.setFocalPoint(...(state.focalPoint as [number, number, number]))
              camera.setViewUp(...(state.viewUp as [number, number, number]))
              camera.setViewAngle(state.viewAngle)
              camera.setParallelScale(state.parallelScale)
              renderer.resetCameraClippingRange()
              renderWindow.render()
              applying = false
            },
            reset: () => {
              // **처음으로는 퍼뜨리지 않는다** — 묶음이 칸마다 따로 돌린다(`resetAll`). 퍼뜨리면
              // 아홉 칸이 서로를 되받아 그려 80번 넘게 그린다.
              applying = true
              isometric()
              renderWindow.render()
              applying = false
              sent = ''
            },
          }
          watching = camera.onModified(() => {
            if (applying || disposed) return
            const state: CameraState = {
              position: [...camera.getPosition()],
              focalPoint: [...camera.getFocalPoint()],
              viewUp: [...camera.getViewUp()],
              viewAngle: camera.getViewAngle(),
              parallelScale: camera.getParallelScale(),
            }
            const key = keyOf(state)
            if (key === sent) return
            sent = key
            cameraSync.publish(member, state)
          })
          leave = cameraSync.join(member)
        }

        let animationFrame = 0
        let lastScale = -1
        let wasPlaying = playingRef.current
        const started = performance.now()
        const animate = () => {
          if (disposed) return
          const scale = scaleFor(ratioRef.current)
          // **멈추면 한 번 더 그린다(최대 변형으로)** — 안 그러면 멈춘 순간의 위상에 서서, 「모두
          // 멈추기」 뒤에 어떤 칸은 거의 안 변한 모양 · 어떤 칸은 뒤집힌 모양으로 남았다.
          const stopped = wasPlaying && !playingRef.current
          wasPlaying = playingRef.current
          if ((playingRef.current || stopped || scale !== lastScale) && scale > 0) {
            const phase = playingRef.current
              ? Math.sin((2 * Math.PI * (performance.now() - started)) / periodMs)
              : 1
            const moved = points.getData() as Float64Array
            for (let index = 0; index < rest.length; index += 1) {
              moved[index] = rest[index] + (vectors as Float32Array)[index] * scale * phase
            }
            lastScale = scale
            points.modified()
            polyData.modified()
            for (const one of pieces) {
              one.piece.modified()
              one.outline.modified()
            }
            renderWindow.render()
          }
          animationFrame = requestAnimationFrame(animate)
        }
        animationFrame = requestAnimationFrame(animate)

        // **창 크기만 보는 것으로는 부족하다.** 전체 화면 · 옆 칸 접기처럼 창은 그대로인데
        // 상자만 바뀌는 일이 있고, 그때 캔버스는 옛 크기로 남아 그림이 잘린다.
        const observer = new ResizeObserver(() => {
          view.resize()
          renderWindow.render()
        })
        observer.observe(container)

        cleanup = () => {
          recolor.current = null
          reshow.current = null
          cancelAnimationFrame(animationFrame)
          observer.disconnect()
          watching?.unsubscribe()
          leave?.()
          // **하나라도 빠뜨리면 WebGL 컨텍스트가 남는다.** 브라우저는 컨텍스트를 몇 개까지만
          // 주므로, 모드를 여러 번 바꾸면 그 뒤로 아무것도 안 그려진다.
          const canvases = Array.from(container.querySelectorAll('canvas'))
          for (const one of pieces) {
            one.actor.delete()
            one.mapper.delete()
            one.lineActor.delete()
            one.lineMapper.delete()
          }
          // **조작기는 따로 지운다** — 창을 지워도 상자(host)에 건 마우스 처리기가 남아, 모드를
          // 바꿀 때마다 쌓이고 지운 창을 건드리다 TypeError 를 낸다(2026-10-05 리뷰).
          view.getInteractor().delete()
          view.delete()
          releaseContexts(canvases)
        }
      } catch (caught) {
        if (disposed) return
        const said = caught instanceof Error ? caught.message : '그리지 못했습니다.'
        // 반쯤 만든 창이 남았으면 캔버스라도 거둔다 — 컨텍스트 한도를 먹는다.
        releaseContexts(Array.from(container.querySelectorAll('canvas')))
        container.querySelectorAll('canvas').forEach((one) => one.remove())
        setError(
          /webgl|context/i.test(said)
            ? `3D 뷰어를 띄울 수 없습니다(WebGL). 표와 그래프는 그대로 볼 수 있습니다. — ${said}`
            : said,
        )
      }
    }

    void draw()
    return () => {
      disposed = true
      cleanup?.()
    }
  }, [data, periodMs, cameraSync])

  useEffect(() => {
    recolor.current?.(colormap)
  }, [colormap])

  const hiddenKey = hidden.join(',')
  useEffect(() => {
    reshow.current?.(shownRef.current.hidden, shownRef.current.prefs)
  }, [hiddenKey, prefs.outline, prefs.edges])

  async function toggleFullscreen() {
    const box = frame.current
    if (!box) return
    if (document.fullscreenElement) {
      await document.exitFullscreen()
    } else {
      await box.requestFullscreen()
    }
  }

  return (
    <div className={className} ref={frame}>
      <div
        ref={host}
        className={cn(
          'bg-muted/30 relative w-full overflow-hidden rounded-md border',
          heightClass,
          // 전체 화면일 때는 그 안을 꽉 채운다 — 테두리 안에 작은 그림이 뜨면 뜻이 없다.
          'fullscreen:h-screen',
        )}
      />
      {controls && (
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">
            끌어서 회전 · 휠로 확대. 변위는 질량 정규화된 상대값이라 크기를 과장해 표시합니다.
          </p>
          {peak > 0 && (
            <div className="mt-1 flex items-center gap-2">
              <span className="text-muted-foreground text-xs">0</span>
              {/* 3D 와 같은 마디로 그린다 — 색을 바꾸면 함께 바뀐다. */}
              <div className="h-2 w-32 rounded" style={{ background: gradientOf(colormap) }} />
              <span className="text-muted-foreground text-xs">
                {peak.toPrecision(3)} (상대 변위)
              </span>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ColormapSelect />
          <DisplayToggles />
          <PartPicker parts={parts} hidden={hidden} onChange={setHidden} />
          <label className="text-muted-foreground flex items-center gap-2 text-xs">
            배율
            <input
              type="range"
              min={0.02}
              max={0.6}
              step={0.01}
              value={ratio}
              onChange={(event) => setRatio(Number(event.target.value))}
              className="w-28"
              aria-label="변위 과장 배율"
            />
            <span className="w-10 font-mono">{Math.round(ratio * 100)}%</span>
          </label>
          <Button variant="outline" size="sm" onClick={() => setPlaying((on) => !on)}>
            {playing ? '정지' : '재생'}
          </Button>
          <Button variant="outline" size="sm" onClick={toggleFullscreen}>
            전체 화면
          </Button>
        </div>
      </div>
      )}
      {error && <p className="text-destructive mt-2 text-sm">{error}</p>}
    </div>
  )
}
