import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ChevronRight, RefreshCw, X, AlertOctagon, Download, Check, Eye, EyeOff, FileText, Unlock } from 'lucide-react'
import { api, getSession } from '../api'
import { APP_STATUS, DECISIONS, Loading, Status, SystemStatus, ago, initials, tileColor, toast, useApi } from '../ui'
import ReviewDesk from './case/ReviewDesk'
import { Documents, History, Infrastructure, Records, Sources } from './case/Tabs'

export default function ApplicationDetail() {
  const { id } = useParams()
  const [unmasked, setUnmasked] = useState(false)
  const res = useApi(`/api/applications/${id}${unmasked ? '?unmask=true' : ''}`)
  const cfg = useApi('/api/config')
  const [tab, setTab] = useState('review')
  const [busy, setBusy] = useState(false)
  const [drawer, setDrawer] = useState(false)
  const [unfreezeModal, setUnfreezeModal] = useState(false)

  if (!res.data || !cfg.data) return <Loading error={res.error || cfg.error} />
  const data = res.data
  const a = data.application
  const docLabels = Object.fromEntries(Object.entries(cfg.data.document_types).map(([k, v]) => [k, v.label]))
  const sourceLabels = Object.fromEntries(Object.values(cfg.data.document_types).filter(v => v.source).map(v => [v.source, v.source_label]))
  const open = data.findings.filter(f => f.review_status === 'OPEN' && f.severity !== 'info').length

  async function rerun() {
    setBusy(true)
    try { await api(`/api/applications/${id}/validate`, { method: 'POST' }); toast('Checks re-run with the current rule set'); res.reload() }
    catch (e) { toast(e.message) } finally { setBusy(false) }
  }

  const tabs = [
    ['review', 'Review', open || null],
    ['documents', 'Documents', data.documents.filter(d => !d.superseded && d.declared_type !== 'infra_photo').length],
    ['sources', 'Issuing authorities', data.verifications.length],
    ['infrastructure', 'Infrastructure'],
    ['records', 'AICTE records'],
    ['history', 'History'],
  ]

  return (
    <div className="case">
      <header className="case-head dark">
        <nav className="crumbs" aria-label="Breadcrumb"><Link to="/">Applications</Link><ChevronRight size={12} /><span>{a.institution_id}</span></nav>
        <div className="case-top">
          <div className="case-title">
            <span className="crest" style={{ background: tileColor(a.institution_id) }} aria-hidden="true">{initials(a.institution_name)}</span>
            <div>
              <h1>{a.institution_name} {a.status === 'UNDER_SCRUTINY' ? <SystemStatus s={a.system_status} /> : <Status tone={APP_STATUS[a.status]?.tone}>{APP_STATUS[a.status]?.label}</Status>}</h1>
              <div className="case-meta">
                <span className="mono">{a.ref}</span>
                <span>{data.report?.category_label || a.category}</span>
                <span>AY <b>{a.academic_year}</b></span>
                <span>Permanent ID <b className="mono">{a.form.aicte_permanent_id}</b></span>
                {data.report?.risk_score !== undefined && (
                  <span>Inspection risk: <b style={{ color: data.report.risk_score >= 40 ? '#C2361F' : '#1F7A4C' }}>{data.report.risk_score}/100</b> ({data.report.inspection_recommendation === 'EVC_PHYSICAL_VISIT' ? 'EVC Visit' : 'Virtual Scrutiny'})</span>
                )}
                <span>Submitted {ago(a.submitted_at)}</span>
              </div>
            </div>
          </div>
          <div className="case-actions">
            <button
              className={`btn ${unmasked ? 'ok' : ''}`}
              onClick={() => {
                const next = !unmasked
                setUnmasked(next)
                toast(next ? 'PII Unmasked under audit log' : 'PII Masked')
              }}
              title={unmasked ? 'PII Unmasked under audit log' : 'Click to unmask Aadhaar/PAN under audit logging'}
            >
              {unmasked ? <EyeOff size={14} /> : <Eye size={14} />}
              {unmasked ? 'Mask PII' : 'Unmask PII'}
            </button>
            <a className="btn" href={`/api/applications/${id}/deficiency-memo?format=html&token=${encodeURIComponent(getSession()?.token || '')}`} target="_blank" rel="noreferrer" title="Deficiency memo: open issues with their configured handbook references">
              <FileText size={14} />Deficiency Memo
            </a>
            <a className="btn" href={`/api/applications/${id}/report.pdf?token=${encodeURIComponent(getSession()?.token || '')}`}><Download size={14} />Report (PDF)</a>
            {a.is_frozen === 1 && (
              <button
                className="btn"
                style={{ borderColor: '#d97706', color: '#b45309', background: '#fffbeb', fontWeight: 600 }}
                onClick={() => setUnfreezeModal(true)}
                title="Unfreeze application and send official rectification notice to the institution"
              >
                <Unlock size={14} /> Send Unfreeze / Rectify
              </button>
            )}
            <button className="btn" onClick={rerun} disabled={busy}><RefreshCw size={14} className={busy ? 'spin' : ''} />{busy ? 'Checking…' : 'Re-run checks'}</button>
            <button className="btn primary" onClick={() => setDrawer(true)}>Record recommendation</button>
          </div>
        </div>
        <Stages a={a} findings={data.findings} />
        <div className="tabs" role="tablist">
          {tabs.map(([k, label, n]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>
              {label}{n ? <span className="n">{n}</span> : null}
            </button>
          ))}
        </div>
      </header>

      <div className="case-body" style={tab === 'review' || tab === 'documents' ? { overflow: 'hidden' } : null}>
        {tab === 'review' && <ReviewDesk data={data} docLabels={docLabels} onChange={res.reload} />}
        {tab === 'documents' && <Documents data={data} docLabels={docLabels} />}
        {tab === 'sources' && <Sources data={data} docLabels={docLabels} sourceLabels={sourceLabels} />}
        {tab === 'infrastructure' && <Infrastructure data={data} />}
        {tab === 'records' && <Records data={data} />}
        {tab === 'history' && <History id={id} />}
      </div>

      {unfreezeModal && (
        <UnfreezeModal
          a={a}
          onClose={() => setUnfreezeModal(false)}
          onDone={() => { setUnfreezeModal(false); res.reload() }}
        />
      )}

      {drawer && <Recommendation data={data} onClose={() => setDrawer(false)} onDone={() => { setDrawer(false); res.reload() }}
                                 goReview={() => { setDrawer(false); setTab('review') }} />}
    </div>
  )
}

