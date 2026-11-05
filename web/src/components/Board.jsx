import { useMemo, useState } from 'react'
import { cents, lockLabel, gameState } from '../lib/format'

const FILTERS = [
  ['all', 'All'],
  ['sports', 'Games'],
  ['curated', 'Curated'],
]
const RANGE = 4 // cents either side of zero on the bar

function Bar({ v }) {
  if (v == null) return <span className="bar empty" aria-hidden="true" />
  const clamped = Math.max(-RANGE, Math.min(RANGE, v))
  const width = (Math.abs(clamped) / RANGE) * 50
  const style = clamped >= 0 ? { left: '50%', width: `${width}%` } : { left: `${50 - width}%`, width: `${width}%` }
  const tone = v > 0 ? 'pos' : v > -0.5 ? 'near' : 'neg'
  return (
    <span className="bar" aria-hidden="true">
      <span className="zero" />
      <span className={`fill ${tone}`} style={style} />
    </span>
  )
}

const px = (v) => (v == null ? '–' : (v * 100).toFixed(1))

export default function Board({ rows, loading, selected, onSelect }) {
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')
  const shown = useMemo(
    () =>
      rows
        .filter((r) => filter === 'all' || r.source === filter)
        .filter((r) => !q || (r.label ?? r.pair_key).toLowerCase().includes(q.toLowerCase())),
    [rows, filter, q],
  )
  return (
    <section className="panel board reveal" aria-labelledby="board-h">
      <div className="panel-head">
        <h2 id="board-h">Closest to an edge</h2>
        <div className="tools">
          <div className="chips" role="tablist" aria-label="Filter pairs">
            {FILTERS.map(([k, label]) => (
              <button key={k} role="tab" type="button" aria-selected={filter === k} className={filter === k ? 'chip on' : 'chip'}
                onClick={() => setFilter(k)}>
                {label}
              </button>
            ))}
          </div>
          <input className="search" type="search" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)}
            aria-label="Filter pairs by name" />
        </div>
      </div>
      <p className="hint">
        Net edge per contract at the best price on both venues, after fees. Right of the line is a locked profit.
      </p>
      <div className="table" role="table" aria-label="Pairs by distance to a locked edge">
        <div className="tr th" role="row">
          <span role="columnheader">pair</span>
          <span role="columnheader" className="num">edge</span>
          <span role="columnheader" className="hide-sm">−4¢ · 0 · +4¢</span>
          <span role="columnheader" className="num hide-sm">K yes/no</span>
          <span role="columnheader" className="num hide-sm">P yes/no</span>
          <span role="columnheader" className="num">lock</span>
        </div>
        {loading && <div className="empty-row">Loading pairs…</div>}
        {!loading && shown.length === 0 && <div className="empty-row">No pairs match. Is the collector running?</div>}
        {shown.slice(0, 80).map((r) => (
          <button key={r.pair_key} type="button" role="row" className={`tr ${selected === r.pair_key ? 'sel' : ''}`}
            onClick={() => onSelect(selected === r.pair_key ? null : r.pair_key)} aria-pressed={selected === r.pair_key}>
            <span role="cell" className="name">
              <span className={`badge ${r.source}`}>{r.source === 'sports' ? 'game' : 'curated'}</span>
              {gameState(r.starts_at) && <span className={`badge ${gameState(r.starts_at)}`}>{gameState(r.starts_at)}</span>}
              <span className="label">{r.label ?? r.pair_key}</span>
              {r.rule_risk ? <span className="risk" title={r.rule_risk}>rules differ on edge cases</span> : null}
            </span>
            <span role="cell" className={`num edge ${r.spread_cents > 0 ? 'pos' : ''}`}>{cents(r.spread_cents)}</span>
            <span role="cell" className="hide-sm"><Bar v={r.spread_cents} /></span>
            <span role="cell" className="num hide-sm mono">{px(r.k_yes)} / {px(r.k_no)}</span>
            <span role="cell" className="num hide-sm mono">{px(r.p_yes)} / {px(r.p_no)}</span>
            <span role="cell" className="num mono">{lockLabel(r.closes_at)}</span>
          </button>
        ))}
      </div>
    </section>
  )
}
