import { useEffect, useRef } from 'react'
import { gsap } from 'gsap'
import { useGSAP } from '@gsap/react'
import { api } from '../lib/api'
import { usePoll } from '../lib/usePoll'
import { cents, time } from '../lib/format'
import { reducedMotion } from '../lib/motion'
import { scrollToTarget } from '../lib/smooth'

const W = 640
const H = 180
const PAD = 26

function path(points, x, y) {
  return points
    .filter((p) => p.v != null)
    .map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`)
    .join('')
}

function Chart({ rows }) {
  const ref = useRef(null)
  useGSAP(
    () => {
      if (reducedMotion() || !ref.current) return
      ref.current.querySelectorAll('path.line').forEach((el) => {
        const len = el.getTotalLength()
        gsap.fromTo(el, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 1.1, ease: 'power2.out' })
      })
    },
    { scope: ref, dependencies: [rows.length > 0] },
  )
  if (rows.length < 2) return <p className="muted">Collecting history for this pair…</p>
  const ts = rows.map((r) => new Date(r.ts.endsWith('Z') || r.ts.includes('+') ? r.ts : r.ts + 'Z').getTime())
  const t0 = ts[0]
  const t1 = ts[ts.length - 1] || t0 + 1
  const mids = rows.flatMap((r) => [r.k_mid, r.p_mid]).filter((v) => v != null)
  const lo = Math.min(...mids) - 1
  const hi = Math.max(...mids) + 1
  const x = (t) => PAD + ((t - t0) / (t1 - t0 || 1)) * (W - PAD * 2)
  const y = (v) => H - PAD - ((v - lo) / (hi - lo || 1)) * (H - PAD * 2)
  const k = rows.map((r, i) => ({ t: ts[i], v: r.k_mid }))
  const p = rows.map((r, i) => ({ t: ts[i], v: r.p_mid }))
  return (
    <svg ref={ref} className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Kalshi and Polymarket YES mid prices over time, ${rows.length} samples`}>
      {[lo, (lo + hi) / 2, hi].map((v) => (
        <g key={v}>
          <line x1={PAD} x2={W - PAD} y1={y(v)} y2={y(v)} className="grid-line" />
          <text x={4} y={y(v) + 4} className="axis">{v.toFixed(0)}¢</text>
        </g>
      ))}
      <path className="line k" d={path(k, x, y)} />
      <path className="line p" d={path(p, x, y)} />
      <text x={PAD} y={H - 6} className="axis">{time(rows[0].ts)}</text>
      <text x={W - PAD} y={H - 6} className="axis" textAnchor="end">{time(rows[rows.length - 1].ts)}</text>
    </svg>
  )
}

export default function PairDetail({ row, onClose }) {
  const series = usePoll(() => api.series(row.pair_key, 6), 15000, [row.pair_key])
  const box = useRef(null)
  useEffect(() => {
    if (box.current) scrollToTarget(box.current, -80)
  }, [row.pair_key])
  const rows = series.data ?? []
  const spreads = rows.map((r) => r.spread_cents).filter((v) => v != null)
  return (
    <section className="panel detail" aria-labelledby="detail-h" ref={box}>
      <div className="panel-head">
        <h2 id="detail-h">{row.label ?? row.pair_key}</h2>
        <button type="button" className="ghost" onClick={onClose} aria-label="Close pair detail">close</button>
      </div>
      <div className="legend">
        <span><i className="dot k" /> Kalshi YES mid</span>
        <span><i className="dot p" /> Polymarket YES mid</span>
        <span className="muted">6 h · best edge {cents(spreads.length ? Math.max(...spreads) : null)}</span>
      </div>
      <Chart rows={rows} />
      {row.rule_risk && <p className="risk-note">Settlement risk: {row.rule_risk}.</p>}
      <p className="muted mono small">{row.pair_key}</p>
    </section>
  )
}