function Stages({ a, findings }) {
  const need = findings.filter(f => ['high', 'medium'].includes(f.severity))
  const done = need.filter(f => f.review_status !== 'OPEN').length
  const steps = [
    { label: 'Submitted', state: 'done' },
    { label: `Automated checks · ${a.finding_counts ? Object.values(a.finding_counts).reduce((x, y) => x + y, 0) : 0} issues`, state: a.validated_at ? 'done' : 'now' },
    { label: `Official review · ${done} of ${need.length}`, state: need.length && done === need.length ? 'done' : 'now' },
    { label: a.decision ? DECISIONS[a.decision]?.label : 'Recommendation', state: a.decision ? 'done' : '' },
  ]
  return (
    <div className="stages" aria-label="Progress">
      {steps.map((st, i) => (
        <span key={i} style={{ display: 'contents' }}>
          {i > 0 && <span className={`stage-line ${steps[i - 1].state === 'done' ? 'done' : ''}`} />}
          <span className={`stage ${st.state}`}><span className="s">{st.state === 'done' ? <Check size={11} strokeWidth={3} /> : i + 1}</span>{st.label}</span>
        </span>
      ))}
    </div>
  )
}

function Recommendation({ data, onClose, onDone, goReview }) {
  const a = data.application
  const [d, setD] = useState('')
  const [remark, setRemark] = useState('')
  const [err, setErr] = useState(null)
  const unreviewed = data.findings.filter(f => f.severity === 'high' && f.review_status === 'OPEN')
  useEffect(() => {
    const k = e => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  async function save() {
    setErr(null)
    try { await api(`/api/applications/${a.id}/decision`, { method: 'POST', body: { decision: d, remark } }); toast('Recommendation recorded'); onDone() }
    catch (e) { setErr(e.message) }
  }
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="rec-title">
        <header>
          <div><h2 id="rec-title">Record recommendation</h2><p className="small muted" style={{ marginTop: 3 }}>{a.institution_name} · {a.ref}</p></div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </header>
        <div className="body">
          {a.decision && <div className="note"><span>Already recorded by {a.decision_by}: <b>{DECISIONS[a.decision]?.label}</b>. Recording again replaces it; both stay in the audit trail.</span></div>}
          {unreviewed.length > 0 && (
            <div className="note danger"><AlertOctagon size={15} />
              <span>{unreviewed.length} high-severity issue{unreviewed.length > 1 ? 's are' : ' is'} not reviewed yet, so approval can’t be recommended. You can still return, refer or escalate.{' '}
                <button className="btn quiet sm" style={{ height: 'auto', padding: 0, color: 'var(--accent)' }} onClick={goReview}>Review them</button></span>
            </div>
          )}
          <div style={{ display: 'grid', gap: 8 }} role="radiogroup" aria-label="Recommendation">
            {Object.entries(DECISIONS).map(([k, v]) => {
              const blocked = k === 'RECOMMEND_FOR_APPROVAL' && unreviewed.length > 0
              return (
                <label key={k} className={`choice ${d === k ? 'on' : ''} ${blocked ? 'blocked' : ''}`}>
                  <input type="radio" name="decision" checked={d === k} disabled={blocked} onChange={() => setD(k)} />
                  <span><b>{v.label}</b><small>{v.sub}</small></span>
                </label>
              )
            })}
          </div>
          <label className="field"><span>Remarks</span>
            <textarea className="input" rows={5} value={remark} onChange={e => setRemark(e.target.value)} placeholder="The basis for your recommendation" />
            <small>Recorded with your name in the audit trail. The competent authority takes the final decision.</small>
          </label>
          {err && <p className="error">{err}</p>}
        </div>
        <footer>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!d || remark.trim().length < 10} onClick={save}>Record recommendation</button>
        </footer>
      </aside>
    </>
  )
}

