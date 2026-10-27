import { useEffect, useMemo, useRef, useState } from 'react'
import { Building2, CheckCircle2, FileText, Image as ImageIcon, PanelLeftClose, PanelLeftOpen, ShieldAlert, ShieldCheck } from 'lucide-react'
import { api } from '../../api'
import {
  Avatar, CHECK_LABEL, checkOf, Empty, Kbd, REVIEW, REVIEW_ACTIONS, SEV_LABEL, SEV_ORDER, SevIcon, ago, fieldLabel, human, toast,
} from '../../ui'
import Viewer, { PhotoPair, valuesFor } from './Viewer'

const SEV_RANK = { high: 0, medium: 1, low: 2, info: 3 }

// Inside a document's group the document name is already the heading; drop it from the title.
const shortTitle = (t, docTitle) => {
  const x = docTitle && t.startsWith(`${docTitle}: `) ? t.slice(docTitle.length + 2) : t
  return x.charAt(0).toUpperCase() + x.slice(1)
}

export default function ReviewDesk({ data, docLabels, onChange }) {
  const { findings, documents, institutional_record: rec, application: app } = data
  const docs = documents.filter(d => !d.superseded)
  const docById = Object.fromEntries(documents.map(d => [d.id, d]))
  const [onlyOpen, setOnlyOpen] = useState(false)
  const [sel, setSel] = useState(null)
  const [pending, setPending] = useState(null)       // review action chosen by keyboard
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    const saved = localStorage.getItem('pramaan_desk_sidebar_open')
    return saved !== null ? saved === 'true' : true
  })

  const toggleSidebar = () => {
    setSidebarOpen(prev => {
      const next = !prev
      localStorage.setItem('pramaan_desk_sidebar_open', String(next))
      return next
    })
  }

  // Group issues the way an official reads a file: by document.
  const groups = useMemo(() => {
    const list = findings.filter(f => !onlyOpen || f.review_status === 'OPEN')
    const by = {}
    for (const f of list) {
      const key = f.module === 'infrastructure' ? 'infra' : f.document_id ? `d${f.document_id}` : 'app'
      ;(by[key] ||= []).push(f)
    }
    const order = Object.entries(by).map(([key, items]) => {
      items.sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity])
      const doc = key.startsWith('d') ? docById[+key.slice(1)] : null
      const title = key === 'app' ? 'Application and AICTE records' : key === 'infra' ? 'Infrastructure' : docLabels[doc?.declared_type] || doc?.original_name
      return { key, doc, title, items, worst: Math.min(...items.map(i => SEV_RANK[i.severity])) }
    })
    order.sort((a, b) => a.worst - b.worst || b.items.length - a.items.length)
    let n = 0
    order.forEach(g => g.items.forEach(i => { i.n = ++n }))
    return order
  }, [findings, onlyOpen]) // eslint-disable-line

  const flat = groups.flatMap(g => g.items)
  const current = flat.find(f => f.id === sel) || flat[0]
  useEffect(() => { if (current && current.id !== sel) setSel(current.id) }, [current, sel])

  // keyboard: J/K move, C/R/I/D choose a review action
  useEffect(() => {
    const onKey = e => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.metaKey || e.ctrlKey || e.altKey) return
      const i = flat.findIndex(f => f.id === current?.id)
      const k = e.key.toLowerCase()
      if (k === 'j' || e.key === 'ArrowDown') { e.preventDefault(); flat[i + 1] && setSel(flat[i + 1].id) }
      else if (k === 'k' || e.key === 'ArrowUp') { e.preventDefault(); flat[i - 1] && setSel(flat[i - 1].id) }
      else { const a = REVIEW_ACTIONS.find(x => x.kbd.toLowerCase() === k); if (a && current?.review_status === 'OPEN') { e.preventDefault(); setPending(a.key) } }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [flat, current])

  useEffect(() => { document.querySelector(`[data-issue="${current?.id}"]`)?.scrollIntoView({ block: 'nearest' }) }, [current?.id])

  if (!findings.length) return <Empty title="Nothing to review">The automated checks raised no issues for this application.</Empty>

  const afterReview = () => {
    const next = flat.slice(flat.findIndex(f => f.id === current.id) + 1).find(f => f.review_status === 'OPEN')
    if (next) setSel(next.id)
    onChange()
  }

  const openCount = findings.filter(f => f.review_status === 'OPEN' && f.severity !== 'info').length

  // center pane: what to show for the selected issue
  const ev = current?.evidence || {}
  const doc = current?.document_id ? docById[current.document_id] : null
  let center
  if (ev.photo_a_id && ev.photo_b_id) {
    center = <PhotoPair a={{ id: ev.photo_a_id, tag: ev.tag_a, name: ev.photo_a }} b={{ id: ev.photo_b_id, tag: ev.tag_b, name: ev.photo_b }}
                        caption="Left and right were submitted as different rooms." />
  } else if (ev.other_document_id && doc) {
    center = <PhotoPair a={{ id: doc.id, tag: `This application`, name: doc.original_name }}
                        b={{ id: ev.other_document_id, tag: ev.other_application, name: 'submitted by another institution' }} />
  } else if (doc?.purged) {
    center = <div className="viewer-stage"><div className="record-sheet"><h3>Document purged</h3><p className="src">Removed under the data-retention policy. The finding, its evidence summary and the review remain on record.</p></div></div>
  } else if (doc) {
    const onDoc = flat.filter(f => f.document_id === doc.id && f.module !== 'infrastructure').map(f => ({ ...f, values: valuesFor(f, doc) }))
    const meta = current.rule_id === 'ANOM-META' ? 'This issue is in the file’s properties, not on the page. See the evidence for details.' : null
    center = <Viewer doc={doc} docLabel={docLabels[doc.declared_type] || 'Photo'} issues={onDoc} selectedId={current.id} onSelect={setSel} note={meta} sidebarOpen={sidebarOpen} onToggleSidebar={toggleSidebar} openCount={openCount} />
  } else {
    center = <div className="viewer-stage"><RecordSheet f={current} rec={rec} app={app} docLabels={docLabels} /></div>
  }

  return (
    <div className={`desk ${!sidebarOpen ? 'sidebar-collapsed' : ''}`}>
      <aside className="pane-issues" aria-label="Issues">
        <div className="pane-head">
          <button
            type="button"
            className="btn-sidebar-toggle"
            onClick={toggleSidebar}
            title="Slide sidebar closed (PDF occupies full space)"
            aria-label="Collapse sidebar"
          >
            <PanelLeftClose size={15} />
          </button>
          <b>{openCount} to review <span className="muted" style={{ fontWeight: 400 }}>of {findings.length}</span></b>
          <span className="seg">
            <button className={!onlyOpen ? 'on' : ''} onClick={() => setOnlyOpen(false)}>All</button>
            <button className={onlyOpen ? 'on' : ''} onClick={() => setOnlyOpen(true)}>Open</button>
          </span>
        </div>
        {groups.map(g => (
          <section className="doc-group" key={g.key}>
            <header>{g.key === 'app' ? <Building2 size={14} /> : g.key === 'infra' ? <ImageIcon size={14} /> : <FileText size={14} />}
              <span>{g.title}</span><span className="count">{g.items.length}</span></header>
            {g.items.map(f => (
              <button key={f.id} data-issue={f.id} className={`issue ${f.id === current?.id ? 'on' : ''} ${f.review_status !== 'OPEN' ? 'done' : ''}`} onClick={() => setSel(f.id)}>
                {f.review_status !== 'OPEN' ? <CheckCircle2 size={15} className="check-done" style={{ marginTop: 2 }} /> : <SevIcon s={f.severity} />}
                <span><span className="t">{shortTitle(f.title, g.title)}</span><span className="g" style={{ display: 'block' }}>
                  {f.review_status !== 'OPEN' ? REVIEW[f.review_status] : CHECK_LABEL[checkOf(f)]}</span></span>
                <span className="pin">{f.n}</span>
              </button>
            ))}
          </section>
        ))}
        {!flat.length && <Empty>All issues reviewed.</Empty>}
      </aside>

      <section className="pane-viewer" aria-label="Document">
        {!sidebarOpen && !doc && (
          <div className="viewer-bar">
            <button
              type="button"
              className="btn-sidebar-toggle"
              onClick={toggleSidebar}
              title="Show issues sidebar"
            >
              <PanelLeftOpen size={14} />
              <span>{openCount} to review</span>
            </button>
          </div>
        )}
        {current && center}
      </section>

      <aside className="pane-evidence" aria-label="Evidence and review">
        {current && <Evidence key={current.id} f={current} doc={doc} docLabels={docLabels} pending={pending} clearPending={() => setPending(null)} onDone={afterReview} />}
      </aside>
    </div>
  )
}

