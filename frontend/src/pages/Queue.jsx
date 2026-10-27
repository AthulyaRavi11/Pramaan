import { Fragment, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Search } from 'lucide-react'
import { fileUrl } from '../api'
import { useAuth } from '../App'
import {
  APP_STATUS, Band, CheckStrip, InstTile, IssueCounts, Loading, Status, StripLegend, SystemStatus, VER_STATUS, ago, greeting, useApi,
} from '../ui'

// Where each application sits in the officer's day. Order = what to look at first.
const LANES = [
  { key: 'review', label: 'Needs your review', dot: '#FF8A73', test: a => a.status === 'UNDER_SCRUTINY' && ['ACTION_REQUIRED', 'DEFICIENCIES_FOUND'].includes(a.system_status) },
  { key: 'sources', label: 'Awaiting authorities', dot: '#AEB8CC', test: a => a.status === 'UNDER_SCRUTINY' && a.system_status === 'MANUAL_VERIFICATION' },
  { key: 'clear', label: 'Clear', dot: '#6FD39C', test: a => a.status === 'UNDER_SCRUTINY' && a.system_status === 'READY_FOR_SCRUTINY' },
  { key: 'returned', label: 'Returned', dot: '#F5B651', test: a => a.status === 'RECTIFICATION_REQUESTED' },
  { key: 'decided', label: 'Recommended', dot: '#9DB6FF', test: a => a.status === 'DECIDED' },
  { key: 'other', label: 'Not submitted', dot: '#6F7C95', test: () => true },
]
const laneOf = a => LANES.find(l => l.test(a)).key
const weight = a => (a.finding_counts?.high || 0) * 100 + (a.finding_counts?.medium || 0) * 10 + (a.finding_counts?.low || 0)
const VER_COLOR = { ok: '#3FB67A', danger: '#E2533D', warn: '#E9A23B', accent: '#5C83F0', info: '#6F7C95' }

function NextUp({ app }) {
  const nav = useNavigate()
  const d = useApi(app ? `/api/applications/${app.id}` : null)
  if (!app) return null
  const top = d.data?.findings.filter(f => f.review_status === 'OPEN' && f.document_id && f.module !== 'infrastructure')
    .sort((x, y) => ({ high: 0, medium: 1, low: 2, info: 3 }[x.severity] - { high: 0, medium: 1, low: 2, info: 3 }[y.severity]))[0]
  return (
    <button className="next-card" onClick={() => nav(`/applications/${app.id}`)} style={{ cursor: 'pointer' }}>
      <div className="next-thumb"><div><span className="stack-edge" />{top ? <img src={fileUrl(top.document_id)} alt="" /> : <div style={{ aspectRatio: '1/1.3', background: '#fff' }} />}</div></div>
      <div>
        <span className="kick">Next up · most serious first</span>
        <h3>{app.institution_name}</h3>
        <p>{top ? top.title : `${app.finding_counts?.high || 0} high-severity issues`}</p>
        <span className="btn primary sm">Start review <ArrowRight size={14} /></span>
      </div>
    </button>
  )
}

