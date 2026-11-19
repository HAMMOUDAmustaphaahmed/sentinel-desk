import { Component, Suspense, lazy, useEffect, useRef, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { animate, motion, useInView, useReducedMotion, useScroll, useSpring } from 'framer-motion'
import { ArrowRight, Ban, FileSearch, History, ListChecks, MessagesSquare, ScrollText, UserCheck } from 'lucide-react'

// three.js loads only on this page, after the text.
const SignalScene = lazy(() => import('../components/landing/SignalScene'))

const REPO = 'https://github.com/HAMMOUDAmustaphaahmed/sentinel-desk'
const EASE = [0.22, 1, 0.36, 1] as const

// Every figure below comes from docs/evaluation.json (python -m scripts.evaluate).
const RESULTS = [
  { value: 91.6, decimals: 1, unit: '%', label: 'Intent found among 77', detail: 'On 3,080 tickets the classifier never saw' },
  { value: 7, decimals: 0, unit: ' s', label: 'To detect an outage', detail: 'Median, from the first failing request' },
  { value: 98.9, decimals: 1, unit: '%', label: 'Of links are correct', detail: '29 wrong links out of 2,626' },
  { value: 87.3, decimals: 1, unit: '%', label: 'Of affected tickets linked', detail: '2,597 of 2,976' },
  { value: 4, decimals: 0, unit: '', label: 'Complaints to spot a silent failure', detail: 'Median, with nothing in the logs' },
]

const STEPS = [
  { name: 'Triage', text: 'A small classifier names the intent and how sure it is. No model API is called to route a ticket.' },
  { name: 'Correlate', text: 'Feature, time window and confidence decide whether the ticket belongs to an open incident.' },
  { name: 'Investigate', text: 'If nothing explains it, an agent searches the knowledge base and the incidents, then decides.' },
  { name: 'Approve', text: 'A person reads the draft, edits it if needed, and sends it. Or hands the ticket to an engineer.' },
]

const GUARDRAILS = [
  { icon: UserCheck, title: 'A person approves', text: 'Replies written by the model and every recovery action wait for approval. The only automatic reply states that a known incident is open.' },
  { icon: ListChecks, title: 'Three allowed actions', text: 'Restart a service, clear a cache, turn a feature off. There is no free-form command anywhere.' },
  { icon: FileSearch, title: 'Decisions are checked by code', text: 'A reply must cite articles that exist. A link must point to an open incident. A rejected decision goes back to the model as an error.' },
  { icon: Ban, title: 'Customer text is data', text: 'It reaches the model in a delimited block, with the instruction not to act on anything written inside.' },
  { icon: History, title: 'Everything is recorded', text: 'Each automatic or human decision lands in an append-only audit table.' },
]

const PROVIDERS = ['OpenAI', 'Groq', 'Mistral', 'Gemini', 'OpenRouter', 'DeepSeek', 'Claude', 'A local server']

class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? null : this.props.children // without WebGL the page simply has no scene
  }
}

// Counts up to its value the first time it is seen. Screen readers get the final number.
function Figure({ value, decimals, unit }: { value: number; decimals: number; unit: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true, margin: '-60px' })
  const reduced = useReducedMotion()
  const final = `${value.toFixed(decimals)}${unit}`

  useEffect(() => {
    const node = ref.current
    if (!node || !inView) return
    if (reduced) {
      node.textContent = final
      return
    }
    const controls = animate(0, value, {
      duration: 1.1,
      ease: EASE,
      onUpdate: (n) => { node.textContent = `${n.toFixed(decimals)}${unit}` },
    })
    return () => controls.stop()
  }, [inView, reduced, value, decimals, unit, final])

  return (
    <>
      <span className="sr-only">{final}</span>
      <span ref={ref} aria-hidden="true">{`${(0).toFixed(decimals)}${unit}`}</span>
    </>
  )
}

