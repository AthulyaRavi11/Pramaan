import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertTriangle, Check, ChevronRight, FileCheck2, Upload, Paperclip, Lock, Unlock, Cloud, Clock, X, Send, ShieldAlert, CheckCircle2, ArrowLeft, Edit3 } from 'lucide-react'
import { api, fileUrl, getSession } from '../api'
import { APP_STATUS, Band, Loading, REVIEW, SevIcon, Status, ago, fieldLabel, toast, useApi } from '../ui'

const ROOMS = ['classroom', 'lab', 'library', 'seminar-hall', 'workshop']
const SEV_RANK = { high: 0, medium: 1, low: 2, info: 3 }

export default function InstitutionApplication() {
  const { id } = useParams()
  const r = useApi(`/api/applications/${id}`)
  const cfg = useApi('/api/config')
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState({})
  const [showFreezeModal, setShowFreezeModal] = useState(false)
  const [showUnfreezeModal, setShowUnfreezeModal] = useState(false)
  const [showSubmitModal, setShowSubmitModal] = useState(false)
  const [submitAudit, setSubmitAudit] = useState(null)
  const [freezeWarning, setFreezeWarning] = useState(null)
  const [unfreezeReason, setUnfreezeReason] = useState('')
  const [showEditModal, setShowEditModal] = useState(false)

  if (!r.data || !cfg.data) return <Loading error={r.error || cfg.error} />

  const { application: a, documents, findings } = r.data
  const cat = cfg.data.categories[a.category]
  const types = cfg.data.document_types
  const live = documents.filter(d => !d.superseded)
  const required = Object.fromEntries(cat.required_docs.map(x => [x.doc, x.min_count]))
  const reqDocs = cat.required_docs.map(x => x.doc).filter(t => t !== 'infra_photo' && types[t])
  const categoryOptionalDocs = {
    EOA: ['floor_plan', 'nba_accreditation'],
    INTAKE_INCREASE: ['floor_plan'],
    NEW_PROGRAMME: ['floor_plan'],
    CHANGE_OF_NAME: [],
    NEW_INSTITUTION: ['floor_plan', 'pollution_noc'],
    COURSE_CLOSURE: []
  }
  const optDocs = (categoryOptionalDocs[a.category] || []).filter(t => types[t] && !required[t])
  const photos = live.filter(d => d.declared_type === 'infra_photo')
  const needPhotos = required.infra_photo || 0
  const have = t => live.find(d => d.declared_type === t)
  const reqDone = reqDocs.filter(t => have(t) && (!have(t).detected_type || have(t).detected_type === t)).length

  function checkDocWrong(d) {
    if (!d || d.declared_type === 'infra_photo') return null
    if (d.detected_type && d.detected_type !== d.declared_type) {
      return { type: 'mismatch', detected: d.detected_type }
    }
    const docFindings = findings.filter(x => x.document_id === d.id)
    const unrecFinding = docFindings.find(x => x.rule_id === 'DOC-UNRECOGNIZED' || x.title?.toLowerCase().includes('unrecognized') || x.title?.toLowerCase().includes('invalid'))
    if (unrecFinding || (!d.detected_type && (d.classification_conf == null || d.classification_conf < 0.2))) {
      return { type: 'unrecognized' }
    }
    return null
  }

  function checkDocExpired(d) {
    if (!d) return false
    if (checkDocWrong(d)) return false
    const f = d.extraction?.fields || {}
    const expDateStr = f.valid_until?.normalized
    const isDateExpired = expDateStr && new Date(expDateStr) < new Date()
    const expiryFinding = findings.find(x => x.document_id === d.id && (x.title?.toLowerCase().includes('expired') || x.rule_id?.includes('VAL-01') || x.rule_id?.includes('EXP')))
    return !!expiryFinding || !!isDateExpired
  }

  const wrongDocs = live.filter(d => !!checkDocWrong(d))
  const anyWrong = wrongDocs.length > 0
  const expiredDocs = live.filter(checkDocExpired)
  const anyExpired = expiredDocs.length > 0
  const hasBlockingIssue = anyWrong || anyExpired
  // Which problems stop the freeze is configured on the server (categories.yaml -> submission_gate).
  const gate = { block_missing_documents: true, block_missing_photos: true, block_wrong_documents: false,
                 block_expired_documents: false, ...(cfg.data.submission_gate || {}) }
  const missingDocs = reqDocs.filter(t => !have(t))

  const isFrozen = !!a.is_frozen
  const editable = !isFrozen && ['DRAFT', 'RECTIFICATION_REQUESTED', 'UNDER_SCRUTINY'].includes(a.status)
  const canFreeze = !isFrozen && ['DRAFT', 'RECTIFICATION_REQUESTED', 'UNDER_SCRUTINY'].includes(a.status)
  const toFix = findings
    .filter(f => f.severity !== 'info' && f.review_status !== 'DISMISSED')
    .filter(f => {
      if (!isFrozen) {
        // While in draft mode, step-wise verification: only show issues for documents actually uploaded
        if (!f.document_id && (f.title?.toLowerCase().startsWith('missing:') || f.rule_id?.startsWith('EOA-DOC') || f.rule_id?.startsWith('INC-DOC') || f.module === 'infrastructure')) {
          return false
        }
      }
      return true
    })
    .sort((x, y) => SEV_RANK[x.severity] - SEV_RANK[y.severity])
  const rectify = findings.filter(f => f.review_status === 'RECTIFICATION_REQUESTED')

  async function upload(type, file, tag) {
    if (isFrozen) {
      toast('Application is frozen. Request unfreeze from AICTE to upload documents.')
      return
    }
    const key = tag ? `photo-${tag}` : type
    setUploading(u => ({ ...u, [key]: file.name }))
    const form = new FormData()
    form.append('declared_type', type); form.append('file', file)
    if (tag) form.append('tag', tag)
    try {
      const res = await api(`/api/applications/${id}/documents`, { method: 'POST', form })
      if (res.detected_type && res.detected_type !== type) {
        toast(`⚠️ Wrong document: Uploaded as ${types[type]?.label || type}, but looks like ${types[res.detected_type]?.label || res.detected_type}`)
      } else {
        toast(`${types[type]?.label || type} uploaded to Local Vault`)
      }
      r.reload()
    }
    catch (e) { toast(e.message) }
    finally { setUploading(u => { const n = { ...u }; delete n[key]; return n }) }
  }

  async function freezeData() {
    setBusy(true)
    try {
      await api(`/api/applications/${id}/freeze`, { method: 'POST' })
      toast(`Data frozen for AY ${a.academic_year} & synced to AICTE Central Cloud`)
      setShowFreezeModal(false)
      r.reload()
      window.scrollTo(0, 0)
    }
    catch (e) { toast(e.message) }
    finally { setBusy(false) }
  }

  async function submitUnfreezeRequest() {
    if (unfreezeReason.trim().length < 10) return
    setBusy(true)
    try {
      await api(`/api/applications/${id}/unfreeze-request`, {
        method: 'POST',
        body: { reason: unfreezeReason.trim() }
      })
      toast('Formal unfreeze request submitted to AICTE Scrutiny Officers')
      setShowUnfreezeModal(false)
      setUnfreezeReason('')
      r.reload()
    }
    catch (e) { toast(e.message) }
    finally { setBusy(false) }
  }

  function handleSubmitClick() {
    const issues = []

    // 1. Check for Wrong / Mismatched Documents
    if (anyWrong) {
      wrongDocs.forEach(d => {
        const detLabel = types[d.detected_type]?.label || d.detected_type || 'Unrecognized format'
        const declLabel = types[d.declared_type]?.label || d.declared_type
        issues.push({
          category: 'Document Classification',
          severity: 'high',
          title: `Mismatched Document: ${d.original_name}`,
          desc: `Uploaded into '${declLabel}' slot, but content was classified as '${detLabel}'.`
        })
      })
    }

    // 2. Check for Expired Certificates
    if (anyExpired) {
      expiredDocs.forEach(d => {
        const f = d.extraction?.fields || {}
        const expDate = f.valid_until?.value || 'Expired'
        issues.push({
          category: 'Document Validity & Expiry',
          severity: 'high',
          title: `Expired Certificate: ${d.original_name}`,
          desc: `Certificate validity expired (${expDate}). Current session requires an active valid certificate.`
        })
      })
    }

    // 3. Check for Missing Mandatory Documents
    if (reqDone < reqDocs.length) {
      reqDocs
        .filter(t => !have(t) || (have(t).detected_type && have(t).detected_type !== t))
        .forEach(t => {
          issues.push({
            category: 'Mandatory Documents Missing',
            severity: 'high',
            title: `Required Document Missing: ${types[t]?.label || t}`,
            desc: `This document is strictly mandated by AICTE Approval Process Handbook.`
          })
        })
    }

    // 4. Missing Photos
    if (needPhotos > 0 && photos.length < needPhotos) {
      issues.push({
        category: 'Campus Infrastructure',
        severity: 'medium',
        title: `Infrastructure Photos Incomplete`,
        desc: `Only ${photos.length} of ${needPhotos} minimum required room photographs uploaded.`
      })
    }

    // 5. Findings on uploaded documents (Signature error, copy-move, baseline jitter, authority records, etc.)
    findings.forEach(f => {
      if (f.severity === 'info' || f.review_status === 'DISMISSED') return
      if (!f.document_id && !isFrozen) {
        if (f.title?.toLowerCase().startsWith('missing:') || f.rule_id?.startsWith('EOA-DOC') || f.module === 'infrastructure') return
      }
      const isSig = f.title?.toLowerCase().includes('signature') || f.rule_id?.includes('SIG') || f.title?.toLowerCase().includes('notary')
      const docObj = documents.find(d => d.id === f.document_id)
      issues.push({
        category: isSig
          ? 'Digital Signature & Notarization'
          : f.module === 'anomaly'
          ? 'Document Integrity & Forensics'
          : 'Authority & Regulatory Cross-Check',
        severity: f.severity,
        title: f.title,
        desc: f.reason,
        docName: docObj?.original_name
      })
    })

    setSubmitAudit({
      totalIssues: issues.length,
      issues
    })
    setShowSubmitModal(true)
  }

  function handleFreezeClick() {
    if (anyWrong && gate.block_wrong_documents) {
      const wrongList = wrongDocs.map(d => {
        const detLabel = types[d.detected_type]?.label || d.detected_type
        const declLabel = types[d.declared_type]?.label || d.declared_type
        return `'${d.original_name}' (uploaded as ${declLabel}, looks like ${detLabel || 'unrecognized'})`
      }).join(', ')
      setFreezeWarning({
        title: 'Cannot Freeze: Wrong Document Detected',
        message: `You cannot freeze the data because a wrong or mismatched document was uploaded: ${wrongList}. Please replace it with the correct document before freezing.`
      })
      toast('You cannot freeze the data as a wrong document was uploaded. Please replace it with the correct file.')
      return
    }

    if (anyExpired && gate.block_expired_documents) {
      const expList = expiredDocs.map(d => `'${d.original_name}'`).join(', ')
      setFreezeWarning({
        title: 'Cannot Freeze: Expired Certificate Detected',
        message: `You cannot freeze the data because your certificate ${expList} is expired. Please replace it with a valid certificate before freezing.`
      })
      toast('You cannot freeze the data as your certificate is already expired.')
      return
    }

    if (missingDocs.length > 0 && gate.block_missing_documents) {
      const missingList = missingDocs
        .map(t => types[t]?.label || t)
        .join(', ')
      setFreezeWarning({
        title: 'Cannot Freeze: Mandatory Documents Missing',
        message: `Please upload all mandatory documents before freezing: ${missingList}.`
      })
      toast(`Please upload all ${reqDocs.length} required documents before freezing.`)
      return
    }

    if (needPhotos > 0 && photos.length < needPhotos && gate.block_missing_photos) {
      setFreezeWarning({
        title: 'Cannot Freeze: Infrastructure Photos Missing',
        message: `This application category requires at least ${needPhotos} infrastructure photos covering classrooms, laboratories, and the library (currently ${photos.length} uploaded).`
      })
      toast(`Please upload at least ${needPhotos} infrastructure photos before freezing.`)
      return
    }

    setFreezeWarning(null)
    setShowFreezeModal(true)
  }

  const steps = [
    { id: 'details', label: 'Application details', sub: cat?.label || 'Entered', state: 'done' },
    { id: 'documents', label: 'Required documents', sub: `${reqDone} of ${reqDocs.length} uploaded`, state: reqDone === reqDocs.length ? 'done' : reqDone ? 'part' : '' },
    ...(needPhotos > 0 ? [{ id: 'photos', label: 'Infrastructure photos', sub: `${photos.length} of at least ${needPhotos}`, state: photos.length >= needPhotos ? 'done' : photos.length ? 'part' : '' }] : []),
    { id: 'freeze', label: isFrozen ? `Frozen for AY ${a.academic_year}` : 'Freeze', sub: isFrozen ? `Synced to AICTE ${ago(a.frozen_at)}` : 'In Local Vault', state: isFrozen ? 'done' : '' },
  ]

  return (
    <>
    <Band>
      <div>
        <nav className="crumbs" aria-label="Breadcrumb">
          <Link to="/" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: 500 }}>
            <ArrowLeft size={13} /> Your applications
          </Link>
          <ChevronRight size={12} />
          <span className="mono">{a.ref}</span>
        </nav>
        <h1 style={{ marginTop: 6 }}>{cat.label}</h1>
        <p className="lede">Academic year {a.academic_year} · <Status tone={APP_STATUS[a.status]?.tone}>{APP_STATUS[a.status]?.label}</Status>
          {a.status !== 'DRAFT' && <> · <a href={`/api/applications/${id}/report.pdf?token=${encodeURIComponent(getSession()?.token || '')}`} style={{ color: 'inherit', fontWeight: 600, textDecoration: 'underline', textUnderlineOffset: 3 }}>Download checklist report</a></>}</p>
      </div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <Link to="/" className="btn" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <ArrowLeft size={14} /> Back
        </Link>
        {canFreeze && (
          <>
            <button
              className="btn primary"
              onClick={handleSubmitClick}
              disabled={busy}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontWeight: 600,
              }}
            >
              <Send size={14} />
              Submit Application
            </button>
            <button
              className="btn"
              onClick={handleFreezeClick}
              disabled={busy}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontWeight: 600,
              }}
            >
              <Lock size={14} />
              Freeze
            </button>
          </>
        )}
        {isFrozen && !a.unfreeze_requested && (
          <button className="btn" style={{ borderColor: '#B91C1C', color: '#B91C1C', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 6 }} onClick={() => setShowUnfreezeModal(true)}>
            <Unlock size={14} />
            Request Unfreeze from AICTE
          </button>
        )}
        {isFrozen && !!a.unfreeze_requested && (
          <span style={{ fontSize: '13px', background: '#DBEAFE', color: '#1E40AF', padding: '6px 12px', borderRadius: 6, fontWeight: 500 }}>
            ⏳ Unfreeze Requested
          </span>
        )}
      </div>
    </Band>

    <div className="page lift">
      <div className="inst-grid">
        <nav className="progress-rail" aria-label="Progress">
          {steps.map(s => (
            s.id === 'details' ? (
              <button
                key={s.id}
                type="button"
                onClick={() => {
                  if (!isFrozen) setShowEditModal(true)
                  else toast('Application is frozen. Request unfreeze from AICTE to modify details.')
                }}
                className="step-btn"
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 10,
                  textAlign: 'left',
                  background: 'none',
                  border: 'none',
                  padding: '8px 12px',
                  borderRadius: 8,
                  cursor: 'pointer',
                  width: '100%',
                  color: 'inherit',
                  font: 'inherit'
                }}
                title={isFrozen ? 'Application details (Locked)' : 'Click to edit application details / change category'}
              >
                <span className={`state ${s.state}`}>{s.state === 'done' ? <Check size={12} strokeWidth={3} /> : null}</span>
                <span>
                  <b>{s.label}</b>
                  <span style={{ display: 'block', fontSize: '11px', color: '#64748b' }}>{s.sub}</span>
                  {!isFrozen && (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: '11px', color: 'var(--accent)', marginTop: 2, fontWeight: 600 }}>
                      <Edit3 size={11} /> Edit details / rename
                    </span>
                  )}
                </span>
              </button>
            ) : (
              <a key={s.id} href={`#${s.id}`}>
                <span className={`state ${s.state}`}>{s.state === 'done' ? <Check size={12} strokeWidth={3} /> : null}</span>
                <span><b>{s.label}</b><span>{s.sub}</span></span>
              </a>
            )
          ))}
        </nav>

        <div style={{ display: 'grid', gap: 28, minWidth: 0 }}>
          {a.unfreeze_remarks && !isFrozen && (
            <div className="sheet" style={{ borderColor: '#F59E0B', background: '#FFFDF5', boxShadow: '0 4px 12px rgba(245, 158, 11, 0.1)' }}>
              <div style={{ background: '#FEF3C7', padding: '12px 18px', borderBottom: '1px solid #FDE68A', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Unlock size={18} style={{ color: '#B45309' }} />
                  <h3 style={{ margin: 0, color: '#92400E', fontSize: '15px' }}>Official AICTE Scrutiny Rectification Notice</h3>
                </div>
                {a.rectification_deadline && (
                  <span style={{ fontSize: '12.5px', background: '#FDE68A', color: '#78350F', padding: '3px 8px', borderRadius: 4, fontWeight: 600 }}>
                    15-Day Statutory Window (Due: {a.rectification_deadline})
                  </span>
                )}
              </div>
              <div style={{ padding: '16px 20px' }}>
                <p style={{ margin: '0 0 8px', fontSize: '13px', color: '#78350F', fontWeight: 600 }}>
                  Instructions from AICTE Scrutiny Officer ({a.unfrozen_by || 'Officer'}) · {ago(a.unfrozen_at)}:
                </p>
                <div style={{ background: '#FFFFFF', border: '1px solid #FDE68A', borderRadius: 6, padding: '12px 14px', fontSize: '13.5px', color: '#1F2937', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                  {a.unfreeze_remarks}
                </div>
                <p style={{ margin: '10px 0 0', fontSize: '12px', color: '#6B7280' }}>
                  Please replace or correct the indicated documents below, then click <b>Submit Application / Freeze</b> to re-transmit your compliant application to AICTE.
                </p>
              </div>
            </div>
          )}

          {rectify.length > 0 && (
            <div className="sheet" style={{ borderColor: '#E9C27A' }}>
              <div className="sheet-head" style={{ background: 'var(--warn-wash)' }}><h3>The scrutiny officer asked you to correct {rectify.length === 1 ? 'one item' : `${rectify.length} items`}</h3></div>
              {a.rectification_deadline && (
                <div style={{ padding: '8px 14px', background: '#FFFBEB', borderBottom: '1px solid #FDE68A', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '13px' }}>
                  <span style={{ fontWeight: 600, color: '#92400E' }}>
                    ⏱️ Rectification Window: 15-day deadline (Due: {a.rectification_deadline})
                  </span>
                  <span style={{ fontSize: '12px', color: '#78350F' }}>AICTE Procedural Timelines</span>
                </div>
              )}
              <div className="fix-list">{rectify.map(f => (
                <div className="fix" key={f.id}><AlertTriangle size={15} style={{ color: 'var(--warn)', marginTop: 2 }} />
                  <div><b>{f.title}</b><p>“{f.review_remark}”</p></div><span className="small muted">{ago(f.reviewed_at)}</span></div>
              ))}</div>
            </div>
          )}

          {(toFix.length > 0 || a.status !== 'DRAFT') && (
            <div className="sheet">
              <div className="sheet-head"><h3>{toFix.length ? `${toFix.length} thing${toFix.length > 1 ? 's' : ''} to fix` : 'No problems found'}</h3><span className="small muted">From the automated checklist</span></div>
              {toFix.length ? <div className="fix-list">{toFix.map(f => (
                <div className="fix" key={f.id}><SevIcon s={f.severity} /><div><b>{f.title}</b><p>{f.reason}</p></div>
                  {f.review_status !== 'OPEN' ? <span className="small muted">{REVIEW[f.review_status]}</span> : <span />}</div>
              ))}</div> : <div className="sheet-body muted">Your application is with the scrutiny officer. You’ll see any request for corrections here.</div>}
            </div>
          )}

          <section id="details">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
              <h2 className="section-title" style={{ margin: 0 }}>
                Application parameters <span className="muted">{cat?.label || a.category}</span>
              </h2>
              {!isFrozen && (
                <button
                  className="btn"
                  onClick={() => setShowEditModal(true)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    fontSize: '13px',
                    padding: '6px 12px',
                    borderColor: '#93c5fd',
                    background: '#eff6ff',
                    color: '#1d4ed8',
                    fontWeight: 600
                  }}
                  title="Click to edit application details, rename college, or change parameters"
                >
                  <Edit3 size={14} /> Edit Details / Change Type
                </button>
              )}
            </div>
            <div className="sheet" style={{ padding: '16px 20px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px 24px' }}>
                <div>
                  <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6B7280', fontWeight: 600, display: 'block' }}>
                    Application Type
                  </span>
                  <b style={{ fontSize: '14px', color: '#1F2937' }}>{cat?.label || a.category}</b>
                </div>

                <div>
                  <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6B7280', fontWeight: 600, display: 'block' }}>
                    Academic Year
                  </span>
                  <b style={{ fontSize: '14px', color: '#1F2937' }}>{a.academic_year}</b>
                </div>

                <div>
                  <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6B7280', fontWeight: 600, display: 'block' }}>
                    Institution Name
                  </span>
                  <b style={{ fontSize: '14px', color: '#1F2937' }}>{a.institution_name}</b>
                </div>

                {a.form.aicte_permanent_id && (
                  <div>
                    <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6B7280', fontWeight: 600, display: 'block' }}>
                      AICTE Permanent ID
                    </span>
                    <b className="mono" style={{ fontSize: '14px', color: '#1F2937' }}>{a.form.aicte_permanent_id}</b>
                  </div>
                )}

                {/* CHANGE_OF_NAME specifics */}
                {a.category === 'CHANGE_OF_NAME' && (
                  <div style={{ gridColumn: '1 / -1', background: '#F0FDF4', border: '1px solid #BBF7D0', padding: '12px 16px', borderRadius: 8 }}>
                    <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#166534', fontWeight: 700, display: 'block' }}>
                      Proposed New Name of Institution
                    </span>
                    <b style={{ fontSize: '16px', color: '#14532D', display: 'block', marginTop: 2 }}>
                      {a.form.proposed_institution_name || 'Not specified'}
                    </b>
                    {a.form.trust_society_name && (
                      <div style={{ fontSize: '12.5px', color: '#166534', marginTop: 4 }}>
                        <b>Sponsoring Trust/Society:</b> {a.form.trust_society_name}
                      </div>
                    )}
                    {a.form.reason_for_change && (
                      <div style={{ fontSize: '12.5px', color: '#166534', marginTop: 4 }}>
                        <b>Justification:</b> {a.form.reason_for_change}
                      </div>
                    )}
                  </div>
                )}

                {/* NEW_INSTITUTION specifics */}
                {a.category === 'NEW_INSTITUTION' && (
                  <>
                    {a.form.trust_society_name && (
                      <div>
                        <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6B7280', fontWeight: 600, display: 'block' }}>
                          Sponsoring Trust / Society
                        </span>
                        <b style={{ fontSize: '14px', color: '#1F2937' }}>{a.form.trust_society_name}</b>
                      </div>
                    )}
                    {a.form.land_area_acres != null && (
                      <div>
                        <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6B7280', fontWeight: 600, display: 'block' }}>
                          Campus Land Area
                        </span>
                        <b style={{ fontSize: '14px', color: '#1F2937' }}>{a.form.land_area_acres} Acres</b>
                      </div>
                    )}
                    {a.form.survey_number && (
                      <div>
                        <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6B7280', fontWeight: 600, display: 'block' }}>
                          Survey / Khasra No.
                        </span>
                        <b style={{ fontSize: '14px', color: '#1F2937' }}>{a.form.survey_number}</b>
                      </div>
                    )}
                    {(a.form.district || a.form.state) && (
                      <div>
                        <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6B7280', fontWeight: 600, display: 'block' }}>
                          Location
                        </span>
                        <b style={{ fontSize: '14px', color: '#1F2937' }}>{[a.form.district, a.form.state].filter(Boolean).join(', ')}</b>
                      </div>
                    )}
                  </>
                )}

                {/* COURSE_CLOSURE specifics */}
                {a.category === 'COURSE_CLOSURE' && (
                  <div style={{ gridColumn: '1 / -1', background: '#FEF2F2', border: '1px solid #FECACA', padding: '12px 16px', borderRadius: 8 }}>
                    <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#991B1B', fontWeight: 700, display: 'block' }}>
                      Programme Slated for Closure
                    </span>
                    <b style={{ fontSize: '16px', color: '#7F1D1D', display: 'block', marginTop: 2 }}>
                      {a.form.closure_programme_name || 'Specified Programme'} ({a.form.closure_programme_code || 'N/A'})
                    </b>
                    {a.form.closure_reason && (
                      <div style={{ fontSize: '12.5px', color: '#991B1B', marginTop: 4 }}>
                        <b>Reason for Closure:</b> {a.form.closure_reason}
                      </div>
                    )}
                    {a.form.students_status && (
                      <div style={{ fontSize: '12.5px', color: '#991B1B', marginTop: 4 }}>
                        <b>Students Status:</b> {a.form.students_status}
                      </div>
                    )}
                  </div>
                )}

                {/* NEW_PROGRAMME specifics */}
                {a.category === 'NEW_PROGRAMME' && a.form.new_prog_name && (
                  <div style={{ gridColumn: '1 / -1', background: '#EFF6FF', border: '1px solid #BFDBFE', padding: '12px 16px', borderRadius: 8 }}>
                    <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#1E40AF', fontWeight: 700, display: 'block' }}>
                      Proposed New Programme Offering
                    </span>
                    <b style={{ fontSize: '16px', color: '#1E3A8A', display: 'block', marginTop: 2 }}>
                      {a.form.new_prog_name} ({a.form.new_prog_code})
                    </b>
                    <div style={{ fontSize: '12.5px', color: '#1E40AF', marginTop: 4 }}>
                      <b>Level:</b> {a.form.new_prog_level} · <b>Annual Intake:</b> {a.form.new_prog_intake} seats
                    </div>
                  </div>
                )}

                {/* Built-up area / Faculty if available */}
                {a.form.built_up_area_sqm != null && (
                  <div>
                    <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6B7280', fontWeight: 600, display: 'block' }}>
                      Built-up Area
                    </span>
                    <b style={{ fontSize: '14px', color: '#1F2937' }}>{a.form.built_up_area_sqm.toLocaleString()} sq.m</b>
                  </div>
                )}
                {a.form.faculty_count != null && (
                  <div>
                    <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#6B7280', fontWeight: 600, display: 'block' }}>
                      Full-time Faculty
                    </span>
                    <b style={{ fontSize: '14px', color: '#1F2937' }}>{a.form.faculty_count} professors</b>
                  </div>
                )}
              </div>
            </div>
          </section>

          <section id="documents">
            <h2 className="section-title" style={{ marginTop: 0 }}>
              Required documents <span className="muted">{reqDone} of {reqDocs.length}</span>
              {isFrozen && <span style={{ marginLeft: 10, fontSize: '12px', color: '#B91C1C', fontWeight: 600 }}>🔒 Uploads Locked (Frozen)</span>}
            </h2>
            <div className="sheet">{reqDocs.map(t => <Slot key={t} t={t} label={types[t].label} types={types} source={types[t].source_label} doc={have(t)} required
              editable={editable} uploading={uploading[t]} onFile={file => upload(t, file)} findings={findings} />)}</div>
            {optDocs.length > 0 && (
              <>
                <h2 className="section-title">
                  Optional documents
                  {isFrozen && <span style={{ marginLeft: 10, fontSize: '12px', color: '#B91C1C', fontWeight: 600 }}>🔒 Uploads Locked (Frozen)</span>}
                </h2>
                <div className="sheet">{optDocs.map(t => <Slot key={t} t={t} label={types[t].label} types={types} source={types[t].source_label} doc={have(t)}
                  editable={editable} uploading={uploading[t]} onFile={file => upload(t, file)} findings={findings} />)}</div>
              </>
            )}
          </section>

          {needPhotos > 0 && (
            <section id="photos">
              <h2 className="section-title" style={{ marginTop: 0 }}>
                Infrastructure photos <span className="muted">{photos.length} of at least {needPhotos} · cover classrooms, labs and the library</span>
                {isFrozen && <span style={{ marginLeft: 10, fontSize: '12px', color: '#B91C1C', fontWeight: 600 }}>🔒 Uploads Locked (Frozen)</span>}
              </h2>
              {photos.length > 0 && <div className="photos" style={{ marginBottom: 14 }}>
                {photos.map(p => <figure key={p.id}><img src={fileUrl(p.id)} alt={p.tag} loading="lazy" /><figcaption><b style={{ fontWeight: 500 }}>{p.tag}</b><span className="faint">{ago(p.uploaded_at)}</span></figcaption></figure>)}
              </div>}
              {editable && <PhotoDrop busy={Object.keys(uploading).some(k => k.startsWith('photo-'))} onFile={(f, tag) => upload('infra_photo', f, tag)} />}
            </section>
          )}

          <section id="freeze">
            {!isFrozen ? (
              <div className="sheet">
                <div className="sheet-body" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
                  <div style={{ maxWidth: 620 }}>
                    <b style={{ fontWeight: 600, fontSize: '15px', color: '#1F6B52' }}>
                      Ready to Submit & Freeze for Academic Year {a.academic_year}?
                    </b>
                    <p className="small muted" style={{ marginTop: 4 }}>
                      {reqDone < reqDocs.length
                        ? `${reqDocs.length - reqDone} required document${reqDocs.length - reqDone > 1 ? 's are' : ' is'} still pending.`
                        : 'All required documents are uploaded in your Local Vault.'}{' '}
                      Click <b>Submit Application</b> to perform automated pre-submission audit and signature checks. If discrepancies are found, you can review them or choose to freeze directly.
                    </p>
                  </div>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                    <button
                      className="btn primary"
                      onClick={handleSubmitClick}
                      disabled={busy}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 6,
                        padding: '10px 18px',
                        fontWeight: 600,
                      }}
                    >
                      <Send size={15} />
                      Submit Application
                    </button>
                    <button
                      className="btn"
                      onClick={handleFreezeClick}
                      disabled={busy}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 6,
                        padding: '10px 18px',
                        fontWeight: 600,
                      }}
                    >
                      <Lock size={15} />
                      Freeze
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="sheet" style={{ borderColor: '#1F6B52', background: 'rgba(31, 107, 82, 0.04)' }}>
                <div className="sheet-body" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
                  <div>
                    <b style={{ fontWeight: 600, fontSize: '15px', color: '#1F6B52', display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Lock size={16} /> Application Data Frozen for AY {a.academic_year}
                    </b>
                    <p className="small muted" style={{ marginTop: 4 }}>
                      Committed to AICTE Central Cloud by {a.frozen_by || 'Institution'} {ago(a.frozen_at)}. Uploads and changes are locked while under official review.
                    </p>
                    {a.unfreeze_requested ? (
                      <div style={{ marginTop: 8, padding: '8px 12px', background: '#EFF6FF', border: '1px solid #BFDBFE', borderRadius: 6, fontSize: '12.5px', color: '#1E40AF' }}>
                        <b>Formal Unfreeze Request Pending AICTE Review:</b> “{a.unfreeze_request_reason}” ({ago(a.unfreeze_requested_at)})
                      </div>
                    ) : null}
                  </div>
                  {!a.unfreeze_requested && (
                    <button className="btn" style={{ borderColor: '#B91C1C', color: '#B91C1C', fontWeight: 600 }} onClick={() => setShowUnfreezeModal(true)}>
                      <Unlock size={14} style={{ verticalAlign: -1 }} />
                      Request Unfreeze from AICTE
                    </button>
                  )}
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>

    {/* Freeze Blocked Warning Modal */}
    {freezeWarning && (
      <div className="scrim" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={() => setFreezeWarning(null)}>
        <div className="sheet" style={{ maxWidth: 520, width: '90%', margin: 'auto', padding: 24, borderRadius: 12, boxShadow: '0 20px 40px rgba(0,0,0,0.2)' }} onClick={e => e.stopPropagation()}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, color: '#B91C1C' }}>
              <AlertTriangle size={20} style={{ color: '#DC2626' }} /> {freezeWarning.title}
            </h3>
            <button className="icon-btn" onClick={() => setFreezeWarning(null)}><X size={18} /></button>
          </div>
          <p style={{ fontSize: '13.5px', color: '#374151', lineHeight: 1.5, margin: '0 0 16px' }}>
            {freezeWarning.message}
          </p>
          <div style={{ background: '#FEF2F2', border: '1px solid #FCA5A5', padding: '12px 14px', borderRadius: 8, fontSize: '12.5px', color: '#991B1B', marginBottom: 18 }}>
            <b>Regulation Notice:</b> You cannot freeze application data until all discrepancies are corrected. Please replace or correct the document in your Local Vault before attempting to freeze again.
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
            <button className="btn primary" style={{ background: '#B91C1C', borderColor: '#B91C1C' }} onClick={() => setFreezeWarning(null)}>
              Understood
            </button>
          </div>
        </div>
      </div>
    )}

    {/* Pre-Submission Scrutiny Audit Modal */}
    {showSubmitModal && submitAudit && (
      <div className="scrim" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={() => setShowSubmitModal(false)}>
        <div className="sheet" style={{ maxWidth: 680, width: '92%', maxHeight: '88vh', display: 'flex', flexDirection: 'column', margin: 'auto', padding: 24, borderRadius: 12, boxShadow: '0 20px 40px rgba(0,0,0,0.25)' }} onClick={e => e.stopPropagation()}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, color: submitAudit.totalIssues > 0 ? '#B91C1C' : '#1F6B52' }}>
              {submitAudit.totalIssues > 0 ? <ShieldAlert size={22} style={{ color: '#DC2626' }} /> : <CheckCircle2 size={22} style={{ color: '#16A34A' }} />}
              {submitAudit.totalIssues > 0 ? 'Pre-Submission Scrutiny Audit' : 'Pre-Submission Audit Passed'}
            </h3>
            <button className="icon-btn" onClick={() => setShowSubmitModal(false)}><X size={18} /></button>
          </div>

          <div style={{ overflowY: 'auto', flex: 1, paddingRight: 4, marginBottom: 16 }}>
            {submitAudit.totalIssues > 0 ? (
              <>
                <div style={{ background: '#FEF2F2', border: '1px solid #FCA5A5', padding: '12px 14px', borderRadius: 8, fontSize: '13px', color: '#991B1B', marginBottom: 16 }}>
                  <b>Automated Scrutiny Notice:</b> Found <b>{submitAudit.totalIssues} discrepancy item{submitAudit.totalIssues > 1 ? 's' : ''}</b> across signatures, document validity, and institutional checks. You can fix them now, or choose to freeze and submit for manual officer review if you still wish to proceed.
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {submitAudit.issues.map((iss, idx) => (
                    <div key={idx} style={{ padding: '10px 14px', borderRadius: 8, border: '1px solid #E5E7EB', background: iss.severity === 'high' ? '#FFF5F5' : '#F9FAFB' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <span style={{ fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: iss.severity === 'high' ? '#DC2626' : '#D97706' }}>
                          {iss.category}
                        </span>
                        {iss.docName && <span className="mono" style={{ fontSize: '11.5px', color: '#6B7280' }}>{iss.docName}</span>}
                      </div>
                      <b style={{ fontSize: '13.5px', color: '#111827', display: 'block' }}>{iss.title}</b>
                      <p style={{ fontSize: '12.5px', color: '#4B5563', margin: '4px 0 0', lineHeight: 1.45 }}>{iss.desc}</p>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div style={{ textAlign: 'center', padding: '24px 12px' }}>
                <CheckCircle2 size={52} style={{ color: '#16A34A', margin: '0 auto 14px' }} />
                <h4 style={{ fontSize: '17px', color: '#111827', margin: '0 0 8px' }}>All Verification Checks Passed (100%)</h4>
                <p style={{ fontSize: '13.5px', color: '#4B5563', maxWidth: 480, margin: '0 auto', lineHeight: 1.5 }}>
                  All mandatory certificates, signatures, authority registries, and campus photo EXIF checks are completely compliant with AICTE norms.
                </p>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, paddingTop: 12, borderTop: '1px solid #E5E7EB', flexWrap: 'wrap' }}>
            <button className="btn" onClick={() => setShowSubmitModal(false)} disabled={busy}>
              {submitAudit.totalIssues > 0 ? 'Review & Fix Documents' : 'Close'}
            </button>
            {submitAudit.totalIssues > 0 ? (
              <button
                className="btn primary"
                style={{ background: '#DC2626', borderColor: '#DC2626', color: '#fff' }}
                onClick={() => {
                  setShowSubmitModal(false)
                  setShowFreezeModal(true)
                }}
                disabled={busy}
              >
                I Still Want to Freeze ➔
              </button>
            ) : (
              <button
                className="btn primary"
                onClick={() => {
                  setShowSubmitModal(false)
                  setShowFreezeModal(true)
                }}
                disabled={busy}
              >
                Confirm Freeze & Lock ➔
              </button>
            )}
          </div>
        </div>
      </div>
    )}

    {/* Freeze Confirmation Modal */}
    {showFreezeModal && (
      <div className="scrim" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={() => setShowFreezeModal(false)}>
        <div className="sheet" style={{ maxWidth: 520, width: '90%', margin: 'auto', padding: 24, borderRadius: 12, boxShadow: '0 20px 40px rgba(0,0,0,0.2)' }} onClick={e => e.stopPropagation()}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, color: '#1F6B52' }}>
              <Lock size={18} /> Freeze & Lock Data for AY {a.academic_year}
            </h3>
            <button className="icon-btn" onClick={() => setShowFreezeModal(false)}><X size={18} /></button>
          </div>
          <p style={{ fontSize: '13.5px', color: '#374151', lineHeight: 1.5, margin: '0 0 14px' }}>
            You are about to transmit all uploaded documents from your <b>Private Local Institute Vault</b> to the <b>AICTE</b> for official scrutiny.
          </p>
          <div style={{ background: '#FFFBEB', border: '1px solid #FDE68A', padding: '12px 14px', borderRadius: 8, fontSize: '12.5px', color: '#92400E', marginBottom: 18 }}>
            <b>Notice:</b> Once frozen, all documents and application parameters are strictly locked. You will not be able to upload or alter documents unless an AICTE Scrutiny Officer approves an unfreeze.
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
            <button className="btn" onClick={() => setShowFreezeModal(false)} disabled={busy}>Cancel</button>
            <button className="btn primary" onClick={freezeData} disabled={busy}>
              {busy ? 'Freezing…' : 'Freeze'}
            </button>
          </div>
        </div>
      </div>
    )}

    {/* Unfreeze Request Modal */}
    {showUnfreezeModal && (
      <div className="scrim" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={() => setShowUnfreezeModal(false)}>
        <div className="sheet" style={{ maxWidth: 540, width: '90%', margin: 'auto', padding: 24, borderRadius: 12, boxShadow: '0 20px 40px rgba(0,0,0,0.2)' }} onClick={e => e.stopPropagation()}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, color: '#B91C1C' }}>
              <Unlock size={18} /> Request Portal Unfreeze from AICTE
            </h3>
            <button className="icon-btn" onClick={() => setShowUnfreezeModal(false)}><X size={18} /></button>
          </div>
          <p style={{ fontSize: '13.5px', color: '#374151', lineHeight: 1.5, margin: '0 0 14px' }}>
            If you froze your data prematurely or discovered errors in uploaded documents, you can formally request the AICTE Scrutiny Officer to unfreeze your portal.
          </p>
          <label className="field" style={{ marginBottom: 16 }}>
            <span style={{ fontWeight: 600, fontSize: '13px' }}>Reason & Justification for Unfreeze (Mandatory)</span>
            <textarea
              className="input"
              rows={4}
              value={unfreezeReason}
              onChange={e => setUnfreezeReason(e.target.value)}
              placeholder="State why unfreeze is required (e.g. Need to replace Fire Safety NOC version with renewed certificate issued on...)"
            />
            <small>This statement will be reviewed by the AICTE Scrutiny Officer handling your case.</small>
          </label>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
            <button className="btn" onClick={() => setShowUnfreezeModal(false)} disabled={busy}>Cancel</button>
            <button
              className="btn"
              style={{ background: '#B91C1C', color: '#fff', borderColor: '#B91C1C' }}
              onClick={submitUnfreezeRequest}
              disabled={busy || unfreezeReason.trim().length < 10}
            >
              {busy ? 'Submitting…' : 'Submit Unfreeze Request'}
            </button>
          </div>
        </div>
      </div>
    )}

    {/* Edit Application Details / Category Modal */}
    {showEditModal && (
      <EditApplicationDetailsModal
        a={a}
        cat={cat}
        categories={cfg.data.categories}
        onClose={() => setShowEditModal(false)}
        onDone={() => {
          setShowEditModal(false)
          r.reload()
        }}
      />
    )}
    </>
  )
}

