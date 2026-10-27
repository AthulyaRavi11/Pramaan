import { Link } from 'react-router-dom'
import { Plus, ArrowRight } from 'lucide-react'
import { useAuth } from '../App'
import { APP_STATUS, Band, Empty, InstTile, Loading, Status, ago, greeting, useApi } from '../ui'

function Ring({ value, tone }) {
  const r = 26, c = 2 * Math.PI * r
  const color = { ok: '#1F7A4C', warn: '#A86400', danger: '#C2361F', accent: '#2550C0', info: '#6A7180' }[tone] || '#2550C0'
  return (
    <svg className="ring" viewBox="0 0 64 64" role="img" aria-label={`${Math.round(value * 100)}% complete`}>
      <circle cx="32" cy="32" r={r} fill="none" stroke="#ECEEF1" strokeWidth="6" />
      <circle cx="32" cy="32" r={r} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round"
              strokeDasharray={`${c * value} ${c}`} transform="rotate(-90 32 32)" />
      <text x="32" y="37" textAnchor="middle">{Math.round(value * 100)}%</text>
    </svg>
  )
}

const STAGE = { DRAFT: 0.25, SUBMITTED: 0.5, UNDER_SCRUTINY: 0.65, RECTIFICATION_REQUESTED: 0.55, DECIDED: 1 }

export default function InstitutionHome() {
  const { session } = useAuth()
  const r = useApi('/api/applications')
  const cfg = useApi('/api/config')
  if (!r.data || !cfg.data) return <Loading error={r.error || cfg.error} />
  const toFix = r.data.reduce((n, a) => n + (a.status !== 'DRAFT' ? a.open_items || 0 : 0), 0)
  const hasApps = r.data.length > 0

  return (
    <>
      <Band>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <InstTile name={session.user.full_name} id={session.user.institution_id} size={52} />
          <div>
            <p className="kicker">{greeting()} · {session.user.institution_id}</p>
            <h1>{session.user.full_name}</h1>
            <p className="lede">{toFix ? `${toFix} item${toFix > 1 ? 's' : ''} to fix across your applications.` : 'Nothing needs fixing right now.'} Upload documents and see straight away what was read from them.</p>
          </div>
        </div>
        {hasApps && (
          <Link className="btn primary" to="/new"><Plus size={15} />New application</Link>
        )}
      </Band>
      <div className="page lift" style={{ maxWidth: 1100 }}>
        {hasApps ? (
          <div className="app-cards lift-first">
            {r.data.map(a => {
              const st = APP_STATUS[a.status]
              return (
                <Link key={a.id} to={`/applications/${a.id}`} className="app-card">
                  <Ring value={STAGE[a.status] || 0.3} tone={st?.tone} />
                  <div>
                    <h3>{cfg.data.categories[a.category]?.label}</h3>
                    <p className="meta"><span className="mono">{a.ref}</span> · AY {a.academic_year}</p>
                    <p style={{ marginTop: 8, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                      <Status tone={st?.tone}>{st?.label}</Status>
                      {a.status !== 'DRAFT' && a.open_items > 0 && <span className="small error">{a.open_items} to fix</span>}
                    </p>
                    <p className="meta" style={{ display: 'flex', justifyContent: 'space-between' }}><span>Updated {ago(a.validated_at || a.submitted_at)}</span><ArrowRight size={15} /></p>
                  </div>
                </Link>
              )
            })}
          </div>
        ) : (
          <div className="sheet lift-first">
            <Empty title="No applications yet">
              <p style={{ margin: '8px 0 22px', color: 'var(--muted)', fontSize: '13.5px' }}>
                You have not created any approval applications yet.
              </p>
              <div style={{ display: 'flex', justifyContent: 'center' }}>
                <Link
                  className="btn primary"
                  to="/new"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '11px 24px',
                    fontSize: '14px',
                    fontWeight: 600,
                    borderRadius: 9,
                    boxShadow: '0 4px 14px rgba(87, 171, 173, 0.35)'
                  }}
                >
                  <Plus size={16} />
                  New application
                </Link>
              </div>
            </Empty>
          </div>
        )}
      </div>
    </>
  )
}
