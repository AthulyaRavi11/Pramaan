import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Clock, Mail } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../App'
import { Band, Empty, Loading, SevIcon, Tag, ago, human, toast, useApi } from '../ui'

const KIND = {
  SUSPECTED_ANOMALY: 'Authenticity', VERIFICATION: 'Issuing authority', INFRASTRUCTURE: 'Infrastructure', DEFICIENCY: 'Checklist',
  RECTIFICATION: 'Rectification requested', VERIFICATION_PENDING: 'Waiting on authority', VERIFICATION_SOURCE_UNAVAILABLE: 'Authority unavailable',
}
const fmtAge = h => h < 1 ? `${Math.round(h * 60)} min` : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} days`

export default function Alerts() {
  const { session } = useAuth()
  const isInst = session.user.role === 'institution'
  const [tab, setTab] = useState('alerts')
  const [all, setAll] = useState(false)
  const [low, setLow] = useState(false)
  const r = useApi(`/api/alerts?include_ack=${all}`)
  const mail = useApi('/api/notifications')
  const groups = useMemo(() => {
    const g = {}
    for (const a of (r.data || []).filter(a => low || a.severity !== 'low')) (g[a.application_id] ||= { ref: a.ref, inst: a.institution_id, items: [] }).items.push(a)
    return Object.entries(g)
  }, [r.data, low])
  if (!r.data) return <Loading error={r.error} />

  async function ack(id) {
    try { await api(`/api/alerts/${id}/ack`, { method: 'POST' }); r.reload() } catch (e) { toast(e.message) }
  }
  const hiddenLow = r.data.filter(a => a.severity === 'low').length
  const overdue = r.data.filter(a => a.overdue).length

  return (
    <>
      <Band>
        <div>
          <h1>{isInst ? 'Notices' : 'Alerts'}</h1>
          <p className="lede">{isInst ? 'What you need to fix before your application can move forward. You also receive these by email.'
            : 'Raised automatically for missing or expired documents, issuing-authority problems, suspected alterations and infrastructure gaps. Reviewing an issue clears its alert.'}</p>
          <div className="band-tabs" role="tablist">
            <button className={tab === 'alerts' ? 'on' : ''} onClick={() => setTab('alerts')}>{isInst ? 'Notices' : 'Open alerts'}<span className="n">{r.data.length}</span></button>
            <button className={tab === 'mail' ? 'on' : ''} onClick={() => setTab('mail')}>Email notifications<span className="n">{mail.data?.length ?? '…'}</span></button>
          </div>
        </div>
        {!isInst && overdue > 0 && <div className="next-card" style={{ width: 300, gridTemplateColumns: '1fr' }}>
          <span className="kick"><Clock size={13} style={{ verticalAlign: -2 }} /> Past response time</span>
          <h3>{overdue} alert{overdue > 1 ? 's' : ''} overdue</h3>
          <p>Response times are set per severity in the rule set (high 24 h, medium 72 h, low 7 days).</p>
        </div>}
      </Band>

      <div className="page lift" style={{ maxWidth: 1000 }}>
        {tab === 'alerts' ? <>
          {!isInst && <div className="sheet lift-first" style={{ padding: '10px 16px', display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
            <label className="small" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><input type="checkbox" checked={low} onChange={e => setLow(e.target.checked)} />Include low severity ({hiddenLow})</label>
            <label className="small" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} />Include acknowledged</label>
          </div>}
          {groups.map(([appId, g]) => (
            <section className="inbox-group" key={appId}>
              <header><b><Link to={`/applications/${appId}`}>{g.ref}</Link> <span className="muted" style={{ fontWeight: 400 }}>· {g.inst}</span></b><span className="small muted">{g.items.length}</span></header>
              <div className={`sheet ${isInst ? 'lift-first' : ''}`}>
                {g.items.map(a => (
                  <div key={a.id} className={`alert-row ${a.acknowledged_by ? 'acked' : ''}`}>
                    <SevIcon s={a.severity} />
                    <div><div>{a.message}</div>
                      <div className="k">{KIND[a.kind] || human(a.kind)} · open {fmtAge(a.age_hours || 0)}{a.overdue && <span className="overdue"> · overdue (target {a.sla_hours} h)</span>}</div></div>
                    <Link className="btn quiet sm" to={`/applications/${appId}`}>Open</Link>
                    {!isInst ? (a.acknowledged_by ? <span className="small muted">Acknowledged</span> : <button className="btn sm" onClick={() => ack(a.id)}>Acknowledge</button>) : <span />}
                  </div>
                ))}
              </div>
            </section>
          ))}
          {!groups.length && <div className="sheet lift-first"><Empty title={isInst ? 'Nothing to fix' : 'No open alerts'}>{isInst ? 'Your applications have no open notices.' : 'You’re up to date.'}</Empty></div>}
        </> : (
          <div className="sheet lift-first">
            <div className="sheet-head"><h3><Mail size={15} style={{ verticalAlign: -2 }} /> Outbox</h3>
              <span className="small muted">No mail server configured in this prototype: messages are kept here with status “queued”. Set PRAMAAN_SMTP_HOST to deliver.</span></div>
            {(mail.data || []).map(n => (
              <div key={n.id} className="mail-row">
                <div><b>{n.subject}</b><div className="small muted">To {n.email} · {n.ref} · {ago(n.created_at)}</div><pre>{n.body}</pre></div>
                <Tag tone={n.status === 'SENT' ? 'ok' : n.status === 'QUEUED' ? 'info' : 'danger'}>{n.status === 'QUEUED' ? 'Queued' : n.status}</Tag>
              </div>
            ))}
            {!mail.data?.length && <Empty>No notifications yet.</Empty>}
          </div>
        )}
      </div>
    </>
  )
}
