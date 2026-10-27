import { useCallback, useEffect, useState } from 'react'
import { AlertOctagon, AlertTriangle, Info, CheckCircle2 } from 'lucide-react'
import { api } from './api'

/* One vocabulary for the whole interface. Officials see plain words; codes stay secondary. */

export const SYSTEM_STATUS = {
  ACTION_REQUIRED: { label: 'Needs review', tone: 'danger', hint: 'High-severity issues need an official’s review' },
  DEFICIENCIES_FOUND: { label: 'Deficiencies', tone: 'warn', hint: 'Gaps found; rectification likely' },
  MANUAL_VERIFICATION: { label: 'Awaiting sources', tone: 'info', hint: 'Checks passed; some documents need manual confirmation' },
  READY_FOR_SCRUTINY: { label: 'Clear', tone: 'ok', hint: 'Automated checks found nothing to raise' },
}
export const APP_STATUS = {
  DRAFT: { label: 'Draft', tone: 'info' },
  SUBMITTED: { label: 'Submitted', tone: 'accent' },
  UNDER_SCRUTINY: { label: 'Under scrutiny', tone: 'accent' },
  RECTIFICATION_REQUESTED: { label: 'Returned for rectification', tone: 'warn' },
  DECIDED: { label: 'Recommendation recorded', tone: 'ok' },
}
export const VER_STATUS = {
  VERIFIED: { label: 'Verified', tone: 'ok' },
  MISMATCH: { label: 'Mismatch', tone: 'danger' },
  EXPIRED: { label: 'Expired', tone: 'warn' },
  PENDING: { label: 'Pending', tone: 'accent' },
  SOURCE_UNAVAILABLE: { label: 'Source unavailable', tone: 'info' },
  MANUAL_REVIEW: { label: 'Manual confirmation', tone: 'info' },
  NOT_APPLICABLE: { label: 'No issuing source', tone: 'info' },
}
export const REVIEW = {
  OPEN: 'Open', CONFIRMED: 'Confirmed', DISMISSED: 'Dismissed',
  RECTIFICATION_REQUESTED: 'Rectification requested', INSPECTION_REQUIRED: 'Inspection required',
}
export const REVIEW_ACTIONS = [
  { key: 'CONFIRMED', label: 'Confirm', kbd: 'C' },
  { key: 'RECTIFICATION_REQUESTED', label: 'Ask to rectify', kbd: 'R' },
  { key: 'INSPECTION_REQUIRED', label: 'Needs inspection', kbd: 'I' },
  { key: 'DISMISSED', label: 'Dismiss', kbd: 'D' },
]
export const DECISIONS = {
  RECOMMEND_FOR_APPROVAL: { label: 'Recommend for approval', sub: 'All high-severity issues must be reviewed first' },
  RETURN_FOR_RECTIFICATION: { label: 'Return to the institution', sub: 'They can correct documents and resubmit' },
  REFER_FOR_INSPECTION: { label: 'Refer for physical inspection', sub: 'For infrastructure or authenticity doubts' },
  REFER_TO_EXPERT_COMMITTEE: { label: 'Refer to expert committee', sub: 'For cases needing a wider view' },
}
export const CHECKS = [
  { key: 'checklist', label: 'Checklist', desc: 'Required documents, validity, consistency' },
  { key: 'records', label: 'AICTE records', desc: 'Matches what AICTE already holds' },
  { key: 'authenticity', label: 'Authenticity', desc: 'Signs of alteration or re-use' },
  { key: 'sources', label: 'Issuing authority', desc: 'Confirmed with whoever issued it' },
  { key: 'infrastructure', label: 'Infrastructure', desc: 'Norms and photo evidence' },
]
export const CHECK_LABEL = Object.fromEntries(CHECKS.map(c => [c.key, c.label]))
export function checkOf(f) {
  if (f.module === 'rules' && (f.rule_id || '').includes('-REC-')) return 'records'
  return { rules: 'checklist', extraction: 'checklist', anomaly: 'authenticity', verification: 'sources', infrastructure: 'infrastructure' }[f.module]
}
export const SEV_ORDER = ['high', 'medium', 'low', 'info']
export const SEV_LABEL = { high: 'High', medium: 'Medium', low: 'Low', info: 'Note' }

/* ------------------------------------------------------------------ small components */

