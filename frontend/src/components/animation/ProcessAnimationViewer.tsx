import { useEffect, useRef, useState } from 'react'
import type { ProcessAnimation, AnimationStep } from '../../services/api'

/** 与 process-animator skill 的 interactive-template 同构的 React 版渲染器 */

const DELAY = 1600
const BAR_COLORS = {
  bar: '#94a3b8', highlight: '#fbbf24', pivot: '#f97316', sorted: '#22c55e', done: '#15803d',
}
const DEFAULT_LEGEND: [string, string][] = [
  ['#fbbf24', 'highlight：当前操作'],
  ['#f97316', 'pivot：基准'],
  ['#22c55e', 'sorted：已就位'],
  ['#94a3b8', '普通元素'],
]

// ── SVG 白名单消毒（与后端 animation_agent.sanitize_svg 同策略，双保险） ──
const SVG_TAGS = new Set([
  'svg', 'g', 'circle', 'rect', 'line', 'path', 'text', 'polygon', 'polyline',
  'marker', 'defs', 'title', 'tspan', 'ellipse', 'lineargradient',
  'radialgradient', 'stop',
])
const SVG_ATTRS = new Map([
  'fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'opacity', 'transform',
  'x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'width',
  'height', 'd', 'font-size', 'font-weight', 'text-anchor', 'font-family',
  'marker-end', 'id', 'offset', 'stop-color', 'stop-opacity', 'gradientunits',
  'paint-order', 'stroke-linejoin',
].map(name => [name, name]))
SVG_ATTRS.set('viewbox', 'viewBox')
SVG_ATTRS.set('preserveaspectratio', 'preserveAspectRatio')
SVG_ATTRS.set('gradientunits', 'gradientUnits')

const SVG_STYLE_ATTRS = new Map([
  'fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'opacity', 'rx', 'ry',
  'font-size', 'font-weight', 'text-anchor', 'font-family', 'stop-color',
  'stop-opacity',
].map(name => [name, name]))

// SVG drawing primitives cannot contain visible child nodes. Treating them as
// leaf tags also repairs common model output such as `<rect ...>` without `/>`.
const SVG_LEAF_TAGS = new Set(['circle', 'rect', 'line', 'path', 'polygon', 'polyline', 'ellipse', 'stop'])

function numericAttr(source: string, name: string): number | null {
  const match = source.match(new RegExp(`\\b${name}\\s*=\\s*["'](-?[0-9]+(?:\\.[0-9]+)?)["']`, 'i'))
  if (!match) return null
  const value = Number(match[1])
  return Number.isFinite(value) ? value : null
}

