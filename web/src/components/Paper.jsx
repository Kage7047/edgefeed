import { ago, cents, usd } from '../lib/format'

// What a fast bot would have got: each new edge is re-fetched at once and "taken" at a fixed size,
// then settled with the venues' real results.
export default function Paper({ items, summary }) {
  const s = summary ?? {}
  return (
    <section className="panel paper reveal" aria-labelledby="paper-h">
      <div className="panel-head">
        <h2 id="paper-h">Paper trades</h2>
        <span className="count">{s.filled ?? 0} filled · {s.missed ?? 0} missed</span>
      </div>
      <dl className="paper-stats">
        <div><dt>fill rate</dt><dd>{s.fill_rate == null ? '–' : `${Math.round(s.fill_rate * 100)}%`}</dd></div>
        <div><dt>re-check</dt><dd>{s.recheck_ms_p50 == null ? '–' : `${Math.round(s.recheck_ms_p50)} ms`}</dd></div>
        <div><dt>settled P&amp;L</dt><dd className={s.pnl > 0 ? 'pos' : s.pnl < 0 ? 'neg' : ''}>{usd(s.pnl ?? 0)}</dd></div>
        <div><dt>broken hedges</dt><dd className={s.broken_hedges ? 'neg' : ''}>{s.broken_hedges ?? 0}</dd></div>
      </dl>
      {items.length === 0 && (
        <p className="muted">
          No paper trades yet. When an edge opens, both books are fetched again straight away and the edge is
          “taken” at a fixed size if it is still there; settlement uses the venues’ real results.
        </p>
      )}
      <ul className="paper-list">
        {items.slice(0, 10).map((t) => (
          <li key={t.id}>
            <span className={`tag ${t.status === 'missed' ? 'miss' : t.status === 'settled' ? (t.note ? 'warn' : 'hit') : 'pending'}`}>
              {t.status}
            </span>
            <span className="sig-text">
              {t.label} · saw {cents(t.seen_cents)}
              {t.status !== 'missed' && <> · got {cents(t.fill_cents)} ×{Math.round(t.contracts)}</>}
              {t.status === 'settled' && <> · <b className={t.pnl >= 0 ? 'pos' : 'neg'}>{usd(t.pnl)}</b></>}
              {t.note && <span className="opp-warn"> {t.note}</span>}
            </span>
            <span className="muted small">{Math.round(t.latency_ms)} ms · {ago(t.opened_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
