import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Bot, CircleSlash, PlugZap, RotateCcw, Save, TriangleAlert } from 'lucide-react'
import type { Config, ConfigField, ModelTest } from '../api'
import { FieldError, configApi } from '../api'

type Draft = Record<string, string>

// What the form shows for a field: its saved value as text. A secret always starts empty.
const initial = (field: ConfigField) => (field.kind === 'secret' ? '' : String(field.value ?? ''))

function check(field: ConfigField, raw: string): string {
  if (field.kind === 'int' || field.kind === 'float') {
    if (raw.trim() === '' || Number.isNaN(Number(raw))) return 'Enter a number.'
    const n = Number(raw)
    if (field.kind === 'int' && !Number.isInteger(n)) return 'Enter a whole number.'
    if (field.min !== null && field.max !== null && (n < field.min || n > field.max)) {
      return `Must be between ${field.min} and ${field.max}.`
    }
  }
  if (field.kind === 'url' && !/^https?:\/\//.test(raw.trim())) return 'Must start with http:// or https://.'
  return ''
}

function FieldRow({ field, value, error, onChange, onBlur }: {
  field: ConfigField
  value: string
  error: string
  onChange: (value: string) => void
  onBlur: () => void
}) {
  const id = `cfg-${field.key}`
  const describedBy = `${id}-help${error ? ` ${id}-error` : ''}`
  const isNumber = field.kind === 'int' || field.kind === 'float'
  const dirty = field.kind === 'secret' ? value !== '' : value !== initial(field)

  return (
    <div className={`field ${error ? 'invalid' : ''} ${dirty ? 'dirty' : ''}`}>
      <label htmlFor={id}>
        {field.label}
        {dirty && <span className="field-flag">edited</span>}
      </label>

      {field.kind === 'select' ? (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={describedBy}>
          {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
      ) : (
        <div className="field-input">
          <input
            id={id}
            type={field.kind === 'secret' ? 'password' : isNumber ? 'number' : field.kind === 'url' ? 'url' : 'text'}
            inputMode={isNumber ? 'decimal' : undefined}
            min={field.min ?? undefined}
            max={field.max ?? undefined}
            step={field.step ?? undefined}
            value={value}
            placeholder={field.kind === 'secret' ? (field.is_set ? 'A key is saved. Type to replace it.' : 'No key saved') : undefined}
            autoComplete={field.kind === 'secret' ? 'off' : undefined}
            spellCheck={false}
            onChange={(e) => onChange(e.target.value)}
            onBlur={onBlur}
            aria-invalid={!!error}
            aria-describedby={describedBy}
          />
          {field.unit && <span className="field-unit" aria-hidden="true">{field.unit}</span>}
        </div>
      )}

      <p className="field-help" id={`${id}-help`}>
        {field.help}
        {field.kind !== 'secret' && field.default !== undefined && String(field.default) !== '' && (
          <> Default: <code>{String(field.default)}{field.unit}</code>.</>
        )}
      </p>
      {error && <p className="field-error" id={`${id}-error`} role="alert">{error}</p>}
    </div>
  )
}

export default function Settings() {
  const [config, setConfig] = useState<Config | null>(null)
  const [draft, setDraft] = useState<Draft>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [loadError, setLoadError] = useState('')
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [test, setTest] = useState<ModelTest | null>(null)

  const load = (next: Config) => {
    setConfig(next)
    setDraft(Object.fromEntries(next.fields.map((f) => [f.key, initial(f)])))
    setErrors({})
  }

  useEffect(() => {
    document.title = 'Configuration · Sentinel Desk'
    configApi.get().then(load).catch((e: Error) => setLoadError(e.message))
  }, [])

  useEffect(() => {
    if (!notice) return
    const id = window.setTimeout(() => setNotice(null), 5000)
    return () => window.clearTimeout(id)
  }, [notice])

  // Only what was edited is sent. An untouched key field means "keep the saved key".
  const changes = useMemo(() => {
    const out: Record<string, string | number> = {}
    for (const field of config?.fields ?? []) {
      const value = draft[field.key] ?? ''
      if (field.kind === 'secret') {
        if (value !== '') out[field.key] = value
      } else if (value !== initial(field)) {
        out[field.key] = field.kind === 'int' || field.kind === 'float' ? Number(value) : value.trim()
      }
    }
    return out
  }, [config, draft])
  const changeCount = Object.keys(changes).length

  // Leaving the page with unsaved edits asks first.
  useEffect(() => {
    if (changeCount === 0) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [changeCount])

  if (loadError) {
    return (
      <main className="settings">
        <p className="banner" role="alert">
          The configuration could not be loaded: {loadError} Is the platform running?
        </p>
      </main>
    )
  }
  if (!config) return <main className="settings"><p className="muted">Loading the configuration…</p></main>

  const set = (key: string, value: string) => {
    setDraft((d) => ({ ...d, [key]: value }))
    setErrors((e) => ({ ...e, [key]: '' }))
    setTest(null)
  }

  const validate = (field: ConfigField) => {
    if (field.kind === 'secret') return
    setErrors((e) => ({ ...e, [field.key]: check(field, draft[field.key] ?? '') }))
  }

  const save = async () => {
    const found: Record<string, string> = {}
    for (const field of config.fields) {
      if (field.key in changes && field.kind !== 'secret') found[field.key] = check(field, draft[field.key])
    }
    if (Object.values(found).some(Boolean)) {
      setErrors((e) => ({ ...e, ...found }))
      setNotice({ ok: false, text: 'Fix the highlighted fields first.' })
      return
    }
    setBusy(true)
    try {
      const next = await configApi.save(changes)
      load(next)
      setNotice(next.model_problem
        ? { ok: false, text: `Saved, but the model cannot be used: ${next.model_problem}` }
        : { ok: true, text: 'Saved. The platform is using the new settings.' })
    } catch (error) {
      if (error instanceof FieldError) {
        setErrors((e) => ({ ...e, [error.field]: error.message }))
        setNotice({ ok: false, text: 'One value was rejected. Nothing was saved.' })
        document.getElementById(`cfg-${error.field}`)?.focus()
      } else {
        setNotice({ ok: false, text: (error as Error).message })
      }
    } finally {
      setBusy(false)
    }
  }

  const resetAll = async () => {
    if (!window.confirm('Put every setting back to its default and remove the saved API key?')) return
    setBusy(true)
    try {
      load(await configApi.reset())
      setTest(null)
      setNotice({ ok: true, text: 'Every setting is back to its default.' })
    } catch (error) {
      setNotice({ ok: false, text: (error as Error).message })
    } finally {
      setBusy(false)
    }
  }

  const runTest = async () => {
    setBusy(true)
    setTest(null)
    try {
      setTest(await configApi.testModel())
    } catch (error) {
      setTest({ ok: false, message: (error as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="settings">
      <header className="settings-head">
        <h1>Configuration</h1>
        <p className="muted">
          Changes apply to the running platform as soon as they are saved. No restart.
        </p>
        <p className="settings-warning">
          <TriangleAlert size={16} aria-hidden="true" />
          This demo has no sign-in: anyone who can reach this server can change these settings.
        </p>
      </header>

      <div className="settings-grid">
        <nav className="settings-nav" aria-label="Sections">
          {config.groups.map((group) => <a key={group.key} href={`#group-${group.key}`}>{group.title}</a>)}
        </nav>

        <div className="settings-groups">
          {config.groups.map((group) => (
            <section key={group.key} id={`group-${group.key}`} className="settings-group" aria-labelledby={`title-${group.key}`}>
              <h2 id={`title-${group.key}`}>{group.title}</h2>
              <p className="muted">{group.description}</p>

              {group.key === 'model' && (
                <>
                  <p className={`model-status ${config.model_active ? 'on' : ''}`} role="status">
                    {config.model_active ? <Bot size={16} aria-hidden="true" /> : <CircleSlash size={16} aria-hidden="true" />}
                    {config.model_active ? `Agents are on, using ${config.model_active}.` : 'Agents are off. The platform runs on rules and runbooks.'}
                  </p>
                  <div className="presets" role="group" aria-label="Provider shortcuts">
                    <span className="label">Fill in for</span>
                    {config.presets.map((preset) => (
                      <button key={preset.name} type="button" className="chip"
                        onClick={() => { set('llm_provider', preset.llm_provider); set('llm_base_url', preset.llm_base_url) }}>
                        {preset.name}
                      </button>
                    ))}
                  </div>
                </>
              )}

              <div className="fields">
                {config.fields.filter((f) => f.group === group.key).map((field) => (
                  <FieldRow key={field.key} field={field} value={draft[field.key] ?? ''} error={errors[field.key] ?? ''}
                    onChange={(value) => set(field.key, value)} onBlur={() => validate(field)} />
                ))}
              </div>

              {group.key === 'model' && (
                <div className="model-test">
                  <button type="button" className="btn" onClick={runTest} disabled={busy || changeCount > 0 || !config.model_active}>
                    <PlugZap size={16} aria-hidden="true" /> Test the connection
                  </button>
                  <span className="muted" role="status">
                    {test ? '' : changeCount > 0 ? 'Save first, then test.' : !config.model_active ? 'Set a model name and save to test it.' : 'Sends one short request to the model.'}
                  </span>
                  {test && (
                    <p className={`test-result ${test.ok ? 'ok' : 'failed'}`} role={test.ok ? 'status' : 'alert'}>
                      {test.message}{test.reply ? ` It replied: "${test.reply}"` : ''}
                    </p>
                  )}
                </div>
              )}
            </section>
          ))}

          <button type="button" className="btn ghost" onClick={resetAll} disabled={busy}>
            <RotateCcw size={16} aria-hidden="true" /> Reset everything to defaults
          </button>
        </div>
      </div>

      <AnimatePresence>
        {(changeCount > 0 || notice) && (
          <motion.div className="savebar" initial={{ y: 80, opacity: 0 }} animate={{ y: 0, opacity: 1 }}
            exit={{ y: 80, opacity: 0 }} transition={{ duration: 0.25 }}>
            <span className={notice ? (notice.ok ? 'ok' : 'failed') : ''} role="status">
              {notice ? notice.text : `${changeCount} unsaved ${changeCount === 1 ? 'change' : 'changes'}`}
            </span>
            {changeCount > 0 && (
              <div className="savebar-buttons">
                <button type="button" className="btn" disabled={busy} onClick={() => load(config)}>Discard</button>
                <button type="button" className="btn primary" disabled={busy} onClick={save}>
                  <Save size={16} aria-hidden="true" /> {busy ? 'Saving…' : 'Save'}
                </button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  )
}
