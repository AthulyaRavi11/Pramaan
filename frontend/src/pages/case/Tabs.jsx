import { Fragment, useState } from 'react'
import { ArrowLeft, Bot, FileUp, Gavel, KeyRound, LogIn, LogOut, RefreshCw, ScanSearch, Send, ShieldAlert, ShieldCheck, Eye, ClipboardCheck, FileDown, Trash2 } from 'lucide-react'
import { fileUrl } from '../../api'
import { Avatar, Empty, Status, Tag, VerStatus, ago, fieldLabel, fmtDate, human, sentence, useApi, Loading, SevIcon } from '../../ui'
import Viewer, { valuesFor } from './Viewer'

/* ------------------------------------------------------------------ documents (dossier) */

export function Documents({ data, docLabels }) {
  const [open, setOpen] = useState(null)
  const docs = data.documents.filter(d => !d.superseded && d.declared_type !== 'infra_photo')
  const status = data.report?.document_status || {}
  const issuesOn = id => data.findings.filter(f => f.document_id === id && f.module !== 'infrastructure')
  const cur = docs.find(d => d.id === open)

  if (cur) {
    const fields = cur.extraction?.fields || {}
    const issues = issuesOn(cur.id).map((f, i) => ({ ...f, n: i + 1, values: valuesFor(f, cur) }))
    const meta = cur.extraction?.pdf_metadata || {}
    return (
      <div className="doc-split">
        <section className="pane-viewer"><Viewer doc={cur} docLabel={docLabels[cur.declared_type]} issues={issues} /></section>
        <aside className="pane-evidence">
          <div className="ev">
            <button className="btn quiet sm" onClick={() => setOpen(null)} style={{ marginLeft: -8 }}><ArrowLeft size={14} />All documents</button>
            <h2 style={{ marginTop: 10 }}>{docLabels[cur.declared_type]}</h2>
            <p className="small muted" style={{ marginTop: 4 }}>{cur.original_name} · version {cur.version} · uploaded {ago(cur.uploaded_at)}</p>
            <div className="ev-section">
              <h4>How it was read</h4>
              <dl className="kv">
                <dt>Method</dt><dd>{cur.ocr_used ? `Scanned page, read with OCR${cur.extraction?.ocr_confidence ? ` (${Math.round(cur.extraction.ocr_confidence * 100)}% confidence)` : ''}` : 'Digital text layer'}</dd>
                <dt>Recognised as</dt><dd>{cur.detected_type === cur.declared_type ? `${docLabels[cur.detected_type]} (${Math.round(cur.classification_conf * 100)}%)` : <span className="error">{docLabels[cur.detected_type] || 'Unrecognised'} — not what was uploaded</span>}</dd>
                <dt>Issuing authority</dt><dd><VerStatus s={status[cur.id] || 'NOT_APPLICABLE'} /></dd>
              </dl>
            </div>
            <div className="ev-section">
              <h4>Fields extracted</h4>
              <table className="cmp"><tbody>{Object.entries(fields).map(([k, v]) => (
                <tr key={k}><td className="muted">{fieldLabel(k)}</td><td>{v.value}</td><td className={v.confidence < .6 ? 'bad' : 'good'} style={{ textAlign: 'right' }}>{Math.round(v.confidence * 100)}%</td></tr>
              ))}</tbody></table>
              {!Object.keys(fields).length && <p className="small muted">No fields could be read.</p>}
            </div>
            {(meta.Creator || meta.Producer) && <div className="ev-section"><h4>File properties</h4><dl className="kv">
              {[['Created with', meta.Creator], ['Last saved with', meta.Producer], ['Created', pdfDate(meta.CreationDate)], ['Modified', pdfDate(meta.ModDate)]]
                .filter(r => r[1]).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl></div>}
            {issues.length > 0 && <div className="ev-section"><h4>Issues on this document</h4>
              {issues.map(f => <p key={f.id} className="small" style={{ display: 'flex', gap: 8, marginBottom: 6 }}><SevIcon s={f.severity} size={14} />{f.title}</p>)}</div>}
          </div>
        </aside>
      </div>
    )
  }
  return (
    <div className="case-body pad">
      <div className="dossier">
        {docs.map(d => {
          const n = issuesOn(d.id).filter(f => ['high', 'medium'].includes(f.severity)).length
          return (
            <button key={d.id} className="doc-card" onClick={() => setOpen(d.id)}>
              <div className="thumb">{d.purged ? <div className="empty small" style={{ padding: '40% 12px' }}>Purged under the retention policy</div> : <img src={fileUrl(d.id)} alt="" loading="lazy" />}{n > 0 && <span className="flag"><Tag tone="danger">{n} issue{n > 1 ? 's' : ''}</Tag></span>}</div>
              <div className="cap"><b>{docLabels[d.declared_type]}</b><VerStatus s={status[d.id] || 'NOT_APPLICABLE'} /></div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function pdfDate(s) {
  const m = /D:(\d{4})(\d{2})(\d{2})/.exec(s || '')
  return m ? new Date(`${m[1]}-${m[2]}-${m[3]}`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : null
}

/* ------------------------------------------------------------------ issuing authorities */

const METHOD = { qr_signed: 'Signed QR code', api: 'Reference lookup', pdf_signature: 'PDF digital signature', repository: 'Issuer’s repository copy', manual: 'No automated source' }

export function Sources({ data, docLabels, sourceLabels }) {
  const v = data.verifications
  if (!v.length) return <Empty title="No source checks">None of the uploaded documents has an issuing-authority source configured.</Empty>
  const docs = Object.fromEntries(data.documents.map(d => [d.id, d]))
  return (
    <div className="case-body pad">
      <div className="sheet">
        <table className="table">
          <thead><tr><th>Document</th><th>Checked with</th><th>Outcome</th><th>Fields compared</th><th>When</th></tr></thead>
          <tbody>{v.map(x => (
            <tr key={x.id}>
              <td><div className="cell-title">{docLabels[docs[x.document_id]?.declared_type]}</div><div className="cell-sub">{docs[x.document_id]?.original_name}</div></td>
              <td><div>{(sourceLabels[x.source] || human(x.source)).replace(' (demo registry)', '')}</div><div className="cell-sub">{METHOD[x.method] || x.method}</div></td>
              <td><VerStatus s={x.status} />{x.response?.message && <div className="cell-sub" style={{ maxWidth: '30ch' }}>{x.response.message}</div>}</td>
              <td className="small">{x.comparison?.length ? x.comparison.map(c => (
                <div key={c.field} style={{ color: c.match ? 'var(--ink-2)' : 'var(--danger)' }}>{c.match ? '✓' : '✕'} {human(c.field)}{!c.match && <span> — {c.document} vs {c.source}</span>}</div>
              )) : <span className="faint">—</span>}</td>
              <td className="muted nowrap small">{fmtDate(x.checked_at)}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <p className="small muted" style={{ marginTop: 12 }}>Pending and unavailable sources are retried when you re-run checks. Documents without an automated source go to manual confirmation. The demo simulates one authority offline and one slow to respond.</p>
    </div>
  )
}

/* ------------------------------------------------------------------ infrastructure */

export function Infrastructure({ data }) {
  const inf = data.report?.infrastructure
  if (!inf) return <Empty title="Not checked yet" />
  const photos = data.documents.filter(d => !d.superseded && d.declared_type === 'infra_photo')
  const flagged = new Set(data.findings.filter(f => f.module === 'infrastructure').flatMap(f => [f.document_id, f.evidence?.photo_a_id]).filter(Boolean))
  const rows = [['Classrooms', 'classrooms'], ['Laboratories', 'labs'], ['Built-up area (m²)', 'built_up_area_sqm']]
  const n = inf.norms
  return (
    <div className="case-body pad">
      <div className="two-col">
        <div className="sheet">
          <div className="sheet-head"><h3>Declared against norms</h3><span className="small muted">Intake {n.total_intake} · faculty {n.faculty ?? '—'}</span></div>
          <div className="sheet-body" style={{ display: 'grid', gap: 16 }}>
            {rows.map(([l, k]) => {
              const have = n.declared[k], need = n.required[k]
              const short = have != null && have < need
              return (
                <div className="meter" key={k}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                    <span>{l}</span><span><b style={{ fontWeight: 500 }}>{have ?? '—'}</b> <span className="muted">of {need} required</span></span></div>
                  <div className="meter-track"><i className={short ? 'short' : ''} style={{ width: `${Math.min(100, (have || 0) / Math.max(need, 1) * 100)}%` }} /></div>
                </div>
              )
            })}
            <p className="small muted">Norm values are illustrative placeholders in <span className="mono">infra_norms.yaml</span> — set them from the applicable handbook.</p>
          </div>
        </div>
        <div className="sheet">
          <div className="sheet-head"><h3>Photo evidence</h3><span className="small muted">{inf.photos.room_types.join(', ') || 'none'}</span></div>
          <div className="sheet-body photos">
            {photos.map(p => (
              <figure key={p.id} className={flagged.has(p.id) ? 'flagged' : ''}>
                <img src={fileUrl(p.id)} alt={p.tag || p.original_name} loading="lazy" />
                <figcaption><b style={{ fontWeight: 500 }}>{p.tag}</b>{flagged.has(p.id) ? <span className="error">flagged</span> : <span className="faint">sharpness {Math.round(p.extraction?.photo_metrics?.blur_var || 0)}</span>}</figcaption>
              </figure>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ AICTE records */

export function Records({ data }) {
  const rec = data.institutional_record, form = data.application.form
  if (!rec) return <Empty title="No AICTE record found">No institution in AICTE records matches this application.</Empty>
  const ay = form.academic_year
  const row = (label, a, b, ok = String(a) === String(b)) => ({ label, a, b, ok })
  const rows = [
    row('Institution name', form.institution_name, rec.name),
    row('Permanent ID', form.aicte_permanent_id, rec.permanent_id),
    row('Faculty', form.faculty_count, rec.faculty_on_record),
    ...rec.approved_programmes.map(p => {
      const r = form.programmes.find(x => x.code === p.code)
      return row(`${p.name} — intake`, r?.intake ?? '—', p.intake, !r || r.intake <= p.intake)
    }),
  ]
  return (
    <div className="case-body pad">
      <div className="two-col">
        <div className="sheet">
          <div className="sheet-head"><h3>Application against AICTE records</h3><span className="small muted">Synthetic records · access logged</span></div>
          <table className="table">
            <thead><tr><th /><th>Application</th><th>AICTE record</th></tr></thead>
            <tbody>{rows.map(r => (
              <tr key={r.label}><td className="muted">{r.label}</td><td style={r.ok ? null : { color: 'var(--danger)', fontWeight: 500 }}>{String(r.a)}</td><td>{String(r.b)}</td></tr>
            ))}</tbody>
          </table>
        </div>
        <div className="sheet">
          <div className="sheet-head"><h3>Standing with AICTE</h3></div>
          <div className="sheet-body">
            <dl className="kv">
              <dt>Established</dt><dd>{rec.established} · {rec.state}</dd>
              <dt>Previous approval</dt><dd>{rec.previous_eoa?.status === 'GRANTED' ? <Status tone="ok">Granted for {rec.previous_eoa.academic_year}</Status> : <Status tone="danger">{rec.previous_eoa?.status || 'None on record'}</Status>}
                <div className="small muted mono">{rec.previous_eoa?.letter_no}</div></dd>
              <dt>Processing fee {ay}</dt><dd>{rec.ter_payments?.[ay] === 'PAID' ? <Status tone="ok">Paid</Status> : <Status tone="danger">{sentence(rec.ter_payments?.[ay] || 'not recorded')}</Status>}</dd>
              <dt>Open deficiencies</dt><dd>{rec.open_deficiencies?.length ? rec.open_deficiencies.map(x => <div key={x}><Status tone="warn">{x}</Status></div>) : <Status tone="ok">None</Status>}</dd>
            </dl>
          </div>
          {rec.application_history?.length > 0 && <>
            <div className="sheet-head" style={{ borderTop: '1px solid var(--line)' }}><h3>Application history</h3><span className="small muted">From AICTE records</span></div>
            <div className="sheet-body">
              <ul className="history">{rec.application_history.map(h => (
                <li key={h.ref} className={h.outcome === 'Approved' ? '' : 'cond'}>
                  <b>{h.academic_year} · {h.type}</b> <span className="muted">— {h.outcome}</span>
                  <div className="meta"><span className="mono">{h.ref}</span>{h.remarks ? ` · ${h.remarks}` : ''}</div>
                </li>
              ))}</ul>
            </div>
          </>}
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ history */

const SOURCE_NAMES = {
  state_fire_services: 'Fire & Emergency Services', state_pollution_board: 'Pollution Control Board', nba_registry: 'NBA',
  affiliating_university: 'Affiliating university', municipal_records: 'Municipal records', aicte_payments: 'AICTE payments',
}

const ICON = {
  LOGIN: LogIn, LOGIN_FAILED: LogIn, LOGOUT: LogOut, SUSPICIOUS_LOGIN_BRUTEFORCE_DETECTED: ShieldAlert,
  DOCUMENT_UPLOADED: FileUp, DOCUMENT_UPLOADED_LOCAL_VAULT: FileUp,
  APPLICATION_SUBMITTED: Send, APPLICATION_DATA_FROZEN_SYNCED_TO_AICTE: ShieldCheck,
  UNFREEZE_REQUESTED_BY_INSTITUTION: RefreshCw, APPLICATION_UNFROZEN_BY_OFFICER: KeyRound,
  VALIDATION_STARTED: ScanSearch, VALIDATION_COMPLETED: ClipboardCheck,
  RECORDS_ACCESSED: KeyRound, RECORD_ACCESSED: KeyRound, SOURCE_RESPONSE: ShieldCheck, FINDING_REVIEWED: Eye,
  OFFICIAL_DECISION: Gavel, FINAL_STATUTORY_DECISION: Gavel, APPLICATION_VIEWED: Eye, PII_UNMASKED: Eye,
  APPLICATION_CREATED: FileUp, RULESET_RELOADED: RefreshCw, DOCUMENT_ACCESSED: Eye, REPORT_GENERATED: FileDown,
  RETENTION_PURGE: Trash2, ALERT_ACKNOWLEDGED: ClipboardCheck,
}

export function describe(e) {
  const d = e.detail || {}
  switch (e.action) {
    case 'DOCUMENT_UPLOADED_LOCAL_VAULT':
      return [`Uploaded to Local Vault (${human(d.type)})`, `version ${d.version} · sha256: ${d.sha256}… (Local Cloud)`]
    case 'APPLICATION_DATA_FROZEN_SYNCED_TO_AICTE':
      return ['Application data frozen & synced to AICTE', `Ref: ${d.ref} · AY ${d.academic_year || '2027-28'} · ${d.documents_synced} file(s) synchronized`]
    case 'UNFREEZE_REQUESTED_BY_INSTITUTION':
      return ['Unfreeze application requested by institution', d.reason ? `Reason: ${d.reason}` : '']
    case 'APPLICATION_UNFROZEN_BY_OFFICER':
      return ['Application unfrozen by AICTE officer', d.remarks ? `Remarks: ${d.remarks}` : 'Unlocked for document modifications']
    case 'PII_UNMASKED':
      return ['PII Data Unmasked for Scrutiny', `${d.reason || 'Authorized statutory inspection'} (IP: ${e.actor_ip || '127.0.0.1'})`]
    case 'LOGIN':
      return ['Signed in via CAPTCHA verification', `Role: ${sentence(e.role)} (IP: ${e.actor_ip || '127.0.0.1'})`]
    case 'LOGIN_FAILED':
      return ['Failed login attempt', `Username: ${e.actor} (IP: ${e.actor_ip || '127.0.0.1'})`]
    case 'LOGOUT':
      return ['Signed out', `Session revoked (IP: ${e.actor_ip || '127.0.0.1'})`]
    case 'SUSPICIOUS_LOGIN_BRUTEFORCE_DETECTED':
      return ['Brute-force security alert triggered', `5 failed attempts locked out for 3 mins (IP: ${e.actor_ip || '127.0.0.1'})`]
      return ['Failed login attempt', `Username: ${e.actor} (IP: ${e.actor_ip || '127.0.0.1'})`]
    case 'FINAL_STATUTORY_DECISION':
      return [`Final Statutory Decision: ${sentence(d.final_decision || d.decision)}`, d.remark || '']
    case 'ALERT_ACKNOWLEDGED':
      return ['Alert acknowledged by officer', `Alert ID: ${d.alert_id}`]
    case 'RECORD_ACCESSED':
      return ['Institutional record accessed', `Institution: ${d.institution_id}`]
    case 'DOCUMENT_UPLOADED': return [`Uploaded ${human(d.type)}`, `version ${d.version} · sha256 ${d.sha256}…`]
    case 'SOURCE_RESPONSE': return [`${SOURCE_NAMES[d.source] || human(d.source)}: ${sentence(d.status)}`, `${d.document} · ${METHOD[d.method] || human(d.method)}`]
    case 'VALIDATION_STARTED': return ['Automated checks started', `rule set ${d.ruleset_version} (${d.ruleset_fingerprint}) · ${d.documents} documents`]
    case 'VALIDATION_COMPLETED': return [`Checks finished: ${sentence(d.system_status)}`, d.timings ? `${d.rules_evaluated} rules · ${d.timings.total_ms} ms` : '']
    case 'RECORDS_ACCESSED': return ['AICTE records read', (d.datasets || []).map(human).join(', ')]
    case 'FINDING_REVIEWED': return [`Reviewed “${d.title}”: ${sentence(d.status)}`, d.remark]
    case 'OFFICIAL_DECISION': return [`Recommendation: ${sentence(d.decision)}`, d.remark]
    case 'APPLICATION_CREATED': return ['Application created', d.ref]
    case 'REPORT_GENERATED': return ['Downloaded the validation report', `run ${d.run_id}`]
    case 'RETENTION_PURGE': return [`Purged ${d.documents} document(s) under the ${d.policy_days}-day retention policy`, `recommendation recorded ${String(d.decided_at).slice(0, 10)}`]
    case 'RULESET_RELOADED': return [`Reloaded rule set ${d.version}`, d.fingerprint]
    default: return [sentence(e.action), '']
  }
}

// Collapse runs of the same routine event (e.g. repeated views) into one line.
function collapse(entries) {
  const out = []
  for (const e of entries) {
    const last = out[out.length - 1]
    if (last && ['APPLICATION_VIEWED', 'LOGIN', 'DOCUMENT_ACCESSED'].includes(e.action) && last.action === e.action && last.actor === e.actor) last.times++
    else out.push({ ...e, times: 1 })
  }
  return out
}

export function Timeline({ entries }) {
  if (!entries || entries.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '42px 20px', color: 'var(--muted)' }}>
        <ShieldCheck size={38} style={{ color: 'var(--accent)', opacity: 0.85, marginBottom: 10 }} />
        <h3 style={{ margin: '0 0 6px', fontSize: 16, color: 'var(--ink)' }}>Audit Trail Active</h3>
        <p style={{ margin: 0, fontSize: 13, maxWidth: 440, marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.5 }}>
          No previous entries found. Live events will be cryptographically signed and streamed here as users sign in, upload documents, freeze data, and perform scrutiny.
        </p>
      </div>
    )
  }
  return (
    <ul className="timeline">
      {collapse(entries).map(e => {
        const I = ICON[e.action] || Bot
        const [what, detail] = describe(e)
        return (
          <li key={e.id}>
            {e.role === 'system' ? <I size={16} className="faint" style={{ marginTop: 2 }} /> : <Avatar name={e.actor} sm />}
            <div className="what"><b>{e.role === 'system' ? 'System' : e.actor}</b> <span>{what}{e.times > 1 ? ` · ${e.times} times` : ''}</span>{detail && <div className="detail">{detail}</div>}</div>
            <time dateTime={e.ts} title={`${fmtDate(e.ts)}${e.actor_ip ? ` · IP: ${e.actor_ip}` : ''}`}>{ago(e.ts)}</time>
          </li>
        )
      })}
    </ul>
  )
}

export function History({ id }) {
  const r = useApi(`/api/audit?application_id=${id}`)
  if (!r.data) return <Loading error={r.error} />
  return <div className="case-body pad"><div className="sheet" style={{ maxWidth: 860 }}><div className="sheet-body" style={{ paddingTop: 4, paddingBottom: 4 }}><Timeline entries={r.data} /></div></div></div>
}
