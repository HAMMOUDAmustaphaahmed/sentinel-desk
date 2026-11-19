import { useState } from 'react'
import { MessageSquarePlus, RotateCcw, VolumeX, Wrench, Zap } from 'lucide-react'
import type { DemoState, Service } from '../api'
import { api } from '../api'

// Controls for the demonstration: break the fake bank and let customers complain.
export function DemoPanel({ demo, onChanged, onError }: {
  demo: DemoState | null
  onChanged: () => void
  onError: (message: string) => void
}) {
  const [service, setService] = useState<Service>('transfers')
  const [busy, setBusy] = useState(false)
  const fault = demo?.faults[service]

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      onChanged()
    } catch (error) {
      onError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const reset = () => {
    if (window.confirm('Clear all tickets, incidents and logs, and repair the demo bank?')) run(api.reset)
  }

  return (
    <section className="demo" aria-labelledby="demo-title">
      <div className="demo-head">
        <h2 id="demo-title">Demo controls</h2>
        <p className="muted">
          {demo === null ? 'Checking the demo bank…'
            : demo.bank_reachable ? 'The demo bank is running. Break something and watch.'
            : 'The demo bank is not reachable: faults cannot be injected, sample tickets still work.'}
        </p>
      </div>

      <div className="demo-row">
        <label htmlFor="demo-service" className="label">Feature</label>
        <select id="demo-service" value={service} onChange={(e) => setService(e.target.value as Service)}>
          {(demo?.services ?? ['transfers']).map((s) => (
            <option key={s} value={s}>{s}{demo?.faults[s] ? ` (broken: ${demo.faults[s]})` : ''}</option>
          ))}
        </select>
      </div>

      <div className="demo-buttons">
        <button type="button" className="btn danger" disabled={busy || !demo?.bank_reachable || fault === 'exception'}
          onClick={() => run(() => api.setFault(service, 'exception'))}>
          <Zap size={16} aria-hidden="true" /> Break it (raises exceptions)
        </button>
        <button type="button" className="btn danger" disabled={busy || !demo?.bank_reachable || fault === 'silent'}
          onClick={() => run(() => api.setFault(service, 'silent'))}>
          <VolumeX size={16} aria-hidden="true" /> Break it silently (no logs)
        </button>
        <button type="button" className="btn" disabled={busy || !fault}
          onClick={() => run(() => api.setFault(service, 'off'))}>
          <Wrench size={16} aria-hidden="true" /> Repair by hand
        </button>
        <button type="button" className="btn" disabled={busy} onClick={() => run(() => api.sendTickets(service, 'problem', 5))}>
          <MessageSquarePlus size={16} aria-hidden="true" /> 5 customers complain
        </button>
        <button type="button" className="btn" disabled={busy} onClick={() => run(() => api.sendTickets(service, 'question', 3))}>
          <MessageSquarePlus size={16} aria-hidden="true" /> 3 customers ask a question
        </button>
        <button type="button" className="btn ghost" disabled={busy} onClick={reset}>
          <RotateCcw size={16} aria-hidden="true" /> Start over
        </button>
      </div>
    </section>
  )
}