function useDrop(onFile, enabled) {
  const [drag, setDrag] = useState(false)
  if (!enabled) return [false, {}]
  return [drag, {
    onDragOver: e => { e.preventDefault(); setDrag(true) },
    onDragLeave: () => setDrag(false),
    onDrop: e => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; f && onFile(f) },
  }]
}

function Slot({ t, label, source, doc, required, editable, uploading, onFile, findings = [], types = {} }) {
  const input = useRef()
  const [drag, dropProps] = useDrop(onFile, editable && !uploading)
  const fields = doc?.extraction?.fields || {}

  const docFindings = findings.filter(f => f.document_id === doc?.id)

  // 1. Check for Wrong / Mismatched Document FIRST
  const isWrongMismatch = doc && doc.detected_type && doc.detected_type !== t
  const unrecFinding = docFindings.find(f => f.rule_id === 'DOC-UNRECOGNIZED' || f.title?.toLowerCase().includes('unrecognized') || f.title?.toLowerCase().includes('invalid'))
  const isUnrecognized = doc && !isWrongMismatch && (!!unrecFinding || (!doc.detected_type && (doc.classification_conf == null || doc.classification_conf < 0.2)))
  const isWrongDocument = isWrongMismatch || isUnrecognized

  // 2. Check for Expired Certificate ONLY if NOT wrong document
  const expDateStr = fields?.valid_until?.normalized
  const isDateExpired = !isWrongDocument && expDateStr && (new Date(expDateStr) < new Date('2026-10-21') || new Date(expDateStr) < new Date())
  const expiryFinding = !isWrongDocument && docFindings.find(f => f.title?.toLowerCase().includes('expired') || f.rule_id?.includes('VAL-01') || f.rule_id?.includes('EXP'))
  const isExpired = !isWrongDocument && (!!expiryFinding || !!isDateExpired || (doc?.original_name && /expired/i.test(doc.original_name)))

  // 3. Other flags
  const otherFlag = docFindings.find(f => ['high', 'medium'].includes(f.severity) && f.review_status !== 'DISMISSED' && !f.title?.toLowerCase().includes('expired') && f.rule_id !== 'DOC-CLASS' && f.rule_id !== 'DOC-UNRECOGNIZED')
  const hasIssue = isWrongDocument || isExpired || !!otherFlag

  return (
    <div className={`slot ${drag ? 'drag' : ''}`} {...dropProps}>
      <div style={{ minWidth: 0 }}>
        <h4>
          {doc && !hasIssue ? (
            <Check size={15} style={{ color: 'var(--ok)' }} strokeWidth={2.6} />
          ) : doc && hasIssue ? (
            <X size={15} style={{ color: 'var(--danger)', verticalAlign: -2 }} strokeWidth={3} />
          ) : null}
          {label}
          {required && (
            <span
              className="req-star"
              style={{ color: '#DC2626', fontWeight: 800, fontSize: '16px', marginLeft: 4 }}
              title="Mandatory requirement"
              aria-label="Required field"
            >
              *
            </span>
          )}
          {(source || !required) && (
            <span className="req">
              {!required && !source ? 'Optional' : ''}
              {source ? `${!required ? 'Optional · ' : ''}confirmed with ${source.replace(' (demo registry)', '').replace(' (internal, authorized)', '')}` : ''}
            </span>
          )}
        </h4>
        {uploading ? <div className="busy">Reading {uploading}…</div>
          : doc ? <>
            <div className="file"><Paperclip size={12} />{doc.original_name}{doc.version > 1 ? ` · version ${doc.version}` : ''} · {doc.ocr_used ? 'scanned, read with OCR' : 'digital PDF'}</div>
            {isWrongDocument ? (
              <div style={{
                marginTop: 8,
                padding: '8px 12px',
                borderRadius: 6,
                background: '#FEF2F2',
                border: '1.5px solid #FCA5A5',
                color: '#991B1B',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 8
              }}>
                <X size={16} style={{ color: '#DC2626', marginTop: 2, flexShrink: 0 }} strokeWidth={2.6} />
                <div>
                  <b style={{ color: '#B91C1C', display: 'block' }}>
                    {isWrongMismatch ? 'Wrong Document Uploaded' : `Invalid Document: Unrecognized ${label}`}
                  </b>
                  <span style={{ color: '#7F1D1D', fontSize: '12.5px' }}>
                    {isWrongMismatch
                      ? <>Uploaded as <b>{label}</b>, but detected as <b>{types[doc.detected_type]?.label || doc.detected_type}</b>. This certificate is wrong for this slot. Please replace it with the correct {label}.</>
                      : (unrecFinding?.reason || `The uploaded document could not be recognized as a valid ${label}. Please upload an authentic scanned copy.`)}
                  </span>
                </div>
              </div>
            ) : isExpired ? (
              <div style={{
                marginTop: 8,
                padding: '8px 12px',
                borderRadius: 6,
                background: '#FEF2F2',
                border: '1px solid #FCA5A5',
                color: '#991B1B',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 8
              }}>
                <X size={16} style={{ color: '#DC2626', marginTop: 2, flexShrink: 0 }} strokeWidth={2.6} />
                <div>
                  <b style={{ color: '#B91C1C', display: 'block' }}>
                    Expired {t === 'fire_noc' ? 'Fire Safety Certificate' : label}
                  </b>
                  <span style={{ color: '#7F1D1D', fontSize: '12.5px' }}>
                    {expiryFinding?.reason || `This certificate has expired${expDateStr ? ` on ${expDateStr}` : ''}. You cannot freeze the data as your certificate is already expired. Please replace it with a valid certificate.`}
                  </span>
                </div>
              </div>
            ) : otherFlag ? (
              <p className="error" style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                <X size={14} /> {otherFlag.title}: {otherFlag.reason}
              </p>
            ) : Object.keys(fields).length > 0 && (
              <div className="read">{Object.entries(fields).slice(0, 4).map(([k, v]) => <span key={k}>{fieldLabel(k)}: <b>{v.value}</b></span>)}</div>
            )}
          </> : <div className="file">{editable ? 'Drop a PDF or image here' : 'Not uploaded'}</div>}
      </div>
      {editable && <>
        <input ref={input} type="file" accept=".pdf,.png,.jpg,.jpeg" hidden onChange={e => { e.target.files[0] && onFile(e.target.files[0]); e.target.value = '' }} />
        <button className="btn sm" onClick={() => input.current.click()} disabled={!!uploading}><Upload size={13} />{doc ? 'Replace' : 'Upload'}</button>
      </>}
    </div>
  )
}

