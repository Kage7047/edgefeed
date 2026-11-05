// The API returns UTC timestamps; SQLite drops the offset, so treat a bare one as UTC.
const toDate = (iso) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)

export const cents = (v, digits = 2) => (v == null ? '–' : `${v >= 0 ? '+' : ''}${v.toFixed(digits)}¢`)
export const usd = (v) =>
  v == null ? '–' : `$${v.toLocaleString('en-US', { maximumFractionDigits: Math.abs(v) < 100 ? 2 : 0 })}`
export const pct = (v, digits = 1) => (v == null ? '–' : `${(v * 100).toFixed(digits)}%`)

export function ago(iso) {
  if (!iso) return 'never'
  const s = Math.max(0, (Date.now() - toDate(iso)) / 1000)
  if (s < 60) return `${Math.round(s)}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

export function duration(fromIso, toIso) {
  const s = Math.max(0, ((toIso ? toDate(toIso) : new Date()) - toDate(fromIso)) / 1000)
  if (s < 90) return `${Math.round(s)}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  return `${(s / 3600).toFixed(1)}h`
}

export function lockLabel(closesAt) {
  if (!closesAt) return '–'
  const d = (toDate(closesAt) - Date.now()) / 86400000
  if (d < 1) return `${Math.max(0, Math.round(d * 24))}h`
  if (d < 60) return `${Math.round(d)}d`
  return `${(d / 365).toFixed(1)}y`
}

/** live: game in play (up to 4h after start) · soon: starts within 20 minutes · null otherwise */
export function gameState(startsAt) {
  if (!startsAt) return null
  const m = (Date.now() - toDate(startsAt)) / 60000
  if (m >= 0 && m <= 240) return 'live'
  if (m < 0 && m >= -20) return 'soon'
  return null
}

export const time = (iso) => toDate(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
