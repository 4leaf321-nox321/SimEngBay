/**
 * VTP 하나를 그리는 3D 뷰어 — 회전 · 컬러바 · **모드 형상 애니메이션.**
 *
 * ## 왜 변위를 화면에서 흔드나
 *
 * 모달의 변위는 **질량 정규화된 상대값**이다(절대 크기가 아니다). 그대로 그리면 아무것도 안
 * 움직인 그림이 나오고, 고정 배율로 과장하면 모델마다 다르게 보인다. 그래서 모델 크기 대비
 * 비율로 배율을 정하고, `sin(t)` 로 흔든다 — **정지 화면으로는 굽힘과 비틀림이 잘 안 갈린다.**
 *
 * ## vtk.js 를 여기서만 import 한다
 *
 * 이 파일은 `lazy()` 로만 불린다(`shared/viewer/index.ts`). 화면이 직접 vtk.js 를 부르면 그
 * 덩어리가 첫 로드에 실린다.
 */

import { useEffect, useRef, useState } from 'react'

import { Button } from '@/shared/components/ui/button'
import { cn } from '@/shared/lib/utils'

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
  playingRef.current = playing

  useEffect(() => {
    if (!host.current) return
    const container = host.current
    let disposed = false
    let cleanup: (() => void) | undefined

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
        ] = await Promise.all([
          import('@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow'),
          import('@kitware/vtk.js/IO/XML/XMLPolyDataReader'),
          import('@kitware/vtk.js/Rendering/Core/Mapper'),
          import('@kitware/vtk.js/Rendering/Core/Actor'),
          import('@kitware/vtk.js/Rendering/Core/ColorTransferFunction'),
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

        const view = vtkFullScreenRenderWindow.newInstance({
          container,
          containerStyle: { height: '100%', width: '100%', position: 'relative' },
          background: [0, 0, 0, 0],
        })
        const renderer = view.getRenderer()
        const renderWindow = view.getRenderWindow()

        const lookup = vtkColorTransferFunction.newInstance()
        // viridis 와 같은 순서 — 썸네일(PyVista)과 색이 어긋나면 같은 모드가 달라 보인다.
        lookup.addRGBPoint(0, 0.267, 0.005, 0.329)
        lookup.addRGBPoint(peak * 0.5, 0.129, 0.567, 0.551)
        lookup.addRGBPoint(peak, 0.993, 0.906, 0.144)

        polyData.getPointData().setActiveScalars('magnitude')
        const mapper = vtkMapper.newInstance({ interpolateScalarsBeforeMapping: true })
        mapper.setInputData(polyData)
        mapper.setLookupTable(lookup)
        mapper.setScalarRange(0, peak)

        const actor = vtkActor.newInstance()
        actor.setMapper(mapper)
        renderer.addActor(actor)

        // 컬러바는 **HTML 로 그린다**(아래 범례). 캔버스 안에 그리면 테마(밝게 · 어둡게)를
        // 따라가지 않아 어두운 화면에서 검은 글씨가 된다.
        setPeak(peak)

        renderer.resetCamera()
        renderWindow.render()

        let animationFrame = 0
        let lastScale = -1
        const started = performance.now()
        const animate = () => {
          if (disposed) return
          const scale = scaleFor(ratioRef.current)
          if ((playingRef.current || scale !== lastScale) && scale > 0) {
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
          cancelAnimationFrame(animationFrame)
          observer.disconnect()
          // **하나라도 빠뜨리면 WebGL 컨텍스트가 남는다.** 브라우저는 컨텍스트를 몇 개까지만
          // 주므로, 모드를 여러 번 바꾸면 그 뒤로 아무것도 안 그려진다.
          actor.delete()
          mapper.delete()
          view.delete()
        }
      } catch (caught) {
        if (disposed) return
        const said = caught instanceof Error ? caught.message : '그리지 못했습니다.'
        // WebGL 이 없는 환경(원격 데스크톱 · 그래픽 드라이버 문제)에서는 vtk.js 가 컨텍스트를
        // 못 만든다. 그때 **썸네일은 그대로 보이므로** 뷰어만 안 되는 것임을 말해 준다.
        setError(
          /webgl|context/i.test(said)
            ? `3D 뷰어를 띄울 수 없습니다(WebGL). 썸네일은 그대로 볼 수 있습니다. — ${said}`
            : said,
        )
      }
    }

    void draw()
    return () => {
      disposed = true
      cleanup?.()
    }
  }, [data, periodMs])

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
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">
            끌어서 회전 · 휠로 확대. 변위는 질량 정규화된 상대값이라 크기를 과장해 표시합니다.
          </p>
          {peak > 0 && (
            <div className="mt-1 flex items-center gap-2">
              <span className="text-muted-foreground text-xs">0</span>
              {/* viridis 와 같은 순서 — 썸네일(PyVista)과 색이 어긋나면 같은 모드가 달라 보인다. */}
              <div
                className="h-2 w-32 rounded"
                style={{
                  background:
                    'linear-gradient(to right, rgb(68,1,84), rgb(33,145,140), rgb(253,231,37))',
                }}
              />
              <span className="text-muted-foreground text-xs">
                {peak.toPrecision(3)} (상대 변위)
              </span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
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
      {error && <p className="text-destructive mt-2 text-sm">{error}</p>}
    </div>
  )
}