function inferViewBox(raw: string): [number, number] {
  const svgTag = raw.match(/<svg\b([^>]*)>/i)?.[1] || ''
  const existing = svgTag.match(/\bviewBox\s*=\s*["']\s*-?[0-9.]+\s+-?[0-9.]+\s+([0-9.]+)\s+([0-9.]+)\s*["']/i)
  const existingWidth = existing ? Number(existing[1]) : 0
  const existingHeight = existing ? Number(existing[2]) : 0
  const svgWidth = numericAttr(svgTag, 'width')
  const svgHeight = numericAttr(svgTag, 'height')

  let maxWidth = 0
  let maxHeight = 0
  for (const rect of raw.match(/<rect\b[^>]*>/gi) || []) {
    const width = numericAttr(rect, 'width')
    const height = numericAttr(rect, 'height')
    if (!width || width <= 0 || !height || height <= 0) continue
    const x = numericAttr(rect, 'x') || 0
    const y = numericAttr(rect, 'y') || 0
    maxWidth = Math.max(maxWidth, x + width)
    maxHeight = Math.max(maxHeight, y + height)
  }
  for (const line of raw.match(/<line\b[^>]*>/gi) || []) {
    maxWidth = Math.max(maxWidth, numericAttr(line, 'x1') || 0, numericAttr(line, 'x2') || 0)
    maxHeight = Math.max(maxHeight, numericAttr(line, 'y1') || 0, numericAttr(line, 'y2') || 0)
  }
  for (const text of raw.match(/<text\b[^>]*>/gi) || []) {
    const x = numericAttr(text, 'x') || 0
    const y = numericAttr(text, 'y') || 0
    const fontSize = numericAttr(text, 'font-size') || 14
    maxWidth = Math.max(maxWidth, x)
    maxHeight = Math.max(maxHeight, y + fontSize * 0.4)
  }

  const baseWidth = existingWidth || (svgWidth && svgWidth > 0 ? svgWidth : 0) || maxWidth || 800
  const baseHeight = existingHeight || (svgHeight && svgHeight > 0 ? svgHeight : 0) || maxHeight || 450
  return [
    maxWidth > baseWidth ? Math.ceil(maxWidth + 12) : baseWidth,
    maxHeight > baseHeight ? Math.ceil(maxHeight + 12) : baseHeight,
  ]
}

function safeStyleValue(value: string): string | null {
  const cleaned = value.trim()
  if (!cleaned || /[<>";]/.test(cleaned) || /javascript:|expression\s*\(/i.test(cleaned)) return null
  if (/url\s*\(/i.test(cleaned) && !/^url\(#[A-Za-z][\w:.-]*\)$/i.test(cleaned)) return null
  return cleaned
}

function parseStyleDeclarations(source: string): Map<string, string> {
  const declarations = new Map<string, string>()
  for (const declaration of source.split(';')) {
    const colon = declaration.indexOf(':')
    if (colon < 1) continue
    const property = declaration.slice(0, colon).trim().toLowerCase()
    const safeName = SVG_STYLE_ATTRS.get(property)
    const safeValue = safeStyleValue(declaration.slice(colon + 1))
    if (safeName && safeValue) declarations.set(safeName, safeValue)
  }
  return declarations
}

function extractCssClasses(raw: string): Map<string, Map<string, string>> {
  const classes = new Map<string, Map<string, string>>()
  for (const match of raw.matchAll(/\.([A-Za-z_][\w-]*)\s*\{([^{}]*)\}/g)) {
    classes.set(match[1], parseStyleDeclarations(match[2]))
  }
  return classes
}

function escapeAttribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
}

export function sanitizeSvg(raw: string): string {
  const [inferredWidth, inferredHeight] = inferViewBox(raw)
  const cssClasses = extractCssClasses(raw)
  const hadCssRules = cssClasses.size > 0
  const rectBounds = (raw.match(/<rect\b[^>]*>/gi) || []).flatMap(rect => {
    const x = numericAttr(rect, 'x') || 0
    const y = numericAttr(rect, 'y') || 0
    const width = numericAttr(rect, 'width') || 0
    const height = numericAttr(rect, 'height') || 0
    return width > 0 && height > 0 ? [{ x, y, width, height }] : []
  })
  let svg = raw.slice(0, 65536)
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '')
    .replace(/\.[A-Za-z_][\w-]*\s*\{[^{}]*\}/g, '')
    .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*')/gi, '')
    .replace(/javascript:/gi, '')
  svg = svg.replace(/<(\/)?(\w+)([^>]*)>/g, (_m, closing: string, rawTag: string, attrs: string) => {
    const tag = rawTag.toLowerCase()
    if (!SVG_TAGS.has(tag)) return ''
    if (closing) return SVG_LEAF_TAGS.has(tag) ? '' : `</${tag}>`

    const kept = new Map<string, string>()
    const keptNames = new Set<string>()
    const classValue = attrs.match(/\bclass\s*=\s*(?:"([^"]*)"|'([^']*)')/i)
    for (const className of (classValue?.[1] || classValue?.[2] || '').split(/\s+/).filter(Boolean)) {
      for (const [name, value] of cssClasses.get(className) || []) kept.set(name, value)
    }
    for (const mm of attrs.matchAll(/([\w-]+)\s*=\s*("[^"]*"|'[^']*')/g)) {
      const sourceName = mm[1].toLowerCase()
      if (sourceName === 'class' || sourceName === 'style') continue
      const safeName = SVG_ATTRS.get(sourceName)
      if (!safeName) continue
      kept.set(safeName, mm[2].slice(1, -1))
      keptNames.add(sourceName)
    }
    const inlineStyle = attrs.match(/\bstyle\s*=\s*(?:"([^"]*)"|'([^']*)')/i)
    for (const [name, value] of parseStyleDeclarations(inlineStyle?.[1] || inlineStyle?.[2] || '')) {
      kept.set(name, value)
    }
    if (hadCssRules && tag === 'rect' && !kept.has('fill')) {
      kept.set('fill', '#f8fafc')
      kept.set('stroke', '#334155')
      kept.set('stroke-width', '1.5')
    }
    if (hadCssRules && tag === 'text') {
      if (!kept.has('fill')) kept.set('fill', '#1e293b')
      if (!kept.has('font-family')) kept.set('font-family', 'Arial, sans-serif')
      if (!kept.has('font-size')) kept.set('font-size', '13px')
      if (!kept.has('text-anchor')) kept.set('text-anchor', 'middle')
      const x = numericAttr(attrs, 'x') || 0
      const y = numericAttr(attrs, 'y') || 0
      const insideNode = rectBounds.some(rect => (
        x >= rect.x && x <= rect.x + rect.width && y >= rect.y && y <= rect.y + rect.height
      ))
      if (!insideNode) {
        kept.set('paint-order', 'stroke')
        kept.set('stroke', '#ffffff')
        kept.set('stroke-width', '4')
        kept.set('stroke-linejoin', 'round')
      }
    }
    if (tag === 'svg') {
      kept.set('viewBox', `0 0 ${inferredWidth} ${inferredHeight}`)
      if (!keptNames.has('preserveaspectratio')) kept.set('preserveAspectRatio', 'xMidYMid meet')
      kept.set('style', 'display:block;width:100%;height:auto')
    }
    const serialized = [...kept].map(([name, value]) => `${name}="${escapeAttribute(value)}"`)
    const opening = `<${tag}${serialized.length ? ' ' + serialized.join(' ') : ''}`
    return SVG_LEAF_TAGS.has(tag) ? `${opening} />` : `${opening}>`
  })
  return svg
}

function renderBars(bars: any): string {
  const vals: number[] = bars.values || []
  if (!vals.length) return ''
  const n = vals.length
  const max = Math.max(...vals, 1)
  const W = 700, H = 260, pad = 4
  const gap = Math.min(10, (W - pad * 2) / n / 4)
  const bw = (W - pad * 2) / n - gap
  const mark = (key: string) => new Set<number>((bars[key] || []).map((i: number) => i))
  const highlight = mark('highlight'), pivot = mark('pivot'), sorted = mark('sorted'), done = mark('done')
  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" style="width:100%;height:auto;max-height:240px">`
  vals.forEach((v, i) => {
    const h = (v / max) * (H - 40)
    const x = pad + i * (bw + gap), y = H - 20 - h
    let fill = BAR_COLORS.bar
    if (done.has(i)) fill = BAR_COLORS.done
    else if (sorted.has(i)) fill = BAR_COLORS.sorted
    else if (pivot.has(i)) fill = BAR_COLORS.pivot
    else if (highlight.has(i)) fill = BAR_COLORS.highlight
    svg += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="${fill}"><title>索引 ${i} = ${v}</title></rect>`
  })
  return svg + '</svg>'
}

interface Props {
  animation: ProcessAnimation
  className?: string
}

export default function ProcessAnimationViewer({ animation, className }: Props) {
  const steps: AnimationStep[] = animation?.steps || []
  const [idx, setIdx] = useState(0)
  const [playing, setPlaying] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const hasBars = steps.some(s => s.bars)
  const legend = animation?.legend?.length ? animation.legend : hasBars ? DEFAULT_LEGEND : []

  useEffect(() => {
    if (!playing) return
    const t = setInterval(() => setIdx(i => i + 1), DELAY)
    return () => clearInterval(t)
  }, [playing])

  useEffect(() => {
    if (playing && idx >= steps.length - 1) setPlaying(false)
  }, [idx, playing, steps.length])

  useEffect(() => { setIdx(0); setPlaying(false) }, [animation?.id])

  const step = steps[Math.min(idx, Math.max(steps.length - 1, 0))]
  const go = (i: number) => {
    setPlaying(false)
    setIdx(Math.max(0, Math.min(steps.length - 1, i)))
  }
  const toggle = () => {
    if (steps.length < 2) return
    if (playing) { setPlaying(false); return }
    if (idx >= steps.length - 1) setIdx(0)
    setPlaying(true)
  }

  if (!steps.length) return null

  // 静态图模式：只有一张 SVG，无控制条/图例/步骤文案
  if (animation?.kind === 'static') {
    const svg = steps[0]?.svg ? sanitizeSvg(steps[0].svg) : ''
    return (
      <figure className={`my-4 rounded-xl border border-gray-200 bg-white overflow-hidden ${className || ''}`}>
        {animation.title && (
          <figcaption className="px-4 pt-3 text-sm font-bold text-gray-900">{animation.title}</figcaption>
        )}
        <div
          className="px-4 py-4 overflow-x-auto [&_svg]:block [&_svg]:w-full [&_svg]:h-auto"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </figure>
    )
  }

  const showBars = !!step?.bars
  const showSvg = !!step?.svg
  const svgSafe = step?.svg ? sanitizeSvg(step.svg) : ''

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onKeyDown={e => {
        if (e.key === 'ArrowRight') go(idx + 1)
        else if (e.key === 'ArrowLeft') go(idx - 1)
        else if (e.key === ' ') { e.preventDefault(); toggle() }
      }}
      className={`my-4 rounded-xl border border-gray-200 bg-white overflow-hidden focus:outline-none focus:ring-2 focus:ring-primary-200 ${className || ''}`}
    >
      <div className="px-4 pt-3">
        {animation?.title && <div className="text-sm font-bold text-gray-900">{animation.title}</div>}
        {animation?.subtitle && <div className="text-xs text-gray-500 mt-0.5">{animation.subtitle}</div>}
      </div>

      <div className="min-h-[260px] flex items-center justify-center px-4 py-4">
        {showBars && <div dangerouslySetInnerHTML={{ __html: renderBars(step.bars) }} />}
        {showSvg && <div className="w-full [&_svg]:block [&_svg]:w-full [&_svg]:h-auto" dangerouslySetInnerHTML={{ __html: svgSafe }} />}
        {!showBars && !showSvg && (
          <div className="text-base text-gray-400 text-center max-w-md leading-relaxed">{step?.text}</div>
        )}
      </div>

      {legend.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 pb-2 text-xs text-gray-500">
          {legend.map(([c, label], i) => (
            <span key={i} className="inline-flex items-center gap-1">
              <i className="inline-block w-3 h-3 rounded-sm" style={{ background: c }} />
              {label}
            </span>
          ))}
        </div>
      )}

      <div className="border-t border-gray-100 px-4 py-3">
        <div className="text-sm font-semibold text-gray-900">{step?.title}</div>
        <p className="text-sm text-gray-600 leading-relaxed mt-1 whitespace-pre-line">{step?.text}</p>
      </div>

      <div className="flex items-center gap-2 border-t border-gray-100 bg-gray-50 px-4 py-2.5">
        <button
          onClick={() => go(idx - 1)}
          disabled={idx === 0}
          className="px-2.5 py-1 rounded-md border border-gray-200 bg-white text-xs text-gray-700 hover:border-primary-400 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          ← 上一步
        </button>
        <button
          onClick={toggle}
          disabled={steps.length < 2}
          className="px-2.5 py-1 rounded-md bg-primary-600 text-white text-xs hover:bg-primary-700 disabled:opacity-40"
        >
          {playing ? '⏸ 暂停' : '▶ 播放'}
        </button>
        <button
          onClick={() => go(idx + 1)}
          disabled={idx >= steps.length - 1}
          className="px-2.5 py-1 rounded-md border border-gray-200 bg-white text-xs text-gray-700 hover:border-primary-400 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          下一步 →
        </button>
        <input
          type="range"
          min={0}
          max={Math.max(steps.length - 1, 0)}
          value={idx}
          onChange={e => go(Number(e.target.value))}
          className="flex-1 accent-primary-600"
        />
        <span className="text-xs text-gray-500 tabular-nums min-w-[52px] text-center">
          {idx + 1} / {steps.length}
        </span>
      </div>
    </div>
  )
}
