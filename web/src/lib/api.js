async function get(path) {
  const r = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!r.ok && r.status !== 503) throw new Error(`${path}: ${r.status}`)
  return r.json()
}

export const api = {
  health: () => get('/healthz'),
  pairs: () => get('/api/pairs'),
  series: (key, hours = 6) => get(`/api/pairs/${encodeURIComponent(key)}/series?hours=${hours}`),
  opportunities: () => get('/api/opportunities?limit=60'),
  signals: () => get('/api/signals?limit=30'),
  events: () => get('/api/events?limit=20'),
  report: () => get('/api/report?days=7'),
}
