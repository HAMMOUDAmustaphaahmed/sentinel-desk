// Types mirror what sentineldesk/api.py returns.

export type Service = 'transfers' | 'cards' | 'topup' | 'atm' | 'exchange' | 'auth'

export interface TraceStep {
  step: string
  by: string
  detail: string
  ok?: boolean
}

export interface Ticket {
  id: number
  created_at: string
  customer: string
  text: string
  intent: string
  confidence: number
  feature: string
  is_problem: boolean
  status: 'new' | 'answered' | 'awaiting_approval' | 'escalated'
  reply: string
  reply_kind: '' | 'incident_status' | 'knowledge'
  reply_sources: string[]
  decided_by: '' | 'auto' | 'human'
  incident_id: number | null
  trace: TraceStep[]
}

export interface Action {
  id: number
  kind: string
  description: string
  rationale: string
  proposed_by: string
  status: 'proposed' | 'executed' | 'failed' | 'rejected'
  result: string
}

export interface ExceptionGroup {
  fingerprint: string
  type: string
  count: number
  example: string
  endpoint: string
}

export interface Incident {
  id: number
  service: Service
  source: 'logs' | 'tickets'
  status: 'open' | 'mitigated' | 'resolved'
  opened_at: string
  title: string
  reason: string
  analysis: string
  analysis_by: '' | 'agent' | 'runbook'
  linked_tickets: number
  exceptions_per_minute: number[]
  exceptions: ExceptionGroup[]
  actions: Action[]
  ticket_ids: number[]
}

export interface Overview {
  now: string
  model: string | null
  counts: {
    tickets: number
    linked: number
    answered_automatically: number
    awaiting_approval: number
    escalated: number
    open_incidents: number
    actions_waiting: number
  }
  incidents: Incident[]
  tickets: Ticket[]
}

export interface DemoState {
  bank_reachable: boolean
  faults: Partial<Record<Service, 'exception' | 'silent'>>
  services: Service[]
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    let message = `Request failed (${response.status}).`
    try {
      const data = await response.json()
      if (typeof data.detail === 'string') message = data.detail
    } catch {
      /* no JSON body */
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  overview: () => request<Overview>('/overview'),
  demoState: () => request<DemoState>('/demo/state'),
  decideTicket: (id: number, approve: boolean, reply = '') =>
    request<Ticket>(`/tickets/${id}/decision`, { approve, reply }),
  decideAction: (id: number, approve: boolean) => request<Action>(`/actions/${id}/decision`, { approve }),
  setFault: (service: Service, mode: 'exception' | 'silent' | 'off') => request('/demo/fault', { service, mode }),
  sendTickets: (service: Service, kind: 'problem' | 'question', count: number) =>
    request('/demo/tickets', { service, kind, count }),
  reset: () => request('/demo/reset', {}),
}

// ------------------------------------------------------------------ configuration

export interface ConfigField {
  key: string
  group: string
  label: string
  help: string
  kind: 'int' | 'float' | 'text' | 'url' | 'select' | 'secret'
  min: number | null
  max: number | null
  step: number | null
  unit: string
  options: string[]
  changed: boolean
  value?: string | number
  default?: string | number
  is_set?: boolean
}

export interface Config {
  groups: { key: string; title: string; description: string }[]
  fields: ConfigField[]
  presets: { name: string; llm_provider: string; llm_base_url: string }[]
  model_active: string | null
  model_problem: string
}

export interface ModelTest {
  ok: boolean
  message: string
  reply?: string
}

// A rejected setting names the field it concerns.
export class FieldError extends Error {
  constructor(public field: string, message: string) {
    super(message)
  }
}

export const configApi = {
  get: () => request<Config>('/config'),
  save: async (changes: Record<string, string | number>): Promise<Config> => {
    const response = await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    })
    const data = await response.json().catch(() => null)
    if (response.ok) return data as Config
    const detail = data?.detail
    if (detail && typeof detail === 'object' && 'field' in detail) throw new FieldError(detail.field, detail.message)
    throw new Error(`Saving failed (${response.status}).`)
  },
  reset: () => request<Config>('/config/reset', {}),
  testModel: () => request<ModelTest>('/config/test-model', {}),
}
