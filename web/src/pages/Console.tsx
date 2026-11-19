import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { Bot, CircleSlash } from 'lucide-react'
import type { DemoState, Overview } from '../api'
import { api } from '../api'
import { DemoPanel } from '../components/DemoPanel'
import { IncidentCard } from '../components/IncidentCard'
import { TicketRow } from '../components/TicketRow'

const POLL_MS = 2000

const KPIS: { key: keyof Overview['counts']; label: string; tone?: string }[] = [
  { key: 'open_incidents', label: 'Open incidents', tone: 'alert' },
  { key: 'tickets', label: 'Tickets received' },
  { key: 'linked', label: 'Linked to an incident' },
  { key: 'answered_automatically', label: 'Answered without a person', tone: 'good' },
  { key: 'awaiting_approval', label: 'Waiting for approval', tone: 'warn' },
  { key: 'escalated', label: 'Escalated to a person' },
]

export default function Console() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [demo, setDemo] = useState<DemoState | null>(null)
  const [offline, setOffline] = useState(false)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState<'all' | 'awaiting_approval' | 'escalated'>('all')
  const timer = useRef<number>()

  const refresh = useCallback(async () => {
    try {
      const [nextOverview, nextDemo] = await Promise.all([api.overview(), api.demoState()])
      setOverview(nextOverview)
      setDemo(nextDemo)
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  useEffect(() => {
    document.title = 'Console · Sentinel Desk'
    refresh()
    timer.current = window.setInterval(() => {
      if (!document.hidden) refresh() // no polling while the tab is in the background
    }, POLL_MS)
    return () => window.clearInterval(timer.current)
  }, [refresh])

  useEffect(() => {
    if (!error) return
    const id = window.setTimeout(() => setError(''), 6000)
    return () => window.clearTimeout(id)
  }, [error])

  const tickets = (overview?.tickets ?? []).filter((t) => filter === 'all' || t.status === filter)
  const incidents = overview?.incidents ?? []

  return (
    <>
      <main>
        <div className="console-head">
          <h1>Console</h1>
          <Link className={`model ${overview?.model ? 'on' : ''}`} to="/settings#group-model">
            {overview?.model ? <Bot size={15} aria-hidden="true" /> : <CircleSlash size={15} aria-hidden="true" />}
            {overview?.model ? `Agents on ${overview.model}` : 'No model configured: rules and runbooks only'}
          </Link>
        </div>

        {offline && (
          <p className="banner" role="alert">
            The platform is not answering on /api. Start it with <code>uvicorn sentineldesk.api:app</code>.
          </p>
        )}
        {error && <p className="banner" role="alert">{error}</p>}

        <dl className="kpis">
          {KPIS.map(({ key, label, tone }) => {
            const value = overview?.counts[key] ?? 0
            return (
              <div key={key} className={`kpi ${value > 0 && tone ? tone : ''}`}>
                <dd>{overview ? value : '–'}</dd>
                <dt>{label}</dt>
              </div>
            )
          })}
        </dl>

        <DemoPanel demo={demo} onChanged={refresh} onError={setError} />

        <div className="columns">
          <section aria-labelledby="incidents-title">
            <h2 id="incidents-title">Incidents</h2>
            {incidents.length === 0 ? (
              <p className="empty">
                Nothing is broken. Use the demo controls above to break a feature, then watch the incident open here.
              </p>
            ) : (
              <div className="incident-list">
                <AnimatePresence initial={false}>
                  {incidents.map((incident) => (
                    <IncidentCard key={incident.id} incident={incident} onChanged={refresh} onError={setError} />
                  ))}
                </AnimatePresence>
              </div>
            )}
          </section>

          <section aria-labelledby="tickets-title">
            <div className="section-head">
              <h2 id="tickets-title">Tickets</h2>
              <div className="filters" role="group" aria-label="Filter tickets">
                {([['all', 'All'], ['awaiting_approval', 'Needs approval'], ['escalated', 'Escalated']] as const).map(
                  ([value, label]) => (
                    <button key={value} type="button" className={`chip ${filter === value ? 'active' : ''}`}
                      aria-pressed={filter === value} onClick={() => setFilter(value)}>
                      {label}
                    </button>
                  ),
                )}
              </div>
            </div>
            {tickets.length === 0 ? (
              <p className="empty">
                {filter === 'all' ? 'No ticket yet. Send a few from the demo controls.' : 'No ticket in this state.'}
              </p>
            ) : (
              <ul className="ticket-list">
                {tickets.map((ticket) => (
                  <TicketRow key={ticket.id} ticket={ticket} onChanged={refresh} onError={setError} />
                ))}
              </ul>
            )}
          </section>
        </div>
      </main>
    </>
  )
}