export function SevIcon({ s, size = 15 }) {
  const I = s === 'high' ? AlertOctagon : s === 'medium' ? AlertTriangle : Info
  return <I className={`sev ${s}`} size={size} strokeWidth={2.2} aria-label={`${SEV_LABEL[s]} severity`} />
}
export const Status = ({ tone = 'info', children, title }) => <span className={`status ${tone}`} title={title}>{children}</span>
export const Tag = ({ tone = 'info', children }) => <span className={`tag ${tone}`}>{children}</span>
export function SystemStatus({ s }) {
  const x = SYSTEM_STATUS[s]
  return x ? <Status tone={x.tone} title={x.hint}>{x.label}</Status> : <Status>Not checked</Status>
}
export function VerStatus({ s }) {
  const x = VER_STATUS[s] || { label: human(s), tone: 'info' }
  return <Status tone={x.tone}>{x.label}</Status>
}
export function CheckStrip({ checks }) {
  if (!checks) return <span className="faint small">Not checked yet</span>
  return (
    <span className="strip" role="img" aria-label={CHECKS.map(c => `${c.label}: ${checks[c.key]}`).join(', ')}>
      {CHECKS.map(c => <i key={c.key} className={checks[c.key]} title={`${c.label} — ${checks[c.key] === 'pass' ? 'no issues' : `${checks[c.key]} severity`}`} />)}
    </span>
  )
}
export function StripLegend() {
  return (
    <div className="strip-legend">
      <span>Checks, left to right: {CHECKS.map(c => c.label).join(' · ')}</span>
      <span><span className="strip"><i className="pass" /></span>no issues</span>
      <span><span className="strip"><i className="low" /></span>low</span>
      <span><span className="strip"><i className="medium" /></span>medium</span>
      <span><span className="strip"><i className="high" /></span>high</span>
    </div>
  )
}
export function IssueCounts({ counts }) {
  if (!counts) return <span className="faint">—</span>
  const parts = ['high', 'medium', 'low'].filter(s => counts[s])
  if (!parts.length) return <span className="muted">None</span>
  return <span className="issues-compact">{parts.map(s => <span key={s}><SevIcon s={s} size={13} />{counts[s]}</span>)}</span>
}
export const Kbd = ({ children }) => <kbd>{children}</kbd>
export function Avatar({ name = '', sm }) {
  const ini = name.replace(/\(.*\)/, '').split(/\s+/).filter(w => /^[A-Za-z]/.test(w)).slice(0, 2).map(w => w[0]).join('').toUpperCase()
  return <span className={`avatar ${sm ? 'sm' : ''}`} aria-hidden="true">{ini || '?'}</span>
}
export function Empty({ title, children }) {
  return <div className="empty">{title && <b>{title}</b>}{children}</div>
}
export function Loading({ error }) {
  if (error) return <Empty title="Couldn’t load this">{error.message}</Empty>
  return <div className="page" aria-busy="true"><div className="skeleton" style={{ width: 220, height: 22, marginBottom: 18 }} />
    {[1, 2, 3, 4].map(i => <div key={i} className="skeleton" style={{ marginBottom: 12, width: `${90 - i * 8}%` }} />)}</div>
}

/* ------------------------------------------------------------------ helpers */

export function useApi(path, deps = []) {
  const [state, set] = useState({ data: null, error: null, loading: true })
  const load = useCallback(() => {
    if (!path) return
    set(s => ({ ...s, loading: true }))
    api(path).then(data => set({ data, error: null, loading: false }))
      .catch(error => set(s => ({ data: s.data, error, loading: false })))
  }, [path]) // eslint-disable-line
  useEffect(() => { load() }, [load, ...deps]) // eslint-disable-line
  return { ...state, reload: load }
}

const WORDS = { aicte: 'AICTE', id: 'ID', noc: 'NOC', ter: 'TER', nba: 'NBA', sqm: 'm²', qr: 'QR', ay: 'AY' }
export const human = s => (s || '').replaceAll('_', ' ').replace(/\b(aicte|id|noc|ter|nba|sqm|qr|ay)\b/gi, w => WORDS[w.toLowerCase()])
export const fieldLabel = s => { const h = human(s); return h.charAt(0).toUpperCase() + h.slice(1) }
export const sentence = s => { const h = human(s).toLowerCase(); return h.charAt(0).toUpperCase() + h.slice(1) }
export const fmtDate = iso => iso ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—'
export function ago(iso) {
  if (!iso) return '—'
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

let toastTimer
export function toast(msg) {
  let el = document.querySelector('.toast')
  if (!el) { el = document.createElement('div'); el.className = 'toast'; el.setAttribute('role', 'status'); document.body.appendChild(el) }
  el.textContent = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => el.remove(), 3000)
}

export { CheckCircle2 }

/* ------------------------------------------------------------------ v2 shared pieces */

const TILE = ['#1D574F', '#557A2B', '#57ABAD', '#276866', '#4B7B3E', '#22524D', '#3B7569', '#638634']
export function tileColor(key = '') {
  let h = 0
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return TILE[h % TILE.length]
}
export function initials(name = '') {
  return name.replace(/\(.*\)/, '').split(/\s+/).filter(w => /^[A-Z]/.test(w) && !['Of', 'And', 'The'].includes(w)).slice(0, 2).map(w => w[0]).join('')
}
export function InstTile({ name, id, size = 34 }) {
  return <span className="inst-tile" style={{ background: tileColor(id || name), width: size, height: size }} aria-hidden="true">{initials(name)}</span>
}
export function Band({ children }) {
  return <section className="band"><div className="band-inner">{children}</div></section>
}
export function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}