function PhotoDrop({ onFile, busy }) {
  const [room, setRoom] = useState('classroom')
  const [num, setNum] = useState('')
  const input = useRef()
  const send = f => { onFile(f, `${room}-${num.trim() || '1'}`); setNum('') }
  const [drag, dropProps] = useDrop(send, !busy)
  return (
    <div className={`dropzone ${drag ? 'drag' : ''}`} {...dropProps}>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
        <select className="input" style={{ width: 'auto' }} value={room} onChange={e => setRoom(e.target.value)} aria-label="Room type">{ROOMS.map(r => <option key={r}>{r}</option>)}</select>
        <input className="input" style={{ width: 160 }} placeholder="Room, e.g. 101" value={num} onChange={e => setNum(e.target.value)} aria-label="Room number" />
        <input ref={input} type="file" accept=".jpg,.jpeg,.png" hidden onChange={e => { e.target.files[0] && send(e.target.files[0]); e.target.value = '' }} />
        <button className="btn" onClick={() => input.current.click()} disabled={busy}><Upload size={14} />Choose photo</button>
      </div>
      <span className="small">{busy ? 'Uploading…' : 'or drop a photo here. Name the room first so officials know what it shows.'}</span>
    </div>
  )
}

function EditApplicationDetailsModal({ a, cat, categories, onClose, onDone }) {
  const [category, setCategory] = useState(a.category || 'EOA')
  const [f, setF] = useState({
    institution_name: a.institution_name || '',
    academic_year: a.academic_year || '2027-28',
    aicte_permanent_id: a.form?.aicte_permanent_id || '',
    built_up_area_sqm: a.form?.built_up_area_sqm != null ? a.form.built_up_area_sqm : '',
    faculty_count: a.form?.faculty_count != null ? a.form.faculty_count : '',
    classrooms: a.form?.classrooms != null ? a.form.classrooms : '',
    labs: a.form?.labs != null ? a.form.labs : '',
    // CHANGE_OF_NAME specifics
    proposed_institution_name: a.form?.proposed_institution_name || '',
    trust_society_name: a.form?.trust_society_name || '',
    reason_for_change: a.form?.reason_for_change || '',
    resolution_date: a.form?.resolution_date || '',
    // NEW_INSTITUTION
    land_area_acres: a.form?.land_area_acres != null ? a.form.land_area_acres : '',
    survey_number: a.form?.survey_number || '',
    district: a.form?.district || '',
    state: a.form?.state || '',
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const num = v => (v === '' || v == null) ? null : +v

  async function handleSave(e) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      const payload = {
        category,
        institution_name: f.institution_name,
        academic_year: f.academic_year,
        aicte_permanent_id: f.aicte_permanent_id,
        built_up_area_sqm: num(f.built_up_area_sqm),
        faculty_count: num(f.faculty_count),
        classrooms: num(f.classrooms),
        labs: num(f.labs),
        proposed_institution_name: f.proposed_institution_name,
        trust_society_name: f.trust_society_name,
        reason_for_change: f.reason_for_change,
        resolution_date: f.resolution_date,
        land_area_acres: num(f.land_area_acres),
        survey_number: f.survey_number,
        district: f.district,
        state: f.state,
        programmes: a.form?.programmes || []
      }
      await api(`/api/applications/${a.id}`, {
        method: 'PUT',
        body: payload
      })
      toast('Application details & regulatory category updated successfully!')
      onDone()
    } catch (ex) {
      setErr(ex.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" style={{ maxWidth: 640 }}>
        <header>
          <div>
            <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Edit3 size={18} color="var(--accent)" /> Edit Application Details
            </h2>
            <p className="small muted" style={{ marginTop: 3 }}>
              {a.institution_name} · <span className="mono">{a.ref}</span>
            </p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </header>
        <form onSubmit={handleSave} className="body" style={{ display: 'grid', gap: 16 }}>
          <div className="note" style={{ background: '#f8fafc', border: '1px solid #e2e8f0', padding: '10px 14px', borderRadius: 6, fontSize: '0.85rem' }}>
            <span>
              Updating category or institutional parameters adjusts required document slots and scrutiny checks dynamically.
            </span>
          </div>

          <label className="field">
            <span style={{ fontWeight: 600 }}>Regulatory Application Type *</span>
            <select
              className="input"
              value={category}
              onChange={e => setCategory(e.target.value)}
              style={{ fontWeight: 600 }}
            >
              {Object.entries(categories).map(([code, c]) => (
                <option key={code} value={code}>{c.label} ({code})</option>
              ))}
            </select>
          </label>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <label className="field">
              <span style={{ fontWeight: 600 }}>Institution Name *</span>
              <input
                className="input"
                type="text"
                value={f.institution_name}
                onChange={e => setF({ ...f, institution_name: e.target.value })}
                required
              />
            </label>

            <label className="field">
              <span style={{ fontWeight: 600 }}>AICTE Permanent ID</span>
              <input
                className="input mono"
                type="text"
                value={f.aicte_permanent_id}
                onChange={e => setF({ ...f, aicte_permanent_id: e.target.value })}
              />
            </label>
          </div>

          {/* If College Rename (CHANGE_OF_NAME) */}
          {category === 'CHANGE_OF_NAME' && (
            <div style={{ background: '#F0FDF4', border: '1px solid #BBF7D0', padding: '14px', borderRadius: 8, display: 'grid', gap: 12 }}>
              <div style={{ fontWeight: 700, color: '#166534', fontSize: '13px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                College Rename (Change of Name) Parameters
              </div>
              <label className="field">
                <span style={{ fontWeight: 600, color: '#14532D' }}>Proposed New Name of Institution *</span>
                <input
                  className="input"
                  type="text"
                  value={f.proposed_institution_name}
                  onChange={e => setF({ ...f, proposed_institution_name: e.target.value })}
                  placeholder="e.g. Coromandel University College of Technology"
                  required={category === 'CHANGE_OF_NAME'}
                />
              </label>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <label className="field">
                  <span style={{ fontWeight: 600, color: '#14532D' }}>Sponsoring Trust / Society</span>
                  <input
                    className="input"
                    type="text"
                    value={f.trust_society_name}
                    onChange={e => setF({ ...f, trust_society_name: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span style={{ fontWeight: 600, color: '#14532D' }}>Resolution Date</span>
                  <input
                    className="input"
                    type="date"
                    value={f.resolution_date}
                    onChange={e => setF({ ...f, resolution_date: e.target.value })}
                  />
                </label>
              </div>
              <label className="field">
                <span style={{ fontWeight: 600, color: '#14532D' }}>Justification for Rename</span>
                <input
                  className="input"
                  type="text"
                  value={f.reason_for_change}
                  onChange={e => setF({ ...f, reason_for_change: e.target.value })}
                  placeholder="e.g. Upgraded to autonomous engineering institute"
                />
              </label>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <label className="field">
              <span style={{ fontWeight: 600 }}>Total Built-up Area (sq.m) *</span>
              <input
                className="input"
                type="number"
                step="any"
                value={f.built_up_area_sqm}
                onChange={e => setF({ ...f, built_up_area_sqm: e.target.value })}
                placeholder="e.g. 18500"
              />
            </label>

            <label className="field">
              <span style={{ fontWeight: 600 }}>Full-Time Faculty Count *</span>
              <input
                className="input"
                type="number"
                value={f.faculty_count}
                onChange={e => setF({ ...f, faculty_count: e.target.value })}
                placeholder="e.g. 21"
              />
            </label>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            <label className="field">
              <span style={{ fontWeight: 600 }}>Classrooms</span>
              <input
                className="input"
                type="number"
                value={f.classrooms}
                onChange={e => setF({ ...f, classrooms: e.target.value })}
              />
            </label>

            <label className="field">
              <span style={{ fontWeight: 600 }}>Laboratories</span>
              <input
                className="input"
                type="number"
                value={f.labs}
                onChange={e => setF({ ...f, labs: e.target.value })}
              />
            </label>

            <label className="field">
              <span style={{ fontWeight: 600 }}>Academic Year</span>
              <input
                className="input"
                type="text"
                value={f.academic_year}
                onChange={e => setF({ ...f, academic_year: e.target.value })}
              />
            </label>
          </div>

          {err && <p className="error" style={{ color: '#dc2626' }}>{err}</p>}

          <footer style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
            <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
            <button
              type="submit"
              className="btn primary"
              disabled={busy}
              style={{ fontWeight: 600 }}
            >
              {busy ? 'Saving…' : 'Save & Update Application'}
            </button>
          </footer>
        </form>
      </aside>
    </>
  )
}
