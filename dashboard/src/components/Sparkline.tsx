import { memo } from 'react'
import { statusColor, type Status } from '@/domain/status'

/** Area sparkline: status colour: green nominal, yellow warning, red critical. */
export const Sparkline = memo(function Sparkline({ values, status = 'ok', height = 34, color }: {
  values: number[]; status?: Status; height?: number; color?: string
}) {
  const c = color ?? statusColor[status]
  if (values.length < 2) return <div style={{ height }} className="rounded-control bg-muted" aria-hidden />
  const min = Math.min(...values), max = Math.max(...values)
  const span = max - min || 1
  const W = 100
  const pts = values.map((v, i) => [(i / (values.length - 1)) * W, height - 3 - ((v - min) / span) * (height - 6)] as const)
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" width="100%" height={height} aria-hidden>
      <polygon points={`0,${height} ${line} ${W},${height}`} fill={c} opacity={0.12} />
      <polyline points={line} fill="none" stroke={c} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
    </svg>
  )
})
