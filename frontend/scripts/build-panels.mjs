// 대화 안 결과 화면(MCP Apps 패널)을 **HTML 한 장씩** 굽는다 — `npm run build:panels`.
//
// 패널은 호스트(HWAX 챗 · Claude)가 격리 창(srcdoc · CSP)에 띄운다. 그 창은 바깥 파일을 받지 못하므로
// (`connect-src 'none'`, 자원은 인라인 · data: 만) 스크립트 · 스타일 · 글꼴을 모두 HTML 안에 넣는다.
// 화면마다 따로 굽는다 — 한 장에 모든 화면을 넣으면 쓰지 않는 화면까지 매번 받는다.
//
//   src/panels/views/<화면>.tsx  →  dist-panels/<화면>.html   (MCP 서버가 ui://<이름>/<화면> 으로 낸다)
//
// 한 장이 HWAX 상한(2 MiB, 포털 PANEL_HTML_MAX_BYTES)을 넘으면 실패한다 — 넘는 패널은 포털이 열지 않는데,
// 그 사실은 운영의 챗에서야 드러난다.

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { build } from 'vite'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const views = fs
  .readdirSync(path.join(root, 'src/panels/views'))
  .filter((name) => name.endsWith('.tsx') && !name.includes('.test.'))
  .map((name) => name.replace(/\.tsx$/, ''))
  .sort()
const only = process.argv.slice(2)
const chosen = only.length ? views.filter((view) => only.includes(view)) : views
const stage = path.join(root, '.panels-build')
const out = path.join(root, 'dist-panels')
const LIMIT = 2 * 1024 * 1024

fs.rmSync(stage, { recursive: true, force: true })
fs.mkdirSync(stage, { recursive: true })
fs.mkdirSync(out, { recursive: true })

/** `</script` · `</style` 가 코드 안에 있으면 HTML 파서가 거기서 태그를 닫는다. */
const guard = (code, tag) => code.replaceAll(`</${tag}`, `<\\/${tag}`)

let failed = false
for (const view of chosen) {
  const entry = path.join(stage, `${view}.html`)
  fs.writeFileSync(
    entry,
    [
      '<!doctype html>',
      '<html lang="ko">',
      '  <head>',
      '    <meta charset="UTF-8" />',
      '    <meta name="viewport" content="width=device-width, initial-scale=1.0" />',
      `    <title>${view}</title>`,
      '  </head>',
      '  <body class="bg-background text-foreground p-3">',
      '    <div id="root"></div>',
      `    <script type="module" src="/src/panels/views/${view}.tsx"></script>`,
      '  </body>',
      '</html>',
      '',
    ].join('\n'),
  )
  const dist = path.join(stage, `dist-${view}`)
  await build({
    root,
    configFile: path.join(root, 'vite.config.ts'),
    logLevel: 'warn',
    // 2 MiB 에 맞춘다 — plotly 는 2D 묶음으로(3D · 산점도 행렬 · 평행 좌표는 웹에서), 3D 형상 뷰어(vtk.js,
    // 1MB 남짓)는 안내 한 줄로. 패널 쪽 길(transport)은 형상 파일을 받지 않는다.
    define: { __PLOT_KIT__: JSON.stringify('cartesian') },
    resolve: {
      alias: [
        { find: /^plotly\.js-dist-min$/, replacement: 'plotly.js-cartesian-dist-min' },
        { find: /^@\/shared\/viewer\/MeshViewer$/, replacement: path.join(root, 'src/panels/MeshNote.tsx') },
      ],
    },
    build: {
      outDir: dist,
      emptyOutDir: true,
      // 글꼴 · 그림까지 data: 로 — 격리 창은 파일을 따로 받지 못한다.
      assetsInlineLimit: 64 * 1024 * 1024,
      cssCodeSplit: false,
      modulePreload: false,
      chunkSizeWarningLimit: LIMIT / 1024,
      rollupOptions: {
        input: entry,
        // 나중에 받는 덩어리(import())도 한 장에 — 받을 길이 없다.
        output: { codeSplitting: false },
      },
    },
  })
  const builtHtml = path.join(dist, path.relative(root, entry))
  let page = fs.readFileSync(builtHtml, 'utf-8')
  const assets = path.join(dist, 'assets')
  page = page.replace(/<link rel="modulepreload"[^>]*>\s*/g, '')
  page = page.replace(/<link rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/g, (_, href) => {
    const css = fs.readFileSync(path.join(assets, path.basename(href)), 'utf-8')
    return `<style>${guard(css, 'style')}</style>`
  })
  page = page.replace(/<script type="module"[^>]*src="([^"]+)"[^>]*><\/script>/g, (_, src) => {
    const js = fs.readFileSync(path.join(assets, path.basename(src)), 'utf-8')
    return `<script type="module">${guard(js, 'script')}</script>`
  })
  const left = page.match(/(?:src|href)="\.?\/?assets\/[^"]+"/g)
  if (left) {
    console.error(`✗ ${view}: 묶지 못한 바깥 파일이 남았습니다 — ${left.join(', ')}`)
    failed = true
    continue
  }
  const bytes = Buffer.byteLength(page, 'utf-8')
  fs.writeFileSync(path.join(out, `${view}.html`), page)
  const size = `${(bytes / 1024).toFixed(0)} KiB`
  if (bytes > LIMIT) {
    console.error(`✗ ${view}: ${size} — HWAX 패널 상한 2 MiB 를 넘습니다(포털이 열지 않는다)`)
    failed = true
  } else {
    console.log(`✓ ${view}.html ${size}`)
  }
}
fs.rmSync(stage, { recursive: true, force: true })
if (failed) process.exit(1)
