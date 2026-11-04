import { cents, duration, pct, usd, ago } from '../lib/format'

function Leg({ leg }) {
  return (
    <li>
      buy <b>{leg.side.toUpperCase()}</b> on {leg.venue} ×{Math.round(leg.contracts).toLocaleString()} @ avg{' '}
      {(leg.avg_price * 100).toFixed(1)}¢
    </li>
  )
}

export default function Opportunities({ items }) {
  const open = items.filter((o) => !o.closed_at)
  const recent = items.filter((o) => o.closed_at).slice(0, 8)
  return (
    <section className="panel opps reveal" aria-labelledby="opps-h">
      <div className="panel-head">
        <h2 id="opps-h">Locked edges</h2>
        <span className="count">{open.length} open</span>
      </div>
      {items.length === 0 && (
        <p className="muted">
          None yet. An edge is logged when both legs together cost less than $1 after fees, at real depth.
        </p>
      )}
      <ul className="opp-list">
        {[...open, ...recent].map((o) => {
          const worth = o.best_apr >= 0.1 && o.best_profit >= 5
          return (
            <li key={o.id} className={`opp ${o.closed_at ? 'closed' : 'live'} ${worth ? 'worth' : ''}`}>
              <div className="opp-top">
                <span className="opp-edge">{cents(o.best_cents)}</span>
                <span className="opp-profit">{usd(o.best_profit)}</span>
                <span className={`opp-apr ${worth ? 'pos' : ''}`}>{pct(o.best_apr)} APR</span>
              </div>
              <p className="opp-label">{o.label}</p>
              <ul className="legs">{(o.best_snapshot?.legs ?? []).map((l) => <Leg key={l.venue} leg={l} />)}</ul>
              <p className="opp-meta">
                {o.closed_at ? `lasted ${duration(o.opened_at, o.closed_at)}` : `open ${duration(o.opened_at)}`} ·{' '}
                {o.scans_seen} scans · {o.lock_days < 2 ? `${(o.lock_days * 24).toFixed(0)}h` : `${o.lock_days.toFixed(0)}d`}{' '}
                lock · {ago(o.opened_at)}
              </p>
              {o.warnings?.length > 0 && <p className="opp-warn">{o.warnings.join(' · ')}</p>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