/* ------------------------------------------------------------------ evidence */

const SHOWN = {
  found_value: 'Printed on document', expected: 'Expected', line_text: 'Line read', value_font: 'Font of this value', expected_font: 'Font of other values',
  creation_date: 'File created', modification_date: 'File last modified', producer: 'Last saved with', creator: 'Created with', incremental_saves: 'Edits appended',
  age_days: 'Age (days)', limit_days: 'Limit (days)', other_value: 'Declared in application', difference_pct: 'Difference (%)',
  application_value: 'In application', record_value: 'In AICTE record', record_path: 'Record', record_source: 'Source',
  required: 'Required', uploaded: 'Uploaded', declared: 'Declared', basis: 'Basis', intake: 'Annual intake', faculty: 'Faculty', ratio: 'Ratio', max: 'Maximum',
  programme: 'Programme', requested_intake: 'Requested intake', approved_intake: 'Approved intake',
  other_application: 'Other application', name_on_document: 'Name on document', text_similarity: 'Text similarity', reference: 'Reference',
  texture_correlation: 'Texture match', ransac_inliers: 'Matched points', recommendation: 'Suggested next step', blur_var: 'Sharpness', brightness: 'Brightness',
  missing_room_types: 'Missing room types', missing_fields: 'Missing fields', span_days: 'Validity (days)', issue_date: 'Issue date', confidence: 'Classifier confidence',
  declared_type: 'Uploaded as', detected_type: 'Reads as', max_block: 'Peak error level', median: 'Median error level', fields: 'Fields',
}

