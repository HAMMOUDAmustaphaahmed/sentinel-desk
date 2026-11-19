import { useEffect } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { MotionConfig, motion } from 'framer-motion'
import { Activity } from 'lucide-react'
import Console from './pages/Console'
import Landing from './pages/Landing'
import Settings from './pages/Settings'

const LINKS = [
  { to: '/', label: 'Overview', end: true },
  { to: '/console', label: 'Console', end: false },
  { to: '/settings', label: 'Configuration', end: false },
]

export default function App() {
  const { pathname, hash } = useLocation()

  // Each page opens at the top, unless the link points at a section.
  useEffect(() => {
    if (!hash) window.scrollTo(0, 0)
  }, [pathname, hash])

  return (
    <MotionConfig reducedMotion="user">
      <a className="skip-link" href="#content">Skip to content</a>
      <header className="topbar">
        <Link className="brand" to="/">
          <Activity size={20} aria-hidden="true" />
          <span>Sentinel Desk</span>
        </Link>
        <nav className="topnav" aria-label="Main">
          {LINKS.map(({ to, label, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => (isActive ? 'active' : '')}>
              {({ isActive }) => (
                <>
                  {label}
                  {/* The same underline slides from one link to the next. */}
                  {isActive && <motion.span layoutId="topnav-line" className="topnav-line" />}
                </>
              )}
            </NavLink>
          ))}
        </nav>
      </header>

      <div id="content">
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/console" element={<Console />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </MotionConfig>
  )
}
