import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, ShieldCheck, Building2, UserCheck, RotateCw } from 'lucide-react'
import PramaanMark from '../Logo'
import { api } from '../api'
import { useAuth } from '../App'
import './login.css'

// Where "Valid Until: 31-03-2028" sits on /hero/fire-noc.jpg, in % of the image.
const DATE = { x0: 22.3, y0: 42.6, x1: 31.3, y1: 44.6 }

/* A generic civic building in line art — colonnade, drum and dome. Not any specific building. */
function Building() {
  const cols = Array.from({ length: 14 }, (_, i) => 70 + i * 47)
  return (
    <svg className="building" viewBox="0 0 800 340" preserveAspectRatio="xMidYMax meet" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="1.4">
        <path d="M400 18 v-14" /><path d="M396 22 h8" />
        <path d="M330 120 Q330 30 400 24 Q470 30 470 120" />
        <path d="M352 120 Q352 52 400 46" opacity=".5" />
        <rect x="318" y="120" width="164" height="44" />
        {[0, 1, 2, 3, 4, 5, 6].map(i => <path key={i} d={`M${334 + i * 22} 128 v28`} />)}
        <path d="M300 164 L400 132 L500 164" />
        <rect x="40" y="164" width="720" height="18" />
        <rect x="52" y="182" width="696" height="12" />
        {cols.map(x => <g key={x}><rect x={x - 7} y="194" width="14" height="96" /><path d={`M${x - 10} 194 h20 M${x - 10} 290 h20`} /></g>)}
        <rect x="40" y="290" width="720" height="12" />
        <path d="M20 302 h760 M8 314 h784 M-6 326 h812 M-20 338 h840" />
      </g>
    </svg>
  )
}

function Scene() {
  const ref = useRef()
  const onMove = e => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const r = ref.current.getBoundingClientRect()
    const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5
    ref.current.style.setProperty('--tilt-y', `${-22 + x * 10}deg`)
    ref.current.style.setProperty('--tilt-x', `${16 - y * 8}deg`)
  }
  const reset = () => { ref.current.style.removeProperty('--tilt-y'); ref.current.style.removeProperty('--tilt-x') }
  // Lens: 34% of the card wide, magnifying 2.6x, centred on the altered date.
  const MAG = 2.6, LENS = 0.34, size = MAG / LENS
  const fx = (DATE.x0 + DATE.x1) / 200, fy = (DATE.y0 + DATE.y1) / 200
  const pos = f => `${((size * f - 0.5) / (size - 1)) * 100}%`
  const lens = { left: `${fx * 100}%`, top: `${fy * 100}%` }
  const glass = { backgroundSize: `${size * 100}%`, backgroundPosition: `${pos(fx)} ${pos(fy)}` }
  const hlIn = { width: `${(DATE.x1 - DATE.x0 + 1.2) / 100 * size * 100}%`, height: `${(DATE.y1 - DATE.y0 + 0.9) / 100 * size * 100}%` }

  return (
    <div className="scene" ref={ref} onMouseMove={onMove} onMouseLeave={reset} aria-hidden="true">
      <div className="floor" />
      <div className="stack">
        <img className="sheet-3d s4" src="/hero/building.jpg" alt="" />
        <img className="sheet-3d s3" src="/hero/affidavit.jpg" alt="" />
        <img className="sheet-3d s2" src="/hero/nba.jpg" alt="" />
        <div className="sheet-3d s1">
          <img src="/hero/fire-noc.jpg" alt="" />
          <span className="scanline" />
          <span className="hl" style={{ left: `${DATE.x0 - 0.6}%`, top: `${DATE.y0 - 0.4}%`, width: `${DATE.x1 - DATE.x0 + 1.2}%`, height: `${DATE.y1 - DATE.y0 + 0.8}%` }} />
          <span className="lens" style={lens}>
            <span className="lens-glass" style={glass}><span className="lens-hl" style={hlIn} /></span>
            <span className="lens-handle" />
          </span>
        </div>
        <div className="verify-card">
          <div className="vc-head"><ShieldCheck size={16} /><b>Signed QR verified</b></div>
          <p className="vc-src">State Fire &amp; Emergency Services · Ed25519</p>
          <dl>
            <dt>Printed</dt><dd className="bad">31-03-2028</dd>
            <dt>Authority</dt><dd className="good">31-03-2026</dd>
          </dl>
          <p className="vc-foot">Printed date was changed after issue</p>
        </div>
        <div className="count-chip"><span className="strip-mini"><i className="r" /><i className="g" /><i className="r" /><i className="r" /><i className="r" /></span><span><b>8</b> issues · checked in 1.4 s</span></div>
      </div>
    </div>
  )
}