function UnfreezeModal({ a, onClose, onDone }) {
  const [remarks, setRemarks] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    const k = e => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])

  async function handleUnfreeze() {
    if (!remarks.trim()) return
    setBusy(true)
    setErr(null)
    try {
      await api(`/api/applications/${a.id}/unfreeze`, {
        method: 'POST',
        body: { remarks }
      })
      toast('Application unlocked! Rectification notice sent to institution.')
      onDone()
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="unfreeze-title" style={{ maxWidth: 540 }}>
        <header>
          <div>
            <h2 id="unfreeze-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Unlock size={18} color="#d97706" /> Send Unfreeze / Rectification
            </h2>
            <p className="small muted" style={{ marginTop: 3 }}>{a.institution_name} · {a.ref}</p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </header>
        <div className="body">
          <div className="note warning" style={{ background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e', padding: '12px 14px', borderRadius: 6, display: 'flex', gap: 8, fontSize: '0.85rem' }}>
            <span>
              Unfreezing unlocks the institution's document repository so they can re-upload corrected documents to address discrepancies.
            </span>
          </div>

          <label className="field" style={{ marginTop: 14 }}>
            <span style={{ fontWeight: 600 }}>Rectification Instructions for Institution *</span>
            <textarea
              className="input"
              rows={5}
              value={remarks}
              onChange={e => setRemarks(e.target.value)}
              placeholder="e.g. Please rectify the following 2 documents:&#10;1) Upload renewed Fire Safety NOC (current NOC expired on 31-03-2024).&#10;2) Re-upload signed Affidavit with full registered institution name."
            />
            <small>These remarks will appear in the institution's portal and official notification banner.</small>
          </label>
          {err && <p className="error" style={{ color: '#dc2626', marginTop: 8 }}>{err}</p>}
        </div>
        <footer>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button
            className="btn"
            style={{ background: '#d97706', color: '#ffffff', fontWeight: 600 }}
            disabled={!remarks.trim() || busy}
            onClick={handleUnfreeze}
          >
            {busy ? 'Unfreezing…' : 'Confirm Unfreeze & Notify Institution'}
          </button>
        </footer>
      </aside>
    </>
  )
}
