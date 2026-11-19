import { useEffect, useId, useState } from 'react'
import { motion } from 'framer-motion'
import { Check, ChevronDown, X } from 'lucide-react'
import type { Ticket } from '../api'
import { api } from '../api'

const STATUS = {
  new: 'New',
  answered: 'Answered',
  awaiting_approval: 'Needs approval',
  escalated: 'Escalated',
} as const

function outcome(ticket: Ticket): string {
  if (ticket.status === 'answered' && ticket.decided_by === 'auto') return `Linked to incident #${ticket.incident_id}`
  if (ticket.status === 'answered') return 'Reply approved'
  return STATUS[ticket.status]
}

export function TicketRow({ ticket, onChanged, onError }: {
  ticket: Ticket
  onChanged: () => void
  onError: (message: string) => void
}) {
  const waiting = ticket.status === 'awaiting_approval'
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(ticket.reply)
  const [busy, setBusy] = useState(false)
  const panelId = useId()
  const draftId = useId()

  // The server may replace a draft (for example when an incident adopts the ticket).
  useEffect(() => setDraft(ticket.reply), [ticket.reply])

  const decide = async (approve: boolean) => {
    setBusy(true)
    try {
      await api.decideTicket(ticket.id, approve, approve && draft !== ticket.reply ? draft : '')
      onChanged()
    } catch (error) {
      onError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <motion.li
      layout="position"
      className={`ticket ${ticket.status} ${ticket.decided_by}`}
      initial={{ opacity: 0, x: 16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.22 }}
    >
      <button type="button" className="ticket-head" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls={panelId}>
        <span className={`pill ${ticket.status} ${ticket.decided_by}`}>{outcome(ticket)}</span>
        <span className="ticket-text">{ticket.text}</span>
        <span className="ticket-meta">
          <code>{ticket.intent}</code> · {Math.round(ticket.confidence * 100)}%
        </span>
        <ChevronDown size={16} className={`chevron ${open ? 'open' : ''}`} aria-hidden="true" />
      </button>

      {open && (
        <div className="ticket-body" id={panelId}>
          <p className="label">#{ticket.id} · {ticket.customer}</p>

          <ol className="trace">
            {ticket.trace.map((step, i) => (
              <li key={i} className={step.ok === false ? 'failed' : ''}>
                <span className="trace-by">{step.by}</span>
                <span>{step.detail}</span>
              </li>
            ))}
          </ol>

          {waiting ? (
            <div className="approval">
              <label className="label" htmlFor={draftId}>
                Draft reply{ticket.reply_sources.length > 0 && ` · from ${ticket.reply_sources.join(', ')}`}
              </label>
              <textarea id={draftId} value={draft} onChange={(e) => setDraft(e.target.value)} rows={5} maxLength={1500} />
              <div className="buttons">
                <button type="button" className="btn primary" disabled={busy || draft.trim().length < 3} onClick={() => decide(true)}>
                  <Check size={16} aria-hidden="true" /> {draft !== ticket.reply ? 'Send edited reply' : 'Approve and send'}
                </button>
                <button type="button" className="btn" disabled={busy} onClick={() => decide(false)}>
                  <X size={16} aria-hidden="true" /> Reject, hand to a person
                </button>
              </div>
            </div>
          ) : (
            ticket.reply && (
              <div className="sent">
                <p className="label">Reply sent</p>
                <p>{ticket.reply}</p>
              </div>
            )
          )}
        </div>
      )}
    </motion.li>
  )
}
