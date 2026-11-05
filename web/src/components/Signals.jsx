import { ago } from '../lib/format'

export default function Signals({ items }) {
  return (
    <section className="panel signals reveal" aria-labelledby="sig-h">
      <div className="panel-head">
        <h2 id="sig-h">Lead-lag</h2>
        <span className="count">{items.length}</span>
      </div>
      {items.length === 0 && (
        <p className="muted">
          Fires when one venue reprices by 2¢+ while the other has not moved (tight books only), then grades
          ten minutes later: did the laggard catch up (hit), or did the leader snap back (revert)?
        </p>
      )}
      <ul className="sig-list">
        {items.slice(0, 10).map((s) => (
          <li key={s.id}>
            <span className={`tag ${s.outcome ?? 'pending'}`}>{s.outcome ?? 'pending'}</span>
            <span className="sig-text">
              <b>{s.leader}</b> moved {s.leader_move > 0 ? '+' : ''}
              {s.leader_move.toFixed(1)}¢; {s.laggard} {s.gap.toFixed(1)}¢ behind · {s.label}
            </span>
            <span className="muted small">{ago(s.ts)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