const ROLES = [
  { id: 'institution', label: 'Institution', icon: Building2, desc: 'College / Institute Applicant' },
  { id: 'officer', label: 'Officer', icon: ShieldCheck, desc: 'AICTE Scrutiny Officer' },
  { id: 'admin', label: 'Admin', icon: UserCheck, desc: 'AICTE Central Administrator' },
]

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [role, setRole] = useState('institution')
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(null)
  const [captchaData, setCaptchaData] = useState(null)
  const [captchaInput, setCaptchaInput] = useState('')
  const [captchaLoading, setCaptchaLoading] = useState(false)

  const loadCaptcha = async () => {
    try {
      setCaptchaLoading(true)
      const data = await api('/api/auth/captcha')
      setCaptchaData(data)
      setCaptchaInput('')
    } catch (e) {
      console.error('Failed to load CAPTCHA', e)
    } finally {
      setCaptchaLoading(false)
    }
  }

  useEffect(() => {
    loadCaptcha()
  }, [])

  async function go(user, pass, selectedRole) {
    if (!captchaInput.trim()) {
      setErr('Please enter the CAPTCHA verification code.')
      return
    }
    setBusy(user); setErr(null)
    try {
      const authData = await api('/api/auth/login', {
        method: 'POST',
        body: {
          username: user,
          password: pass,
          role: selectedRole,
          captcha_id: captchaData?.captcha_id,
          captcha_code: captchaInput.trim().toUpperCase()
        }
      })
      login(authData)
      navigate('/', { replace: true })
    } catch (ex) {
      setErr(ex.status === 401 ? (ex.message || 'That username, password or selected role do not match.') : ex.message)
      setBusy(null)
      loadCaptcha()
    }
  }

  const activeRoleMeta = ROLES.find(r => r.id === role)

  return (
    <div className="lp">
      <div className="tricolour" aria-hidden="true"><i /><i /><i /></div>
      <section className="lp-story">
        <Building />
        <header className="lp-brand">
          <span className="lp-mark"><PramaanMark /></span>
          <span><b>Pramaan</b><small><span className="deva" lang="hi">प्रमाण</span> · verified at the source</small></span>
        </header>
        <Scene />
      </section>

      <section className="lp-panel">
        <div className="lp-card">
          <h2>Sign in</h2>
          <form onSubmit={e => { e.preventDefault(); go(u, p, role) }}>
            <div className="field">
              <span className="field-label-text">Select your role</span>
              <div className="role-selector-pills" role="radiogroup" aria-label="Select role">
                {ROLES.map(r => {
                  const Icon = r.icon
                  const active = role === r.id
                  return (
                    <button
                      type="button"
                      key={r.id}
                      className={`role-pill-btn ${active ? 'active' : ''}`}
                      onClick={() => { setRole(r.id); setErr(null); }}
                      role="radio"
                      aria-checked={active}
                      title={r.desc}
                    >
                      <Icon size={15} />
                      <span>{r.label}</span>
                    </button>
                  )
                })}
              </div>
            </div>

            <label className="field">
              <span>{role === 'institution' ? 'Institution Username' : role === 'officer' ? 'Scrutiny Officer Username' : 'Administrator Username'}</span>
              <input
                className="input"
                value={u}
                onChange={e => setU(e.target.value)}
                autoComplete="username"
                placeholder={role === 'institution' ? 'e.g. coromandel' : role === 'officer' ? 'e.g. officer' : 'e.g. admin'}
                autoFocus
              />
            </label>

            <label className="field">
              <span>Password</span>
              <input
                className="input"
                type="password"
                value={p}
                onChange={e => setP(e.target.value)}
                autoComplete="current-password"
                placeholder="••••••••"
              />
            </label>

            <div className="field">
              <span className="field-label-text">Security Verification</span>
              <div className="captcha-row">
                <div className="captcha-preview-wrap">
                  {captchaData?.captcha_svg ? (
                    <div
                      className="captcha-svg-container"
                      dangerouslySetInnerHTML={{ __html: captchaData.captcha_svg }}
                      title="CAPTCHA security verification challenge"
                    />
                  ) : (
                    <div className="captcha-loading">Loading code...</div>
                  )}
                  <button
                    type="button"
                    className="captcha-refresh-btn"
                    onClick={loadCaptcha}
                    disabled={captchaLoading}
                    title="Click to get a new CAPTCHA code"
                    aria-label="Refresh CAPTCHA"
                  >
                    <RotateCw size={15} className={captchaLoading ? 'spin' : ''} />
                  </button>
                </div>
                <input
                  className="input captcha-input"
                  type="text"
                  placeholder="Enter code"
                  maxLength={6}
                  value={captchaInput}
                  onChange={e => setCaptchaInput(e.target.value.toUpperCase())}
                  autoComplete="off"
                  autoCorrect="off"
                  spellCheck="false"
                  required
                />
              </div>
            </div>

            {err && <p className="error" role="alert">{err}</p>}

            <button className="btn primary lp-submit" disabled={!u || !p || !captchaInput.trim() || !!busy}>
              {busy && busy === u ? 'Signing in…' : <>Sign in as {activeRoleMeta?.label || 'User'} <ArrowRight size={15} /></>}
            </button>
          </form>
        </div>
      </section>
    </div>
  )
}
