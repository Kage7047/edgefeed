import SplitText from './rb/SplitText'
import SpotlightCard from './rb/SpotlightCard'
import CountUp from './rb/CountUp'

function headline(report, best) {
  if (!report || report.scans === 0) return 'Waiting for the first scan.'
  if (report.opportunities.worth_it > 0) return `${report.opportunities.worth_it} edges worth the capital this week.`
  if (best != null && best > 0) return 'Edges exist. None pays for the capital it locks.'
  return 'No locked edge right now. Both venues agree.'
}

function Kpi({ label, value, decimals = 0, suffix = '', hint }) {
  return (
    <SpotlightCard className="kpi reveal" spotlightColor="rgba(65, 240, 168, 0.14)" intensity={0.12}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">
        {value == null ? '–' : <CountUp to={value} decimals={decimals} duration={1.1} trigger="load" />}
        {value == null ? '' : suffix}
      </span>
      {hint && <span className="kpi-hint">{hint}</span>}
    </SpotlightCard>
  )
}

export default function Hero({ report, pairs, opps }) {
  const best = pairs.reduce((m, p) => (p.spread_cents != null && p.spread_cents > m ? p.spread_cents : m), -Infinity)
  const open = opps.filter((o) => !o.closed_at).length
  const hit = report?.latency?.hit_rate
  return (
    <section className="hero" aria-labelledby="verdict">
      <div className="hero-copy reveal">
        <p className="eyebrow">Kalshi × Polymarket · net of fees, depth and lock-up</p>
        <h1 id="verdict">
          <SplitText key={headline(report, best)} text={headline(report, best)} tag="span" splitType="words"
            textAlign="left" delay={40} duration={0.9} trigger="load" />
        </h1>
        <p className="verdict">{report?.verdict ?? 'Loading the ledger…'}</p>
      </div>
      <div className="kpis">
        <Kpi label="pairs priced" value={pairs.length} hint="every 15 s" />
        <Kpi label="closest to an edge" value={Number.isFinite(best) ? best : null} decimals={2} suffix="¢"
          hint="best top-of-book, after fees" />
        <Kpi label="edges open now" value={open} hint={`${report?.opportunities?.total ?? 0} this week`} />
        <Kpi label="lead-lag hit rate" value={hit == null ? null : hit * 100} decimals={0} suffix="%"
          hint={`${report?.latency?.graded ?? 0} graded signals`} />
      </div>
    </section>
  )
}