function Evidence({ f, doc, docLabels, pending, clearPending, onDone }) {
  const ev = f.evidence || {}
  const rows = Object.entries(SHOWN).filter(([k]) => ev[k] !== undefined && ev[k] !== null && ev[k] !== '')
    .map(([k, label]) => [label, Array.isArray(ev[k]) ? ev[k].map(human).join(', ') : k.endsWith('_type') ? (docLabels[ev[k]] || ev[k]) : String(ev[k])])
  const sig = ev.response?.signature
  return (
    <div className="ev">
      <div className="ev-kicker"><SevIcon s={f.severity} size={14} /><span>{SEV_LABEL[f.severity]}</span><span>·</span><span>{CHECK_LABEL[checkOf(f)]}</span>
        <span className="mono faint" style={{ marginLeft: 'auto' }}>{f.rule_id}</span></div>
      <h2>{shortTitle(f.title, doc && docLabels[doc.declared_type])}</h2>
      <p className="why">{f.reason}</p>

      {ev.comparison?.length > 0 && (
        <div className="ev-section">
          <h4>{ev.method === 'qr_signed' ? 'Printed text against the authority’s signed QR code' : 'Document against the issuing authority’s record'}</h4>
          <table className="cmp">
            <thead><tr><th>Field</th><th>On document</th><th>{ev.method === 'qr_signed' ? 'In signed QR' : 'Authority record'}</th></tr></thead>
            <tbody>{ev.comparison.map(c => (
              <tr key={c.field}><td className="muted">{fieldLabel(c.field)}</td>
                <td className={c.match ? 'good' : 'bad'}>{String(c.document ?? '—')}</td>
                <td className={c.match ? 'good' : 'bad'}>{String(c.source ?? '—')}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {sig && <div className={`sig ${sig.startsWith('VALID') ? '' : 'bad'}`}>{sig.startsWith('VALID') ? <ShieldCheck size={15} /> : <ShieldAlert size={15} />}
        <span>{sig.startsWith('VALID') ? 'The QR code’s signature is genuine — it was issued by the authority, so its values can be trusted.' : `QR signature: ${sig}`}</span></div>}
      {ev.method === 'pdf_signature' && ev.response?.signer && (
        <div className="sig-card">
          <header className={f.rule_id === 'VER-SIGNATURE' ? 'bad' : 'ok'}>{f.rule_id === 'VER-SIGNATURE' ? <ShieldAlert size={15} /> : <ShieldCheck size={15} />}
            Digital signature (PAdES)</header>
          <dl className="kv">
            <dt>Signed by</dt><dd>{ev.response.signer}</dd>
            <dt>Signed at</dt><dd>{String(ev.response.signed_at).slice(0, 19).replace('T', ' ')}</dd>
            <dt>Signer trusted</dt><dd>{ev.response.trusted ? 'Yes — chains to a trusted root' : 'No'}</dd>
            <dt>Signature intact</dt><dd>{ev.response.intact && ev.response.valid ? 'Yes' : 'No'}</dd>
            <dt>Covers</dt><dd className={ev.response.coverage === 'ENTIRE_FILE' ? '' : 'error'}>{ev.response.coverage === 'ENTIRE_FILE' ? 'The whole file' : 'Only an earlier version — content was added after signing'}</dd>
          </dl>
        </div>
      )}
      {ev.method === 'repository' && ev.response?.issued_sha256 && (
        <div className="ev-section"><h4>File fingerprints (SHA-256)</h4>
          <div className="hashes"><div><span>Issuer’s copy</span>{ev.response.issued_sha256}…</div>
            {ev.response.uploaded_sha256 && <div className="error"><span>Uploaded</span>{ev.response.uploaded_sha256}…</div>}</div></div>
      )}
      {ev.response?.message && !ev.comparison?.length && !f.reason.includes(ev.response.message) && <div className="ev-section"><h4>Response from {ev.source}</h4><p className="small">{ev.response.message}</p></div>}

      {rows.length > 0 && (
        <div className="ev-section">
          <h4>Evidence</h4>
          <dl className="kv">{rows.map(([k, v]) => <FragmentKV key={k} k={k} v={v} />)}</dl>
        </div>
      )}
      {f.ref && <div className="ev-section"><h4>Basis</h4><p className="small">{f.ref}</p></div>}
      {doc && <p className="small muted" style={{ marginTop: 14 }}>From {doc.original_name}{ev.checked_at ? ` · checked ${ago(ev.checked_at)}` : ''}</p>}
      {ev.note && <p className="disclaimer">{ev.note}</p>}

      <Review f={f} pending={pending} clearPending={clearPending} onDone={onDone} />
    </div>
  )
}

const FragmentKV = ({ k, v }) => <><dt>{k}</dt><dd>{v}</dd></>

function Review({ f, pending, clearPending, onDone }) {
  const [status, setStatus] = useState(null)
  const [remark, setRemark] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const box = useRef()
  useEffect(() => { if (pending) { setStatus(pending); clearPending(); setTimeout(() => box.current?.focus(), 0) } }, [pending, clearPending])

  async function save(next = status) {
    setErr(null); setBusy(true)
    try {
      await api(`/api/findings/${f.id}/review`, { method: 'POST', body: { status: next, remark: next === 'OPEN' ? 'Reopened for review' : remark } })
      toast(next === 'OPEN' ? 'Issue reopened' : `Recorded: ${REVIEW[next].toLowerCase()}`)
      onDone()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  if (f.review_status !== 'OPEN') return (
    <div className="review">
      <div className="reviewed"><Avatar name={f.reviewer} sm /><div><b>{REVIEW[f.review_status]}</b> by {f.reviewer} · {ago(f.reviewed_at)}
        <p className="muted" style={{ marginTop: 3 }}>{f.review_remark}</p></div></div>
      <button className="btn quiet sm" style={{ marginTop: 8 }} onClick={() => save('OPEN')} disabled={busy}>Reopen</button>
    </div>
  )
  const placeholder = { DISMISSED: 'Why this does not apply', RECTIFICATION_REQUESTED: 'What the institution must correct — they will see this',
    INSPECTION_REQUIRED: 'What the inspection should check', CONFIRMED: 'What you checked' }[status] || ''
  return (
    <div className="review">
      <h4>Your review</h4>
      <div className="actions-grid">
        {REVIEW_ACTIONS.map(a => (
          <button key={a.key} className={status === a.key ? 'on' : ''} onClick={() => { setStatus(a.key); setTimeout(() => box.current?.focus(), 0) }}>
            {a.label}<Kbd>{a.kbd}</Kbd></button>
        ))}
      </div>
      {status && (
        <form className="remark" onSubmit={e => { e.preventDefault(); save() }}>
          <textarea ref={box} className="input" value={remark} onChange={e => setRemark(e.target.value)} placeholder={placeholder}
                    onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && remark.trim().length >= 5) save(); if (e.key === 'Escape') setStatus(null) }} />
          {err && <p className="error">{err}</p>}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="btn primary" disabled={remark.trim().length < 5 || busy}>Save review</button>
            <span className="small muted"><Kbd>Ctrl</Kbd> <Kbd>Enter</Kbd></span>
          </div>
        </form>
      )}
      <p className="hint"><span><Kbd>J</Kbd> <Kbd>K</Kbd> next / previous issue</span><span>Every review is signed and logged</span></p>
    </div>
  )
}

/* ------------------------------------------------------------------ issues without a document */

function RecordSheet({ f, rec, app, docLabels }) {
  const ev = f.evidence || {}
  let title = 'Application check', src = 'Rule set', body
  if (ev.application_value !== undefined) {
    title = 'Application against the AICTE institution master'; src = ev.record_source
    body = <VS rows={[[human(f.rule_id.includes('REC-01') ? 'Institution name' : 'Permanent ID'), ev.application_value, ev.record_value]]} a="In application" b="In AICTE record" />
  } else if (ev.record_path) {
    title = 'AICTE record'; src = ev.record_source
    body = <VS rows={[[human(ev.record_path), ev.expected === 'EMPTY' ? 'None open' : ev.expected, String(ev.record_value)]]} a="Required" b="Record shows" />
  } else if (ev.requested_intake !== undefined) {
    title = 'Intake against previous approval'; src = 'Approved intake, AICTE records'
    body = <VS rows={(app.form.programmes || []).map(p => {
      const a = rec?.approved_programmes?.find(x => x.code === p.code)
      return [p.name, a ? a.intake : 'Not approved', p.intake]
    })} a="Approved" b="Requested" diff={(r) => r[1] === 'Not approved' || r[2] > r[1]} />
  } else if (ev.required !== undefined && ev.uploaded !== undefined) {
    title = 'Checklist for this application type'; src = f.ref
    body = <VS rows={[[f.title.replace(/^Missing: /, '').replace(/\s\(\d+\/\d+\)$/, ''), ev.required, ev.uploaded]]} a="Required" b="Uploaded" diff={r => r[2] < r[1]} />
  } else if (ev.declared !== undefined && ev.required !== undefined) {
    title = 'Declared infrastructure against norms'; src = 'infra_norms.yaml (illustrative values)'
    body = <VS rows={[[f.title.replace('Declared ', '').replace(' below norm', ''), ev.required, ev.declared]]} a="Norm" b="Declared" diff={r => r[2] < r[1]} />
  } else if (ev.ratio !== undefined) {
    title = 'Student–faculty ratio'; src = 'infra_norms.yaml (illustrative values)'
    body = <VS rows={[['Annual intake', '', ev.intake], ['Faculty', '', ev.faculty], ['Students per faculty', `≤ ${ev.max}`, ev.ratio]]} a="Norm" b="Application" diff={r => r[0] === 'Students per faculty'} />
  } else if (ev.missing_room_types) {
    title = 'Photo evidence coverage'; src = f.ref
    body = <VS rows={ev.missing_room_types.map(t => [human(t), 'At least one photo', 'None'])} a="Required" b="Submitted" diff={() => true} />
  } else {
    body = <dl className="kv">{Object.entries(ev).filter(([k, v]) => typeof v !== 'object' && k !== 'note').map(([k, v]) => <FragmentKV key={k} k={human(k)} v={String(v)} />)}</dl>
  }
  return (
    <div className="record-sheet">
      <h3>{title}</h3>
      <p className="src">{src}</p>
      {body}
      {docLabels && null}
    </div>
  )
}

function VS({ rows, a, b, diff }) {
  return (
    <table className="vs">
      <thead><tr><th /><th>{a}</th><th>{b}</th></tr></thead>
      <tbody>{rows.map((r, i) => {
        const bad = diff ? diff(r) : String(r[1]) !== String(r[2])
        return <tr key={i}><td className="muted">{r[0]}</td><td>{String(r[1])}</td><td className={bad ? 'diff' : 'same'}>{bad ? <mark>{String(r[2])}</mark> : String(r[2])}</td></tr>
      })}</tbody>
    </table>
  )
}

export { SEV_ORDER }
