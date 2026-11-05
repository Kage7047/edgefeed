import { useEffect, useMemo, useRef, useState } from 'react'
import { gsap } from 'gsap'
import { useGSAP } from '@gsap/react'
import { api } from './lib/api'
import { usePoll } from './lib/usePoll'
import { reducedMotion, setMotion, useReducedMotionState } from './lib/motion'
import { startSmoothScroll, stopSmoothScroll } from './lib/smooth'
import Header from './components/Header'
import Hero from './components/Hero'
import Board from './components/Board'
import PairDetail from './components/PairDetail'
import Opportunities from './components/Opportunities'
import Signals from './components/Signals'
import Paper from './components/Paper'
import Events from './components/Events'

gsap.registerPlugin(useGSAP)

export default function App() {
  const reduced = useReducedMotionState()
  const health = usePoll(api.health, 5000)
  const pairs = usePoll(api.pairs, 5000)
  const opps = usePoll(api.opportunities, 10000)
  const signals = usePoll(api.signals, 15000)
  const paper = usePoll(api.paper, 10000)
  const events = usePoll(api.events, 60000)
  const report = usePoll(api.report, 30000)
  const [selected, setSelected] = useState(null)
  const root = useRef(null)

  useEffect(() => {
    if (reduced) return undefined
    startSmoothScroll()
    return () => stopSmoothScroll()
  }, [reduced])

  useGSAP(
    () => {
      if (reducedMotion()) return
      gsap.from('.reveal', { opacity: 0, y: 24, duration: 0.9, ease: 'power3.out', stagger: 0.08, delay: 0.15 })
    },
    { scope: root },
  )

  const rows = pairs.data ?? []
  const current = useMemo(
    () => rows.find((r) => r.pair_key === selected) ?? null,
    [rows, selected],
  )

  return (
    <div className="app" ref={root}>
      <Header health={health.data} pairs={rows} reduced={reduced} onMotion={() => setMotion(reduced)} />
      <main>
        <Hero report={report.data} pairs={rows} opps={opps.data ?? []} />
        <div className="grid">
          <section className="col-main">
            {current && <PairDetail row={current} onClose={() => setSelected(null)} />}
            <Board rows={rows} loading={!pairs.data} selected={selected} onSelect={setSelected} />
          </section>
          <aside className="col-side">
            <Opportunities items={opps.data ?? []} />
            <Paper items={paper.data ?? []} summary={report.data?.paper} />
            <Signals items={signals.data ?? []} />
            <Events items={events.data ?? []} />
          </aside>
        </div>
      </main>
      <footer className="foot reveal">
        <p>
          Analytics only, not financial advice. EdgeFeed reads public market data from Kalshi and Polymarket; it
          holds no funds and places no orders. Prediction markets carry risk and may be restricted where you live.
        </p>
        <p className="muted">
          Fees: Kalshi round_up(0.07·C·P·(1−P)) per fill × series multiplier · Polymarket C·rate·p·(1−p) per market
          feeSchedule. APR = profit ÷ capital locked × 365 ÷ days to resolution, plus any interest or holding
          rewards the venues pay on the locked legs.
        </p>
      </footer>
    </div>
  )
}
