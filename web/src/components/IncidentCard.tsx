import { useState } from 'react'
import { motion } from 'framer-motion'
import { Check, FileWarning, MessagesSquare, ScrollText, X } from 'lucide-react'
import type { Incident } from '../api'
import { api } from '../api'

// Exceptions per minute over the last half hour. The last bar is the current minute.
function Sparkline({ values }: { values: number[] }) {
  const max = Math.max(...values, 1)
  return (
    <svg className="spark" viewBox={`0 0 ${values.length * 6} 32`} preserveAspectRatio="none" aria-hidden="true">
      {values.map((v, i) => {
        const h = v === 0 ? 1 : Math.max(2, (v / max) * 30)
        return <rect key={i} x={i * 6} y={32 - h} width="4" height={h} rx="1" className={v === 0 ? 'zero' : ''} />
      })}
    </svg>
  )
}

const STATUS_LABEL = { open: 'Open', mitigated: 'Fix applied, watching', resolved: 'Resolved' } as const

export function IncidentCard({ incident, onChanged, onError }: {
  incident: Incident
  onChanged: () => void
  onError: (message: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const total = incident.exceptions_per_minute.reduce((a, b) => a + b, 0)
  const pending = incident.actions.find((a) => a.status === 'proposed')
  const done = incident.actions.filter((a) => a.status !== 'proposed')

  const decide = async (id: number, approve: boolean) => {
    setBusy(true)
    try {
      await api.decideAction(id, approve)
      onChanged()
    } catch (error) {
      onError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <motion.article
      layout
      className={`incident ${incident.status}`}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25 }}
      aria-labelledby={`incident-${incident.id}`}
    >
      <header className="incident-head">
        <div>
          <p className="eyebrow">
            <span className={`dot ${incident.status}`} aria-hidden="true" />
            {STATUS_LABEL[incident.status]} · #{incident.id} · {incident.service}
          </p>
          <h3 id={`incident-${incident.id}`}>{incident.title}</h3>
        </div>
        <span className="source">
          {incident.source === 'logs' ? <ScrollText size={14} aria-hidden="true" /> : <MessagesSquare size={14} aria-hidden="true" />}
          {incident.source === 'logs' ? 'Found in logs' : 'Found from tickets'}
        </span>
      </header>

      <p className="reason">{incident.reason}</p>

      <div className="incident-stats">
        <div>
          <span className="stat-value">{incident.linked_tickets}</span>
          <span className="stat-label">tickets linked</span>
        </div>
        {incident.source === 'logs' && (
          <div className="spark-wrap">
            <Sparkline values={incident.exceptions_per_minute} />
            <span className="stat-label">{total} exceptions in 30 min</span>
          </div>
        )}
      </div>

      {incident.exceptions.length > 0 && (
        <ul className="exceptions">
          {incident.exceptions.slice(0, 2).map((group) => (
            <li key={group.fingerprint}>
              <FileWarning size={14} aria-hidden="true" />
              <code>{group.type}</code>
              <span className="count">×{group.count}</span>
              <span className="example">{group.example}</span>
            </li>
          ))}
        </ul>
      )}

      {incident.analysis && (
        <div className="analysis">
          <p className="label">Likely cause · {incident.analysis_by === 'agent' ? 'analyst agent' : 'runbook'}</p>
          <p>{incident.analysis}</p>
        </div>
      )}

      {pending && (
        <div className="approval">
          <p className="label">Proposed action · needs your approval</p>
          <p className="action-name"><code>{pending.kind}</code> on {incident.service}</p>
          <p className="muted">{pending.description}</p>
          <p className="muted">{pending.rationale}</p>
          <div className="buttons">
            <button type="button" className="btn primary" disabled={busy} onClick={() => decide(pending.id, true)}>
              <Check size={16} aria-hidden="true" /> Approve and run
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => decide(pending.id, false)}>
              <X size={16} aria-hidden="true" /> Reject
            </button>
          </div>
        </div>
      )}

      {done.map((action) => (
        <p key={action.id} className={`action-result ${action.status}`}>
          <code>{action.kind}</code> {action.status}
          {action.result ? `: ${action.result}` : '.'}
        </p>
      ))}
    </motion.article>
  )
}
