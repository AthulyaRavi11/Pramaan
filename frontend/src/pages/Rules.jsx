import { useState } from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'
import { api } from '../api'
import { Band, Loading, ago, toast, useApi } from '../ui'

const FILES = {
  'categories.yaml': 'Application types and the rules each must pass',
  'documents.yaml': 'Document types, what to read from them, validity',
  'sources.yaml': 'Issuing authorities and how to reach them',
  'infra_norms.yaml': 'Infrastructure norms and photo checks',
}

// Minimal YAML colouring: comments and keys.
function Line({ text }) {
  const c = text.indexOf('#')
  if (/^\s*#/.test(text)) return <span className="c">{text}</span>
  const m = /^(\s*-?\s*)([\w.-]+)(:)(.*)$/.exec(c > -1 ? text.slice(0, c) : text)
  const tail = c > -1 ? <span className="c">{text.slice(c)}</span> : null
  if (!m) return <>{text}</>
  return <>{m[1]}<span className="k">{m[2]}</span>{m[3]}{m[4]}{tail}</>
}

function Retention() {
  const [days, setDays] = useState('')
  const q = days === '' ? '' : `?days=${days}`
  const p = useApi(`/api/admin/retention${q}`)
  const [busy, setBusy] = useState(false)
  if (!p.data) return <div className="skeleton" />
  const d = p.data
  async function run() {
    if (!window.confirm(`Purge files for ${d.eligible.length} application(s)? This cannot be undone.`)) return
    setBusy(true)
    try {
      const r = await api('/api/admin/retention/run', { method: 'POST', body: { days: days === '' ? null : +days, confirm: true } })
      toast(`Purged ${r.purged_documents} document(s) from ${r.purged_applications} application(s)`); p.reload()
    } catch (e) { toast(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="sheet" style={{ marginTop: 20 }}>
      <div className="sheet-head"><h3>Data retention</h3><span className="small muted">Policy: {d.retention_days} days after a recommendation is recorded (PRAMAAN_RETENTION_DAYS)</span></div>
      <div className="sheet-body" style={{ display: 'grid', gap: 14 }}>
        <p className="small">After the retention period, uploaded files and extracted text are deleted. Kept: {d.kept_after_purge.join(', ')}. Every purge is written to the audit trail.</p>
        <dl className="kv">
          <dt>Documents held</dt><dd>{d.documents_held}</dd>
          <dt>Already purged</dt><dd>{d.documents_purged}</dd>
          <dt>Eligible now</dt><dd>{d.eligible.length ? d.eligible.map(a => <div key={a.id}><span className="mono">{a.ref}</span> · {a.docs} documents · recommendation {ago(a.decided_at)}</div>) : 'None'}</dd>
        </dl>
        <div className="danger-zone" style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <label className="field" style={{ width: 220 }}><span>Preview with a different period</span>
            <input className="input" type="number" min="0" placeholder={`${d.retention_days} (policy)`} value={days} onChange={e => setDays(e.target.value)} />
            <small>0 = everything with a recorded recommendation</small></label>
          <button className="btn" style={{ color: 'var(--danger)' }} onClick={run} disabled={busy || !d.eligible.length}><Trash2 size={14} />{busy ? 'Purging…' : `Purge ${d.eligible.length} application(s)`}</button>
        </div>
      </div>
    </div>
  )
}

export default function Rules() {
  const r = useApi('/api/admin/rules')
  const [f, setF] = useState('categories.yaml')
  if (!r.data) return <Loading error={r.error} />
  const lines = r.data[f].replace(/\n$/, '').split('\n')
  async function reload() {
    try { const x = await api('/api/admin/rules/reload', { method: 'POST' }); toast(`Loaded rule set ${x.version} (${x.fingerprint})`); r.reload() }
    catch (e) { toast(e.message) }
  }
  return (
    <>
      <Band>
        <div style={{ flex: '1 1 460px' }}>
          <h1>Rules, sources and data</h1>
          <p className="lede">Every check is driven by these files, so the Approval Process Handbook can change without changing code. Each run records the fingerprint of the rule set it used. Values shipped with the prototype are illustrative.</p>
        </div>
        <button className="btn primary" onClick={reload}><RefreshCw size={14} />Reload rule set</button>
      </Band>
      <div className="page lift">
        <div className="inst-grid">
          <nav className="files progress-rail" aria-label="Configuration files">
            {Object.entries(FILES).map(([k, v]) => <button key={k} className={f === k ? 'on' : ''} onClick={() => setF(k)}><b>{k}</b><span>{v}</span></button>)}
          </nav>
          <div>
            <div className="sheet lift-first" style={{ overflow: 'hidden' }}>
              <div className="sheet-head"><span className="mono">backend/app/config/{f}</span><span className="small muted">{lines.length} lines</span></div>
              <div className="code">
                <div className="ln">{lines.map((_, i) => i + 1).join('\n')}</div>
                <pre>{lines.map((l, i) => <div key={i}><Line text={l} />{'​'}</div>)}</pre>
              </div>
            </div>
            <Retention />
          </div>
        </div>
      </div>
    </>
  )
}
