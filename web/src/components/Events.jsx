import { ago } from '../lib/format'

export default function Events({ items }) {
  return (
    <section className="panel events reveal" aria-labelledby="ev-h">
      <div className="panel-head">
        <h2 id="ev-h">Rule watch</h2>
        <span className="count">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <p className="muted">Both venues&apos; rule texts are fingerprinted every scan. Any change shows up here.</p>
      ) : (
        <ul className="ev-list">
          {items.slice(0, 8).map((e) => (
            <li key={e.id}>
              <span className="tag warn">{e.kind.replace('_', ' ')}</span> {e.detail}{' '}
              <span className="muted small">{ago(e.ts)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
