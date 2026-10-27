import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { Bell, ChevronDown, Landmark, Home, FileStack, ScrollText, Sliders, BarChart3, FileText, PlusCircle, X, LogOut, ChevronRight, Menu } from 'lucide-react'
import { api, getSession, setSession } from './api'
import { Avatar, useApi } from './ui'
import PramaanMark from './Logo'
import Login from './pages/Login'
import Queue from './pages/Queue'
import ApplicationDetail from './pages/ApplicationDetail'
import Alerts from './pages/Alerts'
import Audit from './pages/Audit'
import Rules from './pages/Rules'
import Evaluation from './pages/Evaluation'
import InstitutionHome from './pages/InstitutionHome'
import NewApplication from './pages/NewApplication'
import InstitutionApplication from './pages/InstitutionApplication'

const Auth = createContext(null)
export const useAuth = () => useContext(Auth)

const ROLE_LABEL = { officer: 'Scrutiny officer', admin: 'Administrator', institution: 'Institution' }

function TopBar() {
  const { session, logout } = useAuth()
  const role = session.user.role
  const alerts = useApi('/api/alerts')
  const n = alerts.data?.filter(a => a.severity !== 'low').length || 0
  const [open, setOpen] = useState(false)
  const [navOpen, setNavOpen] = useState(false)
  const ref = useRef()

  useEffect(() => {
    const close = e => { if (!ref.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') setNavOpen(false) }
    if (navOpen) {
      document.addEventListener('keydown', onKey)
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [navOpen])

  return (
    <>
      <header className="topbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            type="button"
            className="menu-trigger-btn"
            onClick={() => setNavOpen(true)}
            title="Open side navigation"
            aria-label="Open side navigation"
          >
            <Menu size={20} />
          </button>
          <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none', color: 'inherit' }}>
            <PramaanMark size={28} />
            <b style={{ fontSize: '15px', fontWeight: 700, letterSpacing: '-0.01em', color: '#1F6B52' }}>Pramaan</b>
          </Link>
        </div>

        <nav className="nav" aria-label="Main">
          {role !== 'institution' && <>
            <NavLink to="/" end>Applications</NavLink>
            <NavLink to="/audit">Audit trail</NavLink>
            {role === 'admin' && <NavLink to="/rules">Rules</NavLink>}
            {role === 'admin' && <NavLink to="/evaluation">Evaluation</NavLink>}
          </>}
        </nav>

        <div className="topbar-right">
          <Link to="/alerts" className="icon-btn" aria-label={`${role === 'institution' ? 'Notices' : 'Alerts'}${n ? `, ${n} open` : ''}`}>
            <Bell size={18} />{n > 0 && <span className="dot">{n > 99 ? '99+' : n}</span>}
          </Link>
          <div className="me" ref={ref}>
            <button onClick={() => setOpen(o => !o)} aria-expanded={open}>
              <Avatar name={session.user.full_name} />
              <span className="who"><b>{session.user.full_name.replace(/\s*\(.*\)/, '')}</b><span>{ROLE_LABEL[role]}</span></span>
              <ChevronDown size={14} className="faint" />
            </button>
            {open && <div className="menu" role="menu"><button role="menuitem" onClick={logout}>Sign out</button></div>}
          </div>
        </div>
      </header>

      {navOpen && (
        <div className="sidenav-overlay" onClick={() => setNavOpen(false)}>
          <aside className="sidenav-drawer" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Navigation Menu">
            <div className="sidenav-tricolour" aria-hidden="true"><i /><i /><i /></div>
            
            <div className="sidenav-header">
              <div className="sidenav-brand">
                <PramaanMark size={32} />
                <div>
                  <b className="sidenav-brand-title">Pramaan</b>
                  <span className="sidenav-sub">{role === 'institution' ? 'AICTE Approvals' : 'AICTE Approval Scrutiny'}</span>
                </div>
              </div>
              <button
                type="button"
                className="icon-btn sidenav-close"
                onClick={() => setNavOpen(false)}
                aria-label="Close menu"
              >
                <X size={18} />
              </button>
            </div>

            <div className="sidenav-user-card">
              <Avatar name={session.user.full_name} />
              <div className="sidenav-user-info">
                <b>{session.user.full_name.replace(/\s*\(.*\)/, '')}</b>
                <span className="sidenav-role-badge">{ROLE_LABEL[role]}</span>
              </div>
            </div>

            <div className="sidenav-section-title">Navigation</div>

            <nav className="sidenav-nav">
              {/* On top: Home */}
              <NavLink
                to="/"
                end
                className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                onClick={() => setNavOpen(false)}
              >
                <span className="sidenav-link-icon"><Home size={18} /></span>
                <div className="sidenav-link-text">
                  <span className="sidenav-link-title">Home</span>
                  <span className="sidenav-link-desc">Main dashboard overview</span>
                </div>
                <ChevronRight size={14} className="sidenav-link-arr" />
              </NavLink>

              {role === 'officer' && (
                <>
                  <NavLink
                    to="/"
                    end
                    className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="sidenav-link-icon"><FileStack size={18} /></span>
                    <div className="sidenav-link-text">
                      <span className="sidenav-link-title">Applications Queue</span>
                      <span className="sidenav-link-desc">Scrutinize institutional submissions</span>
                    </div>
                    <ChevronRight size={14} className="sidenav-link-arr" />
                  </NavLink>
                  <NavLink
                    to="/audit"
                    className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="sidenav-link-icon"><ScrollText size={18} /></span>
                    <div className="sidenav-link-text">
                      <span className="sidenav-link-title">Audit Trail</span>
                      <span className="sidenav-link-desc">Immutable verification logs</span>
                    </div>
                    <ChevronRight size={14} className="sidenav-link-arr" />
                  </NavLink>
                  <NavLink
                    to="/alerts"
                    className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="sidenav-link-icon"><Bell size={18} /></span>
                    <div className="sidenav-link-text">
                      <span className="sidenav-link-title">Alerts & Deficiencies</span>
                      <span className="sidenav-link-desc">Urgent document flags</span>
                    </div>
                    {n > 0 && <span className="sidenav-count">{n}</span>}
                    <ChevronRight size={14} className="sidenav-link-arr" />
                  </NavLink>
                </>
              )}

              {role === 'admin' && (
                <>
                  <NavLink
                    to="/"
                    end
                    className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="sidenav-link-icon"><FileStack size={18} /></span>
                    <div className="sidenav-link-text">
                      <span className="sidenav-link-title">Applications Scrutiny</span>
                      <span className="sidenav-link-desc">All institutional submissions</span>
                    </div>
                    <ChevronRight size={14} className="sidenav-link-arr" />
                  </NavLink>
                  <NavLink
                    to="/audit"
                    className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="sidenav-link-icon"><ScrollText size={18} /></span>
                    <div className="sidenav-link-text">
                      <span className="sidenav-link-title">Audit Trail</span>
                      <span className="sidenav-link-desc">Actions, rule checks & source responses</span>
                    </div>
                    <ChevronRight size={14} className="sidenav-link-arr" />
                  </NavLink>
                  <NavLink
                    to="/rules"
                    className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="sidenav-link-icon"><Sliders size={18} /></span>
                    <div className="sidenav-link-text">
                      <span className="sidenav-link-title">Regulatory Rules</span>
                      <span className="sidenav-link-desc">Approval Process Handbook parameters</span>
                    </div>
                    <ChevronRight size={14} className="sidenav-link-arr" />
                  </NavLink>
                  <NavLink
                    to="/evaluation"
                    className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="sidenav-link-icon"><BarChart3 size={18} /></span>
                    <div className="sidenav-link-text">
                      <span className="sidenav-link-title">Pipeline Evaluation</span>
                      <span className="sidenav-link-desc">Synthetic benchmark & accuracy</span>
                    </div>
                    <ChevronRight size={14} className="sidenav-link-arr" />
                  </NavLink>
                  <NavLink
                    to="/alerts"
                    className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="sidenav-link-icon"><Bell size={18} /></span>
                    <div className="sidenav-link-text">
                      <span className="sidenav-link-title">System Alerts</span>
                      <span className="sidenav-link-desc">Active flags and notices</span>
                    </div>
                    {n > 0 && <span className="sidenav-count">{n}</span>}
                    <ChevronRight size={14} className="sidenav-link-arr" />
                  </NavLink>
                </>
              )}

              {role === 'institution' && (
                <>
                  <NavLink
                    to="/"
                    end
                    className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="sidenav-link-icon"><FileText size={18} /></span>
                    <div className="sidenav-link-text">
                      <span className="sidenav-link-title">My Applications</span>
                      <span className="sidenav-link-desc">Active submissions & status</span>
                    </div>
                    <ChevronRight size={14} className="sidenav-link-arr" />
                  </NavLink>
                  <NavLink
                    to="/new"
                    className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="sidenav-link-icon"><PlusCircle size={18} /></span>
                    <div className="sidenav-link-text">
                      <span className="sidenav-link-title">New Application</span>
                      <span className="sidenav-link-desc">Submit 2026-27 EoA or expansion</span>
                    </div>
                    <ChevronRight size={14} className="sidenav-link-arr" />
                  </NavLink>
                  <NavLink
                    to="/alerts"
                    className={({ isActive }) => `sidenav-link ${isActive ? 'active' : ''}`}
                    onClick={() => setNavOpen(false)}
                  >
                    <span className="sidenav-link-icon"><Bell size={18} /></span>
                    <div className="sidenav-link-text">
                      <span className="sidenav-link-title">Notices & Deficiencies</span>
                      <span className="sidenav-link-desc">Rectification requests from AICTE</span>
                    </div>
                    {n > 0 && <span className="sidenav-count">{n}</span>}
                    <ChevronRight size={14} className="sidenav-link-arr" />
                  </NavLink>
                </>
              )}
            </nav>

            <div className="sidenav-footer">
              <button
                type="button"
                className="sidenav-signout"
                onClick={() => { setNavOpen(false); logout(); }}
              >
                <LogOut size={16} />
                <span>Sign out</span>
              </button>
            </div>
          </aside>
        </div>
      )}
    </>
  )
}

function AppContent() {
  const { session } = useAuth()
  const role = session?.user.role

  if (!session) {
    return <Login />
  }

  return (
    <>
      <TopBar />
      <Routes>
        {role === 'institution' ? (
          <>
            <Route path="/" element={<InstitutionHome />} />
            <Route path="/new" element={<NewApplication />} />
            <Route path="/applications/:id" element={<InstitutionApplication />} />
          </>
        ) : (
          <>
            <Route path="/" element={<Queue />} />
            <Route path="/applications/:id" element={<ApplicationDetail />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/rules" element={<Rules />} />
            <Route path="/evaluation" element={<Evaluation />} />
          </>
        )}
        <Route path="/alerts" element={<Alerts />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}

function AppWithAuth() {
  const navigate = useNavigate()
  const [session, set] = useState(getSession())

  const login = s => {
    setSession(s)
    set(s)
    navigate('/', { replace: true })
  }

  const logout = () => {
    api('/api/auth/logout', { method: 'POST' }).catch(() => {})
    setSession(null)
    set(null)
    navigate('/', { replace: true })
  }

  return (
    <Auth.Provider value={{ session, login, logout }}>
      <AppContent />
    </Auth.Provider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppWithAuth />
    </BrowserRouter>
  )
}