// The line under the steps fills as the section scrolls past.
function Pipeline() {
  const ref = useRef<HTMLOListElement>(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start 0.8', 'end 0.55'] })
  const scaleX = useSpring(scrollYProgress, { stiffness: 120, damping: 28 })

  return (
    <ol className="lp-steps" ref={ref}>
      <motion.span className="lp-steps-line" style={{ scaleX }} aria-hidden="true" />
      {STEPS.map((step, i) => (
        <li key={step.name}>
          <span className="lp-step-num">{String(i + 1).padStart(2, '0')}</span>
          <h3>{step.name}</h3>
          <p>{step.text}</p>
        </li>
      ))}
    </ol>
  )
}

export default function Landing() {
  const story = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll({ target: story, offset: ['start start', 'end end'] })

  useEffect(() => {
    document.title = 'Sentinel Desk · Tickets and incidents, correlated'
  }, [])

  return (
    <div className="lp">
      <div className="lp-story" ref={story}>
        <div className="lp-stage">
          <SceneBoundary>
            <Suspense fallback={null}>
              <SignalScene progress={scrollYProgress} />
            </Suspense>
          </SceneBoundary>
          <p className="lp-legend" aria-hidden="true">
            <span><i className="lg-ticket" />Customer tickets</span>
            <span><i className="lg-exception" />Exceptions</span>
            <span><i className="lg-incident" />Incidents</span>
          </p>
        </div>

        <div className="lp-wrap lp-beats">
          <motion.section className="lp-beat" aria-labelledby="lp-title"
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.9, ease: EASE }}>
            <p className="lp-eyebrow">Support tickets + application logs</p>
            <h1 id="lp-title">Twenty complaints.<br /><em>One incident.</em></h1>
            <p className="lp-lede">
              A support ticket and a log exception are often two views of the same problem. Sentinel Desk links
              them, so the team investigates once and every customer is told what is going on.
            </p>
            <div className="lp-actions">
              <Link className="btn primary big" to="/console">Open the console <ArrowRight size={18} aria-hidden="true" /></Link>
              <a className="lp-link" href={REPO} target="_blank" rel="noopener noreferrer">Read the code</a>
            </div>
          </motion.section>

          <section className="lp-beat" aria-labelledby="lp-beat2">
            <p className="lp-eyebrow">What happens when a feature breaks</p>
            <h2 id="lp-beat2">Scattered signals find the incident they belong to</h2>
            <p className="lp-lede">
              Exceptions spike on a service and an incident opens within seconds. Tickets about that feature
              attach to it instead of piling up in a queue. The ones that have nothing to do with it stay where
              they are.
            </p>
          </section>
        </div>
      </div>

      <section className="lp-section" aria-labelledby="lp-directions">
        <div className="lp-wrap">
          <h2 id="lp-directions" className="lp-h2">It works in both directions</h2>
          <div className="lp-two">
            <article className="lp-panel">
              <ScrollText size={22} aria-hidden="true" />
              <h3>The logs show it</h3>
              <p>
                Exceptions on a service rise above their usual rate, or an error type appears that was never
                seen before. An incident opens, and every complaint about that feature is linked to it and
                answered with its status.
              </p>
              <p className="lp-fact"><strong>100%</strong> of 227 simulated outages detected</p>
            </article>
            <article className="lp-panel">
              <MessagesSquare size={22} aria-hidden="true" />
              <h3>Only customers notice</h3>
              <p>
                The feature fails without logging anything. When four customers report the same failure, an
                incident opens from the tickets alone. Monitoring did not see it; the support queue did.
              </p>
              <p className="lp-fact"><strong>97.3%</strong> of 73 silent failures detected</p>
            </article>
          </div>
        </div>
      </section>

      <section className="lp-section tint" aria-labelledby="lp-path">
        <div className="lp-wrap">
          <h2 id="lp-path" className="lp-h2">The path of a ticket</h2>
          <p className="lp-sub">Deterministic where it must be fast or exact. A model only where judgement is needed.</p>
          <Pipeline />
        </div>
      </section>

      <section className="lp-section" aria-labelledby="lp-results">
        <div className="lp-wrap">
          <h2 id="lp-results" className="lp-h2">Measured, not estimated</h2>
          <p className="lp-sub">
            One script reproduces every figure: the Banking77 test split for triage, then 300 simulated incidents
            on a fake clock.
          </p>
          <dl className="lp-results">
            {RESULTS.map((r) => (
              <div key={r.label}>
                <dd><Figure value={r.value} decimals={r.decimals} unit={r.unit} /></dd>
                <dt>{r.label}</dt>
                <p>{r.detail}</p>
              </div>
            ))}
          </dl>
          <p className="lp-note">
            No language model was involved in these numbers. They measure the deterministic path every ticket
            takes first. The agents are covered by tests with a scripted model, not yet evaluated against a real one.
          </p>
        </div>
      </section>

      <section className="lp-section tint" aria-labelledby="lp-guard">
        <div className="lp-wrap">
          <h2 id="lp-guard" className="lp-h2">The model never has the last word</h2>
          <ul className="lp-guards">
            {GUARDRAILS.map(({ icon: Icon, title, text }) => (
              <li key={title}>
                <Icon size={20} aria-hidden="true" />
                <div>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="lp-section" aria-labelledby="lp-providers">
        <div className="lp-wrap lp-providers">
          <div>
            <h2 id="lp-providers" className="lp-h2">Use the model API you already have</h2>
            <p className="lp-sub">
              Two adapters cover the two wire formats in use. Without a model, replies are drafted from the
              knowledge base and actions come from the runbooks.
            </p>
            <Link className="lp-link" to="/settings">Configure a model <ArrowRight size={16} aria-hidden="true" /></Link>
          </div>
          <ul className="lp-chips">
            {PROVIDERS.map((name) => <li key={name}>{name}</li>)}
          </ul>
        </div>
      </section>

      <section className="lp-section closing" aria-labelledby="lp-closing">
        <div className="lp-wrap lp-closing">
          <h2 id="lp-closing" className="lp-h2">Break something and watch.</h2>
          <Link className="btn primary big" to="/console">Open the console <ArrowRight size={18} aria-hidden="true" /></Link>
        </div>
      </section>

      <footer className="lp-footer">
        <div className="lp-wrap">
          <a href="https://www.linkedin.com/in/ahmed-mustapha-hammouda-a55270195/" target="_blank" rel="noopener noreferrer">
            Built by Ahmed Mustapha Hammouda
          </a>
          <a href={REPO} target="_blank" rel="noopener noreferrer">Source on GitHub</a>
        </div>
      </footer>
    </div>
  )
}
