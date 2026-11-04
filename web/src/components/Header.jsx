import { ago } from '../lib/format'

export default function Header({ health, pairs, reduced, onMotion }) {
  const ok = health?.status === 'ok'
  const last = health?.last_scan ?? health?.detail?.last_scan
  const bySource = pairs.reduce((acc, p) => ((acc[p.source] = (acc[p.source] ?? 0) + 1), acc), {})
  return (
    <header className="top reveal">
      <a className="brand" href="/" aria-label="EdgeFeed home">
        <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
          <path d="M5 22l7-8 5 4 10-11" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span>edgefeed</span>
      </a>
      <div className="status" role="status" aria-live="polite">
        <span className={`pulse ${ok ? 'on' : 'off'}`} aria-hidden="true" />
        <span>{ok ? 'live' : health ? 'stale' : 'connecting'}</span>
        <span className="sep">·</span>
        <span className="nowrap"><span className="hide-sm">scan </span>{ago(last)}</span>
        <span className="sep hide-sm">·</span>
        <span className="hide-sm">
          {pairs.length} pairs{bySource.sports ? ` (${bySource.sports} games)` : ''}
        </span>
      </div>
      <button className="ghost" type="button" onClick={onMotion} aria-pressed={!reduced}
        aria-label={`Animations ${reduced ? 'off' : 'on'}`}>
        <span className="hide-sm">motion </span>{reduced ? 'off' : 'on'}
      </button>
    </header>
  )
}