export default function Queue() {
  const { session } = useAuth()
  const apps = useApi('/api/applications')
  const dash = useApi('/api/dashboard')
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [lane, setLane] = useState('all')

  const grouped = useMemo(() => {
    const list = (apps.data || []).filter(a => !q || `${a.institution_name} ${a.ref} ${a.institution_id}`.toLowerCase().includes(q.toLowerCase()))
    const g = Object.fromEntries(LANES.map(l => [l.key, []]))
    list.forEach(a => g[laneOf(a)].push(a))
    Object.values(g).forEach(l => l.sort((x, y) => weight(y) - weight(x)))
    return g
  }, [apps.data, q])

  if (!apps.data || !dash.data) return <Loading error={apps.error || dash.error} />
  const counts = Object.fromEntries(LANES.map(l => [l.key, grouped[l.key].length]))
  const shown = LANES.filter(l => (lane === 'all' || lane === l.key) && grouped[l.key].length)
  const ver = dash.data.verification_status || {}
  const verTotal = Object.values(ver).reduce((a, b) => a + b, 0) || 1
  const open = id => nav(`/applications/${id}`)
  const first = (apps.data || []).filter(a => laneOf(a) === 'review').sort((x, y) => weight(y) - weight(x))[0]
  const name = session.user.full_name.replace(/\s*\(.*\)/, '').split(' ').slice(-1)[0]

  return (
    <>
      <Band>
        <div style={{ flex: '1 1 480px' }}>
          <p className="kicker">{greeting()}, {name} · {new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })}</p>
          <h1>{counts.review ? `${counts.review} application${counts.review > 1 ? 's' : ''} need${counts.review > 1 ? '' : 's'} your review` : 'Nothing is waiting for your review'}</h1>
          <p className="lede">Most serious first. Each issue is marked on the document with the evidence behind it; your review and recommendation are recorded in the audit trail.</p>
          <div className="band-stats" role="tablist" aria-label="Filter applications">
            <button className={lane === 'all' ? 'on' : ''} onClick={() => setLane('all')}><b>{apps.data.length}</b><span>All applications</span></button>
            {LANES.filter(l => counts[l.key] || ['review', 'sources'].includes(l.key)).map(l => (
              <button key={l.key} className={lane === l.key ? 'on' : ''} onClick={() => setLane(lane === l.key ? 'all' : l.key)}>
                <b>{counts[l.key]}</b><span><i className="dotc" style={{ background: l.dot }} />{l.label}</span>
              </button>
            ))}
          </div>
          <div className="verif-bar">
            <div className="track">{Object.entries(VER_STATUS).filter(([k]) => ver[k]).map(([k, v]) => (
              <i key={k} title={`${v.label}: ${ver[k]}`} style={{ width: `${ver[k] / verTotal * 100}%`, background: VER_COLOR[v.tone] }} />))}</div>
            <div className="legend"><span>Issuing-authority checks:</span>
              {Object.entries(VER_STATUS).filter(([k]) => ver[k]).map(([k, v]) => <span key={k}><b>{ver[k]}</b> {v.label.toLowerCase()}</span>)}
              {dash.data.avg_validation_ms && <span>· {(dash.data.avg_validation_ms / 1000).toFixed(1)} s per application</span>}
            </div>
          </div>
        </div>
        <NextUp app={first} />
      </Band>

      <div className="page lift">
        <div className="sheet lift-first">
          <div className="sheet-head" style={{ flexWrap: 'wrap' }}>
            <label className="search">
              <Search size={15} />
              <input className="input" placeholder="Institution, reference or ID" value={q} onChange={e => setQ(e.target.value)} aria-label="Search applications" />
            </label>
            <StripLegend />
          </div>
          <table className="table">
            <thead><tr><th>Institution</th><th>Reference</th><th>Checks</th><th>Issues</th><th>Reviewed</th><th>Assessment</th><th>Submitted</th></tr></thead>
            <tbody>
              {shown.map(l => (
                <Fragment key={l.key}>
                  {lane === 'all' && <tr className="group-row"><td colSpan={7}>{l.label} · {grouped[l.key].length}</td></tr>}
                  {grouped[l.key].map(a => {
                    const total = (a.finding_counts?.high || 0) + (a.finding_counts?.medium || 0)
                    const done = Math.max(0, total - (a.open_items || 0))
                    return (
                      <tr key={a.id} className="row-link" tabIndex={0} onClick={() => open(a.id)} onKeyDown={e => e.key === 'Enter' && open(a.id)}>
                        <td><div className="inst-cell"><InstTile name={a.institution_name} id={a.institution_id} />
                          <div><div className="cell-title">{a.institution_name}</div><div className="cell-sub">{a.institution_id} · AY {a.academic_year}</div></div></div></td>
                        <td className="mono nowrap">{a.ref}</td>
                        <td><CheckStrip checks={a.checks} /></td>
                        <td><IssueCounts counts={a.finding_counts} /></td>
                        <td>{total ? <div className="review-prog"><span>{done} of {total}</span><span className="t"><i style={{ width: `${done / total * 100}%` }} /></span></div> : <span className="faint">—</span>}</td>
                        <td>{a.status === 'UNDER_SCRUTINY' ? <SystemStatus s={a.system_status} /> : <Status tone={APP_STATUS[a.status]?.tone}>{APP_STATUS[a.status]?.label}</Status>}</td>
                        <td className="muted nowrap">{ago(a.submitted_at)}</td>
                      </tr>
                    )
                  })}
                </Fragment>
              ))}
            </tbody>
          </table>
          {!shown.length && <div className="empty"><b>No applications match</b>Clear the search or pick another filter.</div>}
        </div>
      </div>
    </>
  )
}
